# Project Research Summary

**Project:** Financial Document RAG Server
**Domain:** AI-powered document retrieval and analysis for quantitative finance research
**Researched:** 2026-02-12
**Confidence:** MEDIUM

## Executive Summary

This is a specialized RAG (Retrieval Augmented Generation) system designed for financial and quantitative research documents. Unlike generic RAG systems, it must preserve complex document structure including multi-column layouts, LaTeX formulas, financial tables, and code blocks. The research reveals that success hinges on three critical choices: (1) layout-aware PDF parsing (Marker recommended over simple extraction), (2) hybrid retrieval combining semantic search with keyword matching for mathematical notation, and (3) format-aware chunking that treats formulas and tables as atomic units.

The recommended approach is a Python-based architecture using FastAPI for the REST API layer, Marker for PDF parsing, ChromaDB for vector storage, and Ollama for local LLM serving. The system exposes both a REST API and MCP server interface, enabling seamless integration with Claude Code. Start with semantic-only retrieval and standard parsers for MVP, then enhance with hybrid search (BM25 + vector), reranking, and specialized parsers (.tex, .ipynb) based on corpus characteristics.

The primary risk is structural data loss during ingestion. Naive chunking will destroy formulas and tables, making retrieval meaningless. Mitigate by implementing formula-aware and table-aware chunking from the start, testing with real financial documents (dual-column papers, correlation matrices, multi-line equations) before building the retrieval layer. Secondary risks include VRAM conflicts between embedding models and LLMs (sequence operations to avoid OOM errors) and citation provenance loss (design metadata schema upfront to track document ID, page, and section for every chunk).

## Key Findings

### Recommended Stack

Python dominates the ML/NLP/RAG ecosystem with mature libraries for every component. The stack prioritizes local-first operation (privacy requirement for proprietary research) with the flexibility to swap components as the corpus scales.

**Core technologies:**
- **Python 3.11+**: Primary language — ecosystem dominance in ML/NLP, all key RAG libraries are Python-native
- **FastAPI 0.100+**: REST API framework — async support crucial for LLM calls, automatic OpenAPI docs, Pydantic validation
- **Marker**: PDF-to-Markdown conversion — best-in-class for preserving LaTeX formulas, detecting tables, handling multi-column layouts, GPU-accelerated
- **ChromaDB 0.4+**: Vector database — embeddable, persistent, simple API, good for 100-1K document scale (can swap to Qdrant for production)
- **sentence-transformers**: Embedding generation — industry standard, BGE/E5/Nomic models recommended for technical content
- **Ollama**: Local LLM serving — simplest local LLM setup with pre-built model management and OpenAI-compatible API (upgrade to vLLM for production performance)
- **MCP Python SDK**: MCP server protocol — official Anthropic SDK for stdio transport and Claude Code integration
- **SQLite 3.x**: Metadata storage — zero-config, file-based, perfect for single-user local deployment, stores document metadata, chunk mappings, citations

**Supporting libraries:**
- rank-bm25 for hybrid retrieval (keyword search combined with vector search)
- cross-encoder (sentence-transformers) for two-stage retrieval reranking
- nbformat for Jupyter notebook parsing (when .ipynb files in corpus)

**Scaling variants:**
- For <50 docs: Use FAISS in-memory, skip BM25/reranking (lower complexity, faster iteration)
- For 50-500 docs: Use ChromaDB with persistence, add BM25 hybrid search and reranking (quality matters at this scale)
- For 500+ docs: Switch to Qdrant, use vLLM instead of Ollama, add query caching (performance becomes critical)

### Expected Features

The feature landscape divides cleanly into table stakes (users expect these), differentiators (specialized capabilities for financial documents), and anti-features (explicitly avoid to prevent scope creep).

**Must have (table stakes):**
- PDF ingestion with layout preservation — multi-column detection, not just text extraction
- Document CRUD operations — add, list, delete via API
- Semantic search/retrieval — vector embeddings and similarity search
- Chunk-level citations — track source doc, page, section for every chunk
- REST API — standard programmatic access for document operations and queries
- Index status tracking — states (pending, processing, indexed, failed) so users know when documents are queryable
- Local execution — no cloud API dependencies for privacy with proprietary research
- Dual-mode queries — retrieve mode (raw chunks) vs ask mode (LLM-synthesized answers)

