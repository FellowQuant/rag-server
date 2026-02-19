# Technology Stack

**Project:** FellowQuant RAG Server
**Researched:** 2026-02-18 (updated with SOTA verification)
**Confidence:** HIGH for recommendations marked HIGH; MEDIUM for others

---

## Recommended Stack

### PDF / Document Parsing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Docling** (IBM) | Latest | Primary PDF parser | 97.9% accuracy on complex tables; dedicated formula model outputs LaTeX; handles dual-column academic papers via DocLayNet layout model; 258M Granite-Docling VLM unifies pipeline in one model. Benchmark winner for structured document extraction (CVPR 2025 OmniDocBench). |
| **Marker** | Latest | Fallback / fast path | Best speed-to-quality ratio (0.12s/page vs Docling's 4s/page); GPU-accelerated; good for text-dense PDFs where table/formula complexity is low. Keep as fallback for high-throughput ingestion. |
| **nbformat** | Latest | Jupyter notebook parsing | Official .ipynb parser; preserves cell types, outputs, execution order. |
| **Custom LaTeX parser** | — | .tex source parsing | For ground-truth formula extraction from LaTeX source files; no single library handles all LaTeX reliably — use a streaming tokenizer (e.g., pylatexenc or latexwalker) for math extraction. |

**Decision rationale:** Docling supersedes Marker as the primary parser as of 2025. Docling's Code Formula Model (vision-language model) converts formula images to LaTeX — critical for quantitative finance papers. Marker remains useful for speed-sensitive paths.

### Embedding Models

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Qwen3-Embedding-0.6B** | Latest (Apache 2.0) | Primary dense embedding | #1 open-source on MTEB multilingual (0.6B variant competitive with gte-Qwen2-7B). Supports MRL (dimensions 32–1024). Apache 2.0 license. ~1.5GB VRAM. Instruction-aware. HF: `Qwen/Qwen3-Embedding-0.6B` |
| **BGE-M3** | Latest (MIT) | Hybrid retrieval workhorse | Unique: outputs dense + sparse + multi-vector from single model. ~0.9GB VRAM. Supports 100+ languages. Enables three-way hybrid search without multiple model loads. MTEB: 63.0. HF: `BAAI/bge-m3` |
| **stella_en_400M_v5** | Latest (MIT) | Current codebase (retain) | MTEB retrieval strong; MRL support (1024d ≈ 8192d); based on GTE-Qwen2. Reasonable upgrade path. HF: `NovaSearch/stella_en_400M_v5` |

**Decision rationale:**
- For pure dense retrieval quality: **Qwen3-Embedding-0.6B** — best open-source MTEB scores in its class, Apache 2.0.
- For hybrid retrieval (dense + sparse + colbert-style multi-vector in one shot): **BGE-M3** is unique — no other model offers all three retrieval modes simultaneously from a single inference pass.
- **Recommended production approach**: BGE-M3 as the primary model, Qwen3-Embedding-0.6B as a quality upgrade if BGE-M3 retrieval quality is insufficient for finance queries.
- **Do not use NV-Embed-v2** (Mistral-7B base, requires more VRAM, license restrictions for production).

### Reranker Models

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Qwen3-Reranker-0.6B** | Latest (Apache 2.0) | Primary reranker | Apache 2.0; 0.6B params; based on same Qwen3 backbone as recommended embedder (stack cohesion); strong multilingual and code support. HF: `Qwen/Qwen3-Reranker-0.6B` |
| **jina-reranker-v3** | Latest (CC BY-NC 4.0) | Non-commercial alt | BEIR SOTA: 61.94 nDCG@10 vs mxbai-large-v2's 57.49; listwise architecture; 0.6B params; 2.5x more efficient than mxbai-large-v2. Non-commercial only. HF: `jinaai/jina-reranker-v3` |
| **BAAI/bge-reranker-v2-m3** | Latest (MIT) | Safe fallback | MIT license; battle-tested; multilingual; no license concerns. Lower BEIR than jina-v3 but fully open. HF: `BAAI/bge-reranker-v2-m3` |

**License ruling:** jina-reranker-v3 is CC BY-NC 4.0 (no commercial use). If FellowQuant is internal research tooling, it qualifies as non-commercial. If it will be productized, use Qwen3-Reranker-0.6B (Apache 2.0) or bge-reranker-v2-m3 (MIT).

### Vector Store

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Qdrant** | Latest | Primary vector store | Native multi-vector support (required for BGE-M3's three retrieval modes + ColBERT-style multi-vector). Supports MaxSim scoring for late interaction. Better than ChromaDB for production. Self-hostable. |
| **ChromaDB** | 0.4+ | Simple dev alternative | Zero-setup embeddable DB. Use for initial prototyping only — does not support multi-vector/late interaction natively. Migrate to Qdrant before adding hybrid retrieval. |

**Decision rationale:** If BGE-M3 (three-mode retrieval) or ColPali-style late interaction is used, Qdrant is required — ChromaDB cannot store multi-vector representations. Start with Qdrant from Phase 1 to avoid migration cost.

### Visual Retrieval (Optional — Phase 2+ extension)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **ColFlor** | Latest | Visual doc retrieval (efficient) | 174M params; 17x smaller than ColPali; only 1.8% performance drop on text-rich docs; 9.8x faster query encoding. Production-viable on a single GPU. HF: `ahmed-masry/ColFlor` |
| **ColQwen2.5-3B** | Latest | Visual doc retrieval (quality) | Best visual retrieval quality for tabular/figure-heavy financial reports; Qwen2-VL backbone; multilingual. HF: `vidore/colqwen2.5-3b` |
| **ColSmol-500M** | Latest | Visual doc retrieval (minimal) | SmolVLM backbone; runs on consumer GPU or Apple Silicon. ViDoRe v2 score: 0.397. HF: `vidore/colSmol-500M` |

**Visual retrieval is not required for v1.** Consider adding in v2 if text-based parsing of financial tables proves insufficient.

### LLM Serving

| Technology | Purpose | Why |
|------------|---------|-----|
| **Ollama** | Local LLM (MVP) | Simplest setup; OpenAI-compatible API; pre-built model management. Use for v1. |
| **vLLM** | Local LLM (production) | Significantly faster throughput, proper batching, streaming. Upgrade path when Ollama latency bottlenecks. |

### Infrastructure

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **FastAPI** | 0.100+ | REST API | Async, Pydantic v2, OpenAPI docs auto-generated. |
| **SQLite** | 3.x | Metadata storage | Zero-config, single-user, file-based. Stores doc metadata, chunk mappings, job status. |
| **SQLAlchemy** | 2.x | ORM | Clean DB access; future migration to PostgreSQL if needed. |
| **MCP Python SDK** | Latest | MCP server | Official Anthropic SDK; stdio transport for Claude Code. |
| **rank-bm25** | Latest | BM25 keyword search | Python-native BM25; combine with dense for hybrid retrieval. |
| **Pydantic** | 2.x | Data models | API schemas, config, validation. |
| **uvicorn** | Latest | ASGI server | Runs FastAPI. |

### Supporting Libraries

| Library | Purpose | Notes |
|---------|---------|-------|
| **sentence-transformers** | Model loading / inference | Transport layer for embedding models; handles tokenization, batching |
| **FlagEmbedding** | BGE-M3 specific features | BAAI's library for three-mode (dense+sparse+colbert) inference |
| **transformers** | Qwen3-Embedding direct access | When sentence-transformers interface insufficient |
| **pylatexenc** | LaTeX tokenization | Formula extraction from .tex source files |
| **nbformat** | Jupyter notebook parsing | Standard .ipynb cell access |
| **pytest** | Testing | Unit + integration |
| **ruff** | Lint/format | Fast Python linter |

---

## Alternatives Considered and Rejected

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| PDF Parser | Docling | PyPDF2 / pdfplumber | No layout awareness, destroys tables/formulas |
| PDF Parser | Docling | Unstructured | 75% accuracy on complex tables; worse than Docling |
| Embedding | BGE-M3 | NV-Embed-v2 | Mistral-7B base (14GB+ VRAM); license less permissive; overkill for v1 |
| Embedding | BGE-M3 | text-embedding-3-large | Cloud API — excluded by requirement |
| Embedding | Qwen3-0.6B | Qwen3-8B | 8GB VRAM required; 0.6B provides excellent quality for the size |
| Reranker | Qwen3-Reranker-0.6B | bge-reranker-large | Older; lower benchmark scores; replaced by v2-m3 lineage |
| Reranker | jina-reranker-v3 | mxbai-rerank-large-v2 | jina-v3 achieves 61.94 vs mxbai's 57.49 on BEIR with 2.5x fewer params |
| Reranker | Qwen3/jina | Cohere reranker | Cloud API — excluded by requirement |
| Vector Store | Qdrant | ChromaDB | No multi-vector support; limited production features |
| Vector Store | Qdrant | FAISS | No metadata filtering; no persistence; no multi-vector |
| Visual RAG | ColFlor | ColPali (original) | ColFlor is 17x smaller with only 1.8% performance drop — strictly better tradeoff |
| Framework | Direct libraries | LangChain / LlamaIndex | Over-abstraction, heavy dependencies, harder to debug |

---

## Installation

```bash
# Core parsing
pip install docling marker-pdf nbformat pylatexenc

# Embedding and retrieval
pip install sentence-transformers FlagEmbedding transformers

# Vector store
pip install qdrant-client

# Reranking
pip install sentence-transformers  # covers cross-encoders too

# API + serving
pip install fastapi uvicorn pydantic sqlalchemy rank-bm25

# MCP
pip install mcp

# Dev
pip install pytest ruff httpx
```

---

## VRAM Budget (Reference)

| Component | VRAM (FP16) | Notes |
|-----------|-------------|-------|
| BGE-M3 embedding | ~0.9 GB | Three-mode retrieval; CPU fallback viable |
| Qwen3-Embedding-0.6B | ~1.5 GB | Alternative embedding |
| Qwen3-Reranker-0.6B | ~1.5 GB | Can share GPU with embedding |
| jina-reranker-v3 | ~1.5 GB | 0.6B params |
| Ollama (7B Q4) | ~4–5 GB | Separate process |
| Ollama (13B Q4) | ~8–9 GB | Separate process |
| Docling GPU (formula model) | ~1–2 GB | During ingestion only; not always loaded |
| **Total (embedding + reranker + LLM)** | **~7–10 GB** | Sequence ingestion and inference |

**Recommendation for ≥16GB VRAM:** Run embedding + reranker concurrently; sequence LLM inference separately. **For ≤8GB VRAM:** Use CPU for embedding (BGE-M3 CPU is acceptable), GPU for LLM only.

---

## Sources

- [ViDoRe Benchmark (ICLR 2025)](https://arxiv.org/abs/2407.01449v6) — ColPali/ColQwen2/ColFlor benchmarks
- [ColFlor: BERT-Size Visual Retrieval](https://huggingface.co/blog/ahmed-masry/colflor) — ColFlor performance vs ColPali
- [ViDoRe v2 Benchmark](https://arxiv.org/abs/2505.17166) — Updated visual retrieval benchmarks
- [Qwen3-Embedding blog](https://qwenlm.github.io/blog/qwen3-embedding/) — Apache 2.0, MTEB #1 multilingual
- [BGE-M3 HuggingFace](https://huggingface.co/BAAI/bge-m3) — Three-mode retrieval, 0.9GB VRAM
- [NV-Embed-v2 HuggingFace](https://huggingface.co/nvidia/NV-Embed-v2) — MTEB 72.31, Mistral-7B base
- [jina-reranker-v3 paper](https://arxiv.org/abs/2509.25085) — BEIR 61.94, 0.6B params, CC BY-NC 4.0
- [mxbai-rerank-v2 blog](https://www.mixedbread.com/blog/mxbai-rerank-v2) — BEIR 57.49, Apache 2.0
- [Docling IBM](https://github.com/docling-project/docling) — Formula model, 97.9% table accuracy
- [OmniDocBench CVPR 2025](https://github.com/opendatalab/OmniDocBench) — PDF parser benchmarks
- [FinMTEB benchmark](https://arxiv.org/abs/2502.10990) — Finance domain embedding evaluation
- [Qdrant multi-vector docs](https://qdrant.tech/documentation/tutorials-search-engineering/using-multivector-representations/) — Late interaction / MaxSim support
- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard) — Embedding model rankings
