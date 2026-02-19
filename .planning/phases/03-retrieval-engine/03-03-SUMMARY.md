---
phase: 03-retrieval-engine
plan: "03"
subsystem: api
tags: [qwen3, reranker, cross-encoder, transformers, torch, causal-lm, yes-no-logit]

# Dependency graph
requires:
  - phase: 03-retrieval-engine
    provides: BM25Manager, QdrantStore, embedding retrieval pipeline (03-01, 03-02)
provides:
  - Reranker class wrapping Qwen/Qwen3-Reranker-0.6B for cross-encoder reranking
  - load()/unload() for explicit VRAM lifecycle control
  - compute_scores(query, documents) returning float relevance probabilities per document
affects: [03-04-retrieval-engine, 04-synthesis]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - AutoModelForCausalLM for reranking (not AutoModelForSequenceClassification)
    - padding_side=left on tokenizer for causal LM final-position logit extraction
    - Pre-encode fixed prefix/suffix tokens at load time to avoid per-batch re-tokenization
    - log_softmax over [false_logit, true_logit] then exp() for relevance probability
    - asyncio.to_thread() for GPU-bound inference from async context

key-files:
  created:
    - src/rag_server/retrieval/reranker.py
  modified: []

key-decisions:
  - "AutoModelForCausalLM used (not AutoModelForSequenceClassification) — official Qwen/Qwen3-Reranker-0.6B weights require causal LM; seq-cls requires tomaarsen converted checkpoint"
  - "padding_side=left is load-bearing — causal LM reads logits[:, -1, :] (final token position); right-padding shifts output away from -1"
  - "yes/no token IDs resolved at load() time, not per-batch — eliminates repeated tokenizer lookups"
  - "prefix/suffix tokens pre-encoded at load() time — avoids re-tokenizing fixed prompt structure for every batch"
  - "batch_size=8 default, user can reduce to 4 if CUDA OOM"

patterns-established:
  - "Reranker pattern: causal LM yes/no logit extraction for cross-encoder scoring"
  - "VRAM lifecycle: explicit load()/unload() on FastAPI startup/shutdown lifespan"
  - "Batched inference: tokenize body only, prepend/append pre-encoded tokens, left-pad, forward pass"

requirements-completed: [RETR-03]

# Metrics
duration: 1min
completed: 2026-02-19
---

# Phase 3 Plan 03: Reranker Summary

**Qwen3-Reranker-0.6B cross-encoder wrapper using causal LM yes/no logit extraction with left-padding for retrieval reranking (~1.2 GB fp16 VRAM)**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-19T18:03:31Z
- **Completed:** 2026-02-19T18:05:11Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Reranker class implementing official Qwen3-Reranker-0.6B inference pattern (AutoModelForCausalLM, padding_side=left, yes/no logit extraction)
- Batched compute_scores() returning float probabilities in [0.0, 1.0] matching input document order
- Explicit VRAM lifecycle management via load()/unload() for FastAPI startup/shutdown integration
- Pre-encoded prefix/suffix tokens at load time to minimize per-batch tokenization overhead

## Task Commits

Each task was committed atomically:

1. **Task 1: Reranker class — Qwen3-Reranker-0.6B with yes/no logit extraction** - `fa4f443` (feat)

**Plan metadata:** TBD (docs: complete plan)

## Files Created/Modified
- `src/rag_server/retrieval/reranker.py` - Reranker class with load/unload/compute_scores

## Decisions Made
- AutoModelForCausalLM required for official Qwen/Qwen3-Reranker-0.6B weights (seq-cls weights are a separate tomaarsen checkpoint)
- padding_side="left" on tokenizer is load-bearing: causal LM reads final token position (logits[:, -1, :]); right-padding would shift this away
- yes/no token IDs and prefix/suffix tokens resolved once at load() to avoid repeated work per batch
- DEFAULT_BATCH_SIZE=8 with documented reduction to 4 for CUDA OOM scenarios
- compute_scores() synchronous and GPU-bound by design — caller uses asyncio.to_thread()

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Reranker ready to be integrated into retrieval pipeline (03-04)
- Full inference test (requires CUDA + model download) documented in plan verify section
- VRAM budget: ~1.2 GB fp16 in FastAPI process + BGE-M3 in worker (~1 GB) = ~2.2 GB steady-state peak

---
*Phase: 03-retrieval-engine*
*Completed: 2026-02-19*
