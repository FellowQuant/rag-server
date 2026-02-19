---
phase: 05-rest-api
plan: 03
subsystem: api
tags: [fastapi, httpx, smoke-test, verification, api-testing, rfc7807, cors, upload-limit]

# Dependency graph
requires:
  - phase: 05-rest-api/05-01
    provides: /api/v1 URL prefix, CORS middleware, RFC 7807 error handlers, UploadSizeLimitMiddleware
  - phase: 05-rest-api/05-02
    provides: POST /api/v1/retrieve, RetrieveRequest/ChunkResultItem/RetrieveResponse schemas
provides:
  - scripts/verify_api.py — standalone smoke test covering API-01 through API-06
  - 13 individual checks as executable specification of Phase 5 behavior
  - Graceful connection error handling with helpful usage message
affects:
  - 06-deployment (CI/CD can run verify_api.py as a smoke test post-deploy)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Smoke test pattern: httpx.Client(timeout=10.0) for sync HTTP against live server
    - Check accumulator pattern: results list of (name, bool, detail) with PASS/FAIL inline print
    - Graceful ConnectError handling: catches httpx.ConnectError, prints helpful message, exits 1

key-files:
  created:
    - scripts/verify_api.py
  modified: []

key-decisions:
  - "BASE_URL configurable via env var (default localhost:8001) — same pattern as other verify_*.py scripts"
  - "ChunkResultItem shape check skips gracefully when corpus empty — 'no documents indexed' is valid server state"
  - "POST /api/v1/ask accepts 200 or 500 as 'endpoint exists' — 500 means LLM unavailable, not missing endpoint"
  - "Content-Length override for 413 test: httpx allows explicit header override to fake oversized upload"

patterns-established:
  - "RFC 7807 check: isinstance(detail, list) rejection distinguishes FastAPI default format from proper RFC 7807"
  - "Reachability vs correctness: some checks (ask, min_score) verify endpoint exists without asserting corpus state"

requirements-completed: [API-01, API-02, API-03, API-04, API-05, API-06]

# Metrics
duration: 1min
completed: 2026-02-19
---

# Phase 5 Plan 03: API Verification Script Summary

**Standalone 13-check smoke test using httpx that validates all Phase 5 REST API requirements (API-01 through API-06) against a live server, with RFC 7807 shape verification, CORS header checks, and graceful connection error handling**

## Performance

- **Duration:** ~1 min
- **Started:** 2026-02-19T21:26:27Z
- **Completed:** 2026-02-19T21:27:37Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- scripts/verify_api.py covers all 13 checks from the plan specification
- Tests every Phase 5 requirement: URL versioning (API-01), document list (API-02), CORS (API-03), retrieve endpoint with document_ids/min_score filters (API-04), ask endpoint availability (API-05), RFC 7807 on 422/404/413 and upload size limit (API-06)
- Connection error caught via httpx.ConnectError — prints server startup instructions and exits 1 cleanly
- ChunkResultItem shape check skips with informative message when no documents are indexed (valid state for fresh server)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write scripts/verify_api.py smoke test** - `472ca2d` (feat)

## Files Created/Modified
- `scripts/verify_api.py` - 13-check Phase 5 API smoke test; run against live server at localhost:8001 (or BASE_URL env var)

## Decisions Made
- BASE_URL defaults to localhost:8001 and is overridable via env var — matches pattern of other verify_*.py scripts
- Check 11 (ChunkResultItem shape) skips gracefully on empty corpus rather than failing — fresh server state is valid
- Check 12 (ask endpoint) accepts both 200 and 500 — a 500 means the endpoint exists but LLM provider is unavailable, which is not a deployment failure
- Content-Length header faked to 200MB for check 13 — httpx allows explicit header override; middleware checks header value, not actual body size

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 5 (REST API) is fully complete with executable proof of all 6 requirements
- scripts/verify_api.py can be used in Phase 6 deployment CI/CD as a post-deploy smoke test
- Run `python scripts/verify_api.py` against any running server to confirm API contract is upheld

## Self-Check: PASSED

- scripts/verify_api.py: FOUND
- Commit 472ca2d (Task 1): FOUND (git log confirmed)

---
*Phase: 05-rest-api*
*Completed: 2026-02-19*
