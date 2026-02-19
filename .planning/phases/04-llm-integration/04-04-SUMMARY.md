---
phase: 04-llm-integration
plan: "04"
subsystem: api
tags: [fastapi, sse, streaming, sse_starlette, synthesis, llm, ask-endpoint]

# Dependency graph
requires:
  - phase: 04-01
    provides: LLMConfig, LLMSettings, get_llm_settings from llm.yaml
  - phase: 04-02
    provides: LLMProvider ABC, create_provider factory, VLLMProvider, LlamaCppProvider, BedrockProvider
  - phase: 04-03
    provides: SynthesisEngine with synthesize(), stream_synthesize(), parse_result()
  - phase: 03-retrieval-engine
    provides: RetrievalEngine.search() returning RetrievalResult with ChunkResult list
provides:
  - POST /ask endpoint (src/rag_server/api/ask.py) with streaming=true SSE and streaming=false JSON modes
  - SynthesisEngine wired into FastAPI lifespan as app.state.synthesis_engine
  - LLMProvider wired into FastAPI lifespan as app.state.llm_provider
  - scripts/verify_llm.py end-to-end smoke test for Phase 4 pipeline
affects: [05-retrieval-api, 06-evaluation]

# Tech tracking
tech-stack:
  added: [sse_starlette.EventSourceResponse]
  patterns:
    - response_model=None on FastAPI routes returning non-Pydantic responses (EventSourceResponse)
    - SSE event_generator async generator pattern for streaming LLM tokens
    - Lifespan wiring: provider and synthesis engine initialized once at startup, stored on app.state

key-files:
  created:
    - src/rag_server/api/ask.py
    - scripts/verify_llm.py
  modified:
    - src/rag_server/main.py

key-decisions:
  - "response_model=None on POST /ask — FastAPI cannot infer Pydantic response model from AskResponse | EventSourceResponse union type"
  - "streaming=True is the default query param — users get SSE by default, opt-in to non-streaming"
  - "event_generator re-applies context_chunks and token budget to reconstruct selected chunks for done event — synthesis_engine does not expose its selected-chunks list"

patterns-established:
  - "SSE streaming pattern: yield event=token per delta, yield event=done with JSON AskResponse payload, yield event=error on exception"
  - "Non-streaming path: await synthesis_engine.synthesize() returns AskResponse directly as JSON"
  - "Smoke test pattern: unit portion (config/schema/endpoint) runs without server; live portion gracefully skips if server offline"

requirements-completed: [LLM-01, LLM-02, LLM-03]

# Metrics
duration: 2min
completed: 2026-02-19
---

# Phase 4 Plan 04: /ask Endpoint and Lifespan Wiring Summary

**POST /ask endpoint with SSE streaming and non-streaming modes, SynthesisEngine wired into FastAPI lifespan via app.state, completing the full Phase 4 retrieval-synthesis pipeline**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-19T19:51:23Z
- **Completed:** 2026-02-19T19:53:30Z
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- POST /ask endpoint (src/rag_server/api/ask.py) supporting both SSE streaming (event=token, event=done, event=error) and synchronous JSON modes via `streaming` query parameter
- FastAPI lifespan updated to initialize LLMProvider and SynthesisEngine at startup, stored on app.state for request handler access
- scripts/verify_llm.py smoke test verifies the full Phase 4 pipeline (config, schema, endpoint registration, provider factory, synthesis engine, citation regex) — 5/5 pass without a live LLM server

## Task Commits

Each task was committed atomically:

1. **Task 1: POST /ask endpoint with SSE streaming and non-streaming variants** - `09162a8` (feat)
2. **Task 2: FastAPI lifespan wiring and end-to-end smoke test** - `bf8e40b` (feat)

## Files Created/Modified

- `src/rag_server/api/ask.py` - POST /ask endpoint with EventSourceResponse streaming and direct JSON non-streaming; retrieves via app.state.retrieval_engine, synthesizes via app.state.synthesis_engine
- `src/rag_server/main.py` - Added LLM imports, lifespan SynthesisEngine initialization, ask router mount, version bumped to 0.4.0
- `scripts/verify_llm.py` - End-to-end smoke test: config loading, AskResponse schema round-trip, endpoint route registration, provider factory, SynthesisEngine + citation regex, optional live /ask test

## Decisions Made

- `response_model=None` added to the `@router.post("/ask")` decorator — FastAPI raises `FastAPIError` when it encounters `AskResponse | EventSourceResponse` as return type annotation since `EventSourceResponse` is not a Pydantic model type
- `streaming=True` is the default — users get SSE by default without extra query param
- The `event_generator()` in streaming mode re-applies `context_chunks` and `_apply_token_budget()` to reconstruct the `selected` chunks list for the `done` event payload; this mirrors what `stream_synthesize()` does internally since `SynthesisEngine` does not expose its selected chunks

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added response_model=None to POST /ask decorator**

- **Found during:** Task 1 (POST /ask endpoint with SSE streaming and non-streaming variants)
- **Issue:** FastAPI raised `FastAPIError: Invalid args for response field!` when the route return type annotation was `AskResponse | EventSourceResponse`. FastAPI tries to build a Pydantic response model from the return type, but `EventSourceResponse` is not a Pydantic model.
- **Fix:** Added `response_model=None` to the `@router.post("/ask", ...)` decorator to disable automatic response model inference.
- **Files modified:** `src/rag_server/api/ask.py`
- **Verification:** `from rag_server.api.ask import router` succeeds; route registration and verification command pass
- **Committed in:** `09162a8` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug fix)
**Impact on plan:** Necessary fix for correct FastAPI route registration. No scope creep.

## Issues Encountered

None beyond the response_model fix documented above.

## User Setup Required

None - no external service configuration required for the unit/import tests. A running vLLM or LlamaCpp server is required for the optional live /ask test in verify_llm.py (gracefully skipped if offline).

## Next Phase Readiness

- Full Phase 4 pipeline complete: /ask endpoint wired to retrieval and synthesis engines
- Phase 5 (Retrieval API) can add retrieval-only endpoints using the same app.state.retrieval_engine pattern
- Phase 6 (Evaluation) can POST to /ask and compare answers against ground-truth

---
*Phase: 04-llm-integration*
*Completed: 2026-02-19*
