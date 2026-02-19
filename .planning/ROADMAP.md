# Roadmap: FellowQuant RAG Server

## Overview

This roadmap delivers a specialized RAG system for quantitative finance research documents. We start by establishing storage infrastructure (Qdrant + SQLite), then build a layout-aware document ingestion pipeline using Docling with atomic chunking that preserves tables and formulas. Next comes the retrieval engine with three-mode hybrid search (BM25 + dense + sparse via BGE-M3 + RRF fusion) and Qwen3-Reranker cross-encoder reranking, followed by local LLM integration via vLLM, llama.cpp, and AWS Bedrock for answer synthesis. Finally, we expose functionality through a REST API and MCP server for Claude Code integration. Each phase delivers a verifiable capability that enables the next.

**Core technology stack (research-validated 2026-02-18):**
- **Parser:** Docling (IBM) — 97.9% table accuracy, dedicated VLM for formula→LaTeX; Marker as fast-path fallback
- **Embedding:** BGE-M3 — unique three-mode output (dense + sparse + multi-vector) enabling full hybrid retrieval
- **Vector store:** Qdrant (local Docker) — required for BGE-M3 multi-vector and future ColFlor visual retrieval
- **Reranker:** Qwen3-Reranker-0.6B (Apache 2.0) — ~61 BEIR nDCG@10, Qwen3 stack cohesion
- **LLM:** vLLM (local GPU, OpenAI-compatible) | llama.cpp (local CPU/GGUF) | AWS Bedrock (cloud fallback via boto3 standard credential chain) — provider-swappable via llm.yaml
- **Hybrid retrieval:** BM25 + BGE-M3 dense + BGE-M3 sparse, fused via Reciprocal Rank Fusion

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & Storage** - Establish persistent storage for vectors, metadata, and document tracking
- [x] **Phase 2: Document Ingestion Pipeline** - Parse PDFs, LaTeX, and notebooks with structure preservation (completed 2026-02-19)
- [x] **Phase 3: Retrieval Engine** - Semantic and hybrid search with citation tracking (completed 2026-02-19)
- [ ] **Phase 4: LLM Integration** - Local model serving and answer synthesis
- [ ] **Phase 5: REST API** - HTTP endpoints for document lifecycle and queries
- [ ] **Phase 6: MCP Server** - Claude Code integration via MCP protocol

## Phase Details

### Phase 1: Foundation & Storage
**Goal**: Persistent storage infrastructure for embeddings, metadata, and document tracking is operational
**Depends on**: Nothing (first phase)
**Requirements**: STORE-01, STORE-02, STORE-03, STORE-04
**Stack**: Qdrant (local Docker), SQLite + SQLAlchemy, `./data/` directory layout
**Success Criteria** (what must be TRUE):
  1. System can store and retrieve vector embeddings from persistent Qdrant instance (local Docker)
  2. System can store and query document metadata (title, author, pages, format, hash) in SQLite database
  3. System can link chunks to source documents via foreign keys with page/section/chunk-type metadata
  4. System handles 100+ document corpus without performance degradation
  5. Qdrant collection schema supports multi-vector storage (dense + sparse fields) required by BGE-M3
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Project scaffold: pyproject.toml, docker-compose.yml, Settings class with DATA_DIR
- [x] 01-02-PLAN.md — SQLite layer: async ORM models (Document, Chunk), engine, Alembic migration
- [x] 01-03-PLAN.md — Qdrant client wrapper (QdrantStore) and end-to-end storage smoke test

### Phase 2: Document Ingestion Pipeline
**Goal**: Users can upload PDFs, LaTeX, and Jupyter notebooks with preserved structure (tables, formulas, code)
**Depends on**: Phase 1
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, INGEST-06
**Stack**: Docling (primary parser, formula VLM, DocLayNet layout), nbformat (notebooks), pylatexenc (LaTeX source), BGE-M3 (FlagEmbedding) for embeddings
**Chunking strategy**:
  - Atomic units (never split): formula blocks, table blocks, code blocks — one chunk each
  - Text blocks: semantic paragraph splitting (256–512 tokens, 64-token overlap)
  - Formula context enrichment: prepend preceding paragraph to formula chunk's embedding text; store raw LaTeX in display_content
**Success Criteria** (what must be TRUE):
  1. User uploads a PDF and receives back chunks with intact financial tables (no mangled columns)
  2. User uploads a LaTeX file and mathematical notation is preserved as LaTeX markup in chunks
  3. User uploads a Jupyter notebook and code cells remain syntactically complete in chunks
  4. System never splits a formula or code block across chunk boundaries
  5. User can query document indexing status and see pending/indexing/indexed/failed states
  6. Formula chunks include surrounding paragraph text in their embedding context
**Plans**: 4 plans

Plans:
- [x] 02-01-PLAN.md — Parsers & chunker: Docling PDF parser, pylatexenc LaTeX parser, nbformat Jupyter parser, ParsedChunk dataclass
- [x] 02-02-PLAN.md — BGE-M3 embedder: Embedder class with load/unload/embed_chunks, EmbeddingResult with dense+sparse vectors
- [x] 02-03-PLAN.md — Worker process: pipeline (parse→embed→SQLite→Qdrant with rollback), process entry point, WorkerManager lifecycle
- [x] 02-04-PLAN.md — Ingestion API: POST/GET/LIST/DELETE /documents endpoints, FastAPI lifespan, integration smoke test

