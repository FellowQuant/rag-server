---
phase: 02-document-ingestion-pipeline
plan: "04"
subsystem: api
tags: [fastapi, pydantic, aiofiles, multiprocessing, qdrant, sqlite, aiosqlite]

# Dependency graph
requires:
  - phase: 02-document-ingestion-pipeline
    provides: WorkerManager, IngestionJob, QdrantStore, SQLAlchemy models, engine
  - phase: 01-foundation-storage
    provides: async SQLite engine, QdrantStore schema, Document/Chunk models
provides:
  - FastAPI app with lifespan (WorkerManager start/stop, QdrantStore init, SQLite table creation)
  - POST /documents — multipart upload, SHA-256 dedup, 202/409/415 responses
  - GET /documents/{id} — status polling with full metadata
  - GET /documents — document list ordered by created_at desc
  - DELETE /documents/{id} — cascading delete (file + SQLite + Qdrant vectors)
  - Pydantic schemas: DocumentUploadResponse, DocumentStatusResponse, DocumentListItem, DocumentListResponse
  - Integration smoke test: scripts/verify_ingestion.py (5-step end-to-end verification)
affects: [03-retrieval-api, 04-llm-synthesis, 05-citations]

# Tech tracking
tech-stack:
  added: [aiofiles (async file writes), python-multipart (multipart form upload parsing)]
  patterns: [APIRouter with prefix, FastAPI lifespan context manager, explicit db.commit() before cross-process enqueue, SHA-256 hash as filename for dedup storage]

key-files:
  created:
    - src/rag_server/api/__init__.py
    - src/rag_server/api/schemas.py
    - src/rag_server/api/documents.py
    - src/rag_server/main.py
    - scripts/verify_ingestion.py
  modified:
    - src/rag_server/config.py

key-decisions:
  - "multiprocessing.set_start_method('spawn', force=True) called at top of main.py before any CUDA imports — prevents fork-after-CUDA undefined behavior on Linux"
  - "Explicit await db.commit() before worker_manager.enqueue() — guarantees Document row visible in SQLite before worker process reads it (get_db() auto-commit is too late)"
  - "Explicit await db.commit() before qdrant_store.delete_document() — ensures SQLite is authoritative; Qdrant orphan vectors acceptable on Qdrant failure"
  - "Files saved as {sha256_hash}{ext} in DATA_DIR/uploads/ — hash-based naming enables O(1) dedup check and easy cleanup on delete"
  - "config.ensure_data_dirs() creates uploads/ subdirectory — previously only created qdrant/"

patterns-established:
  - "API router pattern: APIRouter(prefix='/documents') mounted in main.py via app.include_router()"
  - "Lifespan pattern: startup initializes QdrantStore + WorkerManager, stores on app.state; shutdown calls stop()/close()/dispose()"
  - "Commit-before-IPC pattern: explicit db.commit() before any cross-process or external-store operation to maintain SQLite as authoritative store"

requirements-completed: [INGEST-06]

# Metrics
duration: 3min
completed: 2026-02-19
---

# Phase 2 Plan 04: REST API Layer Summary

**FastAPI REST API with 4 document lifecycle endpoints, WorkerManager lifespan wiring, and 5-step end-to-end integration smoke test**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-19T14:47:37Z
- **Completed:** 2026-02-19T14:50:41Z
- **Tasks:** 2 auto tasks complete; 1 checkpoint:human-verify pending user approval
- **Files modified:** 6

## Accomplishments
- 4-endpoint documents API (POST/GET/GET-list/DELETE) wired to WorkerManager and QdrantStore
- FastAPI lifespan manages WorkerManager subprocess and Qdrant client lifecycle
- multiprocessing.set_start_method("spawn") called before all CUDA imports in main.py
- Integration smoke test covers full upload→index→poll→verify SQLite→verify Qdrant→delete cycle

## Task Commits

Each task was committed atomically:

1. **Task 1: Pydantic schemas, documents router, and FastAPI app with lifespan** - `1545994` (feat)
2. **Task 2: Integration smoke test script** - `68bd206` (feat)

**Plan metadata:** pending (awaiting checkpoint approval)

## Files Created/Modified
- `src/rag_server/api/__init__.py` — package marker for api subpackage
- `src/rag_server/api/schemas.py` — Pydantic models (DocumentUploadResponse, DocumentStatusResponse, DocumentListItem, DocumentListResponse)
- `src/rag_server/api/documents.py` — APIRouter with POST /documents (202/409/415), GET /documents/{id}, GET /documents, DELETE /documents/{id}
- `src/rag_server/main.py` — FastAPI app with lifespan; set_start_method("spawn") before CUDA imports; mounts documents router
- `src/rag_server/config.py` — ensure_data_dirs() now creates uploads/ subdirectory
- `scripts/verify_ingestion.py` — 5-step integration smoke test (upload ipynb, poll status, verify SQLite, verify Qdrant, delete + verify cleanup)

## Decisions Made
- multiprocessing.set_start_method("spawn", force=True) is the first call in main.py before any CUDA-related imports — required for Linux CUDA fork safety
- Explicit await db.commit() before worker_manager.enqueue() — ensures Document row is durable in SQLite before the worker subprocess tries to read it
- Explicit await db.commit() before qdrant_store.delete_document() — SQLite is authoritative; if Qdrant delete fails, vectors become orphaned but the document no longer exists in the authoritative store
- Files stored as {sha256_hash}{ext} — enables deterministic dedup without a separate lookup; makes DELETE reconstruction trivial

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All dependencies (aiofiles, python-multipart) were already in pyproject.toml from prior planning. The api/ directory did not exist and was created as part of the plan.

## User Setup Required

To run the full integration smoke test:
1. Start Qdrant: `docker compose up -d qdrant`
2. Apply migrations: `alembic upgrade head`
3. Install dependencies: `pip install -e .`
4. Start server: `uvicorn rag_server.main:app --reload`
5. Run: `python scripts/verify_ingestion.py` (expects PASS output)

Note: Full test requires BGE-M3 model download (~2GB) to complete the indexing step.

## Next Phase Readiness
- Phase 2 (Document Ingestion Pipeline) is structurally complete — all 4 plans implemented
- Phase 3 (Retrieval API) can begin: it depends on app.state.qdrant_store and the Qdrant collection schema established in Phase 1-2
- The /documents endpoints provide the ingestion surface; Phase 3 will add /search endpoints
- Checkpoint human-verify required before Phase 2 is officially closed

---
*Phase: 02-document-ingestion-pipeline*
*Completed: 2026-02-19*
