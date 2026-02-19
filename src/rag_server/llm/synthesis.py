"""SynthesisEngine: prompt assembly, token budget, citation parsing, and LLM call orchestration.

This module bridges Phase 3 (retrieval) and the LLM providers:
1. Takes ChunkResult list from RetrievalEngine (already ranked by reranker_score descending)
2. Enforces token budget — drops lowest-scoring chunks if over limit
3. Assembles system prompt + user prompt with labeled context block
4. Calls provider.complete() or provider.stream() with tenacity retry
5. Parses [Source: filename, p.N] citations from the answer
6. Returns AskResponse(answer, sources)

The engine is provider-agnostic — it calls only provider.complete() and provider.stream().
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator

import tiktoken
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from rag_server.api.schemas import AskResponse, SourceItem
from rag_server.llm.config import LLMConfig
from rag_server.llm.provider import LLMProvider
from rag_server.retrieval.models import ChunkResult

logger = logging.getLogger(__name__)

# Lenient citation regex: [Source: filename.pdf, p.12] or [Source: filename.pdf p.12]
# Group 1: filename (everything before optional page spec)
# Group 2: page number (digits only, optional)
_CITATION_RE = re.compile(
    r'\[Source:\s*([^,\]\n]+?)(?:[,\s]+p\.?\s*(\d+))?\]',
    re.IGNORECASE,
)

_USER_PROMPT_TEMPLATE = """\
## Retrieved Context

{context_block}

---

## Question

{question}

