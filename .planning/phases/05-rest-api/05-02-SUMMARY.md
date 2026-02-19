---
phase: 05-rest-api
plan: 02
subsystem: api
tags: [fastapi, qdrant, retrieval, document-filter, hybrid-search, bm25, rrf, reranker]

# Dependency graph
requires:
  - phase: 05-rest-api/05-01
    provides: /api/v1 URL prefix, CORS/Logging/UploadSizeLimit middleware, RFC 7807 error handlers
  - phase: 03-retrieval-engine
    provides: RetrievalEngine.search(), QdrantStore.query_dense/query_sparse(), BM25Manager
provides:
  - POST /api/v1/retrieve endpoint returning raw reranked chunks without LLM synthesis
  - RetrieveRequest/ChunkResultItem/RetrieveResponse Pydantic schemas
  - document_ids filter on RetrievalEngine.search() for scoped per-document queries
  - query_filter param on QdrantStore.query_dense/query_sparse for Qdrant payload filtering
  - BM25 post-filter when document_ids scope is active
affects:
  - 06-deployment (MCP client in Phase 6 calls /api/v1/retrieve directly)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Qdrant Filter with MatchAny for multi-document payload filtering
    - BM25 post-filter pattern (corpus is global; manual filter needed after keyword search)
    - document_ids=None default preserves backward compatibility for /ask endpoint

key-files:
  created:
    - src/rag_server/api/retrieve.py
  modified:
    - src/rag_server/api/schemas.py
    - src/rag_server/vector_store/qdrant.py
    - src/rag_server/retrieval/engine.py
    - src/rag_server/main.py

key-decisions:
  - "query_filter passed directly to query_points() — Qdrant ignores None filters natively (no branching needed)"
  - "BM25 post-filter applied after asyncio.gather — BM25 index is global, cannot use Qdrant payload filter"
  - "allowed_chunk_ids pre-fetched from SQLite before three-leg gather — lightweight single query, sequential is simpler than adding fourth gather coroutine"
  - "document_ids=None default on search() — /ask endpoint calls search() without document_ids and is fully backward compatible"
  - "Filter/FieldCondition/MatchAny imported at call-site in engine.py — avoids circular import risk at module level"

patterns-established:
  - "Scoped search: qdrant_filter (MatchAny on document_id payload) + SQLite pre-fetch (Chunk.document_id.in_) + BM25 post-filter"
  - "RetrieveResponse maps ChunkResult dataclass fields 1:1 — all 5 scores and full citation metadata always returned"

requirements-completed: [API-04]

# Metrics
duration: 2min
completed: 2026-02-19
---

# Phase 5 Plan 02: Retrieve Endpoint Summary

**POST /api/v1/retrieve with document_ids scoping — raw hybrid-search results (BM25+dense+sparse+RRF+reranker) exposed without LLM synthesis for MCP client consumption**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-19T21:21:37Z
- **Completed:** 2026-02-19T21:23:55Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- POST /api/v1/retrieve registered in FastAPI app alongside /documents, /ask, and /health
- document_ids filter wires through the full retrieval stack: Qdrant payload filter on dense+sparse legs, SQLite pre-fetch + BM25 post-filter on keyword leg
- ChunkResultItem exposes all 5 scores (bm25, dense, sparse, rrf, reranker) and full citation metadata matching ChunkResult dataclass
- Fully backward compatible: /ask endpoint calls search() without document_ids and is unaffected

## Task Commits

Each task was committed atomically:

1. **Task 1: Add query_filter to QdrantStore + document_ids to RetrievalEngine** - `f9b2aa6` (feat)
2. **Task 2: Add retrieve schemas, create retrieve.py router, register in main.py** - `1f3f507` (feat)

## Files Created/Modified
- `src/rag_server/api/retrieve.py` - POST /retrieve router; calls engine.search() with document_ids, maps ChunkResult to ChunkResultItem
- `src/rag_server/api/schemas.py` - Added RetrieveRequest, ChunkResultItem, RetrieveResponse after existing AskResponse
- `src/rag_server/vector_store/qdrant.py` - Added Filter|None query_filter param to query_dense() and query_sparse(); added Filter/FieldCondition/MatchAny to module-level imports
- `src/rag_server/retrieval/engine.py` - Added document_ids: list[str] | None = None param to search(); builds Qdrant filter and pre-fetches allowed_chunk_ids from SQLite; post-filters BM25 ranking
- `src/rag_server/main.py` - Imported retrieve_router and registered at /api/v1 prefix

## Decisions Made
- `query_filter=None` default is backward compatible — Qdrant ignores None filters natively, no conditional branching needed in query_dense/query_sparse
- BM25 post-filter applied after the asyncio.gather so all three retrieval legs complete in parallel before filtering
- allowed_chunk_ids fetched sequentially before the gather (not as a fourth gather coroutine) — single lightweight SQLite query, simpler code
- Filter/FieldCondition/MatchAny imported inside search() at the call-site to avoid any potential circular import at module level
- Module-level imports (Filter, FieldCondition, MatchAny) added to qdrant.py since they are used across multiple methods (delete_document already used them via local import — consolidated to top)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 5 (REST API) is now fully complete: /api/v1/documents, /api/v1/ask, /api/v1/retrieve, /health all registered
- POST /api/v1/retrieve ready for MCP client (Phase 6) to call for raw chunk retrieval
- document_ids filter enables scoped "ask about this document" use case from Phase 6 MCP tools
- All endpoints respond with CORS headers and RFC 7807 error shapes

## Self-Check: PASSED

- src/rag_server/api/retrieve.py: FOUND
- src/rag_server/api/schemas.py: FOUND (contains RetrieveRequest, ChunkResultItem, RetrieveResponse)
- src/rag_server/vector_store/qdrant.py: FOUND (contains query_filter)
- src/rag_server/retrieval/engine.py: FOUND (contains document_ids)
- src/rag_server/main.py: FOUND (contains retrieve_router)
- .planning/phases/05-rest-api/05-02-SUMMARY.md: FOUND
- Commit f9b2aa6 (Task 1): FOUND
- Commit 1f3f507 (Task 2): FOUND

---
*Phase: 05-rest-api*
*Completed: 2026-02-19*
