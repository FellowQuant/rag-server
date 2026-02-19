# Phase 6: MCP Server - Research

**Researched:** 2026-02-19
**Domain:** MCP Python SDK (FastMCP), stdio transport, tool definition, lifespan state sharing
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Tool response shape
- `retrieve` returns **full chunk content** (not truncated) — Claude needs complete text to answer accurately
- `retrieve` includes **full citation fields**: source_filename, page_number, section_heading, chunk_type, rrf_score, reranker_score — same as REST ChunkResultItem
- `list_documents` returns **full metadata**: id, filename, title, status, page count, created_at — same as REST GET /documents
- `get_document` returns **document metadata only** (no chunk list) — chunks retrieved separately via `retrieve`
- Empty results from `retrieve` (zero chunks) are a **successful response** with `{results: [], total_candidates: 0}` — not an error

#### Ask tool behavior
- `ask` tool **waits for full completion** then returns a single result — no streaming, simpler for Claude to consume
- `ask` returns `{answer: string, sources: [{filename, page}]}` — clean structured result for Claude to reference
- If LLM provider is unavailable, **fall back to returning raw retrieved chunks** without synthesis — Claude can still help
- `ask` accepts **full parity with REST params**: `query`, `top_k`, `document_ids` filter, `min_score`

#### Error communication
- Tool failures use **MCP tool errors** (raise exceptions) — Claude sees a tool failure and explains to user
- Error messages are **short machine-readable**: e.g., `NOT_FOUND: abc123`, `QDRANT_UNAVAILABLE`, `INVALID_PARAM: top_k`
- Qdrant down at query time → **error immediately** with `QDRANT_UNAVAILABLE` — no silent degradation to BM25-only

#### Phase Boundary
Expose document management and RAG query capabilities to Claude Code via the MCP stdio protocol. Tools: `retrieve`, `ask`, `list_documents`, `get_document`, `delete_document`. File ingestion is intentionally excluded — uploading documents is done manually via the REST API, not via MCP.

### Claude's Discretion
- MCP SDK choice (mcp Python SDK or manual stdio JSON-RPC implementation)
- Exact tool argument schemas (JSON Schema for each parameter)
- Connection transport details (stdio vs other transports — stdio per roadmap)
- Tool description strings shown to Claude Code during discovery

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MCP-01 | MCP server with `retrieve` tool (raw chunks with citations) | FastMCP `@mcp.tool()` with lifespan state; calls `RetrievalEngine.search()` |
| MCP-02 | MCP server with `ask` tool (LLM-synthesized answers) | FastMCP async tool; calls `SynthesisEngine.synthesize()`; LLM fallback returns raw chunks |
| MCP-03 | Claude Code integration via MCP protocol (stdio transport) | `mcp.run(transport="stdio")` entry point; `.mcp.json` project config |
| MCP-04 | `list_documents` tool — inventory with indexing status | FastMCP tool; SQLAlchemy async session via lifespan; queries Document table |
| MCP-05 | `get_document` tool — document metadata by ID | FastMCP tool; SQLAlchemy lookup; `NOT_FOUND: {id}` on missing |
| MCP-06 | `delete_document` tool — remove document from corpus | FastMCP tool; mirrors REST DELETE; removes SQLite + Qdrant + file |
</phase_requirements>

---

## Summary

