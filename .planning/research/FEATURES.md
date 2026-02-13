# Feature Landscape

**Domain:** Financial/Quantitative Document RAG Server
**Researched:** 2026-02-12
**Confidence:** MEDIUM

## Table Stakes

Features users expect. Missing = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| PDF ingestion | Primary source format for finance papers | Medium | Must handle multi-column layouts, not just text extraction |
| Document CRUD operations | Can't manage corpus without basic lifecycle | Low | Add, list, delete documents via API |
| Semantic search/retrieval | Core RAG capability | Medium | Vector embeddings + similarity search |
| Chunk-level citations | Need to verify AI claims against source | Medium | Track source doc + page/section per chunk |
| REST API | Standard programmatic access | Low | Document operations + query endpoint |
| Index status tracking | Need to know when documents are queryable | Low | States: pending, processing, indexed, failed |
| Local execution | Privacy requirement for proprietary research | Medium | No cloud API dependencies for core flow |
| Query both chunks and answers | Different use cases need different outputs | Medium | Retrieve mode (raw chunks) vs Ask mode (LLM synthesis) |

## Differentiators

Features that set product apart. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| LaTeX formula preservation | Formulas as LaTeX not garbled text = 10x better comprehension | High | Requires LaTeX-aware parsing, not OCR |
| Financial table structure preservation | Correlation matrices, factor loadings lose meaning when linearized | High | Need layout-aware parsing (e.g., RAGFlow DeepDoc) |
| Jupyter notebook ingestion | Code + analysis together = complete context | Medium | Parse .ipynb, preserve cell structure and outputs |
| Multi-column layout handling | Academic papers use dual-column; reading order matters | High | Column detection and proper text flow reconstruction |
| Cross-document synthesis | Compare concepts across papers (e.g., "how do 3 authors define alpha?") | High | Requires agentic RAG patterns (PaperQA approach) |
| LaTeX source ingestion | .tex files = ground truth for formulas and structure | Medium | Parsing .tex directly vs OCR from PDF |
| Code block detection and preservation | Python implementations in papers need to stay as code | Medium | Syntax highlighting metadata, language detection |
| MCP server integration | Native Claude Code integration = seamless workflow | Medium | Implements MCP resources + tools protocol |
| Hybrid retrieval (semantic + keyword) | Dense math papers need both concept similarity and exact term matching | Medium | Combine vector search with BM25/full-text |
| Figure caption extraction | Charts/diagrams context crucial for understanding | Medium | OCR + layout analysis to associate captions |
| Citation graph tracking | "Which papers cite this formula?" for research exploration | High | Build document relationship graph |
| Reranking for precision | Initial retrieval casts wide net; rerank for relevance | Medium | Two-stage retrieval with cross-encoder reranker |

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Web UI or dashboard | Adds complexity; not consumption pattern for v1 | REST API + MCP only; UI in separate project if needed later |
| Cloud-hosted deployment | Privacy concerns for proprietary research; network latency | Local-first architecture with GPU acceleration |
| Proprietary LLM API dependency | Cost, privacy, requires internet | Local LLM serving (Ollama, llama.cpp, vLLM) |
| Real-time document watching/sync | Complexity of filesystem monitoring; YAGNI | Manual ingestion via API calls |
| User authentication/multi-tenancy | Single-user local deployment | Simple or no auth for localhost-only API |
| Document versioning | Complex; unclear use case for research corpus | Delete + re-ingest if document updated |
| Fine-tuning custom embeddings | High complexity, marginal gains over SOTA models | Use best available embedding model (Voyage, OpenAI, Nomic) |
| OCR for scanned PDFs | Different problem domain; adds heavy dependencies | Require digital PDFs; flag scanned PDFs as unsupported |
| Natural language document queries in API | Ambiguous; better done via MCP ask tool | Structured query params (filters, k-nearest, etc.) |
| Export to other formats | Scope creep; retrieval is the job | Return chunks/answers as JSON; client handles rendering |

## Feature Dependencies