Answer with inline citations in the format [Source: <filename>, p.<page>].\
"""


class SynthesisEngine:
    """Orchestrates LLM-based answer synthesis from retrieved chunks.

    Usage:
        engine = SynthesisEngine(provider=provider, config=llm_config)

        # Non-streaming
        result = await engine.synthesize(query="...", chunks=[...])
        # result.answer: str, result.sources: list[SourceItem]

        # Streaming — yields token strings; call parse_result() after collecting
        tokens = []
        async for token in engine.stream_synthesize(query="...", chunks=[...]):
            tokens.append(token)
            # send token to SSE client
        result = engine.parse_result("".join(tokens), chunks)
    """

    def __init__(self, provider: LLMProvider, config: LLMConfig) -> None:
        self._provider = provider
        self._config = config
        # Reuse encoder across calls — tiktoken encoding is thread-safe after first load
        self._encoder = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # Token budget enforcement
    # ------------------------------------------------------------------

    def _count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def _apply_token_budget(self, chunks: list[ChunkResult]) -> list[ChunkResult]:
        """Return subset of chunks within max_context_tokens budget.

        Chunks assumed to arrive in reranker_score descending order (best first).
        We include chunks greedily from the top until the budget is exceeded.
        Always includes at least the first chunk.
        """
        budget = self._config.max_context_tokens
        selected: list[ChunkResult] = []
        used_tokens = 0

        for i, chunk in enumerate(chunks):
            chunk_text = self._format_chunk(i + 1, chunk)
            chunk_tokens = self._count_tokens(chunk_text)
            if i == 0 or used_tokens + chunk_tokens <= budget:
                selected.append(chunk)
                used_tokens += chunk_tokens
            else:
                break  # chunks are ordered best-first; stop once budget exceeded

        dropped = len(chunks) - len(selected)
        if dropped > 0:
            logger.warning(
                "Token budget: dropped %d/%d chunks (budget=%d tokens, used=%d tokens)",
                dropped,
                len(chunks),
                budget,
                used_tokens,
            )
        return selected

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def _format_chunk(self, index: int, chunk: ChunkResult) -> str:
        """Format a single chunk with its metadata header."""
        parts = [f"[{index}] Source: {chunk.source_filename}"]
        if chunk.page_number is not None:
            parts.append(f"p.{chunk.page_number}")
        if chunk.section_heading:
            parts.append(f'"{chunk.section_heading}"')
        if chunk.chunk_type:
            parts.append(f"type={chunk.chunk_type}")
        header = " | ".join(parts)

        # Use display_content for formula chunks (raw LaTeX), content otherwise
        text = (
            chunk.display_content
            if (chunk.chunk_type == "formula" and chunk.display_content)
            else chunk.content
        )
        return f"{header}\n{text}"

    def _build_context_block(self, chunks: list[ChunkResult]) -> str:
        """Format all selected chunks into a numbered context block."""
        formatted = [self._format_chunk(i + 1, c) for i, c in enumerate(chunks)]
        return "\n\n---\n\n".join(formatted)

    def _build_messages(self, query: str, chunks: list[ChunkResult]) -> list[dict]:
        """Build the messages list for the LLM call."""
        context_block = self._build_context_block(chunks)
        user_content = _USER_PROMPT_TEMPLATE.format(
            context_block=context_block,
            question=query,
        )
        return [{"role": "user", "content": user_content}]

    # ------------------------------------------------------------------
    # Citation parsing
    # ------------------------------------------------------------------

    def parse_result(self, answer: str, chunks: list[ChunkResult]) -> AskResponse:
        """Parse inline citations from answer text and build AskResponse.

        Matching strategy:
        1. Extract filenames from [Source: ...] markers using lenient regex.
        2. Match against chunk source_filenames (exact match first).
        3. Deduplicate by filename preserving first-seen order.
        4. Fallback: if zero citations found, include ALL chunks as sources.
        """
        cited_filenames: list[str] = []
        seen_in_regex: set[str] = set()

        for match in _CITATION_RE.finditer(answer):
            raw_name = match.group(1).strip()
            if raw_name and raw_name not in seen_in_regex:
                seen_in_regex.add(raw_name)
                cited_filenames.append(raw_name)

        # Build chunk lookup for fast matching
        chunk_by_filename: dict[str, ChunkResult] = {}
        for chunk in chunks:
            if chunk.source_filename not in chunk_by_filename:
                chunk_by_filename[chunk.source_filename] = chunk

        # Match extracted names to known filenames
        sources: list[SourceItem] = []
        seen_sources: set[str] = set()

        for cited in cited_filenames:
            # Exact match
            matched_chunk = chunk_by_filename.get(cited)
            if matched_chunk is None:
                # Suffix match (handles path-prefix variations like "doc.pdf" vs "/data/doc.pdf")
                for fname, chunk in chunk_by_filename.items():
                    if fname.endswith(cited) or cited.endswith(fname):
                        matched_chunk = chunk
                        break

            if matched_chunk and matched_chunk.source_filename not in seen_sources:
                seen_sources.add(matched_chunk.source_filename)
                sources.append(SourceItem(
                    filename=matched_chunk.source_filename,
                    page_number=matched_chunk.page_number,
                    section_heading=matched_chunk.section_heading,
                    chunk_type=matched_chunk.chunk_type,
                ))

        # Fallback: zero citations extracted
        if not sources and chunks:
            logger.warning(
                "Citation parsing found 0 citations in answer. "
                "Falling back to all %d input chunks as sources.",
                len(chunks),
            )
            seen_fallback: set[str] = set()
            for chunk in chunks:
                if chunk.source_filename not in seen_fallback:
                    seen_fallback.add(chunk.source_filename)
                    sources.append(SourceItem(
                        filename=chunk.source_filename,
                        page_number=chunk.page_number,
                        section_heading=chunk.section_heading,
                        chunk_type=chunk.chunk_type,
                    ))

        return AskResponse(answer=answer, sources=sources)

    # ------------------------------------------------------------------
    # LLM calls with retry
    # ------------------------------------------------------------------

    async def synthesize(self, query: str, chunks: list[ChunkResult]) -> AskResponse:
        """Non-streaming synthesis. Returns complete AskResponse.

        Chunks must be pre-sorted by reranker_score descending (RetrievalEngine guarantees this).
        Applies context_chunks limit and token budget before calling provider.
        """
        selected = chunks[: self._config.context_chunks]
        selected = self._apply_token_budget(selected)
        messages = self._build_messages(query, selected)
        system = self._config.system_prompt

        answer = ""
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=10),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                answer = await self._provider.complete(messages, system=system)

        return self.parse_result(answer, selected)

    async def stream_synthesize(
        self,
        query: str,
        chunks: list[ChunkResult],
    ) -> AsyncIterator[str]:
        """Streaming synthesis. Yields token delta strings.

        Caller is responsible for:
        1. Collecting all yielded tokens
        2. Calling parse_result("".join(tokens), chunks) for the final AskResponse
        3. Sending the done event

        Retry wraps the entire stream — if the stream fails mid-way, retry restarts it.
        """
        selected = chunks[: self._config.context_chunks]
        selected = self._apply_token_budget(selected)
        messages = self._build_messages(query, selected)
        system = self._config.system_prompt

        # Retry restarts the stream from scratch on failure
        last_error: Exception | None = None
        for attempt_num in range(1, 4):  # 3 attempts
            try:
                async for token in self._provider.stream(messages, system=system):
                    yield token
                return  # success — exit retry loop
            except Exception as exc:
                last_error = exc
                if attempt_num < 3:
                    import asyncio
                    wait_seconds = min(2 ** attempt_num, 10)
                    logger.warning(
                        "stream_synthesize: attempt %d failed (%s), retrying in %ds",
                        attempt_num,
                        type(exc).__name__,
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)

        # All retries exhausted
        raise RuntimeError(
            f"stream_synthesize: all 3 attempts failed. Last error: {last_error}"
        ) from last_error
