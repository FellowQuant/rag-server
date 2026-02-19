---
phase: 03-retrieval-engine
plan: "02"
subsystem: retrieval
tags: [bm25, rank-bm25, numpy, ipc, multiprocessing, asyncio, background-task, hot-swap]

# Dependency graph
requires:
  - phase: 02-document-ingestion-pipeline
    provides: worker process architecture with multiprocessing.Queue, SQLite chunk storage
  - phase: 01-foundation-storage
    provides: async_session, SQLite models (Chunk, Document)

provides:
  - BM25Manager class with async build(), sync search(), load_from_disk(), chunk_count
  - Atomic pickle persistence to DATA_DIR/bm25.pkl with tmp-rename pattern
  - Hot-swap BM25 index under asyncio.Lock (reads never blocked during rebuild)
  - WorkerManager result_queue property for worker->FastAPI IPC
  - FastAPI lifespan _poll_bm25_updates background asyncio.Task
  - BM25 index initialized at startup (from disk or SQLite) and auto-updated after ingestion

affects: [04-synthesis-api, 03-03, 03-04]

# Tech tracking
tech-stack:
  added: [rank-bm25>=0.2.2, numpy>=1.26.0]
  patterns:
    - asyncio.Lock for hot-swap with GIL-safe reference assignment (readers never blocked)
    - Atomic file write via tmp-rename (write to .tmp, then os.rename to target)
    - asyncio.to_thread for CPU-bound BM25 build operations
    - multiprocessing.Queue for bidirectional IPC between worker process and FastAPI
    - Background asyncio.Task polling a multiprocessing.Queue via asyncio.to_thread(_get_nowait)
    - Disk-first startup (load pickle if exists, else rebuild from SQLite)

key-files:
  created:
    - src/rag_server/retrieval/__init__.py
    - src/rag_server/retrieval/bm25_manager.py
  modified:
    - src/rag_server/worker/manager.py
    - src/rag_server/worker/process.py
    - src/rag_server/worker/pipeline.py
    - src/rag_server/main.py
    - pyproject.toml

key-decisions:
  - "BM25 corpus is global (all indexed chunks), not per-document -- required for cross-document retrieval"
  - "Tokenizer is lowercase whitespace split -- LaTeX chunks have naturally low BM25 weight, acceptable for v1"
  - "asyncio.Lock only held during index reference swap, not during search -- GIL makes reference assignment atomic"
  - "result_queue.put_nowait() for both 'indexed' and 'indexed_partial' statuses -- both have chunks in SQLite"
  - "rank-bm25 and numpy added to pyproject.toml (were installed but undeclared)"
  - "BM25 poll task cancelled before worker stop in shutdown sequence -- avoids race on result_queue drain"

patterns-established:
  - "Worker->FastAPI IPC: multiprocessing.Queue with {'type': ..., 'document_id': ...} message schema"
  - "Background task polling: asyncio.to_thread(queue.get_nowait) + asyncio.sleep(0.5) on empty"
  - "BM25 hot-swap: asyncio.Lock during assignment, GIL protects concurrent reads"

requirements-completed: [RETR-04]

# Metrics
duration: 3min
completed: 2026-02-19
---

# Phase 3 Plan 02: BM25 Keyword Index Subsystem Summary

**BM25 keyword index with asyncio hot-swap, multiprocessing IPC result_queue, and FastAPI background poll task that auto-rebuilds on ingestion signals**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-19T17:00:19Z
- **Completed:** 2026-02-19T17:03:38Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- BM25Manager class with async build() from SQLite, sync search() returning [(chunk_id, score)], atomic pickle persistence, and hot-swap under asyncio.Lock
- WorkerManager gains result_queue (worker->FastAPI IPC): emitted after every successful "indexed"/"indexed_partial" pipeline run
- FastAPI lifespan initializes BM25 from disk (fast path) or rebuilds from SQLite, stores on app.state.bm25_manager, and starts _poll_bm25_updates background task that rebuilds BM25 on each signal

## Task Commits

Each task was committed atomically:

1. **Task 1: BM25Manager class with build, search, persist, and hot-swap** - `1e6d5aa` (feat)
2. **Task 2: result_queue IPC — WorkerManager, worker process, and FastAPI lifespan** - `908ddde` (feat)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified

- `src/rag_server/retrieval/__init__.py` - Package marker for retrieval subsystem
- `src/rag_server/retrieval/bm25_manager.py` - BM25Manager: build from SQLite, search, load_from_disk, atomic pickle persistence, hot-swap via asyncio.Lock
- `src/rag_server/worker/manager.py` - Added _result_queue multiprocessing.Queue and result_queue property
- `src/rag_server/worker/process.py` - worker_main now accepts result_queue as second arg, passes to run_pipeline
- `src/rag_server/worker/pipeline.py` - run_pipeline accepts result_queue=None; emits put_nowait signal after successful indexing
- `src/rag_server/main.py` - Imports BM25Manager; _poll_bm25_updates function; lifespan init + poll task startup/shutdown
- `pyproject.toml` - Added rank-bm25>=0.2.2 and numpy>=1.26.0

## Decisions Made

- BM25 corpus is global (all indexed chunks across all documents) — required for RETR-05 cross-document retrieval
- Tokenizer is lowercase whitespace split; LaTeX tokens have naturally low BM25 weight in v1 (acceptable trade-off)
- asyncio.Lock held only during index reference assignment, not during search; Python's GIL makes reference assignment atomic so concurrent reads are safe
- BM25 signal emitted for both "indexed" and "indexed_partial" pipeline outcomes — both statuses have chunks in SQLite
- rank-bm25 and numpy added to pyproject.toml; they were installed in the environment but undeclared

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added rank-bm25 and numpy to pyproject.toml**
- **Found during:** Task 1 (BM25Manager class)
- **Issue:** rank-bm25 and numpy used in bm25_manager.py but not declared in project dependencies
- **Fix:** Added `rank-bm25>=0.2.2` and `numpy>=1.26.0` to pyproject.toml dependencies
- **Files modified:** pyproject.toml
- **Verification:** `python -c "import rank_bm25; import numpy"` exits 0
- **Committed in:** 1e6d5aa (Task 1 commit)

**2. [Rule 1 - Bug] Removed duplicate `import multiprocessing` in main.py**
- **Found during:** Task 2 (main.py update)
- **Issue:** Adding `import multiprocessing` after imports block created a duplicate (already imported at top)
- **Fix:** Removed the redundant import line, kept original at top of file
- **Files modified:** src/rag_server/main.py
- **Verification:** `python -m py_compile main.py` exits 0; no "redefined-import" lint error
- **Committed in:** 908ddde (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 bug)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered

None - plan executed cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- BM25 index subsystem complete and ready for RETR-04 integration
- app.state.bm25_manager available to retrieval endpoints in 03-03 and 03-04
- BM25.search() returns [] when empty, safe to call before any documents are indexed
- No blockers for Phase 3 Plan 3

---
*Phase: 03-retrieval-engine*
*Completed: 2026-02-19*
