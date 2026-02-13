# Pitfalls Research

**Domain:** Financial Document RAG Server
**Researched:** 2026-02-12
**Confidence:** MEDIUM (based on known RAG failure modes for technical documents)

## Critical Pitfalls

### Pitfall 1: Naive Chunking Destroys Financial Tables and Formulas

**What goes wrong:**
Fixed-size text chunking (e.g., 512 tokens) splits formulas mid-expression ("where α =" in one chunk, "0.05 and β = 0.12" in the next), separates table headers from data rows, and breaks multi-line equations. Retrieved chunks become meaningless fragments.

**Why it happens:**
Default LangChain/LlamaIndex text splitters don't understand document structure. They see text as a character stream, not as a document with semantic units (formulas, tables, code blocks).

**How to avoid:**
- Use format-aware chunking that treats formulas (`$...$`, `$$...$$`), tables, and code blocks as atomic units
- Split on section/paragraph boundaries, not character counts
- Keep tables whole (or split by logical row groups, never mid-row)
- Test chunking quality with sample documents before scaling

**Warning signs:**
- Retrieved chunks contain half-formulas or orphaned table rows
- LLM answers reference "equation X" but the equation is split across chunks
- Search for a known formula returns garbage

**Phase to address:**
Phase 2 (Ingestion Pipeline) — chunking strategy is a core design decision

---

### Pitfall 2: PDF Parser Can't Handle Dual-Column Academic Layouts

**What goes wrong:**
Simple text extraction reads across column boundaries instead of down each column. Result: sentences from left and right columns interleave, creating nonsensical text. This is catastrophic for dual-column papers (standard in academic finance).

**Why it happens:**
Most PDF text extraction (PyPDF2, pdfplumber) extracts text by position on page, left-to-right, top-to-bottom. They don't detect column boundaries.

**How to avoid:**
- Use layout-aware parser (Marker, RAGFlow DeepDoc) that detects column structure
- Validate with dual-column sample papers (e.g., any academic finance paper)
- Test reading order: does extracted text make sense when read sequentially?

**Warning signs:**
- Extracted text from academic papers reads as gibberish
- Sentences suddenly switch topics mid-line (column bleed)
- Parser works fine on single-column books but fails on papers

**Phase to address:**
Phase 2 (Ingestion Pipeline) — parser selection and validation

---

### Pitfall 3: Embedding Model Doesn't Understand Mathematical Notation

**What goes wrong:**
General-purpose embedding models (e.g., all-MiniLM-L6-v2) treat LaTeX notation as random tokens. Query "Black-Scholes formula" doesn't match the chunk containing `$C = S_0 N(d_1) - K e^{-rT} N(d_2)$` because the model can't bridge natural language descriptions to mathematical notation.

**Why it happens:**
Most embedding models are trained primarily on natural language text, not mathematical notation. LaTeX tokens are out-of-vocabulary or poorly represented.

**How to avoid:**
- Include natural language descriptions alongside formulas during chunking (e.g., "The Black-Scholes formula: $C = ...$")
- Use embedding models with scientific/technical training (SPECTER, SciBERT, or BGE with appropriate fine-tuning)
- Add metadata search alongside semantic search: tag chunks with topic keywords during ingestion
- Hybrid retrieval (BM25 + vector) partially mitigates this — keyword search catches "Black-Scholes" even if embeddings miss it

**Warning signs:**
- Queries about specific formulas return unrelated chunks
- Natural language questions work but formula-specific queries fail
- Retrieval precision drops significantly for mathematical queries

**Phase to address:**
Phase 3 (Retrieval) — embedding model selection and hybrid search implementation

---

### Pitfall 4: Local LLM VRAM Conflicts with Embedding Model

**What goes wrong:**
Both the embedding model and the LLM need GPU VRAM. Running Marker (GPU-accelerated) + embedding model + LLM simultaneously exceeds available VRAM. Server crashes with CUDA OOM errors or falls back to CPU (10-100x slower).

**Why it happens:**
Each component loads independently and doesn't know about others' VRAM usage. Marker alone can use 4-8GB. An embedding model uses 1-4GB. A 7B LLM uses 4-8GB (quantized). Total can easily exceed 16-24GB VRAM.

