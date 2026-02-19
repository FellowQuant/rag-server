# Model Comparison: Embeddings and Rerankers

**Domain:** Financial Document RAG Server
**Researched:** 2026-02-18
**Confidence:** HIGH for benchmark scores from verified sources; MEDIUM for inference benchmarks

---

## Embedding Models

### Full Comparison Table

| Model | MTEB English | Params | Dims | VRAM | License | HF Link | Verdict |
|-------|-------------|--------|------|------|---------|---------|---------|
| **Qwen3-Embedding-8B** | ~75.2 (MTEB v2) | 8B | up to 1024 (MRL) | ~16GB | Apache 2.0 | `Qwen/Qwen3-Embedding-8B` | Best open-source quality; needs dedicated GPU |
| **Qwen3-Embedding-0.6B** | ~67-68 est | 0.6B | up to 1024 (MRL) | ~1.5GB | Apache 2.0 | `Qwen/Qwen3-Embedding-0.6B` | **Recommended default**: best quality/VRAM ratio |
| **BGE-M3** | 63.0 | 0.6B | 1024 | ~0.9GB | MIT | `BAAI/bge-m3` | **Recommended for hybrid**: unique three-mode output |
| **stella_en_400M_v5** | ~70.1 (retrieval subcat) | 400M | 1024 (8192 max) | ~1GB | MIT | `NovaSearch/stella_en_400M_v5` | Current codebase model; good baseline |
| **NV-Embed-v2** | 72.31 | 7B (Mistral) | 4096 | ~14GB | NVIDIA Research | `nvidia/NV-Embed-v2` | Top quality but large; license concerns |
| **GTE-Qwen2-7B-instruct** | ~72 est | 7B | 3584 | ~14GB | Apache 2.0 | `Alibaba-NLP/gte-Qwen2-7B-instruct` | Good but superseded by Qwen3 family |
| **E5-Mistral-7B-instruct** | ~66-67 | 7B | 4096 | ~14GB | MIT | `intfloat/e5-mistral-7b-instruct` | Large, good multilingual; use Qwen3 instead |
| **mxbai-embed-large-v1** | ~64-65 | 335M | 1024 | ~1GB | Apache 2.0 | `mixedbread-ai/mxbai-embed-large-v1` | Solid but stella/BGE-M3 outperform it |
| **nomic-embed-text-v1.5** | ~62 | 137M | 768 | ~0.5GB | Apache 2.0 | `nomic-ai/nomic-embed-text-v1.5` | Good for CPU; not competitive with BGE-M3 |
| **bge-large-en-v1.5** | ~63-64 | 335M | 1024 | ~1.3GB | MIT | `BAAI/bge-large-en-v1.5` | Superseded by BGE-M3 and Qwen3 family |
| **Fin-E5** | 0.6767 (FinMTEB) | 7B | 4096 | ~14GB | MIT | See FinMTEB leaderboard | Best finance-domain model; requires 7B VRAM |

### Key Findings on Embedding Models

**1. Qwen3-Embedding-0.6B vs BGE-M3 — different strengths, both recommended**

BGE-M3 has a unique architectural advantage: it produces dense, sparse, and multi-vector (ColBERT-style) embeddings from a single forward pass. This enables full hybrid retrieval without multiple model loads. No other model in this class does this.

Qwen3-Embedding-0.6B has higher raw MTEB quality, Apache 2.0 license, and supports MRL (multiple dimension sizes from 32 to 1024).

**Recommendation:** BGE-M3 as the primary model because its three-mode output uniquely enables the hybrid retrieval architecture. Qwen3-Embedding-0.6B as upgrade path if pure retrieval quality is insufficient.

**2. NV-Embed-v2 — exclude**

Despite topping MTEB at 72.31, it is based on Mistral-7B (14GB VRAM) and has NVIDIA Research license restrictions for production use. Overkill for this project.

**3. Domain-specific models (Fin-E5, FinBERT)**

FinMTEB benchmark (EMNLP 2025) shows Fin-E5 achieves 0.6767 on financial tasks, outperforming general-purpose models including OpenAI text-embedding-3-large. However, Fin-E5 requires 7B param VRAM (~14GB). Viable only if a dedicated embedding GPU is available separate from the LLM.

FinBERT (110M params) is outperformed by general models on retrieval; its advantage is on financial sentiment classification, not retrieval. Do not use for this system.

**4. stella_en_400M_v5 (current codebase model)**

This is a solid model and not a liability. It's based on GTE-Qwen2-1.5B, has MRL support, and performs well on retrieval subsets. If migrating to BGE-M3 creates complications, stella is an acceptable status quo. The gap between stella and BGE-M3 on mixed-content financial retrieval is not verified — test before migrating.

**5. MTEB scores are unreliable predictors for financial domain**

FinMTEB (2025) explicitly found that general MTEB performance does not predict financial-domain performance. A model with lower general MTEB but financial-corpus pretraining may outperform. BGE-M3's hybrid retrieval advantage partially compensates for this by adding BM25 (which FinMTEB shows is surprisingly strong for financial STS).

