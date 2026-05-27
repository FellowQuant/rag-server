"""POST /retrieve endpoint — raw ranked chunks without LLM synthesis.

Returns the top-k reranked ChunkResult objects as JSON, including all five
retrieval scores (bm25, dense, sparse, rrf, reranker) and full citation
metadata. Optionally scoped to specific document_ids.

Use this endpoint when you need raw retrieved chunks for custom synthesis,
MCP tool calls, or debugging the retrieval pipeline. For LLM-synthesized
answers, use POST /ask.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from rag_server.api.schemas import ChunkResultItem, RetrieveRequest, RetrieveResponse
from rag_server.retrieval.engine import RetrievalEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["retrieve"])


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    summary="Retrieve ranked chunks with citations (no LLM synthesis)",
)
async def retrieve(body: RetrieveRequest, request: Request) -> RetrieveResponse:
    """Return reranked chunks for a query without LLM answer synthesis.

    Args:
        body: RetrieveRequest with query, top_k, optional document_ids filter,
              and optional min_score threshold.
        request: FastAPI Request (provides access to app.state).

    Returns:
        RetrieveResponse with ranked ChunkResultItem list and total_candidates count.
    """
    engine: RetrievalEngine = request.app.state.retrieval_engine

    result = await engine.search(
        query=body.query,
        top_k=body.top_k,
        min_score=body.min_score,
        document_ids=body.document_ids,
    )

    logger.info(
        "/retrieve: query=%r, top_k=%d, document_ids=%s, returned=%d",
        body.query[:80],
        body.top_k,
        len(body.document_ids) if body.document_ids else "all",
        len(result.results),
    )

    return RetrieveResponse(
        query=result.query,
        results=[
            ChunkResultItem(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                chunk_index=c.chunk_index,
                content=c.content,
                display_content=c.display_content,
                source_filename=c.source_filename,
                page_number=c.page_number,
                section_heading=c.section_heading,
                chunk_type=c.chunk_type,
                bm25_score=c.bm25_score,
                dense_score=c.dense_score,
                sparse_score=c.sparse_score,
                rrf_score=c.rrf_score,
                reranker_score=c.reranker_score,
            )
            for c in result.results
        ],
        total_candidates=result.total_candidates,
    )