The MCP Python SDK (version 1.26.0, installed in this project's environment) includes `FastMCP` — a decorator-based high-level API that handles all JSON-RPC protocol details, tool registration, schema generation from type annotations, and stdio transport. FastMCP is the standard choice (over manual low-level implementation) because it eliminates hand-rolling the protocol layer and generates tool schemas automatically from Python type hints and docstrings.

The MCP server will be implemented as a **standalone Python script** (`src/rag_server/mcp_server.py`) that imports shared infrastructure from the existing `rag_server` package. It runs as a **separate process** spawned by Claude Code via stdio — it does not run inside the FastAPI process. The script initializes its own lifespan (loading engine components from `app.state` equivalents via a FastMCP lifespan context manager), then exposes five tools: `retrieve`, `ask`, `list_documents`, `get_document`, `delete_document`.

The critical integration concern is that `RetrievalEngine`, `SynthesisEngine`, and the database session factory already exist in `src/rag_server/`. The MCP server must re-initialize these components in its own process (not share with FastAPI), because the two processes are separate. Database access uses the existing `async_session` factory directly; retrieval/synthesis engines are loaded fresh in the MCP process lifespan. All logging must go to stderr (never stdout) or it will corrupt the JSON-RPC stream.

**Primary recommendation:** Use `FastMCP` from `mcp.server.fastmcp`, define all five tools as `async def` functions with type-annotated parameters, use a lifespan context manager to load shared components once at startup, pass components via `ctx.request_context.lifespan_context`, and expose via `mcp.run(transport="stdio")`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp` (FastMCP) | 1.26.0 (installed) | MCP server with tool registration, stdio transport, schema generation | Official Anthropic SDK; handles all JSON-RPC protocol details |
| `mcp.server.fastmcp.exceptions.ToolError` | same | Raise tool-level errors that Claude receives as tool failures | Only mechanism for intentional error messages that pass `mask_error_details` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio` (stdlib) | 3.12+ | Async tool execution | All tools are async; lifespan uses `asynccontextmanager` |
| `sqlalchemy` (existing) | 2.0+ | Database queries for document list/get/delete | Already configured; use `async_session` factory from `rag_server.database.engine` |
| `anyio` (FastMCP dep) | transitive | Event loop for `mcp.run()` | Used internally by FastMCP; no direct usage needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| FastMCP | Manual stdio JSON-RPC implementation | Manual approach requires hand-writing protocol handling, message parsing, schema definition — no benefit for this use case |
| FastMCP lifespan | Module-level globals | Globals work but break testability and make re-initialization order explicit |

**Installation:**
```bash
# Already installed — mcp==1.26.0 is in the environment
# Add to pyproject.toml dependencies:
# "mcp>=1.26.0"
```

## Architecture Patterns

### Recommended Project Structure
```
src/rag_server/
├── mcp_server.py          # Entry point: FastMCP instance + tool definitions + lifespan
└── (existing modules)     # RetrievalEngine, SynthesisEngine, database — unchanged
```

The MCP server is a single file. It imports `RetrievalEngine`, `SynthesisEngine`, `async_session`, and Qdrant/BM25/Embedder/Reranker from the existing package. No new sub-packages needed.

### Pattern 1: FastMCP Lifespan for Shared State

**What:** An `asynccontextmanager` that initializes expensive resources (models, DB engine) once at server startup. Resources are passed to each tool call via `ctx.request_context.lifespan_context`.

**When to use:** Any time tools need to share initialized objects (engine instances, DB factories) across calls without re-loading on every invocation.

**Example:**
```python
# Source: mcp/server/fastmcp/server.py lifespan + shared/context.py
from contextlib import asynccontextmanager
from dataclasses import dataclass
from mcp.server.fastmcp import FastMCP, Context

@dataclass
class AppContext:
    retrieval_engine: RetrievalEngine
    synthesis_engine: SynthesisEngine

@asynccontextmanager
async def lifespan(server: FastMCP):
    # Initialize components — runs once at server start
    embedder = Embedder()
    await asyncio.to_thread(embedder.load)
    reranker = Reranker()
    await asyncio.to_thread(reranker.load)
    qdrant_store = QdrantStore(get_settings())
    await qdrant_store.ensure_collection()
    bm25_manager = BM25Manager(...)
    await bm25_manager.build_or_load()

    retrieval_engine = RetrievalEngine(embedder, qdrant_store, bm25_manager, reranker)
    synthesis_engine = SynthesisEngine(provider, llm_config)

    yield AppContext(
        retrieval_engine=retrieval_engine,
        synthesis_engine=synthesis_engine,
    )

    # Teardown
    await asyncio.to_thread(reranker.unload)
    await asyncio.to_thread(embedder.unload)
    await qdrant_store.close()

mcp = FastMCP("rag-server", lifespan=lifespan)
```

### Pattern 2: Async Tool Definition with Context Access

**What:** Tools are `async def` functions decorated with `@mcp.tool()`. They receive a `ctx: Context` parameter (auto-injected by FastMCP) to access lifespan state and log messages. Tool return types are `dict` for structured JSON output.

**When to use:** All tools in this phase — they are all async (call SQLAlchemy or engine methods).

**Example:**
```python
# Source: FastMCP official docs + mcp/server/fastmcp/server.py
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

@mcp.tool()
async def retrieve(
    query: str,
    top_k: int = 10,
    document_ids: list[str] | None = None,
    min_score: float | None = None,
    ctx: Context,
) -> dict:
    """Retrieve relevant document chunks for a query using hybrid search.

    Returns ranked chunks with full citation metadata (filename, page, section,
    chunk type) and retrieval scores.
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context

    try:
        async with async_session() as session:
            result = await app_ctx.retrieval_engine.search(
                query=query,
                top_k=top_k,
                min_score=min_score,
                document_ids=document_ids,
                session=session,
            )
    except Exception as exc:
        if "qdrant" in str(exc).lower() or "connection" in str(exc).lower():
            raise ToolError("QDRANT_UNAVAILABLE")
        raise ToolError(f"RETRIEVAL_ERROR: {exc}")

    return {
        "results": [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "source_filename": r.source_filename,
                "page_number": r.page_number,
                "section_heading": r.section_heading,
                "chunk_type": r.chunk_type,
                "rrf_score": r.rrf_score,
                "reranker_score": r.reranker_score,
            }
            for r in result.results
        ],
        "total_candidates": result.total_candidates,
    }
```

### Pattern 3: ToolError for Machine-Readable Error Codes

**What:** `ToolError` from `mcp.server.fastmcp.exceptions` is the FastMCP mechanism for intentional tool failures. Its message is always forwarded to Claude (even when `mask_error_details=True`). Standard Python exceptions also become tool errors but may be masked.

**When to use:** All error conditions — NOT_FOUND, QDRANT_UNAVAILABLE, INVALID_PARAM. Use `ToolError` exclusively for predictable failures; let unexpected exceptions propagate naturally.

**Example:**
```python
# Source: mcp/server/fastmcp/exceptions.py (installed)
from mcp.server.fastmcp.exceptions import ToolError

# NOT_FOUND
if doc is None:
    raise ToolError(f"NOT_FOUND: {document_id}")

# Qdrant unavailable
raise ToolError("QDRANT_UNAVAILABLE")

# Invalid parameter
if top_k < 1 or top_k > 100:
    raise ToolError("INVALID_PARAM: top_k must be 1-100")
```

### Pattern 4: stdio Entry Point

**What:** The server script ends with `mcp.run(transport="stdio")` inside an `if __name__ == "__main__":` block. Claude Code spawns this script as a subprocess and communicates via stdin/stdout JSON-RPC.

**When to use:** This is the only entry point for Claude Code integration.

**Example:**
```python
# Source: modelcontextprotocol.io/docs/develop/build-server (official quickstart)
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### Pattern 5: Ask Tool with LLM Fallback

**What:** The `ask` tool calls `SynthesisEngine.synthesize()` normally, but catches `LLM unavailable` exceptions and returns raw retrieved chunks instead with a `note` field so Claude knows synthesis didn't happen.

**When to use:** As per locked decision — fallback to raw chunks when LLM is unavailable.

**Example:**
```python
@mcp.tool()
async def ask(
    query: str,
    top_k: int = 10,
    document_ids: list[str] | None = None,
    min_score: float | None = None,
    ctx: Context,
) -> dict:
    """Query the knowledge base and get an LLM-synthesized answer with citations."""
    app_ctx: AppContext = ctx.request_context.lifespan_context

    async with async_session() as session:
        retrieval_result = await app_ctx.retrieval_engine.search(
            query=query, top_k=top_k, min_score=min_score,
            document_ids=document_ids, session=session,
        )

    chunks = retrieval_result.results

    try:
        ask_response = await app_ctx.synthesis_engine.synthesize(query, chunks)
        return {
            "answer": ask_response.answer,
            "sources": [
                {"filename": s.filename, "page": s.page_number}
                for s in ask_response.sources
            ],
        }
    except Exception:
        # LLM unavailable — return raw chunks per locked decision
        return {
            "answer": None,
            "sources": [
                {"filename": c.source_filename, "page": c.page_number,
                 "content": c.content}
                for c in chunks
            ],
            "note": "LLM unavailable — raw chunks returned",
        }
```

### Pattern 6: Claude Code .mcp.json Configuration

**What:** Project-scope `.mcp.json` at the project root, checked into source control, configures Claude Code to spawn the MCP server. Uses `uv run` to execute the script in the correct environment.

**When to use:** This file is what makes the MCP server available to all team members using Claude Code in this repo.

**Example:**
```json
{
  "mcpServers": {
    "rag-server": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "rag_server.mcp_server"],
      "env": {
        "PYTHONPATH": "${workspaceFolder}/src"
      }
    }
  }
}
```

Or using uv (preferred — uses project's venv automatically):
```json
{
  "mcpServers": {
    "rag-server": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "rag_server.mcp_server"],
      "env": {}
    }
  }
}
```

### Anti-Patterns to Avoid

- **Writing to stdout in tool functions or lifespan:** Any `print()` without `file=sys.stderr` corrupts the JSON-RPC stream and silently breaks the server. Use `logging` (which goes to stderr by default) or `print(..., file=sys.stderr)`.
- **Sharing process state with FastAPI:** The MCP server is a separate process. Do NOT attempt to connect to FastAPI's app.state — load all components fresh in the lifespan.
- **Streaming in the `ask` tool:** The locked decision is non-streaming (full completion then return). Do NOT use `stream_synthesize()` — use `synthesize()` only.
- **Returning empty list as error:** Empty retrieve results are a successful response `{results: [], total_candidates: 0}`, not a ToolError. Only raise ToolError for actual failures (Qdrant unavailable, not-found, etc.).
- **Blocking calls in async tools:** Embedder, Reranker, BM25 are blocking CPU/GPU operations. Always wrap with `asyncio.to_thread()`. `RetrievalEngine.search()` already does this internally.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON-RPC message parsing | Custom stdio parser | FastMCP (`mcp.server.fastmcp`) | Protocol has initialization handshake, message framing, error codes — complex |
| Tool JSON schema | Manual schema dict | FastMCP auto-generates from type hints | FastMCP reflects Python type annotations into JSON Schema automatically |
| Tool error to protocol error mapping | Manual error response construction | `raise ToolError("...")` | FastMCP maps ToolError to MCP isError=true tool result automatically |
| Transport lifecycle | Custom asyncio stream management | `mcp.run(transport="stdio")` | FastMCP manages read/write stream lifecycle, cancellation, shutdown |
| Tool discovery handshake | Manual `list_tools` handler | FastMCP `@mcp.tool()` registration | FastMCP builds the tool list from registered decorators automatically |

**Key insight:** The MCP protocol requires a specific initialization handshake (capabilities negotiation), message framing, and error code conventions. FastMCP handles all of this; a manual implementation would require deeply reading the MCP specification.

## Common Pitfalls

### Pitfall 1: stdout Corruption
**What goes wrong:** Any write to stdout (even from imported libraries) silently corrupts the JSON-RPC stream. Claude Code receives garbled data and the connection fails.
**Why it happens:** stdio transport uses stdout as the communication channel. Any non-JSON-RPC bytes are invalid protocol messages.
**How to avoid:** Configure logging to use stderr: `logging.basicConfig(stream=sys.stderr)`. Never call `print()` without `file=sys.stderr`. Check imported libraries for any stdout side effects at import time.
**Warning signs:** Claude Code reports "Connection closed" or tool discovery fails immediately after startup.

### Pitfall 2: Blocking the Event Loop in Tools
**What goes wrong:** Tool calls that block (Embedder.encode_query, Reranker.compute_scores) freeze the MCP server, causing timeouts.
**Why it happens:** FastMCP runs on an asyncio event loop. Synchronous blocking calls block all other coroutines.
**How to avoid:** Wrap all CPU-bound/blocking calls with `asyncio.to_thread()`. `RetrievalEngine.search()` already does this internally — calling `search()` is safe. Direct calls to `embedder.encode_query()` are not safe without `to_thread`.
**Warning signs:** Claude Code reports tool timeout; MCP server becomes unresponsive after first heavy tool call.

### Pitfall 3: Missing `multiprocessing.set_start_method("spawn")`
**What goes wrong:** The `mcp_server.py` process imports `FlagEmbedding` and `docling` (transitively through shared modules). On Linux, these CUDA libraries may fork incorrectly if the start method is not `spawn`.
**Why it happens:** The MCP server is a separate process — it must set the spawn method just like `main.py` does. However, the MCP server does NOT fork subprocesses itself (no WorkerManager), so this may not matter in practice.
**How to avoid:** Add `multiprocessing.set_start_method("spawn", force=True)` as the FIRST statement in `mcp_server.py`, before any other imports — same pattern as `main.py`.
**Warning signs:** CUDA-related errors at startup on Linux, especially "CUDA error: initialization error".

### Pitfall 4: Qdrant Connection Not Available
**What goes wrong:** The MCP server starts before Qdrant is running, or Qdrant goes down during operation. Tools that need Qdrant must detect this and raise `QDRANT_UNAVAILABLE`.
**Why it happens:** MCP server's lifespan calls `qdrant_store.ensure_collection()` — if Qdrant is not running, this raises at startup. During operation, network errors from Qdrant should be caught per-tool.
**How to avoid:** In the lifespan, catch Qdrant connection errors and log to stderr; tools that call Qdrant must wrap calls in try/except and raise `ToolError("QDRANT_UNAVAILABLE")`. Per the locked decision: NO silent fallback to BM25-only.
**Warning signs:** Server starts successfully but `retrieve` and `ask` tools always fail with QDRANT_UNAVAILABLE.

### Pitfall 5: SQLAlchemy Session Leaks
**What goes wrong:** An async session opened inside a tool is not closed, leading to connection pool exhaustion over many tool calls.
**Why it happens:** Unlike FastAPI's `Depends(get_db)`, MCP tools manage their own sessions. If a session is opened with `async with async_session() as session:` and an exception propagates without the context manager completing, the session leaks.
**How to avoid:** Always use `async with async_session() as session:` — the context manager guarantees cleanup. Never hold a session open across an await that could raise.
**Warning signs:** SQLAlchemy "pool timeout" errors after many tool calls; server slows down progressively.

### Pitfall 6: Context Parameter Position
**What goes wrong:** FastMCP's auto-injection of `ctx: Context` fails if the parameter is not correctly type-annotated or appears in the wrong position.
**Why it happens:** FastMCP detects the context parameter by type annotation (`ctx: Context`). If the annotation is missing or uses a wrong type, the parameter is treated as a required tool argument.
**How to avoid:** Always annotate the context parameter as `ctx: Context` from `mcp.server.fastmcp`. Place it after all real tool parameters. The name does not matter — only the type annotation.
**Warning signs:** Claude Code sees `ctx` as a required tool argument in the schema; tool calls fail because Claude doesn't know what to pass for `ctx`.

### Pitfall 7: Delete Tool Qdrant Cleanup Order
**What goes wrong:** The `delete_document` tool deletes from SQLite first (matching the REST implementation), then Qdrant. If Qdrant delete fails, vectors are orphaned but SQLite has no record.
**Why it happens:** This is the documented behavior from Phase 5 REST implementation — SQLite is authoritative. The MCP tool must replicate this ordering exactly.
**How to avoid:** Use the same delete order as `api/documents.py`: (1) delete file from disk, (2) delete from SQLite with commit, (3) delete Qdrant vectors. Qdrant delete failure is non-fatal (orphaned vectors don't appear in search results).
**Warning signs:** Tool reports success but Qdrant still has vectors; verify by checking Qdrant collection point count.

## Code Examples

Verified patterns from official sources:

### Complete MCP Server Structure
```python
# Source: Official MCP Python SDK quickstart + installed mcp/server/fastmcp/server.py
import multiprocessing
multiprocessing.set_start_method("spawn", force=True)

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.exceptions import ToolError

