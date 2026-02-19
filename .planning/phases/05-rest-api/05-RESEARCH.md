# Phase 5: REST API - Research

**Researched:** 2026-02-19
**Domain:** FastAPI middleware, RFC 7807 error handling, API versioning, endpoint restructuring
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### API versioning & URL structure
- **All endpoints move to /api/v1/ prefix** — /documents → /api/v1/documents, /ask → /api/v1/ask, /retrieve → /api/v1/retrieve
- **Hard cut** — old paths (e.g. /documents) return 404; no redirects needed (no external consumers yet)
- **OpenAPI docs always enabled** — /docs (Swagger UI) and /redoc exposed unconditionally
- **Health stays at root** — /health remains at root for infra/Docker healthchecks; NOT moved to /api/v1/

#### Authentication & middleware
- **No authentication** — open API; trust handled at network level (local server)
- **CORS: allow all origins** — CORSMiddleware with allow_origins=["*"] for browser client compatibility
- **Upload size limit: 100MB default** — configurable via MAX_UPLOAD_SIZE env var; reject oversized uploads with 413 before reading body
- **Request logging middleware** — log all requests: method, path, status code, duration (ms)

#### Retrieve endpoint design
- **Full ChunkResult shape** — POST /api/v1/retrieve returns all 5 scores (bm25, dense, sparse, rrf, reranker) + full metadata (source_filename, page_number, section_heading, chunk_type) + content + display_content
- **Optional document_ids filter** — request body accepts optional `document_ids: list[str]` to scope retrieval to specific documents; omit for global search
- **Optional min_score threshold** — optional `min_score: float` param (0.0–1.0) to filter out weak results before returning
- **top_k default:** Claude's Discretion — recommend top_k=10 default (same as /ask) with caller override; /retrieve consumers can pass higher values explicitly

#### Error response format
- **RFC 7807 Problem Details for all errors** — `{ type: str, title: str, status: int, detail: str }` shape across all HTTP errors
- **422 validation errors also normalized to RFC 7807** — consistent shape everywhere; MCP client needs only one error parser
- **500 errors always expose exception message** — local server, full traceability more useful than security masking

### Claude's Discretion
- `top_k` default for /retrieve endpoint (recommend 10, same as /ask)

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| API-01 | User can ingest documents via POST endpoint with file upload | Existing POST /documents moves to /api/v1/documents; already implemented in Phase 2 |
| API-02 | User can list all documents with metadata and indexing status via GET endpoint | Existing GET /documents moves to /api/v1/documents; already implemented in Phase 2 |
| API-03 | User can delete documents and their associated chunks/embeddings via DELETE endpoint | Existing DELETE /documents/{id} moves to /api/v1/documents/{id}; already implemented in Phase 2 |
| API-04 | User can query the knowledge base via retrieve endpoint returning ranked chunks with citations | New POST /api/v1/retrieve endpoint; calls RetrievalEngine.search() with optional document_ids + min_score |
| API-05 | User can query the knowledge base via ask endpoint returning LLM-synthesized answers with citations | Existing POST /ask moves to /api/v1/ask; already implemented in Phase 4 |
| API-06 | User can check document indexing status via status endpoint | Existing GET /documents/{id} moves to /api/v1/documents/{id}; already implemented in Phase 2 |
</phase_requirements>

## Summary

Phase 5 is primarily a restructuring and hardening phase — most business logic already exists. The existing document endpoints live at `/documents` (Phase 2) and the ask endpoint lives at `/ask` (Phase 4). Both must move under `/api/v1/`. The only net-new endpoint is `POST /api/v1/retrieve`, which calls the existing `RetrievalEngine.search()` and returns raw `ChunkResult` objects serialized to JSON.

The critical new capabilities are: (1) the `/api/v1/` prefix applied to all existing routers via `include_router(router, prefix="/api/v1")`; (2) three middleware additions (CORS, request logging, upload size limit); (3) RFC 7807 Problem Details error handlers overriding FastAPI's defaults for all error types including 422; and (4) the retrieve endpoint with `document_ids` filter support, which requires adding a `document_ids` parameter to `RetrievalEngine.search()` and propagating it to both the Qdrant queries (via `query_filter`) and BM25 post-filter.

