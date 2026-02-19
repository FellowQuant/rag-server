---
phase: 03-retrieval-engine
plan: "01"
subsystem: infra
tags: [qdrant, bge-m3, vector-search, embedder, dense-search, sparse-search]

# Dependency graph
requires:
  - phase: 01-foundation-storage
    provides: QdrantStore async client wrapper, Qdrant collection schema (dense+sparse)
  - phase: 02-document-ingestion-pipeline
    provides: Embedder class with embed_chunks(), BGE-M3 model integration
provides:
  - Qdrant server upgraded to v1.16.3 (resolves client/server version mismatch)
  - AsyncQdrantClient constructed with check_compatibility=False
  - QueryEmbedding dataclass (dense_vector, sparse_indices, sparse_values)
  - Embedder.encode_query() using encode_queries() query mode
  - VectorSearchResult dataclass (chunk_id, score, payload)
  - QdrantStore.query_dense() using query_points(using='dense')
  - QdrantStore.query_sparse() with empty-indices guard using query_points(using='sparse')
affects: [03-retrieval-engine, 04-synthesis]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "encode_queries() for query embedding (vs encode() for passage embedding) — semantically correct per BGE-M3 training"
    - "query_points() for Qdrant retrieval (vs search()) — modern qdrant-client 1.16+ API"
    - "Empty sparse_indices guard pattern in query_sparse() — avoids Qdrant server error on empty sparse vector"

key-files:
  created: []
  modified:
    - docker-compose.yml
    - src/rag_server/ingestion/embedder.py
    - src/rag_server/vector_store/qdrant.py

key-decisions:
  - "check_compatibility=False on AsyncQdrantClient: suppresses UserWarning on minor version drift; server upgraded to v1.16.3 to align with client 1.16.2"
  - "encode_queries() (not encode()) for query embedding: BGE-M3 uses different processing for queries vs passages; encode_queries() applies query_max_length and query_instruction"
  - "query_sparse() returns [] on empty indices: Qdrant server errors on empty sparse vector; early return is safer than passing empty SparseVector"
  - "query_points() API used (not search()): query_points is the modern unified API in qdrant-client 1.16"

patterns-established:
  - "QueryEmbedding pattern: single-query embedding dataclass parallel to EmbeddingResult for batch chunks"
  - "VectorSearchResult pattern: normalized search result dataclass decoupling Qdrant ScoredPoint from retrieval logic"

requirements-completed: [RETR-01, RETR-02]

# Metrics
duration: 3min
completed: 2026-02-19
---

# Phase 3 Plan 01: Retrieval Foundation — Qdrant Upgrade and Search Methods Summary

**Qdrant server upgraded to v1.16.3, Embedder gains encode_query() using BGE-M3 query mode, QdrantStore gains query_dense() and query_sparse() using query_points() API**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-19T16:54:30Z
- **Completed:** 2026-02-19T16:57:40Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Resolved Qdrant client/server version mismatch warning deferred from Phase 2 by upgrading Docker image to v1.16.3 and adding check_compatibility=False
- Added QueryEmbedding dataclass and Embedder.encode_query() using encode_queries() (query mode) for semantically correct retrieval embedding
- Added VectorSearchResult dataclass and QdrantStore.query_dense()/query_sparse() methods using query_points() API, with empty-indices guard on sparse path

## Task Commits

Each task was committed atomically:

1. **Task 1: Upgrade Qdrant to v1.16.3 and add check_compatibility=False** - `0470909` (feat)
2. **Task 2: Add encode_query() to Embedder and query_dense()/query_sparse() to QdrantStore** - `985a8dc` (feat)

**Plan metadata:** TBD (docs: complete plan)

## Files Created/Modified
- `docker-compose.yml` - Updated Qdrant image tag from v1.13.4 to v1.16.3
- `src/rag_server/ingestion/embedder.py` - Added QueryEmbedding dataclass and Embedder.encode_query() method
- `src/rag_server/vector_store/qdrant.py` - Added VectorSearchResult dataclass, check_compatibility=False, query_dense() and query_sparse() methods

## Decisions Made
- Used `check_compatibility=False` belt-and-suspenders even after version alignment — protects against future minor drift without breaking functionality
- Used `encode_queries()` not `encode()` for query embedding — BGE-M3 training distinguishes query vs passage paths; encode_queries() applies query_max_length and optional query instruction
- Added early return `[]` in query_sparse() when indices are empty — Qdrant server raises an error on empty SparseVector; guard is safer than server round-trip
- Used `query_points()` API (qdrant-client 1.16 modern API) rather than legacy `search()` — consistent with current client version

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. Docker image was pulled automatically via docker compose.

## Next Phase Readiness
- Retrieval foundation complete: query embedding (encode_query) and vector search (query_dense, query_sparse) are ready
- Next: 03-02 will build the Retrieval service layer combining dense + sparse search with score fusion (RRF)
- No blockers

## Self-Check: PASSED

- FOUND: docker-compose.yml
- FOUND: src/rag_server/ingestion/embedder.py
- FOUND: src/rag_server/vector_store/qdrant.py
- FOUND: .planning/phases/03-retrieval-engine/03-01-SUMMARY.md
- FOUND commit: 0470909 (Task 1)
- FOUND commit: 985a8dc (Task 2)

---
*Phase: 03-retrieval-engine*
*Completed: 2026-02-19*