**Should have (competitive differentiators):**
- LaTeX formula preservation — formulas as LaTeX not garbled text (10x better comprehension)
- Financial table structure preservation — correlation matrices and factor loadings lose meaning when linearized
- Jupyter notebook ingestion — code + analysis together for complete context
- Multi-column layout handling — academic papers use dual-column, reading order matters
- Hybrid retrieval (semantic + keyword) — dense math papers need both concept similarity and exact term matching
- Reranking for precision — two-stage retrieval with cross-encoder improves relevance
- MCP server integration — native Claude Code integration for seamless workflow
- Code block detection and preservation — Python implementations in papers need to stay as code

**Defer (v2+):**
- Cross-document synthesis — agentic patterns to compare concepts across papers (complex, defer until MVP validated)
- Citation graph tracking — "which papers cite this formula?" for research exploration (complex graph DB, unclear ROI)
- LaTeX source ingestion — parse .tex files directly for ground truth formulas (add when users have .tex sources)
- Figure caption extraction — chart/diagram context (add when visual context proves important)

**Anti-features (explicitly avoid):**
- Web UI/dashboard — adds complexity, not v1 consumption pattern (REST + MCP only)
- Cloud-hosted deployment — privacy concerns and network latency (local-first architecture)
- Proprietary LLM API dependency — cost, privacy, requires internet (use Ollama/vLLM locally)
- Real-time document watching — filesystem monitoring complexity, YAGNI (manual ingestion via API)
- User authentication/multi-tenancy — single-user local deployment (simple or no auth for localhost)
- Document versioning — complex, unclear use case (delete + re-ingest if document updated)

### Architecture Approach

The architecture follows standard RAG patterns with specialized components for financial document processing. The system is structured in layers: API (REST + MCP) → Query Orchestration (Retriever, LLM Synthesis, Doc Manager) → Storage & Indexing (Vector Store, Metadata DB, LLM Engine) → Ingestion Pipeline (format-specific parsers, smart chunking, embeddings).

**Major components:**
1. **Ingestion Pipeline** — PDF/LaTeX/Notebook parsers → format-aware chunking (formula-aware, table-aware) → embedding model → vector store + metadata DB. Critical that parsers preserve structure and chunkers treat formulas/tables as atomic units.
2. **Dual-Mode Retrieval** — Retrieve mode returns raw chunks with citations for manual reasoning; Ask mode returns LLM-synthesized answers with inline citations. Both use same underlying hybrid search (vector + BM25) with optional reranking.
3. **Storage Layer** — Vector store (ChromaDB/FAISS/Qdrant) for semantic search, completely separate from metadata DB (SQLite) for document lifecycle, chunk tracking, and citation building. Clean separation allows swapping vector stores without affecting metadata.
4. **MCP Server as Thin Wrapper** — MCP server is a protocol translation layer over core retrieval/generation logic. All business logic lives in retrieval/generation modules. Easy to add other interfaces (REST, CLI) without duplicating logic.
5. **Local LLM Integration** — vLLM (production) or Ollama (simplicity) for answer generation. Separate service communicating via HTTP. Supports model swapping without changing synthesis logic.

**Critical architectural patterns:**
- **Formula-aware chunking** — Never split mathematical formulas or code blocks across chunk boundaries. Parse elements (text, formula, code, table), treat formulas/code as atomic units. Prevents garbage chunks like "where α = " (formula split mid-expression).
- **Two-stage retrieval (retrieve → rerank)** — Fast semantic search returns top-20-50 candidates, cross-encoder reranks for top-5-10. Much better relevance than single-stage, worth the latency for complex queries.
- **Hybrid search (vector + keyword)** — Combine dense vector search with sparse BM25 keyword search, fuse via Reciprocal Rank Fusion. Catches both semantic similarity AND exact term matches (crucial for financial jargon, formulas, author names).
- **Citation metadata propagation** — Every chunk carries (document_id, page_number, section_header, paragraph_index) from parser → chunker → vector store. Design metadata schema upfront to ensure provenance never gets lost.

### Critical Pitfalls

