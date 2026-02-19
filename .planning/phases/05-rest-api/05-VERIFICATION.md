---
phase: 05-rest-api
verified: 2026-02-19T00:00:00Z
status: human_needed
score: 20/20 must-haves verified (automated checks pass; live server tests pending)
human_verification:
  - test: "Run verify_api.py against live server"
    expected: "13/13 checks passed, exit code 0"
    why_human: "Server requires GPU-loaded models (BGE-M3, Qwen3 reranker) and running Qdrant; cannot execute live HTTP tests in static analysis"
  - test: "POST /api/v1/retrieve with document_ids=[] returns 200 (not error)"
    expected: "Status 200, results: [], total_candidates: 0"
    why_human: "Edge case depends on Qdrant MatchAny(any=[]) runtime behavior with qdrant-client 1.16.2 — static analysis cannot confirm Qdrant server does not reject empty MatchAny filter"
  - test: "CORS + credentials combination works in browser"
    expected: "Browser allows cross-origin requests; no CORS preflight rejection"
    why_human: "allow_origins=['*'] with allow_credentials=True is technically invalid per CORS spec; Starlette may override credentials to False silently when wildcard origins are set. Browser test needed to confirm actual CORS header behavior"
  - test: "Request log emitted at INFO for every request"
    expected: "Log line format: 'GET /health 200 1.2ms' appears in server logs"
    why_human: "LoggingMiddleware implementation verified in code but actual log output requires server execution"
  - test: "POST /api/v1/documents with Content-Length: 200MB header returns 413 before body is read"
    expected: "Status 413, body has type/title/status/detail keys (RFC 7807 shape)"
    why_human: "httpx may not respect overridden Content-Length header as a fake value; behavior depends on httpx and Starlette interaction at runtime"
---

# Phase 5: REST API Verification Report

**Phase Goal:** Full document lifecycle and query operations exposed via HTTP endpoints
**Verified:** 2026-02-19
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | All existing endpoints respond at /api/v1/ prefix | VERIFIED | `main.py:230-236` — all three `include_router()` calls use `prefix="/api/v1"` |
| 2 | GET /health responds 200 at root path (not moved) | VERIFIED | `main.py:239-242` — `@app.get("/health")` registered directly on app, not in any router |
| 3 | GET /documents (old path) returns 404 — hard cut confirmed | VERIFIED | No `@app.get("/documents")` route at root; documents router mounted only at `/api/v1` |
| 4 | CORS headers present on all /api/v1/ responses | VERIFIED (code) | `main.py:220-226` — `CORSMiddleware(allow_origins=["*"])` added last (outermost LIFO) |
| 5 | POST /api/v1/documents with Content-Length > 100MB returns 413 RFC 7807 | VERIFIED (code) | `middleware.py:49-70` — `UploadSizeLimitMiddleware.dispatch()` checks header, returns RFC 7807 JSON with status 413 |
| 6 | HTTPException returns RFC 7807 shape {type, title, status, detail} | VERIFIED | `errors.py:41-44` — `http_exception_handler` calls `_problem()` which returns RFC 7807 shape |
| 7 | 422 validation errors return RFC 7807 shape (not FastAPI default list) | VERIFIED | `errors.py:47-53` — `validation_exception_handler` joins errors into single string, returns `_problem(422, detail)` |
| 8 | Request logs emitted at INFO: method, path, status, duration ms | VERIFIED (code) | `middleware.py:27-33` — `LoggingMiddleware` logs `"%s %s %d %.1fms"` format |
| 9 | Server starts successfully with version 0.5.0 in OpenAPI /docs | VERIFIED | `main.py:208` — `FastAPI(..., version="0.5.0")` |
| 10 | POST /api/v1/retrieve returns {query, results: [], total_candidates: int} | VERIFIED | `retrieve.py:58-79` — returns `RetrieveResponse(query=..., results=[...], total_candidates=...)` |
| 11 | POST /api/v1/retrieve with document_ids filter scopes results | VERIFIED | `engine.py:170-189` — builds `qdrant_filter` + pre-fetches `allowed_chunk_ids` when `document_ids is not None` |
| 12 | /retrieve results include all 5 scores and full citation metadata | VERIFIED | `retrieve.py:61-76` — all five scores (`bm25_score`, `dense_score`, `sparse_score`, `rrf_score`, `reranker_score`) plus all citation fields mapped from `ChunkResult` |
| 13 | POST /api/v1/retrieve with min_score filters out chunks below threshold | VERIFIED | `engine.py:275-276` — `if min_score is not None and reranker_score < min_score: continue` |
| 14 | POST /api/v1/retrieve with invalid body returns 422 RFC 7807 shape | VERIFIED | `errors.py:47-53` wired via `register_exception_handlers(app)` in `main.py:213` |
| 15 | RetrievalEngine.search() accepts document_ids=None (backward compatible) | VERIFIED | `engine.py:132` — `document_ids: list[str] | None = None`; `ask.py:70-73` calls `search()` without `document_ids` |
| 16 | verify_api.py runs to completion (exit 0) against live server | HUMAN NEEDED | Script exists, all 13 checks implemented correctly, connection error handled — live execution required |
| 17 | Script confirms /health at root returns 200 | VERIFIED (code) | `verify_api.py:53-58` — check 1 tests `GET /health` → status 200 + `{"status": "ok"}` |
| 18 | Script confirms CORS header present on /api/v1/documents | VERIFIED (code) | `verify_api.py:83-92` — check 4 tests `access-control-allow-origin: *` |
| 19 | Script confirms POST /api/v1/retrieve returns 200 with RetrieveResponse shape | VERIFIED (code) | `verify_api.py:146-163` — check 8 validates `query`, `results`, `total_candidates` keys |
| 20 | Script confirms GET /documents (old path) returns 404 | VERIFIED (code) | `verify_api.py:63-68` — check 2 expects status 404 |

