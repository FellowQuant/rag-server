# Phase 3: Retrieval Engine - Context

**Gathered:** 2026-02-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the search engine that powers all queries: three-leg retrieval (BM25 + BGE-M3 dense + BGE-M3 sparse), RRF fusion, and Qwen3-Reranker-0.6B cross-encoder reranking. Callers pass a text query string and receive ranked, cited chunks. This phase delivers a Python retrieval module consumed by Phase 5 (REST API) and Phase 6 (MCP). No HTTP endpoints in this phase — pure retrieval logic only.

</domain>

<decisions>
## Implementation Decisions

### Query parameters
- **top_k**: configurable with default of 10 — caller passes `top_k=N`, engine reranks and returns that many results
- **min_score**: optional threshold parameter — caller can pass `min_score` (0.0–1.0) to filter out weak results before returning; omitting it returns top_k regardless of score
- **Scores in results**: return ALL scores — BM25 score, dense score, sparse score, RRF fused score, and Qwen3-Reranker score. Useful for debugging and tuning.
- **Reranker**: always runs — no way to skip the cross-encoder step. Caller cannot bypass reranking.
- **Query input**: engine embeds internally — caller passes a plain text query string; engine handles BGE-M3 embedding (dense + sparse) internally.
- **API style**: synchronous/awaitable — `await retriever.search(query, top_k=10)` blocks until full ranked results are ready. LLM consumers need all results before synthesis anyway; streaming retrieval provides no benefit.
- **No deduplication**: return exactly what the ranker produces — if two chunks from the same page appear in top results, both are returned.
- **No explain mode**: all scores already show contribution per retrieval leg — no separate explain flag needed.

### Claude's Discretion — Query parameters
- Mode override (hybrid/dense/sparse/bm25): Claude decides — default hybrid always; mode param may be added if clearly beneficial
- Multi-query fusion: Claude decides — for LLM-consumed API; HyDE or query expansion may be added if it demonstrably improves recall
- Query instruction prefix: Claude decides — BGE-M3 supports instruction-prefixed queries; Claude tunes the retrieval instruction
- Model architecture (where BGE-M3 lives for query-side embedding): Claude decides — separate FastAPI-owned instance vs shared; main constraint is the worker process already has one in its own process space

### BM25 index lifecycle
- **Build strategy**: build from SQLite at server startup; update incrementally when new documents are indexed — server does NOT require restart after new document ingestion
- **Update notification**: worker signals via the shared multiprocessing.Queue — after indexing a document, worker puts a `'bm25_update'` (or similar) message; FastAPI's retrieval engine picks it up and adds new chunks to the BM25 index
- **Persistence**: BM25 index persisted to disk (e.g., `DATA_DIR/bm25.pkl`) — restarts load from disk if the pickle exists, otherwise rebuild from SQLite. Pickle updated after each successful BM25 update.
- **Concurrency**: read-concurrent safe — multiple queries can read the BM25 index simultaneously; updates use an asyncio.Lock to atomically swap the index object while in-flight queries finish on the old instance.

### Claude's Discretion — BM25 lifecycle
- BM25 chunk type weighting: Claude decides (whether to exclude or down-weight formula/table chunks vs text)
- Deletion handling: Claude decides (full rebuild vs lazy rebuild when document deleted)
- BM25 tokenizer: Claude decides (simple word-level vs aligning with BGE-M3 tokenizer)
- LaTeX content stripping before BM25 indexing: Claude decides
- Global vs per-document corpus: Claude decides (global strongly recommended for RETR-05 cross-document queries)
- Hot-swap mechanism: Claude decides (atomic swap with lock is recommended; implementation details left to Claude)

### Result format
- **Full content always**: return complete chunk text — no truncation. LLM needs full context.
- **All scores included**: BM25, dense cosine, sparse, RRF fused, Qwen3-Reranker — all returned per result.

### Claude's Discretion — Result format
- Formula chunk display_content: Claude decides whether to return both `content` (enriched embedding text) and `display_content` (raw LaTeX) or just one. Recommendation: return both; LLM reasons from content, display layer renders from display_content.
- Citation metadata fields: Claude decides which Document/Chunk metadata to include (original_filename, page_number, section_heading, chunk_type, chunk_index are all available from SQLite)
- total_found field: Claude decides whether to include candidate count before top_k cutoff

### Retrieval scope
- **Document filter and chunk type filter**: both left to Claude's discretion. Claude decides whether to expose `document_ids` and/or `chunk_types` filter parameters based on MCP tool design and complexity/benefit tradeoff.

</decisions>

<specifics>
## Specific Ideas

- The RAG server will be consumed by LLMs (Phase 6 MCP, Phase 5 REST API). The retrieval engine does not need to optimize for human-readable latency — correctness and recall quality matter more than sub-100ms response time. Reranker latency (~200-500ms) is acceptable.
- Scores returned in results are primarily for debugging and tuning, not for display to end users. The LLM consumer will use the ranked order, not the raw scores.
- BM25 index is explicitly NOT rebuilt on every query — the user was clear that the server should not need restart after new ingestion. Incremental updates via worker signal are the required approach.
- The qdrant-client 1.16.2 vs Qdrant server 1.13.4 version mismatch (logged as warning in Phase 2) should be resolved at Phase 3 start before building on top of Qdrant retrieval.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-retrieval-engine*
*Context gathered: 2026-02-19*