The `document_ids` filter is the most technically complex piece: BM25Manager does not support filtering natively (it is a global in-memory index), so BM25 results must be filtered post-retrieval using the chunk's `document_id` stored in `corpus_ids`. Qdrant supports filtering natively via `query_filter=Filter(must=[FieldCondition(key="document_id", match=MatchAny(any=doc_ids))])`.

**Primary recommendation:** Restructure via `include_router` prefix, not by modifying router prefixes. Add middleware with `add_middleware()` in the correct order (LIFO). Override FastAPI's exception handlers with RFC 7807 responses. Add `document_ids` parameter to `RetrievalEngine.search()` with split-strategy filtering.

## Existing Codebase Inventory

### What Exists Today

| Endpoint | File | Current Path | Target Path |
|----------|------|-------------|-------------|
| POST upload | `src/rag_server/api/documents.py` | `/documents` | `/api/v1/documents` |
| GET status | `src/rag_server/api/documents.py` | `/documents/{id}` | `/api/v1/documents/{id}` |
| GET list | `src/rag_server/api/documents.py` | `/documents` | `/api/v1/documents` |
| DELETE document | `src/rag_server/api/documents.py` | `/documents/{id}` | `/api/v1/documents/{id}` |
| POST ask | `src/rag_server/api/ask.py` | `/ask` | `/api/v1/ask` |
| GET health | `src/rag_server/main.py` inline | `/health` | `/health` (unchanged) |
| POST retrieve | (does not exist) | — | `/api/v1/retrieve` (NEW) |

### Router Prefix Analysis (HIGH confidence — empirically verified)

The existing routers have these prefixes:
- `documents.py`: `router = APIRouter(prefix="/documents", tags=["documents"])`
- `ask.py`: `router = APIRouter(prefix="", tags=["ask"])` — the `/ask` path is on the route decorator itself

Current `main.py` registration:
```python
app.include_router(documents_router)   # → /documents
app.include_router(ask_router)         # → /ask
```

Target registration:
```python
app.include_router(documents_router, prefix="/api/v1")   # → /api/v1/documents
app.include_router(ask_router, prefix="/api/v1")         # → /api/v1/ask
```

**Verified empirically**: FastAPI stacks prefixes: router prefix + include_router prefix. `APIRouter(prefix="/documents")` included with `prefix="/api/v1"` yields `/api/v1/documents`. This is a one-line change per `include_router` call in `main.py`.

### Schemas Already Defined

`src/rag_server/api/schemas.py` already has:
- `DocumentUploadResponse`, `DocumentStatusResponse`, `DocumentListItem`, `DocumentListResponse`
- `AskRequest`, `AskResponse`, `SourceItem`

Phase 5 adds: `RetrieveRequest`, `ChunkResultItem`, `RetrieveResponse` (serializing `ChunkResult` dataclass fields).

## Standard Stack

### Core (all already in pyproject.toml — no new dependencies needed)

| Library | Version (installed) | Purpose | Role in Phase 5 |
|---------|---------------------|---------|-----------------|
| fastapi | 0.129.0 | Web framework | Routing, middleware, exception handlers |
| starlette | 0.49.3 | ASGI foundation | `BaseHTTPMiddleware`, `CORSMiddleware` |
| pydantic | (fastapi dep) | Schema validation | `RetrieveRequest`, `ChunkResultItem` |
| pydantic-settings | 2.x | Config from env | `MAX_UPLOAD_SIZE` env var |
| uvicorn | 0.34.x | ASGI server | No changes needed |

**No new packages required.** `fastapi.middleware.cors.CORSMiddleware` is bundled with FastAPI/Starlette.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `BaseHTTPMiddleware` | Pure ASGI middleware | BaseHTTPMiddleware is simpler but has known overhead with streaming responses (SSE); pure ASGI is more efficient but complex |
| Content-Length header check | Full body read + count | Header check prevents large body from being read at all; body read wastes memory |

