# Domain Pitfalls

**Domain:** Financial Document RAG Server
**Researched:** 2026-02-18 (updated with SOTA verification)
**Confidence:** HIGH for pitfalls verified by 2025 research; MEDIUM for inferred pitfalls

---

## Critical Pitfalls

Mistakes that cause rewrites or make the system fundamentally non-functional.

### Pitfall 1: Fixed-Size Chunking Destroys Formulas and Tables

**What goes wrong:** Using token-count chunking (e.g., 512 or 1024 tokens) splits LaTeX formulas mid-expression, breaks table rows away from headers, and cuts code blocks. Retrieved chunks are semantically meaningless fragments.

**Why it happens:** Default chunking strategies from LangChain/LlamaIndex/most tutorials use fixed-size windows. They work for prose text. They catastrophically fail for structured scientific content.

**Consequences:** Query "Black-Scholes formula" returns a chunk ending with `C = S_0 N(d_1) -` with the rest of the formula in the adjacent chunk — both returned without context. The LLM cannot synthesize a complete answer. Users lose trust immediately.

**Prevention:** Content-aware atomic chunking (ARCHITECTURE.md Pattern 1). Parse into typed blocks first (text, formula, table, code). Treat formula/table/code blocks as atomic units — one chunk each, never split. Split text blocks on semantic or paragraph boundaries.

**Detection:** Test with a paper containing multi-line equations (e.g., any factor model paper). Search for "pricing formula" and verify the returned chunk contains the complete formula. If it's truncated, chunking is broken.

---

### Pitfall 2: PDF Parser Fails on Dual-Column Academic Layout

**What goes wrong:** Simple text extractors (PyPDF2, pdfplumber, basic pdfminer) read across columns left-to-right instead of top-to-bottom per column. Words from left column and right column interleave into nonsensical text: "asset The pricing risk-adjusted model CAPM return states assumes that..."

**Why it happens:** PDF text objects have X/Y coordinates. A naive extractor reads by Y position (row by row) instead of by column regions. This is the default behavior for most basic PDF libraries.

**Consequences:** Every academic paper (which uses dual-column layout as standard in journals) is corrupted at parse time. The entire indexing pipeline is built on garbage. No retrieval approach can fix garbled source text.

**Prevention:** Use Docling as primary parser — it uses DocLayNet (a layout detection model trained on academic papers) that correctly identifies column regions and reading order. Validated: OmniDocBench (CVPR 2025) shows layout-aware parsers significantly outperform text-extraction-only parsers on multi-column documents. Marker is also layout-aware but less accurate on complex layouts.

**Detection:** Parse a dual-column finance paper (e.g., any Journal of Finance paper). Check the first paragraph of the markdown output. If sentences make sense, parsing is correct. If words are interleaved from both columns, parser is failing.

---

### Pitfall 3: Embedding Models Cannot Semantically Retrieve Formulas

**What goes wrong:** A user queries "What is the formula for the Sharpe ratio?" The chunk containing `S = \frac{R_p - R_f}{\sigma_p}` is not retrieved because standard embedding models tokenize LaTeX notation as random subword tokens with no semantic meaning.

**Why it happens:** Models like BGE, E5, and most sentence-transformers were trained on natural language corpora. LaTeX syntax is present but sparse. The model cannot bridge "Sharpe ratio" (query) to `\frac{R_p - R_f}{\sigma_p}` (chunk content).

**Consequences:** The primary use case — retrieving quantitative formulas from research papers — silently fails. Retrieval scores are low, reranker may also miss it, and the LLM either hallucinates the formula or says "I cannot find it."

**Prevention (two-layer approach):**
1. **Formula context enrichment:** During chunking, prepend surrounding text (section title + paragraph description) to the formula chunk's embedding text. The actual LaTeX is stored for display, but the embedding includes natural language context. This is the primary mitigation.
2. **BM25 hybrid retrieval:** BM25 keyword search on the chunk's natural language context will catch "Sharpe ratio" if that phrase appears in the surrounding text.
3. **Research validation:** SSEmb (2025, ARQMath-3 benchmark) confirms combining structural + semantic approaches outperforms either alone by >5 points on formula retrieval. However, SSEmb uses graph-based structural encoding beyond what we implement — our mitigation is a pragmatic subset that avoids the complexity of full formula graph embedding.

**Detection:** Index a paper with named formulas. Query "Sharpe ratio formula". If the correct chunk is not in top-5, formula retrieval is failing. Measure recall@5 on a small labeled set of formula queries before declaring Phase 3 complete.

---

### Pitfall 4: VRAM Exhaustion During Concurrent Operations

**What goes wrong:** Running document parsing (Docling with GPU-accelerated formula model), embedding generation (BGE-M3), and LLM inference (Ollama/vLLM) simultaneously on the same GPU exceeds available VRAM. Server crashes with CUDA OOM errors or falls back to CPU (10-100x slower for LLM).

