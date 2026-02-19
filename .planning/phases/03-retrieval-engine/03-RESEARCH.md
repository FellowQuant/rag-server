# Phase 3: Retrieval Engine - Research

**Researched:** 2026-02-19
**Domain:** Hybrid retrieval (BM25 + BGE-M3 dense+sparse + Qwen3 reranking) on Qdrant + SQLite
**Confidence:** HIGH

---

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **top_k**: configurable with default of 10
- **min_score**: optional threshold parameter (0.0–1.0)
- **Scores in results**: return ALL scores (BM25, dense, sparse, RRF, reranker)
- **Reranker**: always runs — not skippable
- **Query input**: engine embeds internally (plain text string in)
- **API style**: synchronous/awaitable
- **No deduplication**, **No explain mode**
- **BM25 index lifecycle**: Build at startup from SQLite; incremental update via worker→queue signal
- **BM25 persistence**: `DATA_DIR/bm25.pkl`
- **BM25 concurrency**: `asyncio.Lock` for atomic swap on update
- **Result format**: Full chunk content always (no truncation); all scores per result

### Claude's Discretion
- Mode override, multi-query, instruction prefix, model architecture (query-side BGE-M3)
- BM25 tokenizer, LaTeX stripping, deletion handling, hot-swap implementation
- Formula display_content in results, citation metadata fields, document/type filters
- RRF alpha tuning, candidate pool size before reranking

### Deferred Ideas (OUT OF SCOPE)
- Explain mode
- Deduplication
- Multi-query

</user_constraints>

---

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RETR-01 | Three-leg parallel retrieval (BM25 + BGE-M3 dense + BGE-M3 sparse) | BM25 via rank-bm25 BM25Okapi; dense+sparse via Qdrant query_points with Prefetch; parallel via asyncio.gather |
| RETR-02 | RRF fusion of the three retrieval results | Standard Python RRF formula (k=60); three-way merge over ranked score lists |
| RETR-03 | Qwen3-Reranker-0.6B cross-encoder reranking | AutoModelForCausalLM (native transformers) with yes/no logit extraction; input: (query, chunk_content) pairs |
| RETR-04 | BM25 index built at startup from SQLite, hot-swapped on document indexing | asyncio.Lock hot-swap; asyncio.to_thread for CPU-bound build; worker→FastAPI queue signal |
| RETR-05 | Results include all scores (BM25, dense, sparse, RRF, reranker) and full chunk content | SQLite JOIN after Qdrant retrieval to populate content; score fields passed through all pipeline stages |

</phase_requirements>

---

## Summary

The retrieval pipeline combines three independent retrieval legs that run in parallel: BM25 keyword search (rank-bm25, in-process), BGE-M3 dense ANN search (Qdrant), and BGE-M3 sparse search (Qdrant). Dense and sparse queries can share a single Qdrant round-trip using the Prefetch API. BM25 results are merged with Qdrant results using a Python RRF implementation. The top-50 candidates after RRF are passed to Qwen3-Reranker-0.6B (native transformers, yes/no logit extraction) and reranked to produce the final top-k results with full chunk content from SQLite.

The existing codebase (Phases 1+2) provides `Embedder` (BGE-M3 wrapper in worker process), `QdrantStore` (async client, dense+sparse collection), and `WorkerManager` (multiprocessing.Queue). Phase 3 adds: a `Retriever` class in the FastAPI process that owns its own BGE-M3 query instance, `QdrantStore.query_dense()` and `QdrantStore.query_sparse()` methods, a BM25 manager, and a Qwen3 reranker wrapper. The worker gains a `result_queue` to signal BM25 rebuild.

The version mismatch between qdrant-client 1.16.2 and Qdrant server 1.13.4 is a non-fatal `UserWarning`. The `query_points` Prefetch API was introduced in server 1.10, so it works on the current server. The fix is to upgrade docker-compose to `qdrant/qdrant:v1.13.6` (latest in the 1.13.x line, data-compatible) or to `v1.16.3` (matches client), or to pass `check_compatibility=False` to `AsyncQdrantClient`.

**Primary recommendation:** Upgrade Qdrant server to v1.13.6 (safe minor-patch upgrade, data compatible) or v1.16.3 (fully matches client). Suppress the warning by passing `check_compatibility=False` in QdrantStore as an intermediate measure.

---

## Standard Stack