```
Document Ingestion
    ├──requires──> Index Status Tracking
    ├──requires──> PDF Parsing
    │   ├──requires──> Multi-column Layout Detection
    │   ├──requires──> Table Structure Extraction
    │   ├──requires──> LaTeX Formula Extraction
    │   └──requires──> Code Block Detection
    ├──requires──> LaTeX Source Parsing (for .tex files)
    └──requires──> Jupyter Notebook Parsing (for .ipynb files)

Semantic Search/Retrieval
    ├──requires──> Vector Embedding Generation
    ├──requires──> Vector Database/Index
    └──enhances──> Chunk-level Citations

Hybrid Retrieval
    ├──requires──> Semantic Search
    ├──requires──> Keyword Search (BM25/full-text)
    └──requires──> Result Fusion

Reranking
    ├──requires──> Semantic Search (initial retrieval)
    └──enhances──> Precision

Cross-document Synthesis
    ├──requires──> Semantic Search
    ├──requires──> LLM Integration
    ├──requires──> Chunk-level Citations
    └──requires──> Multi-query Planning (agentic pattern)

MCP Server
    ├──requires──> REST API (or direct service layer)
    ├──exposes──> Retrieve Tool (chunks)
    ├──exposes──> Ask Tool (LLM answers)
    └──exposes──> Document Management Tools (ingest, list, delete)

Ask Mode (LLM Synthesis)
    ├──requires──> Semantic Search
    ├──requires──> Local LLM Serving
    └──requires──> Chunk-level Citations

Citation Graph Tracking
    ├──requires──> Document Metadata Extraction
    └──enhances──> Cross-document Synthesis
```

### Dependency Notes

- **PDF Parsing → Multi-column/Table/Formula Extraction:** Layout-aware parsing is a single pipeline, not separate steps. Use integrated solution (RAGFlow DeepDoc, Marker).
- **Hybrid Retrieval → Semantic + Keyword Search:** Requires both indexes; fusion algorithm (RRF or similar) to merge results.
- **Cross-document Synthesis → Agentic Pattern:** Needs multi-step planning: generate subqueries, retrieve from multiple sources, synthesize. See PaperQA approach.
- **MCP Server → REST API:** MCP tools can call REST endpoints or directly invoke service layer. Direct service layer = simpler, fewer layers.
- **Ask Mode → Local LLM:** Could use cloud LLM initially for prototyping, but v1 requirement is local. Block on local LLM integration.

## MVP Recommendation

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] **PDF ingestion with layout-aware parsing** — Marker or RAGFlow DeepDoc for multi-column, tables, formulas
- [ ] **Document CRUD via REST API** — Add (POST /documents), list (GET /documents), delete (DELETE /documents/:id)
- [ ] **Index status tracking** — Document states: pending → processing → indexed/failed
- [ ] **Semantic search** — Vector embeddings (Voyage AI or Nomic Embed) + FAISS/Chroma/Qdrant
- [ ] **Chunk-level citations** — Store source doc ID, page number, section heading per chunk
- [ ] **MCP server with retrieve tool** — Expose search as MCP tool returning chunks with citations
- [ ] **Hybrid retrieval (semantic + keyword)** — Combine vector search with BM25 for better recall on math terms
- [ ] **Reranking** — Two-stage retrieval with cross-encoder for precision
- [ ] **Local LLM serving** — Ollama or llama.cpp for answer generation
- [ ] **MCP ask tool** — LLM-synthesized answers with citations

**Why this MVP:**
- Proves core value: accurate retrieval from complex financial documents
- MCP integration = immediate Claude Code workflow value
- Hybrid retrieval + reranking = quality baseline competitive with specialized systems
- Local LLM = validates full self-contained operation

### Add After Validation (v1.x)

Features to add once core is working and validated with real usage.