**Why it happens:** Each component loads its own model weights into VRAM:
- Docling formula model: ~1-2GB during ingestion
- BGE-M3 embedding: ~0.9GB
- Ollama 7B Q4: ~4-5GB
- Total simultaneous: ~7-8GB on a single GPU

**Consequences:** Server instability. Either ingestion or query serving breaks at random. CPU fallback for LLM makes responses take minutes. CUDA errors are non-deterministic and hard to debug.

**Prevention:** Enforce operation sequencing via the job queue (ARCHITECTURE.md Pattern 6). Ingestion (parsing + embedding) runs in background; LLM inference runs only for active queries. These never execute simultaneously. Profile actual VRAM usage during Phase 4 with selected model sizes.

**Detection:** Submit a large document for ingestion, then immediately query the system. Monitor `nvidia-smi` during overlap. If VRAM spikes above 90% or errors appear in logs, sequencing is not working.

---

### Pitfall 5: Citation Provenance Lost During Ingestion Pipeline

**What goes wrong:** By the time chunks reach the vector store, they have lost their connection to the source document, page number, and section heading. The system can retrieve relevant text but cannot tell the user where it came from.

**Why it happens:** Multi-stage pipelines (parse → chunk → embed → store) often treat each stage as a pure transformation. If metadata is not explicitly threaded through every stage, it gets dropped. Vector stores (especially ChromaDB in basic usage) store vectors with minimal metadata.

**Consequences:** System is functionally useless for research purposes. Users cannot verify claims against source documents, cannot cite papers, cannot audit the retrieval. The core requirement ("citations trace back to exact sources") is violated.

**Prevention:** Design the metadata schema upfront in Phase 1 (ARCHITECTURE.md Pattern 5). Every processing stage must accept and return the full metadata object. The vector store must store metadata alongside vectors. Test end-to-end citation round-trip before Phase 3 is complete.

**Detection:** Ingest a document. Retrieve a chunk. Verify that the returned chunk includes document_id, page_number, and section_header that correctly identify where the chunk came from in the original PDF.

---

### Pitfall 6: MCP Server Blocks on Long Operations

**What goes wrong:** The MCP `ingest_document` tool call synchronously parses and indexes a 30-page PDF. Docling at 4 seconds/page = 120 seconds. The MCP server is blocked. Claude Code appears frozen. The user has no progress feedback and cannot cancel.

**Why it happens:** MCP tools are expected to return within a few seconds. The stdio transport does not support streaming partial results by default. Treating ingest as synchronous is a natural mistake.

**Consequences:** Poor user experience. For longer documents, the connection may timeout. Users may resubmit the same document multiple times, causing duplicate indexing.

**Prevention:** Async ingestion pattern (ARCHITECTURE.md Pattern 6). `ingest_document` MCP tool immediately returns a `job_id`. A separate `get_job_status` tool polls for completion. Processing runs in a background thread/process.

**Detection:** Submit a 20+ page PDF via MCP. Verify that `ingest_document` returns within 2 seconds with a job_id. Verify `get_job_status` transitions through pending → processing → indexed.

---

## Moderate Pitfalls

### Pitfall 7: Financial Table Misidentification

**What goes wrong:** Correlation matrices, factor loading tables, and performance attribution tables are parsed as plain text instead of structured tables. Column alignment is lost. "0.87 0.23 -0.45" becomes meaningless without the row/column headers.

**Prevention:** Verify Docling's table extraction quality specifically on financial tables before shipping Phase 2. Docling's TableFormer model achieves 97.9% accuracy on general tables, but financial tables with many decimal values and merged cells may differ. Test with actual correlation matrices from fund fact sheets or academic papers. If accuracy is insufficient, the table chunker needs to handle the specific failure modes.

### Pitfall 8: Embedding Model License Mismatch

**What goes wrong:** A model selected for its benchmark performance (e.g., NV-Embed-v2, Cohere embeddings) has a license that prohibits the intended use case. The project builds on a model it cannot legally use in production.

**Prevention:** Verify license before selecting any model. Verified:
- BGE-M3: MIT — fully permissive
- Qwen3-Embedding: Apache 2.0 — fully permissive
- stella_en_400M_v5: MIT — fully permissive
- jina-reranker-v3: CC BY-NC 4.0 — non-commercial only; check project status
- Qwen3-Reranker: Apache 2.0 — fully permissive
- NV-Embed-v2: NVIDIA Research license — check terms before production use

### Pitfall 9: ChromaDB Cannot Support Multi-Vector Retrieval

**What goes wrong:** Starting with ChromaDB for simplicity, then discovering it does not support BGE-M3's sparse vectors or multi-vector (late interaction) retrieval. Full migration to Qdrant required at Phase 5 after data is already indexed.

