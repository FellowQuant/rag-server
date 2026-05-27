# FellowQuant RAG Server

A local RAG (Retrieval-Augmented Generation) server built for quantitative finance research documents. Ingests PDFs, EPUB books, LaTeX source files, and Jupyter notebooks with structure preservation — financial tables stay as tables, mathematical formulas stay as LaTeX, code blocks stay intact. Exposes a REST API and MCP server.

<p align="center">
  <img src="assets/rag_server_logo.png" alt="RAG Server Logo" width="900">
</p>

## Installation

```bash
pip install rag-server
```

After installation, run `rag-server setup` (or any `rag-server` command) to configure the MCP server in Claude Code.

### Requirements

- Python 3.12+
- Docker (for Qdrant vector database)
- A running LLM endpoint (vLLM, llama.cpp, or AWS Bedrock credentials)
- GPU with ~2.5 GB VRAM (BGE-M3 ~1 GB + Qwen3-Reranker ~1.2 GB)

### CLI Commands

| Command | Description |
|---------|-------------|
| `rag-server setup` | Configure MCP server in Claude Code (global or local scope) |
| `rag-server start-qdrant` | Start Qdrant vector database via Docker |
| `rag-server start` | Start FastAPI REST server on port 8001 |
| `rag-server mcp` | Start legacy stdio MCP compatibility mode (proxies to the shared server) |

### MCP Setup

`rag-server setup` prompts for:
- **Global scope** (`--scope user`): MCP available in all Claude Code projects
- **Local scope**: writes `.mcp.json` in the current directory (commit to share with your team)

If the `claude` CLI is not installed, setup writes `.mcp.json` and prints instructions.

## What it does

- **Ingests** PDFs (via Docling), EPUB books, `.tex` files, and `.ipynb` notebooks with layout-aware chunking
- **Retrieves** using three-mode hybrid search: BM25 keyword + BGE-M3 dense + BGE-M3 sparse, fused via RRF and reranked by Qwen3-Reranker-0.6B
- **Answers** questions with a local LLM (vLLM, llama.cpp, or AWS Bedrock) and inline citations
- **Integrates** with Claude Code/Codex via HTTP MCP — 5 tools: `retrieve`, `ask`, `list_documents`, `get_document`, `delete_document`

## Setup (development / clone-and-run)