**Note on BaseHTTPMiddleware + SSE:** The `/ask` endpoint uses `EventSourceResponse` (SSE). `BaseHTTPMiddleware` wraps the response body into memory in some Starlette versions. This is a known issue. However, since the logging middleware only measures timing and doesn't buffer the body, this risk is mitigated. The upload size middleware should short-circuit on Content-Length BEFORE calling `call_next()` for oversized requests, avoiding the body at all.

## Architecture Patterns

### Recommended Project Structure

```
src/rag_server/
├── api/
│   ├── __init__.py
│   ├── documents.py       # (existing) router prefix="/documents"
│   ├── ask.py             # (existing) router prefix=""
│   ├── retrieve.py        # (NEW) POST /retrieve endpoint
│   ├── schemas.py         # (existing + new RetrieveRequest/Response)
│   ├── middleware.py      # (NEW) LoggingMiddleware, UploadSizeLimitMiddleware
│   └── errors.py          # (NEW) RFC 7807 exception handlers
├── config.py              # (modify) add max_upload_size field
└── main.py                # (modify) prefix, middleware, error handlers
```

### Pattern 1: include_router Prefix Stacking

**What:** Add `prefix="/api/v1"` to `include_router()` calls in `main.py`. Router-level prefix + include_router prefix are concatenated by FastAPI.

**Verified:** `APIRouter(prefix="/documents")` + `include_router(router, prefix="/api/v1")` → `/api/v1/documents/...`

```python
# Source: empirically verified with FastAPI 0.129.0
# In main.py — replace existing include_router calls:
app.include_router(documents_router, prefix="/api/v1")
app.include_router(ask_router, prefix="/api/v1")
app.include_router(retrieve_router, prefix="/api/v1")
# /health stays as inline route at root — no change needed
```

### Pattern 2: Middleware Registration (LIFO Order)

**What:** Starlette's `add_middleware()` is LIFO — the last middleware added becomes the outermost wrapper.

**CORS must be outermost** (handles preflight OPTIONS before the request reaches the app). Add CORS last.

```python
# Source: verified with FastAPI 0.129.0 / Starlette 0.49.3
# In main.py, after app = FastAPI(...):
# Note: add_middleware() calls are LIFO, so add in reverse of desired execution order

# 1. Upload size limit (checked first, before logging — reject before logging a 413)
app.add_middleware(UploadSizeLimitMiddleware)

# 2. Request logging (wraps actual request processing)
app.add_middleware(LoggingMiddleware)

# 3. CORS (outermost — handles preflight before anything else)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Resulting execution order (request in):** CORS → Logging → UploadSizeLimit → Router → Handler

### Pattern 3: Request Logging Middleware

```python
# Source: Starlette BaseHTTPMiddleware documentation pattern, verified with Starlette 0.49.3
import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
```

### Pattern 4: Upload Size Limit Middleware

**Strategy:** Check `Content-Length` header before calling `call_next()`. Returns 413 immediately if header exceeds limit. Chunked transfers (no Content-Length) pass through — acceptable for a local server.

```python
# Source: Starlette BaseHTTPMiddleware + FastAPI pattern, verified with Starlette 0.49.3
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

class UploadSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int):
        super().__init__(app)
        self._max_size = max_upload_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self._max_size:
            return JSONResponse(
                {
                    "type": "about:blank",
                    "title": "Request Entity Too Large",
                    "status": 413,
                    "detail": (
                        f"Upload size {int(content_length)} bytes exceeds "
                        f"limit of {self._max_size} bytes. "
                        f"Set MAX_UPLOAD_SIZE env var to increase."
                    ),
                },
                status_code=413,
            )
        return await call_next(request)