### Core
| Library | Version (installed) | Purpose | Why Standard |
|---------|---------------------|---------|--------------|
| qdrant-client | 1.16.2 | Qdrant async queries, dense+sparse prefetch | Already in project; Prefetch API tested and confirmed working against server 1.13.4 |
| rank-bm25 | 0.2.2 (latest on PyPI) | BM25Okapi in-process keyword index | Single-file pure Python, pickle-serializable, well-known API |
| FlagEmbedding | 1.3.5 | BGE-M3 query embedding via `encode_queries()` | Already installed; `BGEM3FlagModel` used in Phase 2 ingestion |
| transformers | 4.57.1 | Qwen3-Reranker-0.6B loading and yes/no logit inference | >= 4.51.0 required; already satisfies requirement |
| sentence-transformers | 5.2.2 | Optional CrossEncoder wrapper (tomaarsen variant only) | Installed; simpler API but requires different model weights |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio (stdlib) | 3.12+ | asyncio.gather for parallel retrieval legs, asyncio.Lock for BM25 hot-swap | Already used throughout |
| asyncio.to_thread (stdlib) | 3.12+ | Offload CPU-bound BM25 build and reranker inference to thread pool | Avoid blocking event loop |
| pickle (stdlib) | 3.12+ | BM25 index serialization to DATA_DIR/bm25.pkl | rank-bm25 BM25Okapi is pickle-compatible with no custom handlers |
| sqlalchemy async | 2.x | Fetch chunk content from SQLite after vector retrieval | Already in project; use async_session from database.engine |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| rank-bm25 BM25Okapi | bm25s | bm25s is faster but not installed; rank-bm25 is lighter to add, well-tested |
| AutoModelForCausalLM (native transformers) | tomaarsen/Qwen3-Reranker-0.6B-seq-cls + CrossEncoder | CrossEncoder API is simpler but requires downloading a different converted model; official weights use native approach |
| Python 3-way RRF | Qdrant Fusion.RRF + Python 1-way BM25 merge | Qdrant Fusion.RRF saves one round-trip but loses per-leg score access; Python 3-way RRF preserves all individual scores (required by spec) |

**Installation:**
```bash
pip install rank-bm25
# transformers, FlagEmbedding, sentence-transformers, qdrant-client already installed
```

---

## Architecture Patterns

### Recommended Project Structure
```
src/rag_server/
├── retrieval/
│   ├── __init__.py
│   ├── engine.py          # RetrieverEngine: main retrieval orchestrator
│   ├── bm25_manager.py    # BM25Manager: lifecycle, build, persist, hot-swap
│   ├── reranker.py        # Qwen3Reranker: model load, compute_scores()
│   └── models.py          # RetrievalResult, ChunkResult dataclasses
├── vector_store/
│   └── qdrant.py          # ADD: query_dense(), query_sparse() methods
└── worker/
    └── manager.py         # ADD: result_queue for BM25 update signals
```

### Pattern 1: Parallel Three-Leg Retrieval with asyncio.gather

**What:** Run BM25, dense Qdrant query, and sparse Qdrant query concurrently.
**When to use:** Always. Parallel is strictly faster than sequential here.

```python
# Source: verified via asyncio.gather + asyncio.to_thread + Qdrant query_points
import asyncio
from rank_bm25 import BM25Okapi

async def retrieve(query_text: str, top_k: int = 10) -> list:
    # Embed query once (encode_queries uses query_max_length, applies instruction if set)
    embed_result = await asyncio.to_thread(
        embedder.encode_queries,  # encode_queries(), not encode()
        query_text,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense_vec: list[float] = embed_result["dense_vecs"][0].tolist()
    lexical_weights: dict[int, float] = embed_result["lexical_weights"][0]
    sparse_indices = list(lexical_weights.keys())
    sparse_values = list(lexical_weights.values())

    # Run three legs in parallel
    bm25_task = asyncio.to_thread(_bm25_search, query_text, candidate_k)
    dense_task = qdrant_store.query_dense(dense_vec, limit=candidate_k)
    sparse_task = qdrant_store.query_sparse(sparse_indices, sparse_values, limit=candidate_k)

    bm25_results, dense_results, sparse_results = await asyncio.gather(
        bm25_task, dense_task, sparse_task
    )
    # RRF merge + reranker ...
```

### Pattern 2: Qdrant Dense and Sparse Queries (Separate Calls)

**What:** Two separate `query_points` calls for dense and sparse, returning scored lists with individual scores.
**When to use:** Required when spec demands all three individual scores (BM25, dense, sparse) in results.