**How to avoid:**
- Sequence operations: don't run ingestion (Marker + embeddings) and LLM inference simultaneously
- Use CPU for embedding (sentence-transformers supports CPU, still fast enough for batch embedding)
- Use quantized LLM (Q4/Q5 reduces VRAM by 50-70%)
- Profile VRAM usage of each component and plan allocation
- Consider Ollama's model loading/unloading (loads model on demand, frees when idle)

**Warning signs:**
- Intermittent CUDA OOM errors
- Server works fine for queries OR ingestion but crashes when both happen
- Performance degrades severely under concurrent load

**Phase to address:**
Phase 4 (LLM Integration) — VRAM budget planning

---

### Pitfall 5: Citation Provenance Lost During Processing

**What goes wrong:**
After parsing → chunking → embedding, chunks lose their connection to source document, page number, and section. When the system returns a chunk, it can't tell you where it came from. Users can't verify claims against the original source.

**Why it happens:**
Metadata gets dropped during processing pipeline. Parser extracts text but doesn't track page numbers. Chunker splits text but doesn't preserve section headers. Vector store stores embeddings but not the full metadata chain.

**How to avoid:**
- Design metadata schema upfront: every chunk carries (document_id, page_number, section_header, paragraph_index)
- Parser must output structured objects with position metadata, not raw text
- Chunker must propagate metadata from parser output
- Vector store must support metadata storage and filtering (ChromaDB, Qdrant both support this)
- Test end-to-end: ingest a doc, retrieve a chunk, verify citation points to correct source location

**Warning signs:**
- Retrieved chunks have no source information
- Citations are wrong (wrong page, wrong document)
- Can't filter search by document or section

**Phase to address:**
Phase 1 (Foundation) — metadata schema design; Phase 2 (Ingestion) — metadata propagation

---

### Pitfall 6: MCP Server Blocks on Long Operations

**What goes wrong:**
MCP tool calls for ingestion or complex queries block the MCP server. Claude Code appears frozen, can't cancel, no progress feedback. User thinks the system crashed.

**Why it happens:**
MCP tools are expected to return relatively quickly. Long operations (PDF parsing: 30-60s, LLM synthesis: 10-30s) block the tool call response. No built-in streaming or progress mechanism in basic MCP tool pattern.

**How to avoid:**
- Make ingestion async: MCP ingest tool returns immediately with job_id, separate tool to check status
- Use streaming for LLM synthesis if MCP transport supports it
- Set reasonable timeouts and return partial results if needed
- Keep retrieve tool fast (< 2s) by optimizing retrieval pipeline

**Warning signs:**
- Claude Code times out waiting for MCP tool response
- User can't use Claude Code during ingestion
- Large documents cause MCP connection to drop

**Phase to address:**
Phase 6 (MCP Server) — async patterns for long operations

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip hybrid search, semantic only | Simpler pipeline, faster launch | Lower retrieval quality for exact-term queries | MVP with < 20 docs, plan to add BM25 later |
| Skip reranking | One less model to manage, lower latency | Retrieval precision is worse for complex queries | MVP; add when retrieval quality complaints arise |
| Hardcode embedding model | No config complexity | Can't swap models without code changes | Never — always make model configurable |
| Use Ollama instead of vLLM | Simpler setup, easier model management | Slower inference, no batching | Development and early production; switch to vLLM when latency matters |
| Store chunks as files (not DB) | No database dependency | Can't query metadata, no transactional integrity | Never — use SQLite at minimum |
| Skip LaTeX/notebook parsers | Ship faster (PDF only) | Users with .tex or .ipynb can't use the system | MVP — add as v1.x features when requested |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Ollama | Assuming model is loaded and warm | Check if model is available (`ollama list`), pre-pull on startup, handle cold-start latency |
| ChromaDB | Not persisting to disk | Always specify `persist_directory`. Default is in-memory (data lost on restart) |
| Marker | Running without GPU | Marker works on CPU but 5-10x slower. Verify CUDA availability on startup |
| sentence-transformers | First-run model download | Models download from HuggingFace on first use. Cache in known location. Handle offline mode |
| MCP stdio transport | Writing to stdout (interferes with MCP protocol) | Use stderr for logging, never print to stdout. MCP uses stdout for JSON-RPC |
| FastAPI + async | Blocking calls in async handlers | Use `run_in_executor` for CPU-bound operations (embedding, parsing). Don't block event loop |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Embedding one chunk at a time | Ingestion takes minutes for one document | Batch embed chunks (encode multiple at once) | > 10 pages per document |
| No vector index (brute force search) | Retrieval gets slower linearly with corpus size | Use HNSW index (ChromaDB default). Tune ef_search | > 10K chunks |
| Loading LLM for every query | 5-10s cold start per query | Keep LLM loaded in memory (Ollama does this automatically) | Always — never reload per query |
| Storing full document text in vector DB | Vector DB bloated, slow to load | Store only chunks in vector DB. Full text in metadata DB or filesystem | > 50 documents |
| Re-parsing already indexed documents | Wasted compute on re-ingestion | Track document hash (SHA256). Skip if hash matches existing | > 20 documents |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Exposing REST API on 0.0.0.0 without auth | Anyone on network can query your research corpus | Bind to 127.0.0.1 (localhost only). Add API key if network access needed |
| Storing proprietary documents in world-readable paths | IP exposure | Use restricted file permissions (700). Don't put in /tmp |
| Logging full query text and results | Sensitive research queries in log files | Minimal logging. Don't log query text or result content in production |
| LLM prompt injection via document content | Malicious PDF could inject instructions into LLM context | Sanitize retrieved chunks before LLM prompt. Treat document content as untrusted data |

