---
phase: 02-document-ingestion-pipeline
plan: "02"
subsystem: ingestion
tags: [bge-m3, flag-embedding, dense-vectors, sparse-vectors, embeddings, qdrant]

# Dependency graph
requires:
  - phase: 02-document-ingestion-pipeline
    provides: ParsedChunk dataclass and chunking utilities from chunker.py
  - phase: 01-foundation-storage
    provides: QdrantStore with DENSE_DIM=1024 and sparse vector schema
provides:
  - Embedder class with load()/unload()/embed_chunks() lifecycle
  - EmbeddingResult dataclass with dense_vector (1024d), sparse_indices, sparse_values
  - BGE-M3 wrapper producing Qdrant-ready dense+sparse vectors from ParsedChunk content
affects:
  - 02-03-document-ingestion-pipeline
  - 02-04-document-ingestion-pipeline
  - Phase 3 (retrieval pipeline will call Embedder for query embedding)

# Tech tracking
tech-stack:
  added: [FlagEmbedding>=1.3.5, BGEM3FlagModel]
  patterns: [stateful-model-wrapper, batch-processing, empty-input-guard]

key-files:
  created:
    - src/rag_server/ingestion/embedder.py
  modified: []

key-decisions:
  - "Raw int token IDs from lexical_weights used directly as Qdrant sparse indices — do NOT call convert_id_to_token() which returns strings"
  - "Embedder is instantiated once per worker process — not per-document — to avoid repeated 5-10s model load times"
  - "Empty content strings produce zero dense vector + empty sparse instead of crashing, preserving chunk_index sequence integrity"
  - "return_colbert_vecs=False saves VRAM — ColBERT vectors not needed until Phase 3+ reranking"

patterns-established:
  - "Stateful model wrapper pattern: load()/unload() lifecycle with RuntimeError guard before use"
  - "Batch processing with per-batch VRAM bounding (configurable batch_size)"
  - "Two-pass batch approach: pre-fill empty slots with zero vectors, encode only non-empty texts"

requirements-completed: [INGEST-05]

# Metrics
duration: 2min
completed: 2026-02-19
---

# Phase 2 Plan 02: BGE-M3 Embedder Module Summary

**BGE-M3 stateful embedder producing 1024d dense + lexical sparse vectors from ParsedChunk content, with batch processing and empty-text guards for robust Qdrant upsert**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-19T14:35:28Z
- **Completed:** 2026-02-19T14:37:36Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Embedder class with stateful model lifecycle: load() loads BAAI/bge-m3 with use_fp16=True, unload() frees VRAM
- embed_chunks() processes list[ParsedChunk] in configurable batches (default=8), returns list[EmbeddingResult] in same order
- EmbeddingResult dataclass provides dense_vector (1024-dim float list), sparse_indices (raw int token IDs), sparse_values (floats) ready for Qdrant upsert
- Empty content strings produce zero vectors instead of crashing, preserving chunk_index sequence for downstream retrieval

## Task Commits

Each task was committed atomically:

1. **Task 1: BGE-M3 embedder module** - `7c0189d` (feat)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `src/rag_server/ingestion/embedder.py` - Embedder class + EmbeddingResult dataclass; BGE-M3 wrapper with batch encoding, empty-text handling, and raw int sparse indices

## Decisions Made

- Raw int token IDs from lexical_weights used directly as Qdrant sparse indices — convert_id_to_token() returns strings which Qdrant cannot use
- Embedder instantiated once per worker, not per document, to avoid repeated 5-10s model load latency
- return_colbert_vecs=False saves VRAM — ColBERT reranking not needed in Phase 2

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing FlagEmbedding dependency**
- **Found during:** Task 1 (BGE-M3 embedder module)
- **Issue:** FlagEmbedding not installed in the environment despite being in pyproject.toml dependencies
- **Fix:** Ran `pip install "FlagEmbedding>=1.3.5"` which installed FlagEmbedding 1.3.5 and its dependencies
- **Files modified:** None (pip install only)
- **Verification:** `from FlagEmbedding import BGEM3FlagModel` imports without error
- **Committed in:** 7c0189d (included in task commit environment setup)

---

**Total deviations:** 1 auto-fixed (1 blocking — missing dependency)
**Impact on plan:** Essential for module import. No scope creep.

## Issues Encountered

None — module structure verified without GPU. The torchao version mismatch warning (cpp extensions skipped) is a pre-existing environment condition and does not affect FlagEmbedding functionality.

## User Setup Required

None - no external service configuration required. BGE-M3 model downloads automatically on first `embedder.load()` call (~1 GB from HuggingFace Hub).

## Next Phase Readiness

- Embedder module ready for integration into the ingestion worker pipeline (02-03)
- embed_chunks() accepts list[ParsedChunk] from any parser (PDF, Markdown, Jupyter, LaTeX)
- EmbeddingResult.sparse_indices are raw int token IDs compatible with QdrantStore's sparse vector schema established in Phase 1
- Concern: Model load requires VRAM; worker process must call load() at startup, not per-document

---
*Phase: 02-document-ingestion-pipeline*
*Completed: 2026-02-19*