### Phase 3: Retrieval Engine
**Goal**: Users can semantically search documents with hybrid ranking and get back cited chunks
**Depends on**: Phase 2
**Requirements**: RETR-01, RETR-02, RETR-03, RETR-04, RETR-05
**Stack**: BGE-M3 three-mode retrieval (dense + sparse), rank-bm25 for full-text BM25, Reciprocal Rank Fusion for score combination, Qwen3-Reranker-0.6B cross-encoder
**Retrieval pipeline**:
  - Stage 1: Parallel retrieval — BM25 keyword search + BGE-M3 dense ANN + BGE-M3 sparse (learned term weights)
  - Stage 2: RRF fusion with adaptive alpha (exact-term queries favor sparse/BM25; conceptual queries favor dense)
  - Stage 3: Qwen3-Reranker-0.6B cross-encoder reranking of top-50 candidates → return top-10
**Success Criteria** (what must be TRUE):
  1. User queries for a concept and receives semantically relevant chunks ranked by similarity
  2. User queries with specific terminology and results combine BM25 + dense + sparse hybrid search
  3. Initial retrieval results are reranked by Qwen3-Reranker-0.6B cross-encoder for improved top-10 precision
  4. Every returned chunk includes source document name, page number, section heading, and chunk type (text/formula/table/code)
  5. User can ask comparative queries and receive chunks from multiple documents synthesizing the topic
**Plans**: 4 plans

Plans:
- [x] 03-01-PLAN.md — Qdrant v1.16.3 upgrade + encode_query() on Embedder + query_dense()/query_sparse() on QdrantStore
- [x] 03-02-PLAN.md — BM25Manager (build/search/persist/hot-swap) + WorkerManager result_queue + FastAPI BM25 poll task
- [x] 03-03-PLAN.md — Qwen3-Reranker-0.6B wrapper (AutoModelForCausalLM, yes/no logit extraction, padding_side=left)
- [x] 03-04-PLAN.md — RetrievalEngine (three-leg RRF + reranker) + result dataclasses + lifespan wiring + smoke test

### Phase 4: LLM Integration
**Goal**: Local LLM generates synthesized answers with inline citations from retrieved chunks
**Depends on**: Phase 3
**Requirements**: LLM-01, LLM-02, LLM-03
**Stack**: vLLM (local GPU, OpenAI-compatible) | llama.cpp (local CPU/GGUF, OpenAI-compatible) | AWS Bedrock (cloud fallback via boto3 standard credential chain) — provider selected via llm.yaml
**Success Criteria** (what must be TRUE):
  1. System serves a local LLM (vLLM or llama.cpp) or cloud (AWS Bedrock) without hardcoded cloud API keys
  2. User asks a question and receives a synthesized answer with inline citations (e.g., "[Source: paper.pdf, p.12]")
  3. LLM responses stream in real-time as they generate (SSE token events + done event with {answer, sources})
**Plans**: 4 plans

Plans:
- [x] 04-01-PLAN.md — Dependencies (openai, boto3, sse-starlette, tenacity, pyyaml) + llm.yaml config + LLMSettings + LLMProvider ABC + API schemas
- [x] 04-02-PLAN.md — Concrete providers: VLLMProvider + LlamaCppProvider (AsyncOpenAI) + BedrockProvider (boto3 + asyncio.to_thread)
- [x] 04-03-PLAN.md — SynthesisEngine: prompt assembly, token budget (tiktoken), citation parsing (lenient regex), tenacity retry
- [ ] 04-04-PLAN.md — POST /ask endpoint (SSE streaming + non-streaming) + lifespan wiring + smoke test

### Phase 5: REST API
**Goal**: Full document lifecycle and query operations exposed via HTTP endpoints
**Depends on**: Phase 4
**Requirements**: API-01, API-02, API-03, API-04, API-05, API-06
**Success Criteria** (what must be TRUE):
  1. User can POST a document file to ingest endpoint and receive confirmation with document ID
  2. User can GET list of all documents with metadata and indexing status
  3. User can DELETE a document by ID and all associated chunks/embeddings are removed
  4. User can POST to retrieve endpoint with query and receive ranked chunks with citations
  5. User can POST to ask endpoint with query and receive LLM-synthesized answer with citations
  6. User can GET status of a specific document by ID to check indexing progress
**Plans**: 3 plans

Plans:
- [ ] 05-01-PLAN.md — API infrastructure: /api/v1 prefix, middleware (CORS, logging, upload size limit), RFC 7807 error handlers
- [ ] 05-02-PLAN.md — document_ids filter on RetrievalEngine + QdrantStore + new POST /api/v1/retrieve endpoint
- [ ] 05-03-PLAN.md — End-to-end verification script (scripts/verify_api.py) covering all API-01 through API-06

### Phase 6: MCP Server
**Goal**: Claude Code can manage documents and query knowledge base via MCP protocol
**Depends on**: Phase 5
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04, MCP-05, MCP-06
**Success Criteria** (what must be TRUE):
  1. Claude Code discovers MCP server via stdio transport and lists available tools
  2. Claude Code calls retrieve tool and receives raw chunks with citations
  3. Claude Code calls ask tool and receives LLM-synthesized answer with citations
  4. Claude Code calls ingest_document tool and successfully adds file to corpus
  5. Claude Code calls list_documents tool and sees inventory with indexing status
  6. Claude Code calls delete_document tool and document is removed from corpus
**Plans**: TBD

Plans:
- [ ] TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Storage | 3/3 | Complete    | 2026-02-18 |
| 2. Document Ingestion Pipeline | 4/4 | Complete   | 2026-02-19 |
| 3. Retrieval Engine | 4/4 | Complete   | 2026-02-19 |
| 4. LLM Integration | 3/4 | In Progress|  |
| 5. REST API | 2/3 | In Progress|  |
| 6. MCP Server | 0/TBD | Not started | - |