---

## Reranker Models

### Full Comparison Table

| Model | BEIR nDCG@10 | Params | VRAM | License | HF Link | Verdict |
|-------|-------------|--------|------|---------|---------|---------|
| **jina-reranker-v3** | 61.94 | 0.6B (Qwen3) | ~1.5GB | CC BY-NC 4.0 | `jinaai/jina-reranker-v3` | **Best open performance; non-commercial license** |
| **Qwen3-Reranker-0.6B** | ~61 est | 0.6B | ~1.5GB | Apache 2.0 | `Qwen/Qwen3-Reranker-0.6B` | **Recommended: Apache 2.0 + Qwen3 stack cohesion** |
| **Qwen3-Reranker-4B** | Higher est | 4B | ~8GB | Apache 2.0 | `Qwen/Qwen3-Reranker-4B` | Quality upgrade if VRAM allows |
| **ContextualAI/ctxl-rerank-v2** | 61.2 | 1B/2B/6B | 2-12GB | CC BY-NC-SA 4.0 | `ContextualAI/ctxl-rerank-v2-instruct-multilingual-6b` | Instruction-following; non-commercial |
| **mxbai-rerank-large-v2** | 57.49 | 1.5B (Qwen2.5) | ~3GB | Apache 2.0 | `mixedbread-ai/mxbai-rerank-large-v2` | Good Apache 2.0 option; lower BEIR than jina-v3 |
| **mxbai-rerank-base-v2** | 55.57 | 0.5B (Qwen2.5) | ~1GB | Apache 2.0 | `mixedbread-ai/mxbai-rerank-base-v2` | Lightweight; Apache 2.0 |
| **bge-reranker-v2-m3** | ~56-57 est | 0.6B | ~1.5GB | MIT | `BAAI/bge-reranker-v2-m3` | Safe fallback; MIT; multilingual |
| **bge-reranker-v2-gemma** | ~56.5 | 2B (Gemma) | ~4GB | MIT (model) | `BAAI/bge-reranker-v2-gemma` | 8x slower than mxbai-large-v2; not recommended |
| **bge-reranker-large** (v1) | ~54-55 est | 335M | ~1.3GB | MIT | `BAAI/bge-reranker-large` | Current codebase model; superseded |
| **ms-marco-MiniLM-L-6-v2** | ~39-40 | 22M | ~0.1GB | Apache 2.0 | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Very fast; low quality; only for trivial use cases |

### Key Findings on Rerankers

**1. jina-reranker-v3 is the benchmark leader at BEIR 61.94**

Built on Qwen3-0.6B with a listwise architecture (can rank 64 documents simultaneously in one pass using causal self-attention). 2.5x more efficient than mxbai-rerank-large-v2 (1.5B) while achieving higher scores. Architecture is novel: query and all documents attend to each other in the same context window before scoring, unlike traditional pointwise cross-encoders.

**Critical limitation:** CC BY-NC 4.0 — non-commercial only. If FellowQuant is purely internal research tooling with no commercial intent, this qualifies. If there is any commercial usage, use Qwen3-Reranker-0.6B instead.

**2. Qwen3-Reranker-0.6B — recommended for production**

Apache 2.0 license removes all commercial concerns. Same Qwen3 backbone as the recommended embedding model (Qwen3-Embedding-0.6B), providing stack cohesion and shared tokenizer. Performance estimated close to jina-reranker-v3 (both built on Qwen3-0.6B). BEIR scores for Qwen3-Reranker specifically were not found in current sources; flag as LOW confidence on exact benchmark numbers.

**3. mxbai-rerank-large-v2 — Apache 2.0 fallback**

BEIR 57.49 with Apache 2.0 license. 1.5B params (larger than jina-v3 for worse performance). Good option if Qwen3-Reranker quality proves insufficient and commercial license is required.

**4. bge-reranker-large (current codebase model) — should be upgraded**

The v1 BAAI reranker has been superseded by bge-reranker-v2-m3 (multilingual, better benchmark scores) and by the Qwen3/jina generation. Retaining bge-reranker-large means leaving 5-8 BEIR points of precision on the table. Upgrade is straightforward (same sentence-transformers interface).

**5. Cohere reranker — excluded**

Cloud API, conflicts with local-only requirement.

---

## ColPali / Visual Retrieval Models

### Comparison Table