> **For most users:** install via `pip install rag-server` (see [Installation](#installation) above). The steps below are for contributors cloning the repo directly.

**1. Install dependencies**

```bash
uv sync
```

**2. Start Qdrant**

```bash
docker compose up -d qdrant
```

**3. Configure LLM**

Copy and edit the LLM config:

```bash
cp llm.yaml.example llm.yaml
# Edit llm.yaml: set provider (vllm/llamacpp/bedrock), model, base_url
```

**4. Run database migrations**

```bash
uv run alembic upgrade head
```

**5. Start the server**

```bash
./scripts/start.sh
```

This sets `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (prevents CUDA memory fragmentation stalls), binds to `0.0.0.0:8001` with hot-reload, and tees logs to `.logs/rag_server.log`.

## REST API

All endpoints are under `/api/v1`. A health check is at `/health`.

### Documents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/documents` | Upload a PDF, EPUB, `.tex`, or `.ipynb` file |
| `GET` | `/api/v1/documents` | List all documents with indexing status |
| `GET` | `/api/v1/documents/{id}` | Get metadata for a specific document |
| `DELETE` | `/api/v1/documents/{id}` | Delete document and all associated chunks/vectors |

### Query

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/retrieve` | Hybrid search — returns ranked chunks with citations |
| `POST` | `/api/v1/ask` | Full RAG — returns LLM-synthesized answer with citations (streaming SSE by default) |

### Retrieve request

```json
{
  "query": "Sharpe ratio under non-normal returns",
  "top_k": 10,
  "document_ids": ["uuid-1", "uuid-2"],
  "min_score": 0.3
}
```

`document_ids` and `min_score` are optional. Omit `document_ids` to search across all documents.

### Ask request

```json
{
  "query": "What is the Kelly criterion for fractional betting?",
  "top_k": 10
}
```

Returns SSE token stream by default. Add `?streaming=false` for a single JSON response.

### Errors

All errors use [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) Problem Details format:

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "Document abc123 not found"
}
```

Upload size limit: 100 MB (returns 413).

## MCP Server (Claude Code)

The `.mcp.json` at the project root points clients at the shared local MCP endpoint:

`http://127.0.0.1:8001/mcp`

### Tools

| Tool | Description |
|------|-------------|
| `retrieve` | Hybrid search — returns ranked chunks with full citation metadata and scores |
| `ask` | Full RAG pipeline — LLM-synthesized answer with citations; falls back to raw chunks if LLM unavailable |
| `list_documents` | List all documents with metadata and indexing status |
| `get_document` | Get metadata for a document by ID |
| `delete_document` | Delete a document and all associated data |

### Notes

- File upload is done via the REST API (`POST /api/v1/documents`), not through MCP
- MCP now proxies to the shared FastAPI runtime, so multiple clients do not each load their own BGE-M3/reranker stack

### Manual MCP test

```bash
# Browse tools interactively (development only)
uv run mcp dev src/rag_server/mcp_server.py

# Re-run setup to (re-)register with Claude Code
rag-server setup
```

## Technology stack

| Component | Library | Notes |
|-----------|---------|-------|
| PDF parser | Docling (IBM) | 97.9% table accuracy; Granite-Docling VLM for formula→LaTeX |
| EPUB parser | EPUB spine + Docling HTML | Section-based text/table/code extraction; no page numbers |
| LaTeX parser | pylatexenc 2.10 | Direct `.tex` ingestion |
| Notebook parser | nbformat | Code and output cells preserved |
| Embeddings | BGE-M3 (FlagEmbedding) | Dense + sparse vectors from single inference pass |
| Keyword search | rank-bm25 | Full-corpus BM25; persisted as pickle |
| Vector store | Qdrant v1.16.3 | Local Docker; dense + sparse schema |
| Reranker | Qwen3-Reranker-0.6B | Cross-encoder; ~61 BEIR nDCG@10 |
| LLM | vLLM / llama.cpp / AWS Bedrock | Provider-swappable via `llm.yaml` |
| Database | SQLite + SQLAlchemy | Document and chunk metadata |
| API | FastAPI + uvicorn | Async; RFC 7807 errors; SSE streaming |
| MCP | fastmcp | streamable HTTP transport; 5 tools |

## Verification scripts

```bash
# Verify the installed wheel (entry points, assets, subcommands)
bash scripts/smoke_test_cli.sh

# REST API — requires running server at localhost:8001
python scripts/verify_api.py

# Earlier phases (run in order against a running server)
python scripts/verify_storage.py
python scripts/verify_ingestion.py
python scripts/verify_retrieval.py
python scripts/verify_llm.py
```

## Data layout

```
data/
├── uploads/      # Uploaded files, stored as {sha256}{ext}
├── qdrant/       # Qdrant persistent storage (mounted into Docker)
└── bm25.pkl      # BM25 index (rebuilt after each document is indexed)
```

`DATA_DIR` environment variable controls the base path (default: `./data`).

## Configuration

### Environment variables (`.env`)

```bash
DATA_DIR=./data   # optional override; default is repo-local rag-server/data
QDRANT_HOST=localhost      # or container name inside Docker
QDRANT_PORT=6330
MAX_UPLOAD_SIZE=104857600  # 100 MB in bytes
```

### LLM (`llm.yaml`)

```yaml
llm:
  provider: vllm            # vllm | llamacpp | bedrock
  model: Qwen/Qwen2.5-7B-Instruct
  base_url: http://localhost:8000/v1
  context_chunks: 5
  max_context_tokens: 8000
```

See `llm.yaml.example` for all options including Bedrock and the system prompt.
