# Requirements: FellowQuant RAG Server

**Defined:** 2026-02-12
**Core Value:** Accurate retrieval and synthesis from dense quantitative finance documents — tables stay as tables, formulas stay as formulas, and citations trace back to exact sources.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Document Ingestion

- [x] **INGEST-01**: User can upload PDF files and have them parsed with layout-aware extraction preserving tables, formulas, and multi-column structure
- [x] **INGEST-02**: User can upload LaTeX source files (.tex) and have them parsed preserving mathematical notation as ground-truth LaTeX
- [x] **INGEST-03**: User can upload Jupyter notebooks (.ipynb) and have them parsed preserving code cells, markdown, and outputs
- [x] **INGEST-04**: System detects and preserves code blocks with language identification during document parsing
- [x] **INGEST-05**: System chunks documents using formula-aware, table-aware splitting that never breaks atomic content units
- [x] **INGEST-06**: System tracks document indexing status (pending → processing → indexed → failed) queryable via API

### Storage & Indexing

- [x] **STORE-01**: System stores vector embeddings in a persistent vector database (ChromaDB or equivalent) for semantic similarity search
- [x] **STORE-02**: System stores document metadata (title, author, page count, format, hash) in a relational database (SQLite)
- [x] **STORE-03**: System stores chunk metadata (document_id, page_number, section_header, chunk_type) linked to source documents
- [x] **STORE-04**: System supports 100+ document corpus with performant indexing and retrieval

### Retrieval & Search

- [ ] **RETR-01**: User can perform semantic search using vector embeddings to find conceptually relevant chunks
- [ ] **RETR-02**: User can perform hybrid search combining semantic (vector) and keyword (BM25) retrieval with reciprocal rank fusion
- [ ] **RETR-03**: System reranks initial retrieval results using a cross-encoder model for improved precision
- [ ] **RETR-04**: Every retrieved chunk includes citation metadata: source document, page number, and section heading
- [ ] **RETR-05**: User can perform cross-document synthesis queries that compare concepts across multiple sources using agentic multi-query patterns

### LLM Integration

- [ ] **LLM-01**: System serves a local LLM (via Ollama or vLLM) for answer generation without cloud API dependencies
- [ ] **LLM-02**: System generates answers from retrieved chunks with inline citations referencing source documents and pages
- [ ] **LLM-03**: System supports streaming LLM responses as they generate for real-time output

### REST API

- [ ] **API-01**: User can ingest documents via POST endpoint with file upload
- [ ] **API-02**: User can list all documents with metadata and indexing status via GET endpoint
- [ ] **API-03**: User can delete documents and their associated chunks/embeddings via DELETE endpoint
- [ ] **API-04**: User can query the knowledge base via retrieve endpoint returning ranked chunks with citations
- [ ] **API-05**: User can query the knowledge base via ask endpoint returning LLM-synthesized answers with citations
- [ ] **API-06**: User can check document indexing status via status endpoint

### MCP Server

- [ ] **MCP-01**: System exposes an MCP server accessible from Claude Code via stdio transport
- [ ] **MCP-02**: MCP server provides a `retrieve` tool that returns raw chunks with citations for a given query
- [ ] **MCP-03**: MCP server provides an `ask` tool that returns LLM-synthesized answers with citations for a given query
- [ ] **MCP-04**: MCP server provides an `ingest_document` tool to add documents to the corpus from Claude Code
- [ ] **MCP-05**: MCP server provides a `list_documents` tool to view corpus inventory and indexing status
- [ ] **MCP-06**: MCP server provides a `delete_document` tool to remove documents from the corpus

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Retrieval

- **ADV-01**: System caches query results for repeated queries (LRU or Redis)
- **ADV-02**: System tracks citation graphs between documents ("which papers reference this concept")
- **ADV-03**: System supports incremental re-indexing without full corpus rebuild

### Advanced Ingestion

- **ADV-04**: System extracts figure captions and associates them with surrounding text context
- **ADV-05**: System supports custom chunking strategies configurable per document type
- **ADV-06**: System detects duplicate documents by content hash and prevents re-ingestion

### Multi-language

- **ADV-07**: System supports non-English documents (multi-lingual embeddings and retrieval)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Web UI or dashboard | API-only for v1; consumed programmatically from Claude Code and scripts |
| Cloud-hosted deployment | Privacy requirement — runs locally with GPU only |
| Proprietary LLM API dependency | Local models only — no OpenAI/Anthropic API for generation |
| Real-time market data integration | This is a research knowledge base, not a trading system |
| Mobile access | Programmatic API consumption only |
| User authentication / multi-tenancy | Single-user local deployment |
| Document versioning | Delete + re-ingest if updated; low corpus churn |
| OCR for scanned PDFs | Different problem domain; require digital PDFs |
| Fine-tuning custom embeddings | High complexity, marginal gains over SOTA models |
| Real-time filesystem watching | Manual ingestion via API; no auto-sync |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 2 | Complete |
| INGEST-02 | Phase 2 | Complete |
| INGEST-03 | Phase 2 | Complete |
| INGEST-04 | Phase 2 | Complete |
| INGEST-05 | Phase 2 | Complete |
| INGEST-06 | Phase 2 | Complete |
| STORE-01 | Phase 1 | Complete |
| STORE-02 | Phase 1 | Complete |
| STORE-03 | Phase 1 | Complete |
| STORE-04 | Phase 1 | Complete |
| RETR-01 | Phase 3 | Pending |
| RETR-02 | Phase 3 | Pending |
| RETR-03 | Phase 3 | Pending |
| RETR-04 | Phase 3 | Pending |
| RETR-05 | Phase 3 | Pending |
| LLM-01 | Phase 4 | Pending |
| LLM-02 | Phase 4 | Pending |
| LLM-03 | Phase 4 | Pending |
| API-01 | Phase 5 | Pending |
| API-02 | Phase 5 | Pending |
| API-03 | Phase 5 | Pending |
| API-04 | Phase 5 | Pending |
| API-05 | Phase 5 | Pending |
| API-06 | Phase 5 | Pending |
| MCP-01 | Phase 6 | Pending |
| MCP-02 | Phase 6 | Pending |
| MCP-03 | Phase 6 | Pending |
| MCP-04 | Phase 6 | Pending |
| MCP-05 | Phase 6 | Pending |
| MCP-06 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 30 total
- Mapped to phases: 30
- Unmapped: 0

---
*Requirements defined: 2026-02-12*
*Last updated: 2026-02-13 after roadmap creation*