```python
# Source: qdrant-client 1.16.2, verified against server 1.13.4
from qdrant_client.models import SparseVector

# Dense query — returns list of ScoredPoint with .score = cosine similarity
async def query_dense(self, dense_vec: list[float], limit: int) -> list[ScoredPoint]:
    result = await self._client.query_points(
        collection_name=self._collection,
        query=dense_vec,          # list[float] auto-routed to default named vector
        using="dense",
        limit=limit,
        with_payload=True,
    )
    return result.points         # list[ScoredPoint], .score = cosine similarity

# Sparse query — returns list of ScoredPoint with .score = sparse dot product
async def query_sparse(
    self,
    indices: list[int],
    values: list[float],
    limit: int,
) -> list[ScoredPoint]:
    result = await self._client.query_points(
        collection_name=self._collection,
        query=SparseVector(indices=indices, values=values),
        using="sparse",
        limit=limit,
        with_payload=True,
    )
    return result.points
```

**ScoredPoint fields:** `id` (str UUID), `score` (float), `payload` (dict), `version`, `shard_key`, `order_value`.
**Payload fields stored at ingestion:** `document_id`, `chunk_type`, `page_number`, `section_heading`, `chunk_index`.

### Pattern 3: BM25 Build and Hot-Swap

**What:** Build BM25Okapi from SQLite corpus at startup; hot-swap in-place under asyncio.Lock when worker signals a new document is indexed.
**When to use:** Startup and on each successful ingestion completion.

```python
# Source: rank-bm25 docs + asyncio.Lock verified locally
import asyncio, pickle, pathlib
from rank_bm25 import BM25Okapi

class BM25Manager:
    def __init__(self, pkl_path: pathlib.Path):
        self._path = pkl_path
        self._lock = asyncio.Lock()
        self._bm25: BM25Okapi | None = None
        self._corpus_ids: list[str] = []   # parallel to BM25 corpus, stores chunk UUID

    async def build(self, session: AsyncSession) -> None:
        """Build BM25 from all indexed chunks in SQLite. CPU-bound; uses to_thread."""
        from sqlalchemy import select
        from rag_server.database.models import Chunk

        # Fetch all chunk IDs + content (only indexed documents)
        result = await session.execute(
            select(Chunk.id, Chunk.content)
            .join(Chunk.document)
            .where(Document.status == "indexed")
            .order_by(Chunk.id)
        )
        rows = result.all()

        corpus_ids = [r.id for r in rows]
        tokenized = [r.content.lower().split() for r in rows]  # basic tokenizer

        def _build():
            bm25 = BM25Okapi(tokenized) if tokenized else None
            return bm25

        bm25 = await asyncio.to_thread(_build)

        async with self._lock:
            self._bm25 = bm25
            self._corpus_ids = corpus_ids

        # Persist to disk (atomic: write to .tmp, rename)
        await asyncio.to_thread(self._atomic_write, bm25, corpus_ids)

    def search(self, query: str, top_n: int) -> list[tuple[str, float]]:
        """Synchronous BM25 search. Call via asyncio.to_thread."""
        if self._bm25 is None:
            return []
        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)
        # np.argsort returns ascending; reverse for descending
        import numpy as np
        top_indices = np.argsort(scores)[::-1][:top_n]
        return [(self._corpus_ids[i], float(scores[i])) for i in top_indices]

    def _atomic_write(self, bm25, corpus_ids):
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump({"bm25": bm25, "corpus_ids": corpus_ids}, f)
        tmp.rename(self._path)  # atomic rename on Linux
```

### Pattern 4: Python Three-Way RRF

**What:** Merge BM25, dense, and sparse ranked lists using standard RRF formula (k=60).
**When to use:** After parallel retrieval, before reranking.

```python
# Standard RRF formula: score(d) = sum_r( 1 / (k + rank_r(d)) )
# k=60 is the standard constant from the original RRF paper (Cormack 2009)

def rrf_merge(
    rankings: dict[str, list[tuple[str, float]]],  # {leg: [(chunk_id, score), ...]}
    k: int = 60,
) -> list[tuple[str, float]]:  # [(chunk_id, rrf_score), ...]
    rrf_scores: dict[str, float] = {}
    per_leg_scores: dict[str, dict[str, float]] = {}

    for leg, ranked in rankings.items():
        per_leg_scores[leg] = {cid: score for cid, score in ranked}
        for rank, (chunk_id, _) in enumerate(ranked):
            rrf_scores.setdefault(chunk_id, 0.0)
            rrf_scores[chunk_id] += 1.0 / (k + rank + 1)   # rank 0-indexed

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
```

### Pattern 5: Qwen3-Reranker-0.6B Inference (Official Weights, Native Transformers)

**What:** Load `Qwen/Qwen3-Reranker-0.6B` as `AutoModelForCausalLM`. Extract yes/no token logits at the final output position. Apply log-softmax to get a relevance probability.
**When to use:** Always (reranker is not skippable per spec).

