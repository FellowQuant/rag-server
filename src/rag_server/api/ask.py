"""POST /ask endpoint — synthesized answer with inline citations.

Supports both streaming (SSE) and non-streaming variants via the `streaming`
query parameter (default: true).

Streaming (GET /ask?streaming=true, or POST /ask with default):
  - Returns SSE stream (text/event-stream)
  - event="token": token delta strings as they generate
  - event="done": final JSON {"answer": "...", "citations": [...]}
  - event="error": {"detail": "..."} on failure

Non-streaming (POST /ask?streaming=false):
  - Returns JSON {"answer": "...", "citations": [...]}
  - Waits for full generation before returning

Both variants call the same retrieval + synthesis pipeline. The /ask endpoint
is the primary Phase 4 interface; Phase 5 will add retrieval-only endpoints.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

from rag_server.api.schemas import AskRequest, AskResponse
from rag_server.llm.synthesis import SynthesisEngine
from rag_server.retrieval.engine import RetrievalEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["ask"])


@router.post(
    "/ask",
    response_model=None,
    summary="Synthesize an answer with inline citations from retrieved chunks",
    responses={
        200: {
            "description": (
                "Non-streaming: JSON AskResponse. "
                "Streaming: SSE stream with token events then done event."
            )
        }
    },
)
async def ask(
    body: AskRequest,
    request: Request,
    streaming: bool = True,
) -> AskResponse | EventSourceResponse:
    """Answer a question using retrieved chunks and a local/cloud LLM.

    Args:
        body: AskRequest with query and top_k retrieval parameter.
        request: FastAPI Request (provides access to app.state).
        streaming: If True (default), returns SSE stream. If False, returns JSON.

    Returns:
        If streaming=False: AskResponse JSON.
        If streaming=True: EventSourceResponse with token and done SSE events.
    """
    retrieval_engine: RetrievalEngine = request.app.state.retrieval_engine
    synthesis_engine: SynthesisEngine = request.app.state.synthesis_engine

    # Retrieve chunks via Phase 3 RetrievalEngine
    retrieval_result = await retrieval_engine.search(
        query=body.query,
        top_k=body.top_k,
        min_score=body.min_score,
        document_ids=body.document_ids,
    )
    chunks = retrieval_result.results

    logger.info(
        "/ask: query=%r, retrieved %d chunks, streaming=%s",
        body.query[:80],
        len(chunks),
        streaming,
    )

    if not streaming:
        # Non-streaming: wait for full completion
        result = await synthesis_engine.synthesize(query=body.query, chunks=chunks)
        return result

    # Streaming: SSE with token events + final done event
    async def event_generator():
        collected_tokens: list[str] = []
        try:
            async for token in synthesis_engine.stream_synthesize(
                query=body.query,
                chunks=chunks,
            ):
                collected_tokens.append(token)
                yield {"event": "token", "data": token}

            # Final done event: full structured result
            full_answer = "".join(collected_tokens)
            # Recompute selected chunks the same way synthesis_engine does internally
            selected = chunks[: synthesis_engine._config.context_chunks]
            selected = synthesis_engine._apply_token_budget(selected)
            result = synthesis_engine.parse_result(full_answer, selected)
            yield {
                "event": "done",
                "data": json.dumps(result.model_dump()),
            }
        except Exception as exc:
            logger.exception("/ask streaming: error during generation: %s", exc)
            yield {
                "event": "error",
                "data": json.dumps({"detail": str(exc)}),
            }

    return EventSourceResponse(event_generator())
