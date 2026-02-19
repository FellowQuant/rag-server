---
phase: 06-mcp-server
plan: 02
subsystem: api
tags: [mcp, fastmcp, stdio, document-management, list, get, delete, rag]

# Dependency graph
requires:
  - phase: 06-01
    provides: mcp_server.py with retrieve and ask tools, AppContext, FastMCP lifespan
  - phase: 02-document-ingestion-pipeline
    provides: Document model, async_session, QdrantStore.delete_document()
provides:
  - list_documents MCP tool (full document metadata list from SQLite)
  - get_document MCP tool (single document lookup with NOT_FOUND error)
  - delete_document MCP tool (disk + SQLite + Qdrant cascade delete)
  - .mcp.json Claude Code auto-discovery config for stdio rag-server
affects: [claude-code-integration, mcp-tooling]

# Tech tracking
tech-stack:
  added: []
  patterns: [tool-not-found-error, delete-ordering-disk-sqlite-qdrant, mcp-json-discovery]

key-files:
  created:
    - .mcp.json
  modified:
    - src/rag_server/mcp_server.py

key-decisions:
  - "NOT_FOUND error format: ToolError('NOT_FOUND: <id>') — short uppercase machine-readable code prefix, consistent with QDRANT_UNAVAILABLE and INVALID_PARAM patterns established in 06-01"
  - "delete_document delete ordering matches REST API: disk unlink → SQLite commit → Qdrant (non-fatal) — SQLite is authoritative; Qdrant orphan vectors invisible without SQLite record"
  - "env:{} in .mcp.json intentional — Claude Code inherits parent shell environment; DATA_DIR, QDRANT_URL etc need not be listed explicitly"
  - "get_document ctx parameter placed after document_id — document_id has no default value so no Python SyntaxError; ctx second is clean"

requirements-completed: [MCP-05, MCP-06]

# Metrics
duration: 1min
completed: 2026-02-19
---

# Phase 6 Plan 02: Document Management Tools + MCP Discovery Summary

**Three document management tools (list_documents, get_document, delete_document) added to the MCP server, and .mcp.json created for automatic Claude Code discovery via stdio transport**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-19T23:35:13Z
- **Completed:** 2026-02-19T23:36:25Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `list_documents` tool: queries SQLite ordered by `created_at DESC`, returns `{documents: [...], total: N}` with full metadata fields (id, filename, title, status, file_format, file_size, page_count, created_at, indexed_at)
- Added `get_document` tool: single-document lookup by UUID, raises `ToolError("NOT_FOUND: <id>")` when document missing, returns extended metadata including author, file_hash, error_msg, updated_at
- Added `delete_document` tool: disk unlink → SQLite `session.delete()` + `commit()` → Qdrant `delete_document()` (Qdrant failure is non-fatal, logged as warning)
- Created `.mcp.json` at project root with `type: stdio`, `command: uv`, `args: ["run", "python", "-m", "rag_server.mcp_server"]` for automatic Claude Code tool discovery
- mcp_server.py now has exactly 5 tools: retrieve, ask, list_documents, get_document, delete_document

## Task Commits

Each task was committed atomically:

1. **Task 1: Add list_documents, get_document, delete_document tools** - `8f5efbf` (feat)
2. **Task 2: Create .mcp.json for Claude Code discovery** - `ab41f6b` (chore)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `src/rag_server/mcp_server.py` - Three new tools appended before `if __name__ == "__main__":`; new imports: `Path`, `select`, `Document`, `Document` already imported via models. Total: 137 lines added.
- `.mcp.json` - New file at project root; 10 lines; registers `rag-server` server with stdio transport using `uv run`.

## Decisions Made

- `ToolError("NOT_FOUND: <id>")` chosen as the error format for `get_document` and `delete_document`. Uppercase code prefix is consistent with the `QDRANT_UNAVAILABLE` and `INVALID_PARAM` patterns already established in 06-01. The `<id>` suffix lets Claude Code surface the specific missing resource without additional parsing.
- Delete ordering in `delete_document` follows the REST API exactly: disk file first, then SQLite (committed), then Qdrant last (non-fatal). SQLite is the authoritative store; once the Document row is gone, Qdrant orphan vectors are invisible in all subsequent searches.
- `env: {}` in `.mcp.json` is intentional. Claude Code inherits the parent shell environment at launch, making all variables from the user's `.env` file (`DATA_DIR`, `QDRANT_URL`, `SQLITE_URL`, etc.) available automatically without listing them.
- `ctx: Context` placed as the second parameter in `get_document` and `delete_document` (after `document_id`). Since `document_id` has no default value, there is no Python SyntaxError — unlike the `retrieve`/`ask` tools in 06-01 where `ctx` had to move first to avoid the non-default-after-default error.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — `.mcp.json` at the project root is automatically detected by Claude Code. No manual configuration required.

## Next Phase Readiness

- Phase 6 (MCP Server) is complete. Both plans (06-01 and 06-02) are done.
- The RAG server now has a full 5-tool MCP surface: `retrieve`, `ask`, `list_documents`, `get_document`, `delete_document`.
- Claude Code will discover the server via `.mcp.json` on next project open.

---
*Phase: 06-mcp-server*
*Completed: 2026-02-19*