| Model | ViDoRe v2 nDCG@5 | Params | VRAM | Speed | License | HF Link |
|-------|-----------------|--------|------|-------|---------|---------|
| **ColQwen2.5-7B** | ~0.63+ | 7B | ~14GB | Slow | Apache 2.0 | `vidore/colqwen2.5-7b` |
| **ColQwen2.5-3B** | 0.564 | 3B | ~6GB | Medium | Apache 2.0 | `Metric-AI/colqwen2.5-3b-multilingual` |
| **ColQwen2-2B** | 0.583 | 2B | ~4GB | Medium | Apache 2.0 | `vidore/colqwen2-v1.0` |
| **ColFlor** | ~ColPali - 1.8% | 174M | ~0.5GB | 9.8x faster queries vs ColPali | MIT | `ahmed-masry/ColFlor` |
| **ColSmol-500M** | 0.397 | 500M | ~1GB | Fast | Apache 2.0 | `vidore/colSmol-500M` |
| **ColPali** (original) | ~0.55-0.60 | 3B (PaliGemma) | ~6GB | Baseline | Apache 2.0 | `vidore/colpali-v1.2` |

### Visual Retrieval Key Findings

**Visual retrieval is NOT required for v1.** Text extraction from Docling is sufficient for the initial corpus. Visual retrieval becomes relevant if:
- Financial reports are figure-heavy (charts, heat maps, page-layout-dependent tables) where text extraction loses critical structure
- The corpus includes scanned documents or image-heavy PDFs

**When visual retrieval is adopted (v2+):**
- Use ColFlor as the default — 174M params, 9.8x faster query encoding than ColPali, only 1.8% BEIR performance reduction. Production-viable.
- Use ColQwen2.5-3B for maximum quality if GPU memory allows (6GB VRAM for the visual model alone).
- ColPali-style retrieval requires Qdrant (multi-vector MaxSim scoring) — already recommended.

**Financial table evidence (ViDoRe v1):** ColPali specifically outperforms text-based approaches on TabFQuAD (financial table retrieval). The performance difference is "particularly stark" on visually complex benchmark tasks. This suggests visual retrieval may be worth evaluating even for v1 if financial tables prove difficult for Docling.

---

## Recommendation Matrix

| Use Case | Recommended Model | Rationale |
|----------|------------------|-----------|
| Primary dense+sparse embedding | BGE-M3 | Three-mode output enables full hybrid; MIT license; 0.9GB |
| Embedding quality upgrade | Qwen3-Embedding-0.6B | Best open-source MTEB; Apache 2.0; MRL |
| Primary reranker (commercial-safe) | Qwen3-Reranker-0.6B | Apache 2.0; Qwen3 stack cohesion |
| Primary reranker (non-commercial) | jina-reranker-v3 | BEIR 61.94 SOTA; 0.6B efficient |
| Reranker safe fallback | bge-reranker-v2-m3 | MIT; multilingual; battle-tested |
| Finance domain retrieval upgrade | Fin-E5 | FinMTEB #1; requires 7B VRAM |
| Visual retrieval (v2, efficient) | ColFlor | 174M, 9.8x faster, -1.8% vs ColPali |
| Visual retrieval (v2, quality) | ColQwen2.5-3B | Best visual quality per VRAM spent |

---

## Sources

- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard) — Embedding model rankings
- [Qwen3-Embedding technical report](https://arxiv.org/pdf/2506.05176) — Apache 2.0, MTEB scores, MRL support
- [BGE-M3 HuggingFace](https://huggingface.co/BAAI/bge-m3) — Three-mode retrieval, 0.9GB VRAM, MIT license
- [NV-Embed-v2 MTEB post](https://developer.nvidia.com/blog/nvidia-text-embedding-model-tops-mteb-leaderboard/) — MTEB 72.31, Mistral-7B base
- [stella_en_400M_v5 HuggingFace](https://huggingface.co/NovaSearch/stella_en_400M_v5) — MRL, GTE-Qwen2 base, MIT
- [FinMTEB benchmark](https://arxiv.org/abs/2502.10990) — Finance domain evaluation; Fin-E5 results
- [FinMTEB leaderboard](https://huggingface.co/spaces/FinanceMTEB/FinMTEB) — Finance embedding rankings
- [jina-reranker-v3 paper](https://arxiv.org/abs/2509.25085) — BEIR 61.94, CC BY-NC 4.0, listwise architecture
- [mxbai-rerank-v2 blog](https://www.mixedbread.com/blog/mxbai-rerank-v2) — BEIR 57.49, Apache 2.0, 3-stage RL training
- [bge-reranker-v2-m3 HuggingFace](https://huggingface.co/BAAI/bge-reranker-v2-m3) — Updated BAAI reranker, MIT
- [Qwen3-Reranker HuggingFace](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) — Apache 2.0, 0.6B, 32k context
- [ContextualAI Reranker v2](https://contextual.ai/blog/rerank-v2) — BEIR 61.2, CC BY-NC-SA 4.0, instruction-following
- [ColFlor blog post](https://huggingface.co/blog/ahmed-masry/colflor) — 174M, 17x smaller than ColPali, 9.8x faster
- [ViDoRe v2 benchmark](https://arxiv.org/abs/2505.17166) — Visual retrieval model rankings
- [ColPali paper ICLR 2025](https://arxiv.org/abs/2407.01449v6) — Financial table retrieval performance