from rag_server.config import get_settings
from rag_server.database.engine import async_session
from rag_server.ingestion.embedder import Embedder
from rag_server.llm.config import get_llm_settings
from rag_server.llm.provider import create_provider
from rag_server.llm.synthesis import SynthesisEngine
from rag_server.retrieval.bm25_manager import BM25Manager
from rag_server.retrieval.engine import RetrievalEngine
from rag_server.retrieval.reranker import Reranker
from rag_server.vector_store.qdrant import QdrantStore

# CRITICAL: log to stderr only — stdout is the JSON-RPC channel
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    retrieval_engine: RetrievalEngine
    synthesis_engine: SynthesisEngine
    qdrant_store: QdrantStore


@asynccontextmanager
async def lifespan(server: FastMCP):
    settings = get_settings()
    # ... load all components ...
    yield AppContext(retrieval_engine=..., synthesis_engine=..., qdrant_store=...)
    # ... cleanup ...


mcp = FastMCP("rag-server", lifespan=lifespan)


@mcp.tool()
async def list_documents(ctx: Context) -> dict:
    """List all documents in the knowledge base with their indexing status."""
    # Access shared state:
    # app_ctx: AppContext = ctx.request_context.lifespan_context
    ...


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### Accessing Lifespan Context in a Tool
```python
# Source: mcp/shared/context.py — RequestContext.lifespan_context field
@mcp.tool()
async def retrieve(query: str, ctx: Context) -> dict:
    app_ctx: AppContext = ctx.request_context.lifespan_context
    result = await app_ctx.retrieval_engine.search(query=query)
    return {"results": [...], "total_candidates": result.total_candidates}
```

