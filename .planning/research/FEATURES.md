# Feature Landscape

**Domain:** Financial/Quantitative Document RAG Server
**Researched:** 2026-02-18 (updated with SOTA verification)
**Confidence:** HIGH for table stakes (validated against requirements); MEDIUM for differentiators

---

## Table Stakes

Features users expect. Missing = product feels incomplete or broken.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| PDF ingestion with layout preservation | Primary document format; dual-column academic papers and financial reports are standard | Medium | Requires Docling, not basic text extraction |
| LaTeX formula preservation | Core content of quantitative papers; formulas as garbled text are useless | Medium | Docling formula model outputs LaTeX |
| Financial table structure preservation | Correlation matrices, factor loadings lose meaning when cells are linearized | Medium | Table-as-atomic chunking required |
| Semantic search | Core RAG capability | Low | BGE-M3 dense retrieval |
| Chunk-level citations | Cannot verify claims without source document + page number | Medium | Metadata propagation through full pipeline |
| Document CRUD | List, delete, re-ingest documents | Low | Standard API operations |
| Index status tracking | pending/processing/indexed/failed — users need to know when docs are searchable | Low | Job queue with status polling |
| Dual-mode queries | Retrieve (raw chunks) vs Ask (LLM-synthesized answer) | Medium | Two endpoints, same retrieval backend |
| REST API | Programmatic access | Low | FastAPI |
| Local-only execution | Privacy requirement for proprietary research | Medium | Ollama + local models, no cloud dependencies |

---

## Differentiators

Features that set this system apart from generic RAG. Not universally expected, but high value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Hybrid retrieval (BM25 + dense) | Catches both conceptual queries AND exact term matches (α, β, specific model names) | Medium | rank-bm25 + BGE-M3 dense + RRF fusion |
| Cross-encoder reranking | 10-20% precision improvement over bi-encoder retrieval alone on BEIR benchmarks | Medium | Qwen3-Reranker-0.6B or jina-reranker-v3 |
| Jupyter notebook ingestion | Code + analysis + outputs together; critical for quant research workflows | Medium | nbformat parser with cell-type filtering |
| Multi-column layout handling | Academic finance papers use dual-column as standard; reading order matters | Medium | Docling DocLayNet model |
| Code block detection and preservation | Python implementations in papers need to stay as code, not garbled prose | Low | Docling code block classifier |
| MCP server integration | Native Claude Code integration; ingest and query without leaving the editor | Low | MCP Python SDK thin wrapper |
| Formula context enrichment | Enables natural language queries to find formula chunks ("Sharpe ratio formula" finds `\frac{R_p - R_f}{\sigma_p}`) | Medium | Prepend surrounding text to formula embedding |
| Async ingestion with progress | Docling is slow (4s/page); users need feedback without blocking | Low | Job queue returning job_id immediately |

---

## Anti-Features

Features to explicitly NOT build in v1.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Web UI / dashboard | Adds frontend complexity; API-only consumption is the actual pattern (Claude Code, scripts) | REST API + MCP cover all use cases |
| Cloud-hosted deployment | Privacy violation for proprietary quant research; introduces network latency | Local-only deployment |
| Proprietary LLM APIs | Cost, privacy, internet dependency | Ollama with local models |
| Real-time filesystem watching | Filesystem monitoring complexity; YAGNI | Manual API ingestion |
| User authentication / multi-tenancy | Single-user local deployment; no threat model requiring auth | Optional localhost-only binding |
| Document versioning | Complex; delete + re-ingest covers the use case | DELETE + POST ingest |
| OCR for scanned PDFs | Different problem domain; assume digital PDFs | Scope note in docs |
| GraphRAG / knowledge graph | Too expensive and complex for v1; 2025 research shows it underperforms on factual retrieval | Hybrid vector+BM25 retrieval |
| Visual RAG (ColPali-style) | Additional complexity; text extraction is sufficient for v1 with good parsers | Evaluate in v2 if text extraction proves insufficient for figure-heavy reports |
| Fine-tuning custom embeddings | High complexity; SOTA pretrained models (BGE-M3, Qwen3) already well above baseline | Use pretrained models as-is |
| Real-time market data integration | Different system entirely; this is a research knowledge base | Separate concern |

---

## Feature Dependencies

```
Qdrant + SQLite storage schema
    └─> Document ingestion (Docling parser, chunker)
        └─> Embedding model (BGE-M3)
            └─> Semantic retrieval
                └─> BM25 hybrid retrieval (adds sparse to dense)
                    └─> Reranking (adds cross-encoder precision)
                        └─> LLM synthesis (Ask mode)
                            └─> MCP server (wraps all above)

Async job queue
    └─> Document ingestion (job_id + status polling)
        └─> MCP async ingest (depends on job queue being in place)

Citation metadata schema
    └─> (must be designed before everything else — flows through every stage)
```

