# FellowQuant RAG Server

## What This Is

A specialized RAG (Retrieval-Augmented Generation) server built for financial and quantitative research documents. It ingests PDFs, LaTeX source files, and Jupyter notebooks — preserving complex structures like financial tables, mathematical formulas, and multi-column layouts that generic RAG pipelines destroy. Exposes a REST API and MCP server for programmatic access and Claude Code integration.

## Core Value

Accurate retrieval and synthesis from dense quantitative finance documents — tables stay as tables, formulas stay as formulas, and citations trace back to exact sources.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Ingest PDFs with preserved table structure, LaTeX formulas, and multi-column layouts
- [ ] Ingest LaTeX source files (.tex) directly
- [ ] Ingest Jupyter notebooks (.ipynb) with code and analysis preserved
- [ ] Support 100+ document corpus with performant retrieval
- [ ] Local LLM integration for self-contained answer generation
- [ ] Semantic search with intelligent chunking tuned for technical documents
- [ ] REST API for full document lifecycle (ingest, list, delete, query, status)
- [ ] MCP server with retrieve tool (raw chunks with citations) and ask tool (LLM-synthesized answers)
- [ ] MCP document management (ingest, list, delete, index status)
- [ ] Cross-document synthesis (compare concepts across multiple sources)
- [ ] Precise citation with source document, page/section references

### Out of Scope

- Web UI or dashboard — API-only for v1
- Cloud-hosted deployment — runs locally with GPU
- Proprietary LLM dependencies — local models only for generation
- Real-time market data integration — this is a research knowledge base
- Mobile access — programmatic API consumption only

## Context

**Domain:** High-frequency trading (HFT) and quantitative finance research. Documents include works by authors like Marcos Lopez de Prado, academic papers on market microstructure, backtesting methodologies, statistical arbitrage, etc.

**Document complexity:** Quant finance documents are among the hardest to parse. They contain:
- Dense mathematical notation (stochastic calculus, optimization formulas)
- Financial tables (correlation matrices, backtesting results, factor loadings)
- Code snippets (Python implementations of algorithms)
- Dual-column academic paper layouts
- Figures and charts with captions that provide context

**Technology stack (research-validated 2026-02-18):**
- **Docling** (IBM) — Primary PDF parser; 97.9% table accuracy (CVPR 2025 benchmark); dedicated Granite-Docling VLM converts formula images to LaTeX; DocLayNet handles dual-column academic layouts; Apache 2.0
- **Marker** — Fast-path fallback parser (0.12s/page vs Docling's 4s/page); used for text-dense PDFs without complex tables/formulas; GPL-3.0
- **BGE-M3** (BAAI) — Primary embedding model; unique three-mode output (dense + sparse + multi-vector) from single inference pass; enables full hybrid retrieval without multiple model loads; 0.9GB VRAM; MIT
- **Qwen3-Reranker-0.6B** — Cross-encoder reranker; ~61 BEIR nDCG@10 (~7 points above bge-reranker-large); Apache 2.0; Qwen3 stack cohesion with embedding model
- **Qdrant** (local Docker) — Vector store; required for BGE-M3 multi-vector storage and future ColFlor visual retrieval; outperforms ChromaDB for production use cases
- **Ollama** — Local LLM serving (v1); OpenAI-compatible API; vLLM as v2 upgrade path
- **rank-bm25** — BM25 keyword index for hybrid retrieval; FinMTEB (2025) confirms BM25 surprisingly outperforms dense-only on financial STS tasks

**Integration target:** Claude Code via MCP protocol — the primary consumption interface while coding.

**Existing code:** There is existing code in this directory that may serve as a starting point or reference.

## Constraints

- **Hardware**: Must run on local machine with GPU — no cloud LLM API dependencies for core functionality
- **License**: Open source components preferred (Apache 2.0, MIT); GPL-3.0 acceptable for tooling
- **Format fidelity**: Document parsing must preserve mathematical notation, table structure, and code blocks — lossy conversion is a dealbreaker
- **Performance**: Queries should return in reasonable time even with 100+ documents indexed
- **Privacy**: All data stays local — no document content sent to external services

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| API + MCP only (no UI) | Consumed programmatically from Claude Code and scripts | Confirmed |
| Local LLM for generation | Privacy, no API costs, self-contained operation | Confirmed — Ollama v1 |
| Both retrieve and ask MCP modes | Flexibility: raw chunks for Claude Code reasoning, synthesized answers for quick queries | Confirmed |
| Qdrant over ChromaDB | BGE-M3 requires multi-vector storage (sparse + dense fields); ChromaDB cannot support this; Qdrant runs locally via Docker with no cloud dependency | Confirmed |
| Docling as primary parser | 97.9% table accuracy + dedicated formula VLM (Granite-Docling) — resolves the hardest parsing problems in quant finance docs; Marker retained as fast-path fallback | Confirmed |
| BGE-M3 as embedding model | Only open-source model producing dense + sparse + multi-vector from single inference; enables three-mode hybrid retrieval mandatory for finance queries per FinMTEB (2025) | Confirmed |
| Three-mode hybrid retrieval | FinMTEB confirms BM25 outperforms dense-only on financial STS; RRF fusion of BM25 + BGE-M3 dense + BGE-M3 sparse is the recommended approach | Confirmed |
| Qwen3-Reranker-0.6B as reranker | Apache 2.0; ~61 BEIR nDCG@10 (~7 points above bge-reranker-large); same Qwen3 backbone as embedding upgrade path | Confirmed |
| Atomic chunking for formulas/tables/code | Never split formula, table, or code block across chunk boundaries; formula chunks enriched with surrounding paragraph text for embedding context | Confirmed |
| ColFlor visual retrieval deferred to v2 | Text extraction via Docling sufficient for v1; visual retrieval added only if financial tables prove inadequate after validation | Confirmed — v2 |

---
*Last updated: 2026-02-18 — technology stack updated after SOTA research*
