# Phase 5: REST API - Context

**Gathered:** 2026-02-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Consolidate and complete the HTTP API layer. Existing Phase 2 endpoints (POST/GET/LIST/DELETE /documents) and Phase 4 (/ask) are restructured under /api/v1/. The primary new endpoint is POST /api/v1/retrieve (raw ranked chunks without LLM synthesis). Add CORS, request logging middleware, upload size limit, RFC 7807 error handling, and OpenAPI docs. No new retrieval or LLM logic — pure API layer work.

</domain>

<decisions>
## Implementation Decisions

### API versioning & URL structure
- **All endpoints move to /api/v1/ prefix** — /documents → /api/v1/documents, /ask → /api/v1/ask, /retrieve → /api/v1/retrieve
- **Hard cut** — old paths (e.g. /documents) return 404; no redirects needed (no external consumers yet)
- **OpenAPI docs always enabled** — /docs (Swagger UI) and /redoc exposed unconditionally
- **Health stays at root** — /health remains at root for infra/Docker healthchecks; NOT moved to /api/v1/

### Authentication & middleware
- **No authentication** — open API; trust handled at network level (local server)
- **CORS: allow all origins** — CORSMiddleware with allow_origins=["*"] for browser client compatibility
- **Upload size limit: 100MB default** — configurable via MAX_UPLOAD_SIZE env var; reject oversized uploads with 413 before reading body
- **Request logging middleware** — log all requests: method, path, status code, duration (ms)

### Retrieve endpoint design
- **Full ChunkResult shape** — POST /api/v1/retrieve returns all 5 scores (bm25, dense, sparse, rrf, reranker) + full metadata (source_filename, page_number, section_heading, chunk_type) + content + display_content
- **Optional document_ids filter** — request body accepts optional `document_ids: list[str]` to scope retrieval to specific documents; omit for global search
- **Optional min_score threshold** — optional `min_score: float` param (0.0–1.0) to filter out weak results before returning
- **top_k default:** Claude's Discretion — recommend top_k=10 default (same as /ask) with caller override; /retrieve consumers can pass higher values explicitly

### Error response format
- **RFC 7807 Problem Details for all errors** — `{ type: str, title: str, status: int, detail: str }` shape across all HTTP errors
- **422 validation errors also normalized to RFC 7807** — consistent shape everywhere; MCP client needs only one error parser
- **500 errors always expose exception message** — local server, full traceability more useful than security masking

</decisions>

<specifics>
## Specific Ideas

- The /api/v1/ prefix enables a clean v2 path in the future without breaking existing consumers
- RFC 7807 everywhere means the MCP client (Phase 6) can have a single error handler
- document_ids filter on /retrieve enables per-document scoped queries which is useful for the MCP "ask about this document" tool pattern
- Request logging middleware helps debug latency issues across the retrieval + LLM pipeline

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-rest-api*
*Context gathered: 2026-02-19*