---

## MVP Recommendation

Build in this order, validate each phase before proceeding:

**Phase 1 (Foundation):** Storage schema with full citation metadata. Qdrant + SQLite. This must be right before anything else is built.

**Phase 2 (Ingestion):** Docling parser + content-aware atomic chunker + BGE-M3 embedding. Test with real financial documents: dual-column paper, paper with formulas, paper with tables. Do not proceed until formula and table preservation is verified.

**Phase 3 (Basic Retrieval):** Dense-only retrieval to validate end-to-end. Citations, document CRUD, retrieve endpoint. Confirm citation round-trip works.

**Phase 4 (LLM):** Ollama + ask endpoint + VRAM sequencing. Answer synthesis with inline citations.

**Phase 5 (Hybrid Retrieval + Reranking):** BM25 + RRF fusion + cross-encoder reranker. Measure improvement on formula retrieval specifically.

**Phase 6 (MCP):** Thin wrapper over Phase 3-5 logic. Async ingest tool. Retrieve and ask tools.

**Phase 7 (Advanced Parsers):** LaTeX .tex and Jupyter .ipynb ingestion.

**Deferred to v2:**
- Visual RAG (ColFlor/ColQwen2) for figure-heavy reports
- Cross-document synthesis (agentic multi-query patterns)
- Citation graph tracking ("which papers reference this formula?")
- RAPTOR hierarchical indexing for very long documents

---

## Domain-Specific Feature Notes

### Quantitative Finance Document Types

The system must handle these document types well:
1. **Academic papers** (arXiv, SSRN, Journal of Finance): dual-column, dense formulas, Greek-letter variables, citations
2. **Quant strategy research** (internal research notes): single-column, heavy Python code, performance tables, Sharpe/drawdown statistics
3. **Jupyter notebooks**: mixed code + prose + output tables; execution order matters
4. **LaTeX source files**: ground-truth formula extraction without PDF rendering artifacts

### Finance-Specific Retrieval Challenges

- **Exact symbol queries:** "alpha" (generic word) vs "alpha" (factor model intercept) vs `\alpha` (LaTeX). BM25 is essential for disambiguation.
- **Formula name lookup:** "Black-Scholes" should retrieve both the formula `C = S_0 N(d_1) - K e^{-rT} N(d_2)` AND the surrounding explanation.
- **Table queries:** "correlation between SPY and GLD" should retrieve the correlation matrix where that value appears, including headers.
- **Cross-paper concept queries:** "momentum premium" should retrieve chunks across multiple papers discussing the same factor.

### FinMTEB Research Implications

The FinMTEB benchmark (EMNLP 2025) reveals:
1. Domain-specialized models (Fin-E5, FinBERT) outperform general models on financial STS tasks by 15+ percentage points.
2. General MTEB performance is a **poor predictor** of financial domain performance.
3. BoW models (BM25) surprisingly outperform dense embeddings on financial STS tasks — this validates the hybrid retrieval approach.

**Implication for this project:** The BGE-M3 + BM25 hybrid approach directly addresses the FinMTEB finding. If retrieval quality remains insufficient for financial-specific queries, Fin-E5 (fine-tuned e5-Mistral-7B on financial synthetic data) is the upgrade path — but requires 7B-param VRAM budget.

---

## Sources

- [FinMTEB: Finance Massive Text Embedding Benchmark](https://arxiv.org/abs/2502.10990) — Domain specialization importance, BoW outperforms dense on financial STS
- [FinMTEB Leaderboard](https://huggingface.co/spaces/FinanceMTEB/FinMTEB) — Fin-E5 top performing model
- [Assessing RAG on Financial Documents (ACL 2025)](https://aclanthology.org/2025.finnlp-2.9.pdf) — 0.91 factual accuracy vs 0.44 multi-document synthesis
- [MultiFinRAG framework](https://arxiv.org/abs/2506.20821) — Multimodal RAG for financial QA
- [RAG for financial filings (FinSage)](https://arxiv.org/html/2504.14493v2) — Multi-aspect retrieval for 10-K/10-Q
- [RAPTOR for RAG](https://arxiv.org/html/2401.18059v1) — Hierarchical indexing for long documents
- [Advanced RAG optimization strategies](https://medium.com/@joycebirkins/6-advanced-rag-optimization-strategies-analysis-of-14-key-research-papers-f12329975009) — Agentic chunking, contextual retrieval survey
