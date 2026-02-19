# Phase 6: MCP Server - Context

**Gathered:** 2026-02-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose document management and RAG query capabilities to Claude Code via the MCP stdio protocol. Tools: `retrieve`, `ask`, `list_documents`, `get_document`, `delete_document`. File ingestion is intentionally excluded — uploading documents is done manually via the REST API, not via MCP.

</domain>

<decisions>
## Implementation Decisions

### Tool response shape
- `retrieve` returns **full chunk content** (not truncated) — Claude needs complete text to answer accurately
- `retrieve` includes **full citation fields**: source_filename, page_number, section_heading, chunk_type, rrf_score, reranker_score — same as REST ChunkResultItem
- `list_documents` returns **full metadata**: id, filename, title, status, page count, created_at — same as REST GET /documents
- `get_document` returns **document metadata only** (no chunk list) — chunks retrieved separately via `retrieve`
- Empty results from `retrieve` (zero chunks) are a **successful response** with `{results: [], total_candidates: 0}` — not an error

### Ask tool behavior
- `ask` tool **waits for full completion** then returns a single result — no streaming, simpler for Claude to consume
- `ask` returns `{answer: string, sources: [{filename, page}]}` — clean structured result for Claude to reference
- If LLM provider is unavailable, **fall back to returning raw retrieved chunks** without synthesis — Claude can still help
- `ask` accepts **full parity with REST params**: `query`, `top_k`, `document_ids` filter, `min_score`

### Error communication
- Tool failures use **MCP tool errors** (raise exceptions) — Claude sees a tool failure and explains to user
- Error messages are **short machine-readable**: e.g., `NOT_FOUND: abc123`, `QDRANT_UNAVAILABLE`, `INVALID_PARAM: top_k`
- Qdrant down at query time → **error immediately** with `QDRANT_UNAVAILABLE` — no silent degradation to BM25-only

### Claude's Discretion
- MCP SDK choice (mcp Python SDK or manual stdio JSON-RPC implementation)
- Exact tool argument schemas (JSON Schema for each parameter)
- Connection transport details (stdio vs other transports — stdio per roadmap)
- Tool description strings shown to Claude Code during discovery

</decisions>

<specifics>
## Specific Ideas

- The `ask` LLM fallback should return raw chunks clearly labeled so Claude knows synthesis didn't happen (e.g., `{answer: null, sources: [...], note: "LLM unavailable — raw chunks returned"}`)
- No ingest_document tool — document upload is a manual operation via REST POST /api/v1/documents

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-mcp-server*
*Context gathered: 2026-02-19*
