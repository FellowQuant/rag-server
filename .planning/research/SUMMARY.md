# Research Summary: FellowQuant RAG Server

**Domain:** RAG system for quantitative finance technical documents
**Researched:** 2026-02-18 (v2 — updated with current sources; replaces 2026-02-12 training-data-only research)
**Overall confidence:** HIGH for model benchmarks and architectural patterns; MEDIUM for finance-specific performance claims

---

## Executive Summary

This is a specialized RAG server for dense quantitative finance documents — academic papers with LaTeX formulas, financial tables, Python code, Jupyter notebooks, and dual-column academic layouts. The research confirms that SOTA techniques as of early 2026 have matured significantly from the initial (2026-02-12) training-data-based research, with clearer model recommendations and stronger architectural evidence.

Three discoveries from the updated research are roadmap-critical. First, **Docling (IBM, 2025) supersedes Marker** as the primary PDF parser because it includes a dedicated formula model (outputs LaTeX from formula images) and achieves 97.9% table extraction accuracy — two requirements that directly address the core document types. Second, **BGE-M3 enables a uniquely efficient three-mode hybrid retrieval** (dense + sparse + optional multi-vector) from a single model inference, which directly addresses the FinMTEB finding that BM25 outperforms dense embeddings alone on financial content. Third, **the reranker landscape has shifted**: jina-reranker-v3 achieves BEIR 61.94 at 0.6B params (vs bge-reranker-large's ~54 in the current codebase), and Qwen3-Reranker-0.6B provides a commercially safe Apache 2.0 alternative at similar performance.

The architectural recommendation remains a Python-based system with FastAPI, SQLite, and local LLM serving — but the specific component choices have been updated: Docling over Marker, Qdrant over ChromaDB (required for BGE-M3 multi-vector), BGE-M3 over stella_en_400M_v5, and Qwen3-Reranker-0.6B over bge-reranker-large. The phase structure from the initial research is sound and does not need to be restructured.

The primary risk remains structural data loss during ingestion — confirmed by the OmniDocBench (CVPR 2025) benchmark showing academic papers achieve only 40-60% accuracy with basic parsers. The secondary risk confirmed by new research: formula retrieval via standard embeddings is genuinely hard, and the recommended mitigation (formula context enrichment + BM25 hybrid) is a practical workaround, not a complete solution. The SSEmb approach (2025) demonstrates that structural graph + semantic embedding achieves 5+ point improvements on formula retrieval — but adds significant implementation complexity not warranted for v1.

---

## Key Findings

**Stack:** Python + FastAPI + Docling (parsing) + BGE-M3 (embedding) + Qdrant (vector store) + Qwen3-Reranker-0.6B (reranking) + Ollama/vLLM (LLM) + SQLite (metadata)

**Architecture:** Content-aware atomic chunking + three-mode hybrid retrieval (BM25 + dense + sparse) + two-stage cross-encoder reranking + formula context enrichment + parent-child chunk indexing

**Critical pitfall:** Fixed-size chunking destroys formulas and tables; formula retrieval via pure embedding is unreliable — use context enrichment + BM25 hybrid as mitigation

**New finding vs initial research:** Migrate from ChromaDB to Qdrant from Phase 1 — BGE-M3's multi-vector output requires multi-vector storage. This is an infrastructure change from the initial STACK.md.

---

## Implications for Roadmap

Based on research, the 7-phase structure from the initial research remains valid. Key updates:

1. **Phase 1 (Foundation)** — Change vector store from ChromaDB to Qdrant. Qdrant is required for BGE-M3's three-mode output and any future ColPali-style visual retrieval. ChromaDB cannot be migrated to later without rebuilding all embeddings.
   - Addresses: STORE-01 through STORE-04
   - Updated from initial research: Qdrant instead of ChromaDB

2. **Phase 2 (Ingestion Pipeline)** — Use Docling as primary parser (not Marker). Docling's formula model converts formula images to LaTeX — this is the core capability for quantitative finance papers. Formula-aware chunking is non-negotiable.
   - Addresses: INGEST-01 through INGEST-06
   - Updated from initial research: Docling instead of Marker as primary

3. **Phase 3 (Basic Retrieval)** — Dense-only retrieval for initial validation. Add formula context enrichment during Phase 2 (affects chunking, not retrieval logic). Measure recall@5 on formula queries before declaring Phase 3 complete.
   - Addresses: RETR-01, RETR-04, RETR-06

4. **Phase 4 (LLM Integration)** — Ollama for simplicity. Sequence ingestion and LLM inference via job queue. VRAM budget: BGE-M3 (0.9GB) + Qwen3-Reranker (1.5GB) + Ollama 7B Q4 (5GB) = ~7.4GB — workable on 8GB GPU if sequenced.
   - Addresses: LLM-01 through LLM-03

5. **Phase 5 (Hybrid Retrieval + Reranking)** — Upgrade from bge-reranker-large to Qwen3-Reranker-0.6B (+7 BEIR points). Implement full BGE-M3 three-mode hybrid via RRF. Add parent-child chunk indexing for formula context in LLM synthesis.
   - Addresses: RETR-02, RETR-03
   - Research flag: Profile reranker latency on GPU; keep candidate set ≤30 to stay under 300ms

6. **Phase 6 (MCP Server)** — No changes from initial research. Thin wrapper pattern.
   - Addresses: MCP-01 through MCP-06

7. **Phase 7 (Advanced Parsers)** — LaTeX .tex (pylatexenc for formula extraction) and Jupyter .ipynb (nbformat with output cell filtering).
   - Addresses: INGEST-01 (LaTeX), INGEST-03/04 (notebooks)

**Phase ordering rationale:**
- Qdrant before everything — cannot migrate vector store without rebuilding all embeddings
- Docling before Marker — establish correct formula extraction from the start; switching parsers mid-corpus requires full re-ingestion
- Formula context enrichment in Phase 2, not Phase 5 — this is a chunking-time decision, not retrieval-time
- Reranker upgrade in Phase 5 — drop-in replacement (same sentence-transformers interface), zero migration cost

**Research flags for phases:**
- **Phase 2**: Verify Docling formula model output quality on actual quant finance papers (arXiv math-fin, SSRN). Test TableFormer on correlation matrices specifically. Flag as needing hands-on validation before Phase 3 begins.
- **Phase 3**: Measure recall@5 on 20+ labeled formula queries before declaring Phase 3 complete. If recall is below 0.6, prioritize Phase 5 hybrid retrieval before Phase 4 LLM.
- **Phase 5**: Profile jina-reranker-v3 vs Qwen3-Reranker-0.6B latency on actual hardware. If using jina-v3 (NC license), confirm the project qualifies as non-commercial.
- **Phase 7**: LaTeX .tex parsing is fragile for real-world papers with custom macros. Scope to formula and section extraction only; do not attempt full document rendering.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack (parsers) | HIGH | Docling benchmarks verified (CVPR 2025 OmniDocBench, Procycons 2025). Marker speed confirmed. |
| Stack (embeddings) | HIGH | MTEB scores verified from official sources; BGE-M3 three-mode capability confirmed from HF model card; FinMTEB findings verified (EMNLP 2025). |
| Stack (rerankers) | HIGH (jina-v3, mxbai-v2) / MEDIUM (Qwen3-Reranker) | jina-v3 BEIR 61.94 confirmed from paper; mxbai-v2 57.49 confirmed; Qwen3-Reranker exact BEIR score not found — estimated from architecture similarity to jina-v3. |
| Indexing strategies | HIGH | Hybrid retrieval IBM findings verified; late chunking paper verified; GraphRAG limitations verified from 2025 evaluations. |
| Architecture | HIGH | Component boundaries and data flow are standard RAG patterns; multi-vector Qdrant capability confirmed from documentation. |
| Features | HIGH | Table stakes and differentiators align with requirements; FinMTEB research confirms finance domain specifics. |
| Pitfalls | HIGH | OmniDocBench verifies parsing difficulty; SSEmb confirms formula retrieval difficulty; VRAM estimates from model card data. |
| Finance-domain specifics | MEDIUM | FinMTEB is verified; ColPali financial table advantage is verified. But actual retrieval quality on this specific corpus (quant finance papers) cannot be confirmed without empirical testing. |

---

## Gaps to Address

**Gap 1: Qwen3-Reranker exact BEIR score not found** — The Qwen3-Reranker family is Apache 2.0 and architecturally close to jina-reranker-v3 (both built on Qwen3-0.6B), but the exact BEIR nDCG@10 score was not found in current sources. Confidence: MEDIUM. During Phase 5: benchmark both Qwen3-Reranker-0.6B and jina-reranker-v3 on a sample of finance-specific retrieval queries.

**Gap 2: Docling formula model quality on quant finance notation** — Docling's formula model is validated on general scientific papers. Quantitative finance uses specialized notation (risk-neutral pricing, factor models, stochastic calculus). Quality on this specific notation sub-domain is untested. During Phase 2: create a labeled test set of 50 formulas from actual quant papers, compare Docling LaTeX output to ground truth.

**Gap 3: BGE-M3 vs Qwen3-Embedding-0.6B for finance retrieval** — Both are recommended but for different reasons. The choice depends on whether three-mode hybrid retrieval (BGE-M3) or raw embedding quality (Qwen3) matters more. Cannot resolve without empirical testing on the target corpus. During Phase 3: A/B test both models on the same labeled query set.

**Gap 4: Parent-child chunk indexing implementation details** — The pattern is well-understood conceptually but the Qdrant implementation (storing both parent and child, linking them, returning parent to LLM) needs hands-on verification. During Phase 5: prototype this before committing to the architecture.

**Gap 5: VRAM sequencing on actual hardware** — VRAM budget estimate (7.4GB for BGE-M3 + Qwen3-Reranker + Ollama 7B Q4) depends on the target GPU. The user's hardware is unknown. During Phase 4: profile actual VRAM usage and document safe operating parameters.

---

## Updated Model Selections (vs Initial Research)

| Component | Initial Selection (2026-02-12) | Updated Selection (2026-02-18) | Reason |
|-----------|-------------------------------|-------------------------------|--------|
| Primary PDF parser | Marker | **Docling** | Formula model (LaTeX output), 97.9% table accuracy, DocLayNet for dual-column |
| Vector store | ChromaDB | **Qdrant** | BGE-M3 multi-vector requires multi-vector storage |
| Embedding model | BGE/E5/Nomic (unspecified) | **BGE-M3** (three-mode hybrid) or **Qwen3-Embedding-0.6B** | BGE-M3 uniquely enables full hybrid; Qwen3 for quality |
| Reranker | bge-reranker-large | **Qwen3-Reranker-0.6B** or **jina-reranker-v3** | +7 BEIR points over bge-reranker-large |
| LaTeX parser | plasTeX | **pylatexenc** (focused formula extraction) | plasTeX attempts full document rendering; pylatexenc is simpler and more reliable for targeted formula extraction |

---

## Sources

### Parsers and Indexing
- [Docling project](https://github.com/docling-project/docling) — IBM's document parser with formula model
- [OmniDocBench CVPR 2025](https://github.com/opendatalab/OmniDocBench) — 1,355 page benchmark across 9 document types
- [PDF Data Extraction Benchmark 2025](https://procycons.com/en/blogs/pdf-data-extraction-benchmark/) — Docling 97.9% table accuracy
- [Marker GitHub](https://github.com/datalab-to/marker) — PDF to markdown at 0.12s/page
- [Late chunking paper](https://arxiv.org/abs/2409.04701) — Contextual chunk embeddings
- [SSEmb formula retrieval](https://arxiv.org/abs/2508.04162) — Formula retrieval benchmark ARQMath-3
- [Vision-guided chunking](https://arxiv.org/abs/2506.16035) — Multimodal chunking research

### Embedding Models
- [Qwen3-Embedding technical report](https://arxiv.org/pdf/2506.05176) — Apache 2.0, MTEB #1 multilingual
- [BGE-M3 HuggingFace](https://huggingface.co/BAAI/bge-m3) — Three-mode retrieval
- [FinMTEB benchmark (EMNLP 2025)](https://arxiv.org/abs/2502.10990) — Finance domain evaluation
- [FinMTEB leaderboard](https://huggingface.co/spaces/FinanceMTEB/FinMTEB) — Fin-E5 results
- [stella_en_400M_v5](https://huggingface.co/NovaSearch/stella_en_400M_v5) — Current codebase model
- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard) — General rankings

### Rerankers
- [jina-reranker-v3 paper](https://arxiv.org/abs/2509.25085) — BEIR 61.94, CC BY-NC 4.0
- [mxbai-rerank-v2 blog](https://www.mixedbread.com/blog/mxbai-rerank-v2) — BEIR 57.49, Apache 2.0
- [Qwen3-Reranker](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) — Apache 2.0
- [ContextualAI Reranker v2](https://contextual.ai/blog/rerank-v2) — BEIR 61.2, CC BY-NC-SA 4.0

### Visual Retrieval
- [ColPali ICLR 2025](https://arxiv.org/abs/2407.01449v6) — Visual document retrieval
- [ViDoRe v2 benchmark](https://arxiv.org/abs/2505.17166) — Updated benchmarks
- [ColFlor blog](https://huggingface.co/blog/ahmed-masry/colflor) — 174M, 9.8x faster
- [Qdrant multi-vector docs](https://qdrant.tech/documentation/tutorials-search-engineering/using-multivector-representations/) — MaxSim support

### Finance-Specific
- [RAG for financial documents (ACL 2025)](https://aclanthology.org/2025.finnlp-2.9.pdf) — System capabilities evaluation
- [GraphRAG for finance](https://aclanthology.org/2025.genaik-1.6/) — 6% hallucination reduction
- [RAG vs GraphRAG evaluation](https://arxiv.org/html/2502.11371v2) — When GraphRAG fails
- [Hybrid retrieval best practices](https://infiniflow.org/blog/best-hybrid-search-solution) — Three-way hybrid superiority

---
*Research v2 completed: 2026-02-18*
*Supersedes: 2026-02-12 training-data-only research*
*Ready for roadmap: yes*
