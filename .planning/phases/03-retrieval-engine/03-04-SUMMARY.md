---
phase: 03-retrieval-engine
plan: "04"
subsystem: retrieval
tags: [python, asyncio, bm25, qdrant, bge-m3, qwen3-reranker, rrf, fastapi, sqlalchemy]

# Dependency graph
requires:
  - phase: 03-retrieval-engine/03-01
    provides: QdrantStore.query_dense() and query_sparse() for vector retrieval
  - phase: 03-retrieval-engine/03-02
    provides: BM25Manager.search() for keyword retrieval and hot-swap lifecycle
  - phase: 03-retrieval-engine/03-03
    provides: Reranker.compute_scores() for Qwen3-Reranker-0.6B cross-encoder
  - phase: 02-document-ingestion-pipeline/02-04
    provides: Embedder.encode_query() for query-time BGE-M3 embedding
provides:
  - RetrievalEngine class with three-leg parallel retrieval (BM25 + dense + sparse)
  - RRF fusion (_rrf_merge) combining all three ranked lists with k=60
  - ChunkResult dataclass with all five scores and full citation metadata
  - RetrievalResult dataclass for full search result sets
  - FastAPI lifespan wiring for query-side Embedder and Reranker on app.state
  - scripts/verify_retrieval.py end-to-end smoke test
affects: [04-llm-synthesis, 05-retrieval-api, 06-production-hardening]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.gather for parallel three-leg retrieval (BM25 + dense + sparse concurrent)
    - RRF fusion with k=60 per Cormack 2009 (1.0 / (k + rank + 1) formula)
    - Bulk SQLite JOIN fetch for content after RRF, before reranker (content only in SQLite)
    - asyncio.to_thread wrapping all synchronous GPU-bound calls (embed, rerank, BM25)
    - Separate Embedder instance in FastAPI process vs worker process (multiprocessing.spawn)

key-files:
  created:
    - src/rag_server/retrieval/models.py
    - src/rag_server/retrieval/engine.py
    - scripts/verify_retrieval.py
  modified:
    - src/rag_server/main.py

key-decisions:
  - "Separate query-side Embedder instance in FastAPI process -- worker Embedder lives in spawned subprocess, FastAPI needs its own instance for encode_query() at request time"
  - "min_score filter applied BEFORE top_k cutoff -- ensures final slice is always highest-quality results"
  - "Reranker always runs -- not skippable per spec; handles empty documents list gracefully"
  - "Chunk content fetched from SQLite after RRF, before reranker -- content lives only in SQLite, not Qdrant payload"
  - "ordered_ids filters to only chunk_ids present in chunk_rows -- handles edge case where Qdrant has point IDs not yet in SQLite"

patterns-established:
  - "Three-leg hybrid retrieval: asyncio.gather(bm25_task, dense_task, sparse_task) for parallel execution"
  - "RRF merge: collect per-leg raw scores, compute 1/(k+rank+1), sort descending, take top_n"
  - "All ChunkResult fields populated at retrieval time from SQLite JOIN -- no Qdrant payload reliance for content"

requirements-completed: [RETR-01, RETR-02, RETR-03, RETR-04, RETR-05]

# Metrics
duration: 3min
completed: 2026-02-19
---

# Phase 3 Plan 04: Retrieval Engine Wiring Summary

**RetrievalEngine integrating BM25 + BGE-M3 dense + BGE-M3 sparse with RRF fusion and mandatory Qwen3-Reranker-0.6B reranking, wired into FastAPI lifespan on app.state**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-19T18:07:24Z
- **Completed:** 2026-02-19T18:10:14Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- ChunkResult and RetrievalResult dataclasses with all five scores (bm25, dense, sparse, rrf, reranker) and full citation metadata
- RetrievalEngine.search() executing three-leg parallel retrieval via asyncio.gather, RRF fusion with k=60, bulk SQLite content fetch, and Qwen3 reranking
- FastAPI lifespan updated to load query-side Embedder and Reranker, wire RetrievalEngine onto app.state.retrieval_engine; version bumped to 0.3.0
- End-to-end smoke test script verifying BM25 index persistence, search results, SQLite citation metadata, and document cleanup

## Task Commits

Each task was committed atomically:

1. **Task 1: Result dataclasses and RetrievalEngine with three-leg retrieval + RRF + reranker** - `1047d87` (feat)
2. **Task 2: FastAPI lifespan wiring and end-to-end smoke test** - `3075856` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/rag_server/retrieval/models.py` - ChunkResult and RetrievalResult dataclasses with all score and citation fields
- `src/rag_server/retrieval/engine.py` - RetrievalEngine with parallel three-leg retrieval, RRF fusion, SQLite bulk fetch, Qwen3 reranking
- `src/rag_server/main.py` - Lifespan wiring for query Embedder, Reranker, RetrievalEngine on app.state; version 0.3.0
- `scripts/verify_retrieval.py` - End-to-end smoke test: upload notebook, poll indexing, validate BM25 + SQLite, cleanup

## Decisions Made

- Separate query-side Embedder instance in FastAPI process -- worker Embedder lives in spawned subprocess, FastAPI needs its own for encode_query()
- min_score filter applied before top_k cutoff -- ensures final slice is always highest-quality results above threshold
- ordered_ids filters to only chunk_ids present in chunk_rows -- handles edge case where Qdrant has IDs not yet reflected in SQLite
- Reranker unloaded in shutdown after worker_manager.stop() but before qdrant_store.close() -- preserves VRAM release ordering

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- RetrievalEngine is fully wired and available on app.state.retrieval_engine
- Phase 4 (LLM synthesis) can call app.state.retrieval_engine.search() directly from route handlers
- Phase 5 (Retrieval API) can expose HTTP endpoints wrapping the same engine
- VRAM budget: BGE-M3 worker (~1 GB) + query Embedder (~1 GB) + Reranker (~1.2 GB) = ~3.2 GB total; monitor under load

---
*Phase: 03-retrieval-engine*
*Completed: 2026-02-19*
