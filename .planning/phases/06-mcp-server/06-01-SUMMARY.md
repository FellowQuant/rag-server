---
phase: 06-mcp-server
plan: 01
subsystem: api
tags: [mcp, fastmcp, stdio, rag, retrieval, synthesis, python]

# Dependency graph
requires:
  - phase: 03-retrieval-engine
    provides: RetrievalEngine, BM25Manager, Reranker, QdrantStore with search()
  - phase: 04-llm-integration
    provides: SynthesisEngine, LLM providers, synthesize()
  - phase: 05-rest-api
    provides: RetrieveRequest/Response schemas, document_ids filtering on RetrievalEngine
provides:
  - FastMCP "rag-server" server exposing retrieve and ask tools over stdio transport
  - mcp_server.py standalone process separate from FastAPI application
  - retrieve tool returning full chunk fields with citation metadata
  - ask tool with LLM synthesis and graceful LLM-unavailable fallback
affects: [claude-code-integration, mcp-tooling, 06-02]

# Tech tracking
tech-stack:
  added: [mcp, fastmcp]
  patterns: [fastmcp-lifespan-context, tool-error-codes, ctx-first-parameter]

key-files:
  created:
    - src/rag_server/mcp_server.py
  modified: []

key-decisions:
  - "ctx: Context placed as first parameter — Python syntax prevents non-default parameter after default-having parameters; FastMCP injects it by type annotation regardless of position"
  - "BM25 loaded from disk only on MCP start (no rebuild) — stale BM25 is acceptable; restart server after indexing new documents"
  - "No WorkerManager in MCP lifespan — MCP server is query-only; ingestion happens exclusively via FastAPI"
  - "LLM failure in ask tool falls back to answer=null + raw sources + note (not ToolError) — partial results are more useful than an error for Claude Code"

patterns-established:
  - "AppContext dataclass as lifespan_context: typed access to shared resources via ctx.request_context.lifespan_context"
  - "ToolError with uppercase codes: QDRANT_UNAVAILABLE, INVALID_PARAM, RETRIEVAL_ERROR — Claude Code parses error codes not messages"
  - "stderr-only logging: logging.basicConfig(stream=sys.stderr) must precede any logger usage to keep stdout clean for JSON-RPC"

requirements-completed: [MCP-01, MCP-02, MCP-03]

# Metrics
duration: 2min
completed: 2026-02-19
---

# Phase 6 Plan 01: MCP Server Summary

**FastMCP server with stdio transport, AppContext lifespan, retrieve tool (raw chunks + citations), and ask tool (LLM synthesis with fallback to raw chunks when LLM unavailable)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-19T23:30:39Z
- **Completed:** 2026-02-19T23:32:47Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `src/rag_server/mcp_server.py` as a standalone MCP server (separate process from FastAPI)
- retrieve tool: returns full chunk fields including all 5 retrieval scores (bm25, dense, sparse, rrf, reranker), raises ToolError(QDRANT_UNAVAILABLE) on connection errors
- ask tool: full RAG pipeline with LLM synthesis; falls back to `{answer: null, sources: [...], note: "LLM unavailable"}` when LLM fails

## Task Commits

Each task was committed atomically:

1. **Task 1: Create mcp_server.py with lifespan and retrieve + ask tools** - `e072edc` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `src/rag_server/mcp_server.py` - Standalone FastMCP server with lifespan loading Qdrant/BM25/Embedder/Reranker/SynthesisEngine, retrieve tool, ask tool, stdio entry point

## Decisions Made

- `ctx: Context` placed as the first parameter in both tool functions. Python's syntax rule prevents a non-default parameter after parameters with defaults (`top_k`, `document_ids`, `min_score`). FastMCP identifies the context parameter by type annotation via `find_context_parameter()`, so position does not matter for injection — first position is the cleanest fix.
- BM25 loaded from disk only (no rebuild on MCP start). Stale BM25 is acceptable for query sessions; restart the MCP server after indexing new documents to pick up a fresh index.
- No WorkerManager in MCP lifespan — the MCP server is query-only. Document ingestion happens exclusively through the FastAPI application.
- LLM failure in `ask` falls back gracefully to `answer=null` + raw sources + note string. Returning ToolError would give Claude Code nothing to work with; partial results are more useful.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ctx parameter position causing SyntaxError**
- **Found during:** Task 1 (initial file creation)
- **Issue:** Plan shows `ctx: Context` as the last parameter but after parameters with defaults (`top_k`, `document_ids`, `min_score`). Python raises `SyntaxError: parameter without a default follows parameter with a default`.
- **Fix:** Moved `ctx: Context` to be the first parameter in both `retrieve` and `ask` tool functions. FastMCP uses type-annotation inspection to find the context parameter (`find_context_parameter()`), so position is irrelevant for injection.
- **Files modified:** `src/rag_server/mcp_server.py`
- **Verification:** `python -c "import rag_server.mcp_server"` returns OK with no stdout output
- **Committed in:** e072edc (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — Python syntax constraint)
**Impact on plan:** Required fix for the file to be importable at all. No scope creep. All plan requirements fulfilled.

## Issues Encountered

- Python parameter ordering syntax prevented the exact signature from the plan; resolved by moving `ctx: Context` first (FastMCP injection is position-independent).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `src/rag_server/mcp_server.py` is ready to run via `python -m rag_server.mcp_server` with stdio transport
- 06-02 can proceed to wire the MCP server configuration for Claude Code integration

---
*Phase: 06-mcp-server*
*Completed: 2026-02-19*