```python
# Source: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B (official README)
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

class Qwen3Reranker:
    MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"

    def __init__(self, device: str = "cuda", dtype=torch.float16):
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.MODEL_ID, padding_side="left"
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            self.MODEL_ID, torch_dtype=dtype
        ).to(device).eval()

        # Token IDs for yes/no classification
        self.token_true_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.token_false_id = self.tokenizer.convert_tokens_to_ids("no")
        self.max_length = 8192

        # Fixed prefix and suffix wrapping for chat-format prompt
        self._prefix = (
            "<|im_start|>system\n"
            'Judge whether the Document meets the requirements based on the Query and '
            'the Instruct provided. Note that the answer can only be "yes" or "no".'
            "<|im_end|>\n<|im_start|>user\n"
        )
        self._suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self._prefix_tokens = self.tokenizer.encode(self._prefix, add_special_tokens=False)
        self._suffix_tokens = self.tokenizer.encode(self._suffix, add_special_tokens=False)

    def _format_pair(self, query: str, document: str, instruction: str) -> str:
        return f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {document}"

    @torch.no_grad()
    def compute_scores(
        self,
        query: str,
        documents: list[str],
        instruction: str = "Given a search query, retrieve relevant passages that answer the query",
        batch_size: int = 8,
    ) -> list[float]:
        """Return relevance scores in [0.0, 1.0] for each (query, document) pair."""
        pairs = [self._format_pair(query, doc, instruction) for doc in documents]
        all_scores: list[float] = []

        for i in range(0, len(pairs), batch_size):
            batch_pairs = pairs[i : i + batch_size]
            # Tokenize without padding, then pad manually to include prefix+suffix
            inputs = self.tokenizer(
                batch_pairs,
                padding=False,
                truncation="longest_first",
                return_attention_mask=False,
                max_length=self.max_length - len(self._prefix_tokens) - len(self._suffix_tokens),
            )
            for j, ele in enumerate(inputs["input_ids"]):
                inputs["input_ids"][j] = self._prefix_tokens + ele + self._suffix_tokens
            padded = self.tokenizer.pad(
                inputs, padding=True, return_tensors="pt", max_length=self.max_length
            )
            padded = {k: v.to(self.model.device) for k, v in padded.items()}

            # Extract yes/no logits from final output token position
            logits = self.model(**padded).logits[:, -1, :]
            true_logit = logits[:, self.token_true_id]
            false_logit = logits[:, self.token_false_id]
            stacked = torch.stack([false_logit, true_logit], dim=1)
            log_probs = torch.nn.functional.log_softmax(stacked, dim=1)
            scores = log_probs[:, 1].exp().tolist()
            all_scores.extend(scores)

        return all_scores
```

**Threading:** `compute_scores` is synchronous and GPU-bound. Call via `asyncio.to_thread(reranker.compute_scores, query, documents)` from the async retrieval path. Since the reranker runs in the FastAPI process (not the worker), it shares the GPU with BGE-M3 in the worker process — VRAM budget must account for both.

### Pattern 6: Worker-to-FastAPI BM25 Update Signal

**What:** A second `multiprocessing.Queue` (`result_queue`) flowing from the worker process to FastAPI. FastAPI runs an asyncio background task polling it.
**When to use:** After every successful document ingestion in the worker.

```python
# WorkerManager additions (manager.py)
class WorkerManager:
    def __init__(self):
        self._queue: multiprocessing.Queue | None = None
        self._result_queue: multiprocessing.Queue | None = None   # NEW
        self._stop_event: multiprocessing.Event | None = None
        self._process: multiprocessing.Process | None = None

    def start(self):
        self._queue = multiprocessing.Queue(maxsize=200)
        self._result_queue = multiprocessing.Queue(maxsize=200)   # NEW
        self._stop_event = multiprocessing.Event()
        self._process = multiprocessing.Process(
            target=worker_main,
            args=(self._queue, self._result_queue, self._stop_event),  # pass result_queue
            daemon=True,
        )
        self._process.start()

    @property
    def result_queue(self) -> multiprocessing.Queue:
        return self._result_queue

# worker/process.py: after successful indexing in run_pipeline(), put signal:
result_queue.put_nowait({"type": "indexed", "document_id": job.document_id})

# FastAPI lifespan: start background polling task
async def _poll_bm25_updates(result_queue, bm25_manager, session_factory):
    while True:
        try:
            def _get():
                try:
                    return result_queue.get_nowait()
                except Exception:
                    return None
            msg = await asyncio.to_thread(_get)
            if msg and msg.get("type") == "indexed":
                async with session_factory() as session:
                    await bm25_manager.build(session)
            else:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
```

