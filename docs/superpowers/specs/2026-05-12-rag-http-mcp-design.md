# RAG Server HTTP MCP + Stable Data Directory Design

## Summary

Refactor `rag-server` so Codex connects to a shared HTTP MCP endpoint instead of launching one heavy stdio MCP process per client. At the same time, make the default `DATA_DIR` resolve consistently to the repository-local `rag-server/data` directory instead of depending on the caller's current working directory.

## Goals

1. Replace per-client stdio MCP startup with a shared HTTP MCP endpoint.
2. Reuse one loaded retrieval/synthesis runtime for all MCP clients.
3. Keep Codex MCP configuration simple: local loopback HTTP, no TLS in phase 1.
4. Make the default data path deterministic and repo-local.
5. Align compose/runtime port configuration with the actual application port.

## Non-Goals

1. No HTTPS/TLS in this phase.
2. No change to retrieval quality or ingestion pipeline behavior.
3. No rework of Qdrant deployment beyond port/config alignment.
4. No attempt to preserve compatibility with existing stdio MCP configs as the primary path, except optionally as a temporary fallback.

## Current State

### MCP transport

- `src/rag_server/cli/commands.py` starts MCP with `mcp.run(transport="stdio")`.
- `src/rag_server/mcp_server.py` also runs only in stdio mode.
- `src/rag_server/cli/setup_wizard.py` writes MCP config using:
  - `type = "stdio"`
  - `command = "rag-server"`
  - `args = ["mcp"]`

This causes each Codex client to spawn its own `rag-server mcp` process.

### Runtime duplication

`src/rag_server/mcp_server.py` loads its own:

- BGE-M3 query embedder
- Qwen reranker
- BM25 manager
- Qdrant client
- LLM provider

`src/rag_server/main.py` separately loads another heavy runtime for the FastAPI app. This duplicates memory and defeats multi-client sharing.

### Data directory instability

`src/rag_server/config.py` defaults `DATA_DIR` to `Path("./data")`, which is resolved relative to whatever process working directory started the app. That means the server can write to an unintended location depending on how it was launched.

### Compose mismatch

- `docker-compose.yml` exposes `8000:8000`
- `cmd_start()` serves on port `8001`
- `scripts/start.sh` also serves on port `8001`

The compose app service is also under profile `app`, and only Qdrant is currently active.

## Chosen Approach

Expose MCP over HTTP from the shared RAG server runtime, with Codex configured to use:

`http://127.0.0.1:8001/mcp`

This is preferred over a thin stdio proxy because:

1. Codex supports HTTP MCP directly.
2. It removes per-client process duplication entirely.
3. It keeps deployment and troubleshooting simpler.

## Architecture

### 1. Shared runtime module

Create a shared runtime abstraction that owns:

- `QdrantStore`
- `BM25Manager`
- `Embedder`
- `Reranker`
- `RetrievalEngine`
- `LLM provider`
- `SynthesisEngine`
- optionally `WorkerManager` for the FastAPI app lifecycle

This runtime is initialized once and attached to the FastAPI app state.

### 2. HTTP MCP endpoint

Expose MCP on the same process as the FastAPI server at:

- `http://127.0.0.1:8001/mcp`

The MCP tools should call the shared runtime services instead of constructing their own lifespan-local copies.

### 3. REST + MCP parity

MCP and REST should use the same underlying retrieval/document operations.

Where MCP currently supports options not present in REST, the REST schemas/endpoints should be updated for parity if needed, especially:

- `ask.document_ids`
- `ask.min_score`

### 4. Deterministic data directory

Default `DATA_DIR` should resolve to the repository-local directory:

- `rag-server/data`

Implementation rule:

- if `DATA_DIR` is provided explicitly, use it
- otherwise derive default from the package/project root in a deterministic way
- normalize to an absolute path once in settings construction

This removes dependence on current working directory.

### 5. Compose alignment

Align compose and runtime to the same local app port. For this phase, standardize on:

- app port `8001`
- MCP URL `http://127.0.0.1:8001/mcp`