1. **Naive chunking destroys financial tables and formulas** — Fixed-size text chunking (e.g., 512 tokens) splits formulas mid-expression, separates table headers from data rows, breaks multi-line equations. Retrieved chunks become meaningless fragments. Prevention: Use format-aware chunking that treats formulas, tables, and code blocks as atomic units. Split on section/paragraph boundaries, not character counts. Test with sample financial documents before scaling.

2. **PDF parser can't handle dual-column academic layouts** — Simple text extraction (PyPDF2, pdfplumber) reads across column boundaries instead of down each column. Sentences from left and right columns interleave, creating nonsensical text. Catastrophic for dual-column papers (standard in academic finance). Prevention: Use layout-aware parser (Marker, RAGFlow DeepDoc) that detects column structure. Validate with dual-column sample papers.

3. **Embedding model doesn't understand mathematical notation** — General-purpose embedding models treat LaTeX notation as random tokens. Query "Black-Scholes formula" doesn't match chunk containing the actual formula because model can't bridge natural language to mathematical notation. Prevention: Include natural language descriptions alongside formulas during chunking. Use embedding models with scientific/technical training (SPECTER, SciBERT, BGE). Add hybrid retrieval (BM25 + vector) to catch exact term matches.

4. **Local LLM VRAM conflicts with embedding model** — Embedding model and LLM both need GPU VRAM. Running Marker (GPU-accelerated) + embedding model + LLM simultaneously exceeds available VRAM. Server crashes with CUDA OOM errors or falls back to CPU (10-100x slower). Prevention: Sequence operations (don't run ingestion and LLM inference simultaneously). Use CPU for embedding. Use quantized LLM (Q4/Q5). Profile VRAM usage and plan allocation.

5. **Citation provenance lost during processing** — After parsing → chunking → embedding, chunks lose connection to source document, page number, and section. Users can't verify claims against original source. Prevention: Design metadata schema upfront. Parser must output structured objects with position metadata. Chunker must propagate metadata. Vector store must support metadata storage and filtering. Test end-to-end before building on top.

6. **MCP server blocks on long operations** — MCP tool calls for ingestion or complex queries block the MCP server. Claude Code appears frozen, can't cancel, no progress feedback. Prevention: Make ingestion async (return job_id immediately, separate tool to check status). Use streaming for LLM synthesis if transport supports it. Keep retrieve tool fast (<2s) by optimizing retrieval pipeline.

## Implications for Roadmap

Based on research, suggested phase structure follows dependency order: Foundation (storage) → Ingestion → Retrieval → LLM → API → MCP → Advanced Features.

### Phase 1: Foundation & Storage Layer
**Rationale:** All other components depend on storage. Must exist before ingestion or retrieval can function. Metadata schema design is critical for citation provenance (Pitfall #5).

**Delivers:**
- Vector store interface (ChromaDB or FAISS abstraction)
- Metadata database schema (SQLite with document/chunk tables)
- Document and chunk data models (Pydantic)
- Configuration management (embedding model, vector store, LLM endpoint)

**Addresses:**
- Citation provenance (PITFALLS.md Pitfall #5) — metadata schema designed upfront
- Enables swapping vector stores later (STACK.md scaling variants)

**Avoids:**
- Citation metadata lost during processing — schema includes document_id, page_number, section_header, chunk_index from start

### Phase 2: Ingestion Pipeline (Basic)
**Rationale:** Depends on storage layer. Start with basic PDF parsing and chunking to validate end-to-end flow. Formula-aware chunking is critical to avoid Pitfall #1. Test with real financial documents before building retrieval.

**Delivers:**
- PDF parser integration (Marker for layout-aware parsing)
- Formula-aware chunker (treats formulas and code blocks as atomic units)
- Table-aware chunker (preserves table structure, doesn't split mid-row)
- Embedding model integration (sentence-transformers with BGE/E5/Nomic)
- Metadata propagation (parser → chunker → storage)
- Document ingestion API endpoint (POST /documents)

**Uses:**
- Marker (STACK.md) for PDF-to-Markdown with formula/table preservation
- sentence-transformers (STACK.md) for embedding generation
- ChromaDB (STACK.md) for vector storage

**Implements:**
- Ingestion Pipeline architecture component (ARCHITECTURE.md)
- Formula-aware chunking pattern (ARCHITECTURE.md Pattern 2)

**Addresses:**
- PDF ingestion with layout preservation (FEATURES.md table stakes)
- Document CRUD operations (FEATURES.md table stakes) — ingestion half

**Avoids:**
- Naive chunking destroys formulas/tables (PITFALLS.md Pitfall #1) — formula-aware chunking from start
- Column detection failures (PITFALLS.md Pitfall #2) — Marker handles multi-column layouts
- Citation provenance lost (PITFALLS.md Pitfall #5) — metadata propagation through pipeline

### Phase 3: Basic Retrieval
**Rationale:** Depends on indexed documents from Phase 2. Start with semantic-only search to validate end-to-end query flow. Hybrid search and reranking deferred to Phase 5 (can launch without them).

**Delivers:**
- Semantic search (vector similarity)
- Citation building (chunk metadata → source references)
- Document list/delete API endpoints (GET /documents, DELETE /documents/:id)
- Query API endpoint (POST /query for retrieve mode)
- Index status tracking (document states: pending, processing, indexed, failed)

**Uses:**
- ChromaDB (STACK.md) for vector similarity search
- SQLite (STACK.md) for metadata queries and citation building

**Implements:**
- Retriever component (ARCHITECTURE.md)
- Citation metadata system (ARCHITECTURE.md)

**Addresses:**
- Semantic search/retrieval (FEATURES.md table stakes)
- Chunk-level citations (FEATURES.md table stakes)
- Index status tracking (FEATURES.md table stakes)
- REST API (FEATURES.md table stakes) — document + query endpoints

**Tests:**
- End-to-end: ingest document, retrieve chunks, verify citations point to correct pages
- Validate formula preservation: query known formulas, verify chunks contain complete expressions

### Phase 4: LLM Integration (Ask Mode)
**Rationale:** Depends on retrieval (Phase 3) to provide context chunks. LLM synthesis enables ask mode (table stakes feature). VRAM planning critical to avoid Pitfall #4.

**Delivers:**
- Ollama client (local LLM serving)
- RAG prompt templates (query + context chunks → answer)
- Answer synthesis with inline citations
- Ask API endpoint (POST /ask)
- VRAM budget planning (sequence ingestion and LLM operations)

**Uses:**
- Ollama (STACK.md) for local LLM serving (simple setup, good for MVP)
- Prompt engineering for citation-aware synthesis

**Implements:**
- LLM Synthesis component (ARCHITECTURE.md)
- Ask mode data flow (ARCHITECTURE.md)

**Addresses:**
- Query both chunks and answers (FEATURES.md table stakes) — ask mode implemented
- Local execution (FEATURES.md table stakes) — Ollama runs locally

**Avoids:**
- VRAM conflicts (PITFALLS.md Pitfall #4) — sequence ingestion and LLM operations, profile VRAM usage
- LLM in retrieval loop (PITFALLS.md anti-pattern #5) — LLM used only for synthesis after retrieval

### Phase 5: Hybrid Retrieval & Reranking
**Rationale:** Enhancement to Phase 3. Not critical for MVP but significantly improves retrieval quality for mathematical queries. Addresses Pitfall #3 (embedding models miss mathematical notation).

**Delivers:**
- BM25 keyword search (rank-bm25 library)
- Reciprocal Rank Fusion (combine vector + keyword results)
- Cross-encoder reranker (two-stage retrieval)
- Updated query/ask endpoints to use hybrid retrieval

**Uses:**
- rank-bm25 (STACK.md) for keyword search
- cross-encoder (STACK.md) for reranking

**Implements:**
- Hybrid search pattern (ARCHITECTURE.md Pattern 5)
- Two-stage retrieval pattern (ARCHITECTURE.md Pattern 3)

**Addresses:**
- Hybrid retrieval (FEATURES.md competitive differentiator)
- Reranking for precision (FEATURES.md competitive differentiator)

**Avoids:**
- Embedding model doesn't understand math notation (PITFALLS.md Pitfall #3) — BM25 catches exact term matches

### Phase 6: MCP Server
**Rationale:** Depends on REST API logic (Phases 3-4). MCP server is thin wrapper over existing retrieval/synthesis. Enables Claude Code integration.

**Delivers:**
- MCP Python SDK integration
- MCP tools: retrieve (raw chunks), ask (LLM answers)
- MCP resources: document list, indexing status
- Async ingestion pattern (job_id + status polling)
- Stdio transport for Claude Code

**Uses:**
- MCP Python SDK (STACK.md)
- Existing retrieval and synthesis components (thin wrapper pattern)

**Implements:**
- MCP Server component (ARCHITECTURE.md)
- MCP as thin wrapper pattern (ARCHITECTURE.md Pattern 4)

**Addresses:**
- MCP server integration (FEATURES.md competitive differentiator)

**Avoids:**
- MCP blocking on long operations (PITFALLS.md Pitfall #6) — async ingestion with job_id/status
- Monolithic MCP server (PITFALLS.md anti-pattern #6) — thin wrapper, business logic in service layer

### Phase 7: Advanced Parsers (LaTeX, Notebooks)
**Rationale:** Enhances Phase 2 ingestion pipeline. Deferred until MVP validated with PDF-only corpus. Add when users have .tex or .ipynb files.

**Delivers:**
- LaTeX source parser (.tex files)
- Jupyter notebook parser (.ipynb files)
- Format detection and parser routing
- Code block preservation metadata (language detection, syntax hints)

**Uses:**
- plasTeX or custom parser (STACK.md) for LaTeX
- nbformat (STACK.md) for Jupyter notebooks

**Addresses:**
- LaTeX source ingestion (FEATURES.md deferred, now v1.x)
- Jupyter notebook ingestion (FEATURES.md competitive differentiator)
- Code block detection and preservation (FEATURES.md competitive differentiator)

### Phase Ordering Rationale

- **Storage before everything** — Foundation dependency. Can't ingest or retrieve without storage layer. Metadata schema design upfront prevents citation provenance loss.
- **Basic ingestion before advanced parsers** — Validate PDF pipeline with formula-aware chunking before adding .tex/.ipynb complexity. Test with real financial documents to avoid chunking pitfalls.
- **Retrieval before LLM** — Retrieval is core capability. Ask mode (LLM synthesis) builds on retrieval. Validate chunk quality and citations before adding LLM complexity.
- **Semantic-only before hybrid** — Launch faster with semantic search. Add BM25 hybrid search when retrieval quality for math terms becomes issue. Both use same pipeline, hybrid is enhancement not rewrite.
- **REST API before MCP** — MCP wraps REST logic. Build REST endpoints first (easier to test with curl/httpx), then add MCP protocol layer.
- **Advanced parsers last** — PDF covers 80%+ of use cases. LaTeX/notebook parsing are enhancements, not MVP blockers.

This ordering minimizes rework (no backtracking to redesign storage or chunking), validates core quality early (formula preservation, citations), and defers complexity (hybrid search, advanced parsers) until MVP proven.

### Research Flags

**Phases likely needing deeper research during planning:**
- **Phase 2 (Ingestion)** — Marker API and configuration needs verification. Formula-aware chunking logic requires hands-on testing with financial documents. Table extraction quality varies by parser (Marker vs RAGFlow DeepDoc benchmark needed).
- **Phase 5 (Hybrid Retrieval)** — Reciprocal Rank Fusion parameter tuning (k value) for optimal fusion. Cross-encoder model selection (ms-marco-MiniLM vs bge-reranker-large benchmarking).
- **Phase 7 (Advanced Parsers)** — LaTeX parsing libraries (plasTeX vs custom) need evaluation. Notebook cell structure preservation patterns.

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (Foundation)** — SQLite schema design and Pydantic models are well-documented, standard patterns.
- **Phase 3 (Basic Retrieval)** — Vector similarity search is core ChromaDB/FAISS functionality, straightforward integration.
- **Phase 4 (LLM Integration)** — Ollama has clear documentation, OpenAI-compatible API is standard.
- **Phase 6 (MCP Server)** — MCP Python SDK has official docs and examples, stdio transport is standard pattern.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Based on training data (Jan 2025). Library versions need verification. Marker vs RAGFlow DeepDoc comparison needs hands-on testing. BGE/E5/Nomic embedding model recommendations current as of 2025 but may have evolved. |
| Features | MEDIUM | Table stakes and differentiators align with standard RAG patterns and financial document requirements. MVP recommendations solid based on dependency analysis. Cross-document synthesis (deferred) is complex; PaperQA patterns need verification. |
| Architecture | MEDIUM | Standard RAG architecture patterns (ingestion → chunking → embedding → vector store → retrieval → synthesis) are well-established. MCP integration patterns relatively new (late 2024 protocol) but official SDK provides clear guidance. Build order dependencies are sound. |
| Pitfalls | MEDIUM | Based on known RAG failure modes for technical documents. Chunking, column detection, VRAM conflicts, citation provenance are established challenges. MCP blocking issue inferred from protocol design (stdio transport) but not verified with real usage. |

**Overall confidence:** MEDIUM

All research areas are MEDIUM confidence because they rely on training data (up to Jan 2025) without access to current 2026 sources. Core patterns (RAG architecture, chunking strategies, hybrid retrieval) are well-established and unlikely to change fundamentally. Specific library choices (Marker, ChromaDB, Ollama) and versions need verification during implementation.

### Gaps to Address

- **Marker vs RAGFlow DeepDoc table extraction quality** — Research identified both as options but lacks empirical comparison. During Phase 2 planning: Test both with sample financial documents (correlation matrices, factor loadings) and benchmark table structure preservation accuracy. May need to swap parsers if Marker table extraction proves insufficient.

- **Embedding model performance on financial notation** — General-purpose models (BGE, E5, Nomic) recommended but not validated for LaTeX/financial notation. During Phase 3 planning: Test retrieval quality with financial queries ("Black-Scholes formula", "VWAP calculation", "Fama-French factors"). If semantic search misses mathematical terms, prioritize Phase 5 (hybrid retrieval) or evaluate domain-specific embeddings (SPECTER, SciBERT).

- **VRAM budget for concurrent operations** — Research identifies VRAM conflicts but actual usage depends on model sizes and GPU hardware. During Phase 4 planning: Profile VRAM usage for selected embedding model + LLM combination. Document safe concurrency limits (can ingestion and queries run simultaneously, or must they sequence). May need to implement queuing or CPU fallback for embeddings.

- **MCP async patterns for long operations** — Research recommends job_id + status polling for ingestion but pattern not verified against MCP SDK. During Phase 6 planning: Check MCP SDK documentation for long-running operation patterns (streaming, progress notifications, or job queue). May need custom status endpoint or MCP resource for job tracking.

- **LaTeX parsing library selection** — Research mentions plasTeX and custom parsers but doesn't evaluate them. Defer to Phase 7 planning: When LaTeX ingestion is prioritized, research plasTeX capabilities (can it extract formulas, handle complex documents), compare to building custom parser using pyparsing or lark. Decision impacts complexity and maintenance.

## Sources

### Primary (MEDIUM confidence)
- User-provided analysis of RAGFlow, PaperQA, Marker (initial project context) — informed parser selection and feature priorities
- MCP Protocol documentation (modelcontextprotocol.io) — MCP server patterns and best practices
- Training data on RAG architectures, Python ML ecosystem (up to Jan 2025) — stack recommendations, architectural patterns, pitfall identification

### Secondary (MEDIUM confidence)
- Anthropic Cookbooks (anthropic-cookbook GitHub) — RAG patterns, PDF processing, embeddings strategies
- Training data on financial document parsing — dual-column layouts, table structure, LaTeX formula preservation challenges
- Training data on hybrid retrieval strategies — BM25 + vector search fusion, reranking patterns

### Tertiary (LOW confidence, needs validation)
- Marker vs RAGFlow DeepDoc benchmarks — no hands-on comparison, needs empirical testing
- Specific library versions (FastAPI 0.100+, ChromaDB 0.4+, etc.) — training data cutoff Jan 2025, versions may have evolved by Feb 2026
- Current best embedding models for financial content — BGE/E5/Nomic recommended based on 2024-2025 landscape but models improve rapidly

---
*Research completed: 2026-02-12*
*Ready for roadmap: yes*