### Anti-Patterns to Avoid

- **Loading BGE-M3 in the FastAPI event loop:** BGE-M3 load is ~5-10 seconds. Use `asyncio.to_thread` for all model inference.
- **Reusing the worker's BGE-M3 instance for queries:** The worker process has its own model instance via `multiprocessing.spawn`. The FastAPI process must load its own BGE-M3 instance for query embedding.
- **Calling `encode()` instead of `encode_queries()`:** `encode()` uses `passage_max_length` defaults. `encode_queries()` uses `query_max_length` and applies `query_instruction_for_retrieval` if set.
- **BM25 direct mutation without asyncio.Lock:** Hot-swap must be atomic to prevent retrieval reading a half-built index.
- **Storing chunk content in Qdrant:** Chunk `content` and `display_content` are in SQLite only. Always JOIN with SQLite after vector retrieval to get content for reranker.
- **Using Qdrant Fusion.RRF for three-leg RRF:** Qdrant built-in RRF only handles dense+sparse, not BM25. Individual per-leg scores are not exposed in the fusion result. Use Python RRF for true three-way merge and score access.
- **Blocking asyncio event loop on reranker or BM25:** Both are CPU/GPU-bound. Always use `asyncio.to_thread`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| BM25 keyword scoring | Custom TF-IDF | rank-bm25 `BM25Okapi` | Handles IDF, avgdl, k1/b tuning; tested for pickle correctness |
| Query embedding | Raw tokenizer call | `BGEM3FlagModel.encode_queries()` | Applies query_max_length and optional instruction prefix consistently |
| Sparse vector representation | Custom dict | `qdrant_client.models.SparseVector(indices=..., values=...)` | Required exact type for Qdrant sparse query |
| Yes/no logit extraction | Hand-crafted logit code | Pattern from official Qwen3-Reranker README | Tokenizer side-effects (padding_side, prefix/suffix encoding) are subtle |
| Pickle atomic write | In-place file overwrite | Write to `.tmp` then `path.rename()` | `rename()` is atomic on Linux same-filesystem; in-place overwrite leaves corrupt state on crash |

**Key insight:** The reranker's prompt format (system prompt, `<Instruct>`, `<Query>`, `<Document>` tags, suffix `<think>` block) is load-bearing. Wrong formatting silently degrades scores rather than crashing.

---

## Common Pitfalls

### Pitfall 1: BGE-M3 Query Instance vs Worker Instance
**What goes wrong:** Code tries to call `embed_chunks()` or `encode()` from the FastAPI process, but the model is loaded only in the worker subprocess.
**Why it happens:** Phase 2 only loaded BGE-M3 in the worker. Phase 3 needs query embedding in FastAPI.
**How to avoid:** Load a separate `BGEM3FlagModel` in the FastAPI process (inside `Retriever.__init__()` or `lifespan`). The worker's instance and the FastAPI instance are independent.
**Warning signs:** `RuntimeError: Embedder.load() must be called before embed_chunks()` or model not loaded errors.

### Pitfall 2: Qwen3-Reranker VRAM Pressure
**What goes wrong:** Qwen3-Reranker-0.6B (0.6B params, ~1.2 GB fp16 VRAM) loaded in FastAPI process while BGE-M3 (~1 GB VRAM) is in the worker process. CUDA device shared between OS processes.
**Why it happens:** GPU VRAM is not fully shared between processes — each process allocates its own VRAM pool. BGE-M3 worker + Qwen3 FastAPI = ~2.2 GB VRAM minimum at steady state.
**How to avoid:** Monitor VRAM. Reranker can be loaded lazily (on first query) or the reranker and embedder can be in the same process (worker process does reranking). However, reranking in FastAPI process is simpler architecturally.
**Warning signs:** CUDA OOM on second model load.

### Pitfall 3: BM25 Corpus ID Mapping Drift
**What goes wrong:** BM25 `get_scores()` returns a numpy array indexed by corpus position. If the corpus order changes between build and search, chunk IDs are mismatched.
**Why it happens:** `corpus_ids` list must be parallel to the tokenized corpus passed to `BM25Okapi(corpus)`. If SQLite query ordering changes, IDs drift.
**How to avoid:** Always build corpus with `ORDER BY Chunk.id` (or any stable ordering). Store `corpus_ids` alongside the BM25 object (in pickle or in-memory). Never re-query IDs separately from the corpus build.
**Warning signs:** Returned chunks have wrong content for their scores.