## "Looks Done But Isn't" Checklist

- [ ] **PDF Parsing:** Test with dual-column papers, not just single-column books — verify column detection
- [ ] **Table Extraction:** Test with correlation matrices and multi-header tables — verify structure preserved
- [ ] **Formula Extraction:** Test with inline ($...$) and display ($$...$$) formulas — verify LaTeX output
- [ ] **Citation Accuracy:** Retrieve a chunk, check if cited page number matches original document
- [ ] **Hybrid Search:** Query a specific term (e.g., "VWAP") — verify BM25 catches it even if embeddings miss
- [ ] **LLM Answers:** Ask about a specific topic, verify answer cites correct sources (not hallucinated citations)
- [ ] **MCP Integration:** Test from actual Claude Code, not just curl — verify tool discovery and invocation works
- [ ] **Concurrent Operations:** Ingest a document while querying — verify no VRAM crashes or data corruption
- [ ] **Large Documents:** Test with 500+ page book — verify ingestion completes and chunks are queryable

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Naive chunking destroyed data | MEDIUM | Re-ingest all documents with new chunking strategy. Existing data must be discarded |
| Wrong embedding model | MEDIUM | Re-embed all chunks with new model. Vector store must be rebuilt. Metadata preserved |
| Citation metadata lost | HIGH | Must re-design metadata schema and re-ingest everything. If parser didn't track positions, parser must change too |
| VRAM conflicts | LOW | Reconfigure to time-share GPU or use CPU for embeddings. No data loss |
| MCP blocking | LOW | Refactor to async pattern. No data loss, just API design change |
| Column detection failure | MEDIUM | Switch parser (Marker → RAGFlow DeepDoc). Re-ingest affected documents |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-----------------|--------------|
| Naive chunking | Phase 2 (Ingestion) | Test chunks from sample financial documents contain complete formulas/tables |
| Column detection | Phase 2 (Ingestion) | Parse 3+ dual-column papers, verify text reads correctly |
| Embedding model mismatch | Phase 3 (Retrieval) | Query known formulas, verify relevant chunks retrieved |
| VRAM conflicts | Phase 4 (LLM Integration) | Run ingestion + query concurrently, monitor VRAM |
| Citation provenance | Phase 1 (Foundation) + Phase 2 | End-to-end: ingest → retrieve → verify citation accuracy |
| MCP blocking | Phase 6 (MCP Server) | Ingest large PDF via MCP, verify Claude Code stays responsive |

## Sources

- Training data on RAG system failure modes and best practices (up to Jan 2025)
- Known issues with PDF parsing for academic/financial documents
- Common VRAM management challenges with local LLM deployments
- MCP protocol documentation patterns
- **Note:** Unable to verify against 2026 sources. Pitfalls are based on established patterns that remain relevant.

---
*Pitfalls research for: Financial Document RAG Server*
*Researched: 2026-02-12*
