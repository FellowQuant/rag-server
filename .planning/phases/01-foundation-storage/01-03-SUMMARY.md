---
phase: 01-foundation-storage
plan: "03"
subsystem: vector-store
tags: [python, qdrant, async, qdrant-client, vector-store, smoke-test]

# Dependency graph
requires:
  - 01-01 (pyproject.toml dependencies, Settings class)
  - 01-02 (SQLite models, engine, migration applied)
provides:
  - src/rag_server/vector_store/qdrant.py — QdrantStore async wrapper
  - scripts/verify_storage.py — end-to-end smoke test
  - Qdrant collection "documents" with dense (1024d cosine) + sparse schema
affects:
  - Phase 2 (ingestion pipeline uses QdrantStore.upsert_chunks)
  - Phase 3 (hybrid search adds sparse key to vector dict, no schema change needed)

# Tech tracking
tech-stack:
  added:
    - qdrant-client 1.16.2 AsyncQdrantClient (async HTTP wrapper)
  patterns:
    - AsyncQdrantClient only — sync QdrantClient causes event loop deadlocks in FastAPI
    - ensure_collection() idempotent pattern — get_collection() probe then create on exception
    - Sparse vector declared at collection creation — immutable after creation in Qdrant
    - upsert_chunks() sends {"dense": [...]} only in Phase 1 — "sparse" key added in Phase 3 with no schema change
    - delete_document() uses payload Filter on document_id — cross-store sync pattern
    - get_collection_info() uses points_count/segments_count — vectors_count removed in qdrant-client >=1.14

key-files:
  created:
    - src/rag_server/vector_store/__init__.py
    - src/rag_server/vector_store/qdrant.py
    - scripts/verify_storage.py
  modified: []

key-decisions:
  - "AsyncQdrantClient used exclusively — sync QdrantClient deadlocks FastAPI event loop (research pitfall #1)"
  - "sparse_vectors_config declared at collection creation — cannot add later without dropping collection (data loss)"
  - "get_collection_info() uses points_count not vectors_count — vectors_count field absent in qdrant-client 1.16.x CollectionInfo"

# Metrics
duration: 10min
completed: 2026-02-18
---

# Phase 1 Plan 03: Qdrant Client Wrapper Summary

**AsyncQdrantClient wrapper with ensure_collection() idempotent setup (dense 1024d cosine + sparse from day one), upsert/delete methods, and end-to-end smoke test confirming both Qdrant and SQLite stores are operational**

## Performance

- **Duration:** 10 min
- **Started:** 2026-02-18T22:23:06Z
- **Completed:** 2026-02-18T22:33:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- QdrantStore class wrapping AsyncQdrantClient with full lifecycle management
- Collection schema fixed at creation: dense (1024d, Cosine) + sparse (on_disk=False) — no migration needed in Phase 3
- ensure_collection() is idempotent — safe to call on every startup
- upsert_chunks() accepts Phase 1 dense-only vectors; Phase 3 adds "sparse" key with zero schema changes
- delete_document() uses payload filter for cross-store sync with SQLite
- scripts/verify_storage.py passes all 3 sections: Settings, Qdrant CRUD, SQLite CRUD with cascade delete

## Task Commits

Each task was committed atomically:

1. **Task 1: QdrantStore client wrapper** - `15ce778` (feat)
2. **Task 2: End-to-end storage verification script** - `35444d9` (feat)

## Files Created/Modified

- `src/rag_server/vector_store/__init__.py` - Empty package marker
- `src/rag_server/vector_store/qdrant.py` - QdrantStore with ensure_collection, upsert_chunks, delete_document, get_collection_info, close
- `scripts/verify_storage.py` - End-to-end smoke test for Settings + Qdrant + SQLite

## Decisions Made

- AsyncQdrantClient only — sync QdrantClient causes event loop deadlocks in FastAPI (pinned from research pitfall #1)
- sparse_vectors_config declared at collection creation — Qdrant collection schema is immutable after creation; adding sparse fields later requires dropping the collection (data loss)
- get_collection_info() returns points_count/segments_count instead of vectors_count — vectors_count was removed from CollectionInfo in qdrant-client >= 1.14

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed get_collection_info() AttributeError on vectors_count**
- **Found during:** Task 2 (smoke test run)
- **Issue:** `CollectionInfo` object in qdrant-client 1.16.2 does not have a `vectors_count` attribute (removed in client >= 1.14); accessing it raised `AttributeError` and caused smoke test to fail at Step 5
- **Fix:** Updated `get_collection_info()` to use `points_count`, `indexed_vectors_count`, and `segments_count` (all present in the CollectionInfo model), with an explanatory comment about the API change
- **Files modified:** `src/rag_server/vector_store/qdrant.py`
- **Commit:** `35444d9`

---

**Total deviations:** 1 auto-fixed (1 bug — API compatibility)
**Impact on plan:** Deviation was isolated to `get_collection_info()` return dict. All other methods and the smoke test logic were unaffected. All success criteria met.

## Issues Encountered

- qdrant-client 1.16.2 vs Qdrant server 1.13.4 version mismatch produces a UserWarning at startup. This is expected given the pinned server version in docker-compose.yml. The warning can be suppressed with `check_compatibility=False` if needed in production.

## User Setup Required

None — both stores are verified operational. The smoke test can be re-run at any time with:
```bash
python scripts/verify_storage.py
```
(requires Qdrant running via `docker compose up -d qdrant` and migration applied via `alembic upgrade head`)

## Next Phase Readiness

- QdrantStore ready for ingestion pipeline (Phase 2)
- Collection schema locked with sparse field — Phase 3 hybrid search adds "sparse" vector key with no schema migration
- Both storage layers verified operational
- No blockers

---
*Phase: 01-foundation-storage*
*Completed: 2026-02-18*

## Self-Check: PASSED

- src/rag_server/vector_store/__init__.py: FOUND
- src/rag_server/vector_store/qdrant.py: FOUND
- scripts/verify_storage.py: FOUND
- 01-03-SUMMARY.md: FOUND
- Commit 15ce778 (Task 1): FOUND
- Commit 35444d9 (Task 2): FOUND