### Pitfall 4: Qdrant Client/Server Version Warning Breaks Tests
**What goes wrong:** `UserWarning: Qdrant client version 1.16.2 is incompatible with server version 1.13.4` fires on every client construction, breaks warning-as-error test configurations.
**Why it happens:** Minor version difference of 3 exceeds the qdrant-client's allowed maximum of 1.
**How to avoid:** Pass `check_compatibility=False` to `AsyncQdrantClient()`, or upgrade Qdrant server in `docker-compose.yml` to `v1.13.6` or `v1.16.3`.
**Warning signs:** Tests fail with `warnings.warn` even though queries work correctly.

### Pitfall 5: Qwen3 Tokenizer `padding_side` Must Be `left`
**What goes wrong:** Default tokenizer padding is right-side. For a causal LM reranker that reads the final token position (`logits[:, -1, :]`), right-padding shifts the meaningful output token away from position -1.
**Why it happens:** `AutoTokenizer.from_pretrained()` defaults to `padding_side="right"` for most models. Qwen3-Reranker README explicitly requires `padding_side="left"`.
**How to avoid:** Always pass `padding_side="left"` in `AutoTokenizer.from_pretrained(...)`.
**Warning signs:** All pairs score identically or near-random — the model is reading padding tokens instead of the assistant response token.

### Pitfall 6: BM25 Build Blocks the Event Loop
**What goes wrong:** `BM25Okapi(tokenized_corpus)` for thousands of chunks is CPU-bound (seconds). Calling it directly in an `async def` blocks the event loop.
**Why it happens:** rank-bm25 is synchronous pure Python.
**How to avoid:** Always call `await asyncio.to_thread(lambda: BM25Okapi(corpus))` for corpus construction.
**Warning signs:** FastAPI becomes unresponsive during BM25 rebuild.

