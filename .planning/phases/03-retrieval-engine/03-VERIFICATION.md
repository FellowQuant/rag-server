---
phase: 03-retrieval-engine
verified: 2026-02-19T00:00:00Z
status: human_needed
score: 5/5 must-haves verified (automated); 1 item needs human confirmation
re_verification: false
human_verification:
  - test: "Run scripts/verify_retrieval.py with a live server to confirm BM25 index persistence and SQLite citation metadata pass"
    expected: "Script prints '=== PASS ===' with BM25 chunk_count > 0, BM25 search returns results, and citation fields present on chunks"
    why_human: "Smoke test requires running server with BGE-M3 and Reranker models loaded; cannot verify without live GPU hardware"
  - test: "Call RetrievalEngine.search('sharpe ratio') against a corpus with at least one indexed document"
    expected: "Returns ChunkResult list with reranker_score > 0 on top result and all five score fields populated"
    why_human: "Full pipeline (Qdrant query_dense + query_sparse + Qwen3 reranker) requires live Qdrant + GPU; not testable via grep/file checks"
  - test: "Index two different documents and run a cross-document query"
    expected: "Results include chunks with different document_id values (RETR-05 verification)"
    why_human: "RETR-05 (multi-document synthesis) requires a live multi-document corpus; architecture supports it but no multi-document test in smoke script"
---

# Phase 3: Retrieval Engine Verification Report

**Phase Goal:** Users can semantically search documents with hybrid ranking and get back cited chunks
**Verified:** 2026-02-19
**Status:** human_needed — all automated checks pass; 3 items need live server verification
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | User passes a plain text query and receives ChunkResult list with content, scores, and citation metadata | VERIFIED | `engine.py` `search()` returns `RetrievalResult` with `list[ChunkResult]`; `ChunkResult` has `source_filename`, `page_number`, `section_heading`, `chunk_type` from SQLite JOIN |
| 2 | Results combine BM25 + BGE-M3 dense + BGE-M3 sparse via RRF fusion | VERIFIED | `engine.py` lines 161–170: `asyncio.gather(bm25_task, dense_task, sparse_task)` then `_rrf_merge()` with k=60; all three legs wired |
| 3 | Qwen3-Reranker-0.6B always reranks the candidate pool before results are returned | VERIFIED | `reranker.py`: `AutoModelForCausalLM`, `padding_side="left"`, `logits[:, -1, :]`, log_softmax yes/no extraction — all present; `engine.py` line 224: `await asyncio.to_thread(self._reranker.compute_scores, ...)` always executes (no skip path) |
| 4 | Every ChunkResult includes citation metadata (filename, page, section, chunk_type) and all five scores | VERIFIED | `models.py` `ChunkResult` dataclass: `source_filename`, `page_number`, `section_heading`, `chunk_type`; `bm25_score`, `dense_score`, `sparse_score`, `rrf_score`, `reranker_score` all present; `engine.py` populates all fields from SQLite JOIN |
| 5 | Multi-document corpus returns chunks from different documents | VERIFIED (architectural) | `bm25_manager.py` comment: "Corpus built from ALL indexed chunks globally (not per-document) — required for RETR-05"; `engine.py` SQLite query fetches by `Chunk.id.in_(candidate_ids)` — no document_id filter; different `document_id` values will appear in results naturally |

**Score:** 5/5 truths verified (automated code analysis)

---

## Required Artifacts

### Plan 03-01

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `docker-compose.yml` | Qdrant v1.16.3 | VERIFIED | Line 3: `image: qdrant/qdrant:v1.16.3` |
| `src/rag_server/vector_store/qdrant.py` | `query_dense`, `query_sparse` | VERIFIED | Lines 155–225: both methods present, call `self._client.query_points()` with `using="dense"` / `using="sparse"`; `VectorSearchResult` dataclass exported |
| `src/rag_server/ingestion/embedder.py` | `encode_query` using `encode_queries()` | VERIFIED | Lines 147–188: `encode_query()` calls `self._model.encode_queries()`; `QueryEmbedding` dataclass exported |