Compose should expose:

- `8001:8001` for the app
- existing Qdrant ports unchanged unless there is a separate reason to change them

## Detailed Design

### Shared runtime extraction

Refactor startup logic now duplicated across `main.py` and `mcp_server.py` into a common module, for example:

- `src/rag_server/runtime.py`

Responsibilities:

1. ensure data directories exist
2. initialize Qdrant store
3. load BM25
4. load query embedder
5. load reranker
6. build retrieval engine
7. build LLM provider and synthesis engine
8. expose cleanup methods

FastAPI app startup should use this runtime directly.

MCP HTTP handlers should read the runtime from app state and not create their own heavy resources.

### MCP server integration

There are two acceptable implementation variants:

1. mount FastMCP's HTTP ASGI app into FastAPI under `/mcp`
2. expose a FastAPI route layer that bridges incoming MCP requests to the MCP app/runtime

Preferred variant: mount the FastMCP HTTP app under `/mcp`, because it preserves standard MCP behavior while still sharing app-owned services.

### MCP setup/config changes

Update setup/config generation so new MCP registration uses HTTP instead of stdio:

```json
{
  "mcpServers": {
    "rag-server": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp"
    }
  }
}
```

No `DATA_DIR` env injection is needed in the MCP client config once the server itself owns the runtime and stable default path.

### Data path policy

Settings should treat the repo-local `data` directory as canonical for local development.

Expected resulting paths:

- uploads: `rag-server/data/uploads`
- sqlite: `rag-server/data/rag.db`
- bm25: `rag-server/data/bm25.pkl`
- qdrant bind mount: `rag-server/data/qdrant`

### Backward compatibility

For phase 1, existing stdio command support may remain in the CLI temporarily, but it should no longer be the recommended or generated configuration path.

If stdio is retained, it should either:

1. become a lightweight compatibility wrapper, or
2. be clearly documented as legacy/high-memory mode

## Error Handling

1. If the shared server is not running, Codex MCP requests fail with a clear connection error.
2. If Qdrant is unavailable, tools continue returning the existing MCP error codes such as `QDRANT_UNAVAILABLE`.
3. If LLM synthesis fails, keep the current fallback behavior returning raw sources.
4. If the data directory cannot be created, startup should fail fast with a clear absolute path in the error.

## Testing Strategy

### Unit tests

1. settings default path resolves to repo-local `rag-server/data`
2. explicit `DATA_DIR` env overrides the default
3. MCP config writer emits HTTP config with the expected URL
4. compose/config helper values agree on port `8001`

### Integration tests

1. FastAPI app starts with shared runtime and exposes `/mcp`
2. MCP `retrieve` works through HTTP transport
3. MCP `ask` works through HTTP transport
4. document tools operate against the same runtime/data store as REST

### Manual validation

1. Start Qdrant
2. Start `rag-server`
3. Confirm `http://127.0.0.1:8001/health`
4. Confirm MCP endpoint responds at `http://127.0.0.1:8001/mcp`
5. Point Codex MCP config to that URL
6. Open multiple Codex clients and confirm only one heavy RAG runtime is loaded

## Migration Plan

1. Add tests for settings and setup output.
2. Refactor shared runtime.
3. Add HTTP MCP endpoint.
4. Update setup/config generation.
5. Align compose/app port to `8001`.
6. Validate that data goes to `rag-server/data`.
7. Optionally keep stdio as temporary legacy compatibility mode.

## Risks

1. Mounting FastMCP into FastAPI may require careful lifecycle sharing.
2. Shared runtime increases concurrency pressure on embedder/reranker, so request serialization or throttling may be needed.
3. Existing local configs using stdio will need regeneration or manual update.

## Open Decisions Resolved

1. Transport: HTTP on loopback, not HTTPS, for phase 1.
2. Local MCP URL: `http://127.0.0.1:8001/mcp`
3. Canonical local data directory: `rag-server/data`
4. Canonical app port for this phase: `8001`