### Pitfall 7: Returning Qdrant Point IDs Without Fetching Content
**What goes wrong:** Retrieval returns chunk IDs and Qdrant payload (document_id, page_number, etc.) but not `content` — which is only in SQLite.
**Why it happens:** Content was not stored in Qdrant payload (by design — it's in SQLite).
**How to avoid:** After vector retrieval, do a bulk SQLite fetch: `SELECT id, content, display_content FROM chunks WHERE id IN (...)`. Use `sqlalchemy.select(Chunk).where(Chunk.id.in_(chunk_ids))`.
**Warning signs:** Result objects have empty `content` fields; reranker receives empty strings.

---

## Code Examples

Verified patterns from official sources:

### BGE-M3 Query Embedding (encode_queries vs encode)
```python
# Source: FlagEmbedding 1.3.5, M3Embedder.encode_queries() verified locally
# encode_queries() uses query_max_length (512) and applies query_instruction_for_retrieval
# encode() uses passage_max_length (512) by default
# For BGE-M3 with default config (no instruction), outputs are identical
# BUT use encode_queries() for semantic correctness and future instruction support

output = model.encode_queries(
    query_text,                  # str or list[str]
    return_dense=True,
    return_sparse=True,
    return_colbert_vecs=False,
)
# output["dense_vecs"]: ndarray shape (1024,) for single query
# output["lexical_weights"]: dict[int, float] — token IDs to weights (raw ints, same format as ingestion)
dense_vector = output["dense_vecs"].tolist()  # or [0].tolist() if batched
sparse_indices = list(output["lexical_weights"].keys())
sparse_values = list(output["lexical_weights"].values())
```

### Qdrant Dense Query (query_points)
```python
# Source: qdrant-client 1.16.2, tested against server 1.13.4
result = await client.query_points(
    collection_name="documents",
    query=dense_vector,   # list[float] of length 1024
    using="dense",
    limit=50,
    with_payload=True,
    with_vectors=False,
)
# result.points: list[ScoredPoint]
# point.id: str (chunk UUID)
# point.score: float (cosine similarity, 0.0-1.0)
# point.payload: dict with document_id, chunk_type, page_number, section_heading, chunk_index
```

### Qdrant Sparse Query (query_points)
```python
# Source: qdrant-client 1.16.2, tested against server 1.13.4
from qdrant_client.models import SparseVector

result = await client.query_points(
    collection_name="documents",
    query=SparseVector(indices=sparse_indices, values=sparse_values),
    using="sparse",
    limit=50,
    with_payload=True,
    with_vectors=False,
)
```

### BM25 Build and Search
```python
# Source: rank-bm25 0.2.2, verified locally
from rank_bm25 import BM25Okapi
import numpy as np

# Build: tokenized must be list[list[str]] (whitespace-split, lowercased)
corpus_ids = [chunk.id for chunk in chunks]   # parallel list
tokenized = [chunk.content.lower().split() for chunk in chunks]
bm25 = BM25Okapi(tokenized)

# Search: returns ndarray of shape (corpus_size,)
query_tokens = query_text.lower().split()
scores = bm25.get_scores(query_tokens)   # numpy.ndarray
top_indices = np.argsort(scores)[::-1][:top_n]
results = [(corpus_ids[i], float(scores[i])) for i in top_indices]
```

### Pickle Atomic Write/Load
```python
# Source: verified locally
import pickle, pathlib

def save_bm25(bm25, corpus_ids, path: pathlib.Path):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({"bm25": bm25, "corpus_ids": corpus_ids}, f)
    tmp.rename(path)   # atomic on Linux (same filesystem)

def load_bm25(path: pathlib.Path):
    if not path.exists():
        return None, []
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data["bm25"], data["corpus_ids"]
```

### RRF Three-Way Merge
```python
# Source: RRF paper (Cormack 2009) + verified locally
# k=60 is the standard constant

def rrf_merge(
    bm25_ranking: list[tuple[str, float]],    # [(chunk_id, bm25_score), ...]
    dense_ranking: list[tuple[str, float]],   # [(chunk_id, cosine_score), ...]
    sparse_ranking: list[tuple[str, float]],  # [(chunk_id, sparse_score), ...]
    k: int = 60,
    top_n: int = 50,
) -> list[tuple[str, float, dict]]:
    """Returns top_n by RRF score. Each result includes per-leg scores."""
    all_legs = {"bm25": bm25_ranking, "dense": dense_ranking, "sparse": sparse_ranking}
    rrf_scores: dict[str, float] = {}
    individual: dict[str, dict] = {}

    for leg, ranked in all_legs.items():
        for rank, (chunk_id, score) in enumerate(ranked):
            rrf_scores.setdefault(chunk_id, 0.0)
            rrf_scores[chunk_id] += 1.0 / (k + rank + 1)
            individual.setdefault(chunk_id, {"bm25": 0.0, "dense": 0.0, "sparse": 0.0})
            individual[chunk_id][leg] = score

    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [(cid, rrf_score, individual[cid]) for cid, rrf_score in merged[:top_n]]
```

---

## Qdrant Version Fix

**Situation:** qdrant-client 1.16.2 vs Qdrant server 1.13.4. Minor version difference = 3 (exceeds allowed 1). Results in a non-fatal `UserWarning` on every `AsyncQdrantClient` instantiation. The Prefetch-based hybrid query API (`query_points`) works correctly on server 1.13.4 (introduced in server 1.10).

**Option A — Upgrade Qdrant server (recommended):** Edit `docker-compose.yml`:
```yaml
image: qdrant/qdrant:v1.13.6   # Latest 1.13.x patch — data compatible, no migration needed
# OR
image: qdrant/qdrant:v1.16.3   # Matches client major+minor — fully compatible
```
`v1.16.3` is the safest long-term fix (client and server match). `v1.13.6` is a minimal-risk patch upgrade. Data stored on the Docker volume is forward-compatible across these patch versions.

**Option B — Suppress in QdrantStore (intermediate fix):**
```python
# In qdrant.py QdrantStore.__init__:
self._client = AsyncQdrantClient(
    url=self._settings.qdrant_url,
    check_compatibility=False,   # suppress UserWarning for version mismatch
)
```
This is safe because `query_points` Prefetch works on server 1.13.4 (confirmed via live testing).

**Recommendation:** Do both — suppress the warning with `check_compatibility=False` as an immediate fix, and upgrade the Docker image to `v1.16.3` in the same PR.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `client.search()` (deprecated) | `client.query_points()` with Prefetch | Qdrant 1.10 (2024-Q3) | Unified API; enables hybrid search in one call |
| `FlagLLMReranker` from FlagEmbedding | Native `AutoModelForCausalLM` | Qwen3 launch (2025-Q2) | FlagLLMReranker prompt format differs from Qwen3's; use official approach |
| `CrossEncoder` (sentence-transformers) | Official Qwen3 yes/no logit approach | Qwen3 launch (2025-Q2) | CrossEncoder works only with `tomaarsen/Qwen3-Reranker-0.6B-seq-cls` (converted weights, not official) |
| BGEM3FlagModel.encode() for queries | `BGEM3FlagModel.encode_queries()` | FlagEmbedding 1.x | encode_queries uses query_max_length and instruction prefix — semantically correct for retrieval |

**Deprecated/outdated:**
- `AsyncQdrantClient.search()`: Removed in qdrant-client 1.14+. Method no longer exists — confirmed via inspection. Use `query_points()` only.
- `qdrant_client.models.NamedVector` / `NamedSparseVector`: Not needed with new `query_points(using=...)` API.
- Qdrant `init_from` collection param: Deprecated in 1.16, removed — not relevant for Phase 3.

---

## Open Questions

1. **Reranker VRAM budget with BGE-M3 worker**
   - What we know: BGE-M3 in worker uses ~1 GB VRAM (fp16); Qwen3-Reranker-0.6B would need ~1.2 GB VRAM in FastAPI process
   - What's unclear: Whether the GPU can sustain both simultaneously during a retrieval call that coincides with an ingestion job
   - Recommendation: Load reranker lazily on first query (not at startup); document the VRAM requirement; test under load

2. **BM25 tokenizer for quantitative finance content**
   - What we know: Simple whitespace split + lowercase is the rank-bm25 default and works for English prose
   - What's unclear: Whether formula chunks (LaTeX removed or not) degrade BM25 quality; LaTeX stripping is in Claude's discretion
   - Recommendation: Start with simple tokenizer; add LaTeX stripping (pylatexenc is already installed) as an option, but avoid over-engineering for v1

3. **Candidate pool size before reranking**
   - What we know: Spec says "top-50 → return top-10"; candidate_k is in Claude's discretion
   - What's unclear: Whether 50 is optimal for this domain; trade-off is reranker latency vs recall
   - Recommendation: Default to 50, make it configurable via Settings

4. **BGE-M3 in FastAPI process startup timing**
   - What we know: BGE-M3 load is ~5-10 seconds; FastAPI needs it for queries
   - What's unclear: Whether to load at lifespan startup (blocking) or lazily on first query
   - Recommendation: Load eagerly in lifespan startup so the first query is not penalized; health endpoint should not be marked healthy until model is loaded

---

## Sources

### Primary (HIGH confidence)
- `qdrant-client` 1.16.2 Python package — `AsyncQdrantClient.query_points()` signature introspected locally; Prefetch + SparseVector tested against live Qdrant 1.13.4 server
- `FlagEmbedding` 1.3.5 — `BGEM3FlagModel.encode_queries()` and `BGEM3FlagModel.__init__` introspected locally; encode_queries source read
- `rank-bm25` 0.2.2 — installed and tested locally: BM25Okapi constructor, `get_scores()`, pickle roundtrip all verified
- `transformers` 4.57.1 — `AutoModelForCausalLM` import confirmed; >= 4.51.0 requirement confirmed met
- `sentence-transformers` 5.2.2 — `CrossEncoder.__init__` and `predict()` signatures introspected locally
- [Qwen/Qwen3-Reranker-0.6B on Hugging Face](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) — official inference code with yes/no logit extraction verified
- [Qdrant Hybrid Queries documentation](https://qdrant.tech/documentation/concepts/hybrid-queries/) — Prefetch API introduced Qdrant 1.10; confirmed server 1.13.4 support via live test

### Secondary (MEDIUM confidence)
- [tomaarsen/Qwen3-Reranker-0.6B-seq-cls on Hugging Face](https://huggingface.co/tomaarsen/Qwen3-Reranker-0.6B-seq-cls) — CrossEncoder.predict() usage for sentence-transformers path; alternative to official weights
- [Qdrant 1.10 blog post](https://qdrant.tech/blog/qdrant-1.10.x/) — Universal Query API introduction; used to confirm server version support
- [GitHub qdrant/qdrant releases](https://github.com/qdrant/qdrant/releases) — v1.16.3 is latest stable server

### Tertiary (LOW confidence)
- WebSearch results on qdrant-client/server compatibility — confirmed non-fatal UserWarning (not exception); verified directly by running against live server

---

## Metadata

**Confidence breakdown:**
- Qdrant query API: HIGH — introspected client 1.16.2 and tested against live server 1.13.4
- BGE-M3 query embedding: HIGH — encode_queries() source read; parameters verified
- rank-bm25 API: HIGH — installed and tested locally
- RRF formula: HIGH — standard algorithm, verified with test data
- Qwen3-Reranker inference: HIGH — official README code verified; transformers version confirmed
- BM25 IPC pattern: HIGH — asyncio patterns verified locally
- Qdrant version fix: HIGH — UserWarning behavior confirmed live

**Research date:** 2026-02-19
**Valid until:** 2026-03-21 (30 days — qdrant-client and FlagEmbedding are moderately active)