### Plan 03-02

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/rag_server/retrieval/__init__.py` | Package marker | VERIFIED | File exists (1 line — empty package marker) |
| `src/rag_server/retrieval/bm25_manager.py` | `BM25Manager` with `build`, `search`, `load_from_disk` | VERIFIED | All three methods plus `chunk_count` property present; `asyncio.to_thread(_build)` for CPU-bound indexing; `asyncio.Lock` hot-swap |
| `src/rag_server/worker/manager.py` | `result_queue` property | VERIFIED | Lines 113–118: `result_queue` property; `_result_queue` initialized in `start()` line 60 |
| `src/rag_server/worker/process.py` | Accepts `result_queue` parameter | VERIFIED | Line 34–38: `worker_main(job_queue, result_queue, stop_event)` signature; passes `result_queue` to `run_pipeline()` line 98 |
| `src/rag_server/main.py` | `_poll_bm25_updates` background task | VERIFIED | Lines 35–70: function defined; lines 120–123: `asyncio.create_task(_poll_bm25_updates(...))` in lifespan |

### Plan 03-03

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/rag_server/retrieval/reranker.py` | `Reranker` with `load`, `unload`, `compute_scores` | VERIFIED | All three methods present; `AutoModelForCausalLM` (causal, not seq-cls); `padding_side="left"` (line 84, load-bearing); `logits[:, -1, :]` (line 187); log_softmax yes/no extraction (lines 191–194) |

