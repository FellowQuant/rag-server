# Stack Research

**Domain:** Financial Document RAG Server
**Researched:** 2026-02-12
**Confidence:** MEDIUM (based on training data + user-provided analysis; versions need verification)

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ | Primary language | Ecosystem dominance in ML/NLP/RAG. All key libraries are Python-native. |
| FastAPI | 0.100+ | REST API framework | Async support, automatic OpenAPI docs, Pydantic validation. Standard for ML APIs. |
| Marker | Latest | PDF-to-Markdown conversion | Best-in-class PDF parser: preserves LaTeX formulas, detects tables, handles multi-column layouts, detects code blocks. GPU-accelerated. |
| ChromaDB | 0.4+ | Vector database | Embeddable, persistent, simple API. Good for 100-1K document scale. Can swap to Qdrant for production. |
| sentence-transformers | Latest | Embedding generation | Industry standard. BGE, E5, or Nomic embed models for technical content. |
| Ollama | Latest | Local LLM serving | Simplest local LLM setup. Pre-built model management. OpenAI-compatible API. Start here, upgrade to vLLM for production. |
| MCP Python SDK | Latest | MCP server protocol | Official Anthropic SDK. Stdio transport for Claude Code integration. |
| SQLite | 3.x | Metadata storage | Zero-config, file-based. Perfect for single-user local deployment. Stores document metadata, chunk mappings, citations. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rank-bm25 | Latest | BM25 keyword search | Hybrid retrieval: combine with vector search via RRF |
| cross-encoder (sentence-transformers) | Latest | Reranking | Two-stage retrieval: rerank top-N candidates for precision |
| nbformat | Latest | Jupyter notebook parsing | When ingesting .ipynb files |
| plasTeX or custom | Latest | LaTeX source parsing | When ingesting .tex files directly |
| Pydantic | 2.x | Data models/validation | API request/response schemas, config management |
| uvicorn | Latest | ASGI server | Runs FastAPI in production |
| SQLAlchemy | 2.x | ORM | Clean metadata DB access if SQLite queries get complex |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest | Testing | Unit + integration tests for parsers, retrieval, API |
| Docker | Containerization | Optional: package server + dependencies for reproducibility |
| ruff | Linting/formatting | Fast Python linter, replaces flake8 + black |

## Installation

```bash
# Core
pip install fastapi uvicorn marker-pdf chromadb sentence-transformers ollama pydantic sqlalchemy

# Supporting
pip install rank-bm25 nbformat

# MCP
pip install mcp

# Dev dependencies
pip install pytest ruff httpx
```

## Alternatives Considered