**Prevention:** Use Qdrant from the start (Phase 1). The multi-vector capability of BGE-M3 and any future ColPali-style visual retrieval both require a vector store that supports multi-vector payloads and MaxSim scoring. Qdrant supports this natively. ChromaDB does not.

### Pitfall 10: Docling Is Slow for Batch Ingestion

**What goes wrong:** Docling processes ~4 seconds per page. A 100-document corpus with 20 pages average = 2,000 pages = ~133 minutes of ingestion time. This is acceptable for background processing but must be planned for.

**Prevention:** Run ingestion as background jobs (Pattern 6). Provide clear status tracking. Consider batching documents rather than one-at-a-time ingestion. Marker (0.12s/page) can serve as a fast-path fallback for text-only PDFs where formula/table complexity is low.

---

## Minor Pitfalls

### Pitfall 11: Jupyter Notebook Output Cells Create Noise

**What goes wrong:** Notebook output cells containing large DataFrames, matplotlib figure text, or long tracebacks are indexed as chunks, polluting retrieval results with non-informative content.

**Prevention:** Filter output cells by type during nbformat parsing. Include: markdown cells, code cells, short text outputs. Exclude: error tracebacks, raw bytes, large data outputs (>500 chars). This is a heuristic that needs tuning with actual notebooks.

### Pitfall 12: Reranker Latency Blows Retrieval Budget

**What goes wrong:** Running a cross-encoder reranker on 50 candidates with 200-token average chunk length takes 2-4 seconds on CPU, breaking the <2s retrieve endpoint target.

**Prevention:** Load reranker on GPU (even the 0.6B models benefit significantly). Keep candidate set to 20-30 for the reranker, not 50. Cache reranker results for repeated identical (query, chunk_id) pairs. Profile during Phase 5.

### Pitfall 13: BM25 Index Out of Sync with Vector Store

**What goes wrong:** A document is deleted from the vector store but the BM25 in-memory index still contains its chunks. BM25 returns hits for deleted documents; citation resolution fails.

**Prevention:** Maintain BM25 index as a derived artifact rebuilt from SQLite chunk table on startup. When a document is deleted, update SQLite first, then rebuild BM25 index. Treat BM25 index as ephemeral (no separate persistence needed for <500 doc corpus).

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Storage schema | Metadata fields added later break existing indexes | Define complete ChunkMetadata schema in Phase 1 even if not all fields are populated yet |
| Phase 2: PDF ingestion | Dual-column academic papers | Use Docling with DocLayNet; test with real arXiv papers |
| Phase 2: Formula chunking | LaTeX split mid-expression | Implement atomic chunking before any other chunking logic |
| Phase 2: Table extraction | Financial table column alignment lost | Test with correlation matrices and factor loading tables specifically |
| Phase 3: Formula retrieval | Formula chunks not retrieved by natural language queries | Formula context enrichment mandatory; measure recall@5 before shipping |
| Phase 4: VRAM | OOM errors when ingestion + LLM overlap | Job queue enforces sequencing; never parallel |
| Phase 5: Reranker | Latency >2s on CPU | Load on GPU; cap candidate set at 20-30 |
| Phase 5: BM25 | Index staleness after document deletion | Rebuild from SQLite on startup; treat as ephemeral |
| Phase 6: MCP | Synchronous ingest blocks Claude Code | Async job queue must be in place before MCP |
| Phase 7: LaTeX .tex parsing | plasTeX fails on complex real-world LaTeX packages | Use pylatexenc for focused formula extraction; do not attempt full document rendering |

---

## Sources

- [OmniDocBench CVPR 2025](https://github.com/opendatalab/OmniDocBench) — Multi-column layout parsing accuracy measurements
- [PDF Data Extraction Benchmark 2025](https://procycons.com/en/blogs/pdf-data-extraction-benchmark/) — Docling vs Marker vs Unstructured table accuracy
- [SSEmb formula retrieval 2025](https://arxiv.org/abs/2508.04162) — Formula retrieval via structural+semantic approaches
- [Vision-guided chunking](https://arxiv.org/abs/2506.16035) — Multi-page table and complex structure chunking
- [Chunking strategies evaluation](https://arxiv.org/abs/2504.19754) — Comparative evaluation of chunking approaches
- [Hybrid retrieval RRF](https://ragaboutit.com/hybrid-retrieval-for-enterprise-rag-when-to-use-bm25-vectors-or-both/) — BM25+dense hybrid best practices
- [FinMTEB benchmark](https://arxiv.org/abs/2502.10990) — Finance domain embedding model evaluation
- [RAG for financial documents (ACL 2025)](https://aclanthology.org/2025.finnlp-2.9.pdf) — RAG system capabilities on financial documents
- [jina-reranker-v3 license](https://huggingface.co/jinaai/jina-reranker-v3) — CC BY-NC 4.0 non-commercial