```

**Initialization in main.py:** Pass `max_upload_size` from settings:
```python
app.add_middleware(UploadSizeLimitMiddleware, max_upload_size=settings.max_upload_size)
```

**Note:** `add_middleware` for `BaseHTTPMiddleware` subclasses passes kwargs to `__init__`. This requires the middleware to accept them via `__init__`, NOT via `dispatch`.

### Pattern 5: RFC 7807 Exception Handlers

**What:** Override FastAPI's default exception handlers to return `{ type, title, status, detail }` JSON for all errors.

**Three handlers required:**
1. `StarletteHTTPException` — covers all `HTTPException` raises in route handlers
2. `RequestValidationError` — covers 422 Pydantic validation failures
3. `Exception` — covers unhandled 500 errors

```python
# Source: FastAPI exception handling docs pattern, verified with FastAPI 0.129.0
import logging
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

HTTP_STATUS_TITLES = {
    400: "Bad Request",
    404: "Not Found",
    409: "Conflict",
    413: "Request Entity Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

def _problem(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {
            "type": "about:blank",
            "title": HTTP_STATUS_TITLES.get(status, "Error"),
            "status": status,
            "detail": detail,
        },
        status_code=status,
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return _problem(exc.status_code, detail)

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in errors
    )
    return _problem(422, detail)

async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return _problem(500, str(exc))

# Registration in main.py (after app = FastAPI(...)):
def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
```

**Important:** `add_exception_handler(StarletteHTTPException, ...)` overrides the default handler for all `HTTPException` instances including FastAPI's own. FastAPI's `HTTPException` is a subclass of `StarletteHTTPException`.

### Pattern 6: POST /api/v1/retrieve Endpoint

**What:** New endpoint in `src/rag_server/api/retrieve.py`. Calls `RetrievalEngine.search()` with `document_ids` filter.

**Schema additions to `schemas.py`:**
```python
# New in schemas.py
class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 10                         # Claude's discretion: 10 default
    document_ids: list[str] | None = None   # optional scope filter
    min_score: float | None = None          # optional threshold (0.0-1.0)

class ChunkResultItem(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    display_content: str | None
    source_filename: str
    page_number: int | None
    section_heading: str | None
    chunk_type: str
    bm25_score: float
    dense_score: float
    sparse_score: float
    rrf_score: float
    reranker_score: float

class RetrieveResponse(BaseModel):
    query: str
    results: list[ChunkResultItem]
    total_candidates: int
```

**Endpoint:**
```python
# src/rag_server/api/retrieve.py
from fastapi import APIRouter, Request
from rag_server.api.schemas import RetrieveRequest, RetrieveResponse, ChunkResultItem
from rag_server.retrieval.engine import RetrievalEngine

router = APIRouter(prefix="", tags=["retrieve"])

@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(body: RetrieveRequest, request: Request) -> RetrieveResponse:
    engine: RetrievalEngine = request.app.state.retrieval_engine
    result = await engine.search(
        query=body.query,
        top_k=body.top_k,
        min_score=body.min_score,
        document_ids=body.document_ids,
    )
    return RetrieveResponse(
        query=result.query,
        results=[
            ChunkResultItem(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                chunk_index=c.chunk_index,
                content=c.content,
                display_content=c.display_content,
                source_filename=c.source_filename,
                page_number=c.page_number,
                section_heading=c.section_heading,
                chunk_type=c.chunk_type,
                bm25_score=c.bm25_score,
                dense_score=c.dense_score,
                sparse_score=c.sparse_score,
                rrf_score=c.rrf_score,
                reranker_score=c.reranker_score,
            )
            for c in result.results
        ],
        total_candidates=result.total_candidates,
    )
```

### Pattern 7: Settings Extension for MAX_UPLOAD_SIZE

**What:** Add `max_upload_size` field to `Settings` in `config.py`. Pydantic-settings maps env var `MAX_UPLOAD_SIZE` to field `max_upload_size` automatically (case-insensitive, underscore-to-uppercase mapping).

**Verified empirically:** Setting env `MAX_UPLOAD_SIZE=52428800` and reading `settings.max_upload_size` returns `52428800` correctly.

```python
# In config.py Settings class, add:
max_upload_size: int = Field(default=100 * 1024 * 1024)  # 100MB, MAX_UPLOAD_SIZE env var
```

### Anti-Patterns to Avoid

- **Modifying router-level prefixes** to add `/api/v1/`: doing this means all other code that imports and uses the router prefix breaks. Use `include_router(router, prefix="/api/v1")` instead.
- **Reading request body in middleware for size check**: reads entire body into memory, defeating the purpose. Check `Content-Length` header instead.
- **Buffering SSE response in logging middleware**: `BaseHTTPMiddleware` wraps response bodies. The logging middleware must only record timing and status_code — never consume the response body. Confirmed safe with the pattern above.
- **Adding CORS middleware first** (before other `add_middleware()` calls): CORS will end up innermost, meaning preflight OPTIONS requests reach the router before being handled. CORS must be added last (outermost).
- **Using `@app.exception_handler` decorator** instead of `add_exception_handler()` after lifespan setup: the decorator syntax works but `add_exception_handler()` in a setup function is cleaner and testable.
- **Post-retrieval document_ids filtering** (filtering `ChunkResult` list after `engine.search()` returns): results in incorrect top_k behavior — the engine retrieves top_k globally, then post-filtering reduces count below top_k. The filter must propagate into the engine's retrieval legs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CORS headers | Custom response header middleware | `CORSMiddleware` from starlette | Handles preflight OPTIONS, wildcard patterns, credentials complexity |
| OpenAPI docs UI | Custom Swagger HTML | FastAPI built-in `/docs` and `/redoc` | Auto-generated from route schemas; always-enabled by default |
| Request body validation | Manual type checking | Pydantic model in endpoint parameter | FastAPI auto-validates and returns 422 |
| RFC 7807 JSON responses | Custom error response class | `JSONResponse` with dict | Simple dict is sufficient; no library needed for this shape |

**Key insight:** This phase adds no new libraries. All required capabilities exist in FastAPI 0.129.0 + Starlette 0.49.3.

## Critical Discovery: document_ids Filter Implementation

**This is the most architecturally significant piece of Phase 5.**

The existing `RetrievalEngine.search()` signature has NO `document_ids` parameter:
```python
async def search(self, query: str, top_k: int = 10, min_score: float | None = None,
                 candidate_k: int = 50, session: AsyncSession | None = None) -> RetrievalResult
```

The `document_ids` filter must be implemented by modifying `RetrievalEngine.search()` to:

1. **Qdrant dense + sparse queries**: pass `query_filter=Filter(must=[FieldCondition(key="document_id", match=MatchAny(any=document_ids))])` to `query_points()`. The Qdrant `query_points()` method accepts `query_filter` parameter — **verified empirically**.

2. **BM25 results**: BM25Manager stores a flat `corpus_ids` list with no document_id association. Post-filter BM25 results by joining against SQLite to get document_id for each chunk_id — OR, simpler: use the document_id stored in the Qdrant payload. Best approach: pre-fetch the set of chunk_ids belonging to `document_ids` from SQLite, then filter BM25 results to only those chunk_ids.

3. **QdrantStore needs new filter-aware query methods**: `query_dense(dense_vector, limit, query_filter=None)` and `query_sparse(sparse_indices, sparse_values, limit, query_filter=None)`. Both pass `query_filter` to `query_points()`.

**Verified:** Qdrant `query_points()` accepts `query_filter` parameter (verified from method signature).
**Verified:** `Filter(must=[FieldCondition(key="document_id", match=MatchAny(any=["id1","id2"]))])` constructs correctly.

**Implementation approach for document_ids filtering:**

```python
# In RetrievalEngine.search(), when document_ids is not None:
# 1. Build Qdrant filter
from qdrant_client.models import Filter, FieldCondition, MatchAny
qdrant_filter = Filter(
    must=[FieldCondition(key="document_id", match=MatchAny(any=document_ids))]
) if document_ids else None

# 2. Pass to QdrantStore methods (requires signature update)
dense_task = self._qdrant.query_dense(dense_vec, limit=candidate_k, query_filter=qdrant_filter)
sparse_task = self._qdrant.query_sparse(sparse_indices, sparse_values, limit=candidate_k, query_filter=qdrant_filter)

# 3. For BM25: pre-fetch allowed chunk_ids from SQLite
#    This runs concurrently with the other two legs
#    Then filter BM25 results: [(chunk_id, score) for (chunk_id, score) in bm25_results if chunk_id in allowed_ids]
```

**Files requiring modification for document_ids:**
- `src/rag_server/vector_store/qdrant.py`: Add optional `query_filter` param to `query_dense()` and `query_sparse()`
- `src/rag_server/retrieval/engine.py`: Add `document_ids` param to `search()`, construct Qdrant filter, add BM25 post-filter

## Common Pitfalls

### Pitfall 1: Middleware LIFO Ordering Confusion
**What goes wrong:** Developer adds `CORSMiddleware` first (before logging), expecting it to be outermost. It ends up innermost instead, causing CORS preflight failures.
**Why it happens:** `add_middleware()` is LIFO — last added = outermost.
**How to avoid:** Add middleware in reverse of desired execution order. CORS must be added LAST. Logging added before CORS.
**Warning signs:** Preflight OPTIONS requests return 404 or 405 instead of 200.

### Pitfall 2: BaseHTTPMiddleware + SSE Streaming Body Buffering
**What goes wrong:** Middleware subclassing `BaseHTTPMiddleware` can buffer the entire streaming response body before returning it. For SSE endpoints, this means the client receives all events at once at the end instead of as they stream.
**Why it happens:** Starlette's `BaseHTTPMiddleware.call_next()` implementation may buffer body chunks in some versions.
**How to avoid:** Logging middleware must NEVER call `response.body()` or consume the body. Only record `response.status_code` and timing. The patterns above do this correctly.
**Warning signs:** `/ask` streaming endpoint stops streaming; client receives entire response at once.

### Pitfall 3: 422 Errors Not Covered by HTTP Exception Handler
**What goes wrong:** Developer registers only `StarletteHTTPException` handler. FastAPI's 422 validation errors use `RequestValidationError` which does NOT inherit from `HTTPException`. Validation errors still return default format.
**Why it happens:** `RequestValidationError` inherits from `ValidationException(Exception)`, not from `HTTPException`.
**How to avoid:** Register BOTH `StarletteHTTPException` AND `RequestValidationError` handlers. Also register `Exception` for 500s.
**Warning signs:** Sending a malformed JSON body to any endpoint returns `{"detail": [...]}` format instead of RFC 7807 shape.

### Pitfall 4: document_ids Post-Filtering Gives Incorrect top_k
**What goes wrong:** Developer filters `result.results` list in the endpoint AFTER `engine.search()` returns. Result: if global search returns 10 chunks, 8 belong to the requested documents, you return 8 instead of 10 even though more matching chunks exist.
**Why it happens:** `top_k` is applied inside the engine before results are returned.
**How to avoid:** document_ids filter MUST be applied inside the engine's retrieval legs (Qdrant filter + BM25 post-filter within the engine), not in the endpoint handler.
**Warning signs:** `top_k=20` with `document_ids=["single_doc_id"]` returns fewer than 20 results even when that document has 100+ chunks.

### Pitfall 5: Router Prefix Modification Instead of include_router Prefix
**What goes wrong:** Developer changes `APIRouter(prefix="/documents")` to `APIRouter(prefix="/api/v1/documents")`. Now old tests that import the router directly expect the old prefix.
**Why it happens:** Easier to modify the router than the include call.
**How to avoid:** Keep router-level prefixes as they are. Only change `include_router(router)` → `include_router(router, prefix="/api/v1")`.
**Warning signs:** Scripts or tests that imported router paths directly break.

### Pitfall 6: Forgetting to Initialize UploadSizeLimitMiddleware with max_upload_size
**What goes wrong:** `app.add_middleware(UploadSizeLimitMiddleware)` without the `max_upload_size` kwarg. The middleware uses a hardcoded default instead of the configurable value.
**Why it happens:** `add_middleware()` passes kwargs to `__init__`, which requires the kwarg to be defined in `__init__`.
**How to avoid:** Pass `max_upload_size=get_settings().max_upload_size` in the `add_middleware()` call. Note: `get_settings()` should be called after env vars are loaded, which is at module load time for `main.py` — this is safe.

### Pitfall 7: ask Router Empty Prefix Stacking
**What goes wrong:** The ask router has `prefix=""` and routes declared as `@router.post("/ask", ...)`. Including with `prefix="/api/v1"` gives `/api/v1/ask`. This is correct — no issue. But if someone changes the ask router to `prefix="/ask"` and then the route becomes `@router.post("")`, the stacking must be re-verified.
**Why it happens:** Confusion about where the path lives (router prefix vs route decorator).
**How to avoid:** Do not modify ask.py prefix. Only change `include_router(ask_router)` → `include_router(ask_router, prefix="/api/v1")` in main.py.
**Warning signs:** `/api/v1/ask` returns 404 after restructuring.

## Code Examples

### Complete Error Handlers Module

```python
# Source: FastAPI exception handling, verified with FastAPI 0.129.0
# src/rag_server/api/errors.py

import logging
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_STATUS_TITLES = {
    400: "Bad Request",
    404: "Not Found",
    409: "Conflict",
    413: "Request Entity Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _problem(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {
            "type": "about:blank",
            "title": _STATUS_TITLES.get(status, "Error"),
            "status": status,
            "detail": detail,
        },
        status_code=status,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return _problem(exc.status_code, detail)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in errors
    )
    return _problem(422, detail)


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
    return _problem(500, str(exc))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
```

### Middleware Module

```python
# Source: Starlette BaseHTTPMiddleware docs, verified with Starlette 0.49.3
# src/rag_server/api/middleware.py

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class UploadSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int = 100 * 1024 * 1024) -> None:
        super().__init__(app)
        self._max_size = max_upload_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = None
            if size is not None and size > self._max_size:
                return JSONResponse(
                    {
                        "type": "about:blank",
                        "title": "Request Entity Too Large",
                        "status": 413,
                        "detail": (
                            f"Upload size {size} bytes exceeds limit of "
                            f"{self._max_size} bytes. "
                            f"Set MAX_UPLOAD_SIZE env var to increase."
                        ),
                    },
                    status_code=413,
                )
        return await call_next(request)