| Category | Recommended | Alternative | When to Use Alternative |
|----------|-------------|-------------|-------------------------|
| PDF Parser | Marker | RAGFlow DeepDoc | If Marker table extraction is insufficient for complex financial tables. RAGFlow has vision-based table detection but is a heavier dependency (full RAG system, not just parser). |
| PDF Parser | Marker | PaperQA | If you want built-in agentic cross-document synthesis. PaperQA handles paper parsing + retrieval + citation in one package. Less control over individual components. |
| Vector Store | ChromaDB | Qdrant | For production deployment or if scaling beyond 1K documents. Better performance, more features (filtering, payload indexing). Requires running separate service. |
| Vector Store | ChromaDB | FAISS | If maximum retrieval speed needed. No persistence built-in (need to manage save/load). Facebook Research library, battle-tested. |
| LLM Serving | Ollama | vLLM | For production: significantly faster inference, batching, streaming. More complex setup. Use when Ollama latency becomes a bottleneck. |
| LLM Serving | Ollama | llama.cpp (via llama-cpp-python) | If you want embedded LLM (no separate server process). Good for minimal deployments. Less feature-rich than Ollama/vLLM. |
| API Framework | FastAPI | Flask | If team prefers Flask. FastAPI is better for async (important for LLM calls), has better Pydantic integration. |
| Metadata DB | SQLite | PostgreSQL | If multi-user or complex queries needed. Overkill for single-user local deployment. |
| Embedding Model | BGE/E5/Nomic | Voyage AI | Higher quality embeddings, especially for technical content. Requires API key (cloud). Conflicts with local-only constraint. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| LangChain (full framework) | Over-abstracted for this use case. Adds complexity without proportional value. Many unnecessary dependencies. | Build pipeline with direct library calls. Use specific components if needed (langchain-community has useful utilities). |
| LlamaIndex (full framework) | Similar to LangChain — heavy abstraction layer. Good for prototyping but obscures what's happening. | Direct integration with vector store + embedding model. More control, easier debugging. |
| PyPDF2 / pdfplumber | Cannot preserve table structure, formulas, or multi-column layouts. Text-only extraction. | Marker for layout-aware parsing. |
| OpenAI Embeddings | Cloud API dependency. Conflicts with local-only constraint. Costs money per request. | sentence-transformers with BGE/E5/Nomic models. Free, local, comparable quality. |
| Pinecone / Weaviate Cloud | Cloud-hosted vector DBs. Privacy conflict + requires internet. | ChromaDB (local) or Qdrant (local deployment). |
| Elasticsearch | Heavy Java-based system for what you need. Overkill for keyword search on 100-1K docs. | rank-bm25 (Python, lightweight BM25 implementation) + SQLite for filtering. |
| RAGFlow (as full system) | While DeepDoc parser is excellent, RAGFlow is a full RAG platform with web UI, user management, etc. Using it means adopting their architecture, not yours. | Extract patterns from RAGFlow's approach, use Marker for parsing, build custom pipeline. |

## Stack Patterns by Variant

**If corpus is < 50 documents:**
- Use FAISS (in-memory) instead of ChromaDB
- Skip BM25/hybrid search — semantic only is fine
- Skip reranking — simpler pipeline
- Because: Lower complexity, faster iteration

**If corpus is 50-500 documents:**
- Use ChromaDB with persistence
- Add BM25 hybrid search
- Add cross-encoder reranking
- Because: Quality matters at this scale, worth the complexity

**If corpus is 500+ documents:**
- Use Qdrant (production vector store)
- Use vLLM instead of Ollama
- Add query result caching (Redis or simple LRU)
- Consider sharding by document type
- Because: Performance and reliability become critical

**If GPU VRAM is limited (< 8GB):**
- Use smaller embedding model (all-MiniLM-L6-v2, 384 dims)
- Use quantized LLM (Q4 or Q5)
- Run embedding and LLM on different GPUs or time-share
- Because: VRAM is the bottleneck for local deployment

**If GPU VRAM is generous (24GB+):**
- Use larger embedding model (BGE-large, 1024 dims)
- Use larger LLM (13B or 34B params, Q5/Q6)
- Run Marker with GPU acceleration for faster parsing
- Because: Quality scales with model size when VRAM allows

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Marker | PyTorch 2.x | GPU acceleration requires CUDA-compatible PyTorch |
| sentence-transformers | PyTorch 2.x | Same PyTorch version as Marker |
| ChromaDB | sentence-transformers | Can use same embedding function directly |
| FastAPI + Pydantic v2 | Ensure Pydantic 2.x | FastAPI 0.100+ requires Pydantic v2 |
| MCP SDK | Python 3.10+ | Requires modern Python for async features |
| Ollama | Any (HTTP API) | Separate process, communicates via HTTP. No Python version dependency. |

## Sources

- User-provided analysis of RAGFlow, PaperQA, Marker (initial project context)
- Training data on RAG architectures, Python ML ecosystem (up to Jan 2025)
- MCP Protocol documentation (modelcontextprotocol.io)
- **LOW confidence items needing verification:** Specific library versions, Marker vs RAGFlow DeepDoc benchmarks, current best embedding models for financial content

---
*Stack research for: Financial Document RAG Server*
*Researched: 2026-02-12*
