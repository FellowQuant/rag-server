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

**Candidate technologies identified:**
- **RAGFlow** — DeepDoc engine for layout-aware PDF parsing, table extraction, Apache 2.0
- **PaperQA** — Scientific paper RAG with precise citations and agentic multi-source synthesis, MIT
- **Marker** — Best-in-class PDF-to-Markdown converter with LaTeX and code detection, GPL-3.0

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
| API + MCP only (no UI) | Consumed programmatically from Claude Code and scripts | — Pending |
| Local LLM for generation | Privacy, no API costs, self-contained operation | — Pending |
| Both retrieve and ask MCP modes | Flexibility: raw chunks for Claude Code reasoning, synthesized answers for quick queries | — Pending |
| Research best RAG stack before committing | Multiple viable options (RAGFlow, PaperQA, Marker combo) — need data-driven choice | — Pending |

---
*Last updated: 2026-02-12 after initialization*