### Plan 03-04

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/rag_server/retrieval/models.py` | `ChunkResult`, `RetrievalResult` | VERIFIED | Both dataclasses exported; `ChunkResult` has all 5 score fields and 4 citation fields |
| `src/rag_server/retrieval/engine.py` | `RetrievalEngine` with three-leg RRF + reranker | VERIFIED | `asyncio.gather` (line 168); `_rrf_merge` (lines 62–97); SQLite bulk fetch via `Chunk.id.in_()` (line 208); `asyncio.to_thread(compute_scores)` (line 224) |
| `src/rag_server/main.py` | `retrieval_engine` on `app.state` | VERIFIED | Lines 141–148: `RetrievalEngine(...)` constructed and stored as `app.state.retrieval_engine`; version bumped to `0.3.0` |
| `scripts/verify_retrieval.py` | End-to-end smoke test | VERIFIED (file exists, substantive) | 200+ line script; exercises upload → poll → BM25 verify → SQLite citation check → cleanup; NOTE: does NOT call `RetrievalEngine.search()` directly — deferred because retrieval HTTP endpoint is Phase 5 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `vector_store/qdrant.py` | `AsyncQdrantClient.query_points()` | `using="dense"` and `using="sparse"` | WIRED | Lines 170–177 (dense), 210–217 (sparse): `query_points()` calls confirmed |
| `ingestion/embedder.py` | `BGEM3FlagModel.encode_queries()` | `encode_query()` wrapper | WIRED | Line 174: `self._model.encode_queries([query], return_dense=True, return_sparse=True)` |
| `worker/process.py` | `result_queue` | `result_queue.put_nowait({"type": "indexed", ...})` | WIRED | `pipeline.py` lines 339–346: `result_queue.put_nowait({"type": "indexed", "document_id": document_id})` after both `indexed` and `indexed_partial` paths |
| `main.py` | `bm25_manager.build()` | `_poll_bm25_updates` background task | WIRED | Lines 54–70: `_poll_bm25_updates` polls `result_queue`; on `type == "indexed"` calls `bm25_manager.build(session)` |
| `retrieval/bm25_manager.py` | `BM25Okapi` | `asyncio.to_thread(_build)` | WIRED | Line 82: `bm25 = await asyncio.to_thread(_build)` where `_build` imports and calls `BM25Okapi(tokenized)` |
| `retrieval/engine.py` | `asyncio.gather(bm25_task, dense_task, sparse_task)` | Parallel three-leg retrieval | WIRED | Lines 164–170: all three tasks created and gathered |
| `retrieval/engine.py` | SQLite bulk fetch via `Chunk.id.in_()` | JOIN for citation metadata | WIRED | Lines 195–210: `select(...).join(Document, ...).where(Chunk.id.in_(candidate_ids))` |
| `retrieval/engine.py` | `reranker.compute_scores()` | `asyncio.to_thread` after RRF | WIRED | Lines 224–226: `await asyncio.to_thread(self._reranker.compute_scores, query, documents_text, instruction)` |
| `retrieval/engine.py` | `Document.id` JOIN | SQLite JOIN for filename | WIRED | Line 207: `.join(Document, Chunk.document_id == Document.id)` |

All 9 key links verified.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| RETR-01 | 03-01, 03-04 | Semantic search via vector embeddings | SATISFIED | `Embedder.encode_query()` + `QdrantStore.query_dense()` + `RetrievalEngine.search()` provide dense ANN retrieval |
| RETR-02 | 03-01, 03-04 | Hybrid search BM25 + semantic + RRF | SATISFIED | `BM25Manager.search()` + `query_dense()` + `query_sparse()` + `_rrf_merge(k=60)` in `RetrievalEngine.search()` |
| RETR-03 | 03-03, 03-04 | Cross-encoder reranking | SATISFIED | `Reranker` (Qwen3-Reranker-0.6B) with correct causal LM inference pattern; always runs in `engine.py` (no skip path) |
| RETR-04 | 03-02, 03-04 | Citation metadata on every chunk | SATISFIED | `ChunkResult` has `source_filename`, `page_number`, `section_heading`, `chunk_type` — all populated from SQLite JOIN in `engine.py`; all five scores also present |
| RETR-05 | 03-02, 03-04 | Cross-document synthesis queries | SATISFIED (architectural) | BM25 corpus is global (all indexed chunks); Qdrant search has no document filter; SQLite fetch uses `chunk_ids` from all documents; architecture supports multi-document results. Live test needed to confirm |

No orphaned requirements. All 5 RETR requirements claimed by plans and evidenced in code.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `retrieval/reranker.py` | 152 | `return []` | Info | Guard condition — correct behavior for empty `documents` list, not a stub |
| `retrieval/bm25_manager.py` | 133, 137 | `return []` | Info | Guard conditions — correct: empty index or empty query returns empty list |
| `scripts/verify_retrieval.py` | 636–646 | Comment block explaining smoke test scope limitation | Info | Smoke test validates BM25 + SQLite but does NOT call `RetrievalEngine.search()` end-to-end; documented as Phase 5 HTTP endpoint deferral — intentional |

No blockers or stub anti-patterns. All `return []` instances are documented guard conditions.

---

## Human Verification Required

### 1. Full Smoke Test Execution

**Test:** With Qdrant running and GPU available, start the server with `uvicorn rag_server.main:app` and run `python scripts/verify_retrieval.py`
**Expected:** Script prints `=== PASS ===`; BM25 index shows `chunk_count > 0`; BM25 search for "sharpe ratio" returns results; citation fields (`chunk_type`, `filename`, `page_number`) are populated on chunks; document deleted cleanly (204)
**Why human:** Requires live GPU, Qdrant Docker container, and BGE-M3/Reranker model downloads

### 2. End-to-End RetrievalEngine.search() Execution

**Test:** With server running and at least one indexed document, call `RetrievalEngine.search("sharpe ratio")` (via Phase 5 endpoint or direct Python import)
**Expected:** Returns `RetrievalResult` with `results` list; top `ChunkResult` has `reranker_score > 0`; all five score fields (`bm25_score`, `dense_score`, `sparse_score`, `rrf_score`, `reranker_score`) populated; `source_filename` matches uploaded file
**Why human:** Requires live Qdrant (dense + sparse query), live BGE-M3 for `encode_query()`, and live Qwen3-Reranker-0.6B for `compute_scores()`; smoke test intentionally defers this to Phase 5 HTTP endpoint

### 3. RETR-05 Multi-Document Cross-Query

**Test:** Index two different PDF/notebook documents, then run `RetrievalEngine.search("concept that spans both documents")`
**Expected:** `results` list contains `ChunkResult` entries with at least two distinct `document_id` values
**Why human:** Requires at least two indexed documents in a live corpus; architecture verifiably supports it (no document_id filter in retrieval) but functional confirmation needs real data

---

## Gaps Summary

No gaps found. All artifacts exist, are substantive (not stubs), and are correctly wired. The three human verification items above are functional confirmations that require a live environment with GPU models loaded — they are not code defects.

**RETR-05 note:** The smoke test (`verify_retrieval.py`) does not exercise `RetrievalEngine.search()` at all (the comment on lines 630–646 explicitly states retrieval endpoints are Phase 5, so the script validates BM25 and SQLite instead). This is not a gap in the retrieval engine itself — the engine code is complete and wired — but the end-to-end validation of the full pipeline is deferred to when Phase 5 adds the HTTP endpoint.

---

_Verified: 2026-02-19_
_Verifier: Claude (gsd-verifier)_