### ToolError Patterns
```python
# Source: mcp/server/fastmcp/exceptions.py — ToolError class
from mcp.server.fastmcp.exceptions import ToolError

# Pattern: NOT_FOUND
result = await session.execute(select(Document).where(Document.id == document_id))
doc = result.scalar_one_or_none()
if doc is None:
    raise ToolError(f"NOT_FOUND: {document_id}")

# Pattern: QDRANT_UNAVAILABLE (catch connection errors)
try:
    result = await app_ctx.retrieval_engine.search(...)
except Exception as exc:
    if _is_qdrant_error(exc):
        raise ToolError("QDRANT_UNAVAILABLE")
    raise ToolError(f"SEARCH_ERROR: {exc}")
```

### .mcp.json for Claude Code (project scope)
```json
{
  "mcpServers": {
    "rag-server": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "rag_server.mcp_server"],
      "env": {}
    }
  }
}
```

### FastMCP Tool with Optional Parameters
```python
# Source: FastMCP tools documentation — type annotations auto-generate JSON schema
@mcp.tool()
async def retrieve(
    query: str,                                    # required string
    top_k: int = 10,                               # optional, default 10
    document_ids: list[str] | None = None,         # optional, null means global search
    min_score: float | None = None,                # optional, null means no threshold
    ctx: Context,                                  # auto-injected, not in schema
) -> dict:
    ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON-RPC stdio implementation | FastMCP SDK | 2024-2025 | No manual protocol code; SDK handles all framing and error mapping |
| SSE transport (deprecated) | stdio for local, HTTP for remote | 2025 | SSE is officially deprecated; use stdio for Claude Code local servers |
| Low-level `Server` API | `FastMCP` high-level API | 2024 | FastMCP is now the recommended approach in official docs |

**Deprecated/outdated:**
- SSE transport: Deprecated per official Claude Code docs (February 2026). For Claude Code integration, use stdio.
- Manual `tools/list` + `tools/call` handlers: Replaced by `@mcp.tool()` decorator in FastMCP.

## Open Questions

1. **VRAM impact of loading Embedder + Reranker in MCP process**
   - What we know: FastAPI process loads BGE-M3 (~1 GB) + Qwen3-Reranker (~1.2 GB). MCP server would need to load them again in a separate process.
   - What's unclear: Whether the combined VRAM (FastAPI + MCP both loaded simultaneously) causes OOM on the target GPU.
   - Recommendation: The MCP server lifespan should load the same components as `main.py`. If VRAM is a concern, consider an architecture where the MCP server calls the REST API instead of loading models directly. However, this adds HTTP coupling. For now, load models directly and monitor with `nvidia-smi`.

2. **BM25 index sharing between processes**
   - What we know: FastAPI loads BM25 from pickle (`data/bm25.pkl`). The MCP process can also load from this same file.
   - What's unclear: If FastAPI rebuilds the BM25 index while the MCP process has it loaded, the MCP process will have stale BM25 until restart. This is acceptable for now (BM25 is only one of three retrieval legs).
   - Recommendation: Load BM25 from pickle in MCP lifespan. Do not implement hot-reload; document that MCP server must be restarted after new documents are indexed if BM25 freshness matters.

3. **Whether `multiprocessing.set_start_method("spawn")` is needed in mcp_server.py**
   - What we know: `main.py` requires it because it uses `WorkerManager` (spawns subprocesses). The MCP server has no WorkerManager.
   - What's unclear: Whether importing `FlagEmbedding` or `docling` transitively triggers CUDA initialization that requires spawn.
   - Recommendation: Add it defensively as the first statement, same as `main.py`. Cost is zero; failure to add it on Linux with CUDA can be silent and hard to debug.

## Sources

### Primary (HIGH confidence)
- `mcp==1.26.0` installed at `/home/jcanossa/.pyenv/versions/3.13.3/lib/python3.13/site-packages/mcp/` — FastMCP class, Context class, ToolError exception, lifespan pattern, `run(transport="stdio")` method — all read directly from source
- `mcp/shared/context.py` — `RequestContext.lifespan_context` field — read directly from source
- `mcp/server/fastmcp/exceptions.py` — `ToolError` class — read directly from source
- `mcp/server/fastmcp/server.py` — `FastMCP.__init__`, `run()`, `Context` class — read directly from source
- `https://modelcontextprotocol.io/docs/develop/build-server` — Official MCP Python quickstart, FastMCP tool pattern, stdio pattern, logging warning (never write to stdout)
- `https://code.claude.com/docs/en/mcp` — Claude Code MCP configuration format, `.mcp.json` schema, `claude mcp add` CLI, project vs user scope, `MAX_MCP_OUTPUT_TOKENS`

### Secondary (MEDIUM confidence)
- `https://gofastmcp.com/servers/lifespan` — FastMCP lifespan pattern (`@asynccontextmanager`, `yield context`, `ctx.lifespan_context`) — consistent with source code inspection
- `https://gofastmcp.com/servers/tools` — ToolError usage pattern, async tool support, Context injection syntax — consistent with source code inspection
- `https://gofastmcp.com/deployment/running-server` — `mcp.run()` entry point pattern

### Tertiary (LOW confidence)
- WebSearch findings on VRAM concern — not verified against hardware specs; flagged as open question

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — MCP SDK installed and source-inspected; `ToolError` confirmed in `exceptions.py`; `lifespan_context` confirmed in `shared/context.py`
- Architecture: HIGH — patterns verified in SDK source + official docs; existing codebase interfaces read directly
- Pitfalls: HIGH (stdout corruption, blocking event loop) / MEDIUM (VRAM concern) — stdout issue is official documented warning; blocking is well-known asyncio behavior; VRAM is speculative

**Research date:** 2026-02-19
**Valid until:** 2026-03-19 (MCP SDK moves fast; re-verify if `mcp` package is upgraded)