```

### main.py Changes Summary

```python
# Source: FastAPI docs + empirical verification with FastAPI 0.129.0

# 1. Import new modules
from fastapi.middleware.cors import CORSMiddleware
from rag_server.api.middleware import LoggingMiddleware, UploadSizeLimitMiddleware
from rag_server.api.errors import register_exception_handlers
from rag_server.api.retrieve import router as retrieve_router

# 2. Update FastAPI instantiation (add version)
app = FastAPI(
    title="FellowQuant RAG Server",
    description="Document ingestion and retrieval for quantitative finance research",
    version="0.5.0",
    lifespan=lifespan,
)

# 3. Register exception handlers (before middleware and routers)
register_exception_handlers(app)

# 4. Add middleware (LIFO order — CORS added LAST to be outermost)
app.add_middleware(UploadSizeLimitMiddleware, max_upload_size=get_settings().max_upload_size)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Mount routers with /api/v1 prefix
app.include_router(documents_router, prefix="/api/v1")
app.include_router(ask_router, prefix="/api/v1")
app.include_router(retrieve_router, prefix="/api/v1")

# 6. /health stays at root (no change)
@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

### QdrantStore query_filter Extension

```python
# Source: verified with qdrant-client 1.16.x (query_points accepts query_filter param)
# Modifications to src/rag_server/vector_store/qdrant.py

async def query_dense(
    self,
    dense_vector: list[float],
    limit: int = 50,
    query_filter=None,   # qdrant_client.models.Filter | None
) -> list[VectorSearchResult]:
    result = await self._client.query_points(
        collection_name=self._collection,
        query=dense_vector,
        using="dense",
        limit=limit,
        query_filter=query_filter,    # None means no filter (global search)
        with_payload=True,
        with_vectors=False,
    )
    return [
        VectorSearchResult(chunk_id=str(p.id), score=p.score, payload=p.payload or {})
        for p in result.points
    ]

# Same change for query_sparse
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat router mounting | `include_router(prefix=)` prefix stacking | FastAPI 0.63+ | Clean versioning without touching route files |
| Custom error dicts | RFC 7807 Problem Details (IETF standard) | Standardized 2016 | MCP client only needs one error parser |
| Per-endpoint CORS headers | `CORSMiddleware` | Starlette 0.12+ | Handles preflight automatically |

**Still current in FastAPI 0.129.0:**
- `BaseHTTPMiddleware` is the standard way for middleware (not deprecated)
- `add_exception_handler()` is the correct API (decorator and method both work)
- `RequestValidationError` still separate from `HTTPException` (requires separate handler)

## Open Questions

1. **BaseHTTPMiddleware + SSE latency overhead**
   - What we know: `BaseHTTPMiddleware` has documented overhead with streaming responses in some Starlette versions; it may serialize the entire streaming body to memory before completing
   - What's unclear: Whether Starlette 0.49.3 specifically buffers SSE responses or streams them correctly through `BaseHTTPMiddleware`
   - Recommendation: The logging middleware as written (only inspects `status_code` and timing, does not consume body) should be safe. If `/ask` streaming is observed to buffer, switch the logging middleware to a pure ASGI middleware instead.

2. **BM25 document_ids filter implementation detail**
   - What we know: BM25Manager has no document_id awareness in its `corpus_ids` list; it stores chunk_ids only
   - What's unclear: Whether chunk_id → document_id mapping should be pre-fetched from SQLite inline in the engine's `search()` method, or whether `BM25Manager` should maintain a `chunk_id_to_document_id` dict
   - Recommendation: Pre-fetch the set of valid chunk_ids from SQLite (WHERE document_id IN (...)) at the start of `search()` when `document_ids` is not None, then filter BM25 results using that set. This is a small query and avoids coupling BM25Manager to document awareness.

## Sources

### Primary (HIGH confidence)
- FastAPI 0.129.0 + Starlette 0.49.3 — installed in project virtualenv; all patterns empirically verified via Python interpreter
- `src/rag_server/api/documents.py` — existing endpoint implementations, router prefix, error codes
- `src/rag_server/api/ask.py` — existing ask endpoint, response_model=None pattern, SSE
- `src/rag_server/api/schemas.py` — existing Pydantic schemas
- `src/rag_server/main.py` — existing app setup, lifespan, router mounting
- `src/rag_server/retrieval/engine.py` — `search()` signature, existing params
- `src/rag_server/retrieval/bm25_manager.py` — no document_id awareness confirmed
- `src/rag_server/vector_store/qdrant.py` — `query_dense`/`query_sparse` signatures; `query_filter` param verified via `AsyncQdrantClient.query_points` signature inspection
- `src/rag_server/config.py` — Settings class; `MAX_UPLOAD_SIZE` mapping verified empirically
- `pyproject.toml` — installed library versions

### Secondary (MEDIUM confidence)
- RFC 7807 (Problem Details for HTTP APIs) — `about:blank` as generic type URI is spec-conformant

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and verified
- Architecture: HIGH — prefix stacking, middleware ordering, exception handlers all empirically verified
- Pitfalls: HIGH — all verified by code inspection or empirical test
- document_ids filter design: HIGH for Qdrant leg (verified), MEDIUM for BM25 leg (design is sound but not tested)

**Research date:** 2026-02-19
**Valid until:** 2026-04-19 (30 days — stable framework versions)