**Score:** 19/20 truths fully verified via code; 1 requires live server execution

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/rag_server/api/middleware.py` | LoggingMiddleware and UploadSizeLimitMiddleware | VERIFIED | Both classes present, substantive, wired via `add_middleware()` in `main.py` |
| `src/rag_server/api/errors.py` | RFC 7807 exception handlers + register_exception_handlers() | VERIFIED | All three handlers present, `register_exception_handlers()` called in `main.py:213` |
| `src/rag_server/config.py` | Settings.max_upload_size field (100MB default) | VERIFIED | `config.py:17` — `max_upload_size: int = Field(default=100 * 1024 * 1024)` |
| `src/rag_server/main.py` | App with /api/v1 routers, middleware stack, RFC 7807 handlers | VERIFIED | All three routers mounted at `/api/v1`; correct LIFO middleware order |
| `src/rag_server/api/retrieve.py` | POST /retrieve router | VERIFIED | `router = APIRouter(prefix="", tags=["retrieve"])`; POST `/retrieve` route registered |
| `src/rag_server/api/schemas.py` | RetrieveRequest, ChunkResultItem, RetrieveResponse | VERIFIED | All three classes present with correct fields including all 5 score fields |
| `src/rag_server/vector_store/qdrant.py` | query_dense/query_sparse with optional query_filter | VERIFIED | Both methods have `query_filter: Filter | None = None` with backward-compatible defaults |
| `src/rag_server/retrieval/engine.py` | search() with optional document_ids param | VERIFIED | `document_ids: list[str] | None = None` param; full filter logic implemented |
| `scripts/verify_api.py` | End-to-end API smoke test | VERIFIED | 13 numbered checks covering all API requirements; graceful connection error handling |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `main.py` | `api/middleware.py` | `app.add_middleware(LoggingMiddleware)` and `app.add_middleware(UploadSizeLimitMiddleware, ...)` | VERIFIED | `main.py:218-219` — both middleware classes imported and added |
| `main.py` | `api/errors.py` | `register_exception_handlers(app)` | VERIFIED | `main.py:213` — called before routers |
| `main.py` | `include_router` calls | `prefix="/api/v1"` on all three routers | VERIFIED | `main.py:230, 233, 236` — all three use `prefix="/api/v1"` |
| `api/retrieve.py` | `retrieval/engine.py` | `engine.search(query, top_k, min_score, document_ids=body.document_ids)` | VERIFIED | `retrieve.py:43-48` — all params including `document_ids` passed |
| `retrieval/engine.py` | `vector_store/qdrant.py` | `query_dense(..., query_filter=qdrant_filter)` and `query_sparse(..., query_filter=qdrant_filter)` | VERIFIED | `engine.py:196-197` — both calls pass `query_filter=qdrant_filter` |
| `retrieval/engine.py` | SQLite Chunk table | `select(Chunk.id).where(Chunk.document_id.in_(document_ids))` | VERIFIED | `engine.py:180-183` — pre-fetches allowed_chunk_ids from SQLite |
| `main.py` | `api/retrieve.py` | `app.include_router(retrieve_router, prefix="/api/v1")` | VERIFIED | `main.py:235-236` — retrieve_router imported and registered |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| API-01 | 05-01, 05-03 | User can ingest documents via POST endpoint with file upload | SATISFIED | `documents.py:56-153` — POST `""` on `/documents` router → `/api/v1/documents`; returns 202 `DocumentUploadResponse` |
| API-02 | 05-01, 05-03 | User can list all documents with metadata and indexing status via GET endpoint | SATISFIED | `documents.py:181-204` — GET `""` returns `DocumentListResponse{documents, total}` |
| API-03 | 05-01, 05-03 | User can delete documents and their associated chunks/embeddings via DELETE endpoint | SATISFIED | `documents.py:207-255` — DELETE `/{document_id}` removes SQLite row (CASCADE chunks) + Qdrant vectors + uploaded file |
| API-04 | 05-02, 05-03 | User can query knowledge base via retrieve endpoint returning ranked chunks with citations | SATISFIED | `retrieve.py` POST `/retrieve` returns `RetrieveResponse{query, results[ChunkResultItem], total_candidates}`; document_ids filter and min_score threshold both implemented |
| API-05 | 05-01, 05-03 | User can query knowledge base via ask endpoint returning LLM-synthesized answers with citations | SATISFIED | `ask.py` POST `/ask` at `/api/v1/ask`; streaming and non-streaming variants; calls RetrievalEngine.search() + SynthesisEngine |
| API-06 | 05-01, 05-03 | User can check document indexing status via status endpoint | SATISFIED | `documents.py:156-178` — GET `/{document_id}` returns `DocumentStatusResponse` with full status + metadata including `indexed_at` |

All 6 requirement IDs from all three plans are accounted for. No orphaned requirements detected.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | No TODO/FIXME/placeholder/stub returns detected in any modified file | — | — |

The only `return []` in `qdrant.py:218` is an intentional guard for empty sparse vectors (not a stub), documented with a comment: "Returns empty list if sparse_indices is empty (avoids Qdrant error on empty sparse vector)".

### Human Verification Required

#### 1. Full API Smoke Test via verify_api.py

**Test:** Start server with `uvicorn rag_server.main:app --port 8001`, then run `python scripts/verify_api.py`
**Expected:** `13/13 checks passed`, exit code 0
**Why human:** Server requires BGE-M3 embedder, Qwen3 reranker (both GPU-loaded), SQLite database, and running Qdrant instance. Cannot execute live HTTP requests in static code analysis.

#### 2. document_ids=[] Empty List Edge Case

**Test:** `POST /api/v1/retrieve` with `{"query": "test", "document_ids": []}`
**Expected:** Status 200, `results: []`, `total_candidates: 0` (empty but not an error)
**Why human:** The engine uses `if document_ids is not None` (true for `[]`), which triggers `MatchAny(any=[])` filter in Qdrant. Whether qdrant-client 1.16.2 accepts an empty `any=[]` list without raising a validation error requires runtime confirmation. SQLAlchemy `IN ([])` is safe (generates `WHERE 1=0`), but the Qdrant path is uncertain.

#### 3. CORS Wildcard + Credentials Combination

**Test:** Issue a cross-origin request with credentials from a browser
**Expected:** `Access-Control-Allow-Origin: *` header present; requests succeed
**Why human:** The CORS spec forbids `Access-Control-Allow-Origin: *` with `Access-Control-Allow-Credentials: true`. Starlette's `CORSMiddleware` implementation may silently drop `allow_credentials=True` when `allow_origins=["*"]` is set (it does this in some versions). A browser-based test is needed to confirm the actual behavior — particularly whether the `Access-Control-Allow-Origin: *` header is actually emitted (for non-credentialed requests from JS clients, it should be fine regardless).

#### 4. Request Logging Format Confirmation

**Test:** Send any request to the server, observe server log output
**Expected:** Log line at INFO level: `"GET /health 200 1.2ms"` (method, path, status, duration)
**Why human:** `LoggingMiddleware` code is correct but the logger must be configured at INFO level in the running environment. Logging configuration lives outside the verified files.

#### 5. 413 Upload Size Limit via fake Content-Length Header

**Test:** Run check 13 from `verify_api.py` (sends 1-byte body with `Content-Length: 209715200`)
**Expected:** Status 413, RFC 7807 body with `type/title/status/detail` keys
**Why human:** httpx may recompute `Content-Length` from the actual body rather than using the explicitly set header value, depending on the httpx version in the virtualenv. The middleware checks the header value — if httpx overrides the header, the test would not trigger the 413. Confirm httpx preserves the manually set `Content-Length` header.

### Gaps Summary

No blocking gaps found. All 20 must-have truths verified at the code level:

- All three API subplans (infrastructure, retrieve endpoint, verification script) are fully implemented
- No stubs, placeholders, or incomplete wiring detected
- All 6 requirements (API-01 through API-06) have concrete, substantive implementations
- The verify_api.py script covers all 13 checks including RFC 7807 shape validation, CORS presence, old-path 404 confirmation, and document_ids filter testing

The 5 human verification items are all runtime confirmation tasks. The code is structurally complete and correctly wired. The `human_needed` status reflects that live server execution is required to confirm no runtime-specific surprises (Qdrant MatchAny edge case, CORS credentials behavior, httpx Content-Length override).

---

_Verified: 2026-02-19_
_Verifier: Claude (gsd-verifier)_