- [ ] **LaTeX source ingestion** — Parse .tex files directly (trigger: user has .tex sources, not just PDFs)
- [ ] **Jupyter notebook ingestion** — Parse .ipynb files (trigger: notebooks are common in corpus)
- [ ] **Cross-document synthesis** — Agentic multi-query pattern (trigger: users ask comparative questions)
- [ ] **Figure caption extraction** — Associate chart/diagram context (trigger: users need visual context)
- [ ] **Code block preservation metadata** — Language detection, syntax highlighting hints (trigger: code snippets important for corpus)
- [ ] **MCP document management tools** — Ingest/delete via MCP not just REST (trigger: Claude Code wants to manage corpus)

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] **Citation graph tracking** — "Which papers reference this concept?" (defer: complex graph DB, unclear ROI)
- [ ] **Query result caching** — Speed up repeated queries (defer: optimize when it's a bottleneck)
- [ ] **Incremental re-indexing** — Update index without full rebuild (defer: corpus churn likely low initially)
- [ ] **Custom chunking strategies per document type** — LaTeX vs PDF vs notebook chunking (defer: tune when default chunking shows clear gaps)
- [ ] **Multi-lingual support** — Non-English papers (defer: English-only corpus initially)
- [ ] **Audio/video ingestion** — Lecture recordings, webinars (defer: different problem, expand scope later)

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| PDF ingestion with layout parsing | HIGH | MEDIUM | P1 |
| Semantic search | HIGH | MEDIUM | P1 |
| Chunk-level citations | HIGH | MEDIUM | P1 |
| REST API | HIGH | LOW | P1 |
| Index status tracking | HIGH | LOW | P1 |
| Hybrid retrieval | HIGH | MEDIUM | P1 |
| Reranking | HIGH | MEDIUM | P1 |
| MCP retrieve tool | HIGH | MEDIUM | P1 |
| Local LLM serving | HIGH | MEDIUM | P1 |
| MCP ask tool | HIGH | MEDIUM | P1 |
| LaTeX source ingestion | MEDIUM | MEDIUM | P2 |
| Jupyter notebook ingestion | MEDIUM | MEDIUM | P2 |
| Cross-document synthesis | MEDIUM | HIGH | P2 |
| Figure caption extraction | MEDIUM | MEDIUM | P2 |
| Code block metadata | LOW | LOW | P2 |
| MCP document management | MEDIUM | LOW | P2 |
| Citation graph tracking | LOW | HIGH | P3 |
| Query caching | MEDIUM | LOW | P3 |
| Incremental re-indexing | LOW | MEDIUM | P3 |
| Custom chunking strategies | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have for launch (validates core value)
- P2: Should have, add when MVP validated
- P3: Nice to have, future consideration

## Comparative Analysis

### Specialized Financial RAG vs Generic RAG

| Feature | Generic RAG (LangChain/LlamaIndex) | Financial Document RAG (This Project) |
|---------|-------------------------------------|----------------------------------------|
| PDF parsing | Simple text extraction | Layout-aware: multi-column, tables, formulas |
| Formula handling | Text or OCR (garbled) | LaTeX preservation |
| Table extraction | Linearized or lost | Structure preserved (rows/cols/headers) |
| Code blocks | Plain text | Detected, language-tagged |
| Citations | Document-level or none | Page-level + section headings |
| Retrieval | Semantic only | Hybrid (semantic + keyword) for math terms |
| LLM integration | Cloud APIs | Local models (privacy) |
| Interface | Python library | REST API + MCP (Claude Code integration) |

### MCP Server Patterns

Based on MCP documentation research:

**MCP Resources** (expose data):
- List indexed documents as resources
- Each document = resource with URI `doc://[id]`
- Clients can subscribe to document updates (resource change notifications)
- Resource annotations: priority (importance), audience (user/assistant), lastModified

**MCP Tools** (expose actions):
- `retrieve` tool: Search corpus, return chunks with citations
- `ask` tool: Search + LLM synthesis, return answer with citations
- `ingest_document` tool: Add document to corpus (if MCP document management added)
- `delete_document` tool: Remove document from corpus
- `list_documents` tool: Get corpus inventory with indexing status

**MCP Best Practices** (from protocol docs):
- Tools use JSON Schema for input validation
- Return structured content + text fallback for compatibility
- Use resource links to point to full documents from tool results
- Implement listChanged notifications when corpus changes
- Human-in-the-loop: clients should confirm tool invocations (especially delete/ingest)

## Implementation Notes

### LaTeX Formula Preservation

**Challenge:** PDFs render formulas as glyphs; need to recover LaTeX source.

**Solutions:**
- **Marker**: Detects LaTeX in PDFs, extracts as `$...$` or `$$...$$` markdown
- **LaTeX source parsing**: Parse .tex files directly (ground truth)
- **OCR + LaTeX**: Tools like pix2tex (image to LaTeX) — expensive, lower accuracy

**Recommendation:** Marker for PDF extraction, add .tex parsing as P2 feature.

### Table Structure Preservation

**Challenge:** Tables as image regions or fragmented text lose semantic structure.

**Solutions:**
- **RAGFlow DeepDoc**: Vision model detects tables, extracts structure
- **Marker**: Table detection + markdown table output
- **Table Transformer**: Hugging Face model for table structure recognition

**Recommendation:** Marker first (simpler), RAGFlow DeepDoc if Marker tables insufficient.

### Multi-column Layout Handling

**Challenge:** Dual-column academic papers read left-to-right across columns (wrong) if not detected.

**Solutions:**
- **Layout detection models**: Detectron2-based layout models
- **Marker**: Includes column detection
- **RAGFlow DeepDoc**: Vision-based layout analysis

**Recommendation:** Marker includes this; verify quality with sample papers.

### Hybrid Retrieval

**Challenge:** Semantic search misses exact math terms; keyword search misses concepts.

**Solutions:**
- **Dual indexes**: Vector (FAISS/Chroma) + full-text (Elasticsearch/Tantivy/BM25)
- **Fusion**: Reciprocal Rank Fusion (RRF) to merge results
- **Libraries**: LangChain has hybrid retrieval, LlamaIndex too

**Recommendation:** Implement RRF over vector + BM25. Tantivy for Rust-based BM25 (fast), or Python BM25Okapi (simple).

### Reranking

**Challenge:** Initial retrieval (top-100) casts wide net; rerank top-20 for precision.

**Solutions:**
- **Cross-encoders**: Encode query + chunk together (vs bi-encoder embeddings)
- **Models**: `ms-marco-MiniLM-L-12-v2` (fast), `bge-reranker-large` (accurate)
- **Libraries**: sentence-transformers, LlamaIndex rerankers

**Recommendation:** Use cross-encoder reranker; minimal latency for top-100 → top-10 rerank.

### Local LLM Serving

**Challenge:** Answer synthesis needs LLM; must run locally for privacy.

**Solutions:**
- **Ollama**: Simplest, good for prototyping (runs Llama, Mistral, etc.)
- **llama.cpp**: Fast inference, low-level control
- **vLLM**: Production-grade serving, OpenAI-compatible API
- **TGI (Text Generation Inference)**: Hugging Face serving

**Recommendation:** Ollama for MVP (ease of use), vLLM for production (performance, batching).

### MCP Integration

**Challenge:** Expose retrieve + ask as MCP tools for Claude Code.

**Solutions:**
- **MCP SDK**: TypeScript or Python SDK from Anthropic
- **Protocol**: JSON-RPC over stdio or HTTP
- **Tool definitions**: JSON Schema for inputs, structured outputs

**Recommendation:** Python MCP SDK (aligns with Python RAG stack). Stdio transport for local use.

### Cross-document Synthesis

**Challenge:** "Compare how 3 authors define momentum" requires multi-query planning.

**Solutions:**
- **PaperQA approach**: Generate subqueries per paper, retrieve, synthesize
- **Agentic RAG**: LLM plans queries, retrieves, self-critiques, repeats if needed
- **Libraries**: PaperQA (research-specific), LangChain agents, LlamaIndex agents

**Recommendation:** Defer to P2. When implemented, adapt PaperQA patterns (MIT license). Generate "For paper X, retrieve definition of Y" subqueries, aggregate answers.

## Confidence Assessment

| Feature Category | Confidence | Source |
|------------------|------------|--------|
| MCP capabilities | HIGH | Official MCP protocol docs (modelcontextprotocol.io) |
| RAG best practices | MEDIUM | Anthropic Cookbook (official examples), training data |
| PDF parsing solutions | MEDIUM | Training data on Marker/RAGFlow (no official docs accessed) |
| Hybrid retrieval | HIGH | Standard RAG practice (training data + Anthropic Cookbook patterns) |
| Local LLM serving | HIGH | Common practice (Ollama/vLLM well-documented) |
| Financial domain specifics | MEDIUM | Training data on quant finance document structure |

**Verification needed:**
- Marker vs RAGFlow DeepDoc capability comparison (need hands-on testing or detailed benchmarks)
- Table extraction quality across solutions (empirical evaluation required)
- LaTeX formula extraction accuracy from PDFs (test with sample corpus)

## Sources

- MCP Protocol Documentation: https://modelcontextprotocol.io/docs (Resources, Tools)
- Anthropic Cookbooks: https://github.com/anthropics/anthropic-cookbook (RAG patterns, PDF processing, embeddings)
- Training data: RAG architectures, financial document parsing, hybrid retrieval strategies

---
*Feature research for: FellowQuant RAG Server*
*Researched: 2026-02-12*
