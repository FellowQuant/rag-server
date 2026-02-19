---
phase: 04-llm-integration
plan: "03"
subsystem: llm
tags: [synthesis, tiktoken, tenacity, citation-parsing, token-budget, streaming]

# Dependency graph
requires:
  - phase: 04-01
    provides: LLMConfig, LLMSettings, system_prompt, context_chunks, max_context_tokens
  - phase: 04-02
    provides: LLMProvider ABC (complete/stream), VLLMProvider, LlamaCppProvider, BedrockProvider
  - phase: 03-retrieval-engine
    provides: ChunkResult dataclass with reranker_score, source_filename, content, display_content
  - phase: api-schemas
    provides: AskResponse, SourceItem pydantic models
provides:
  - SynthesisEngine class in src/rag_server/llm/synthesis.py
  - Token budget enforcement via tiktoken cl100k_base (drops lowest-scoring chunks first)
  - Context block assembly with numbered, metadata-annotated chunk headers
  - Lenient citation regex for [Source: filename, p.N] inline markers
  - parse_result() with fallback to all-chunks when 0 citations found
  - synthesize() with AsyncRetrying (3 attempts, exponential jitter)
  - stream_synthesize() with manual retry loop for async generator compatibility
affects: [04-04-ask-endpoint, future-api-routes]

# Tech tracking
tech-stack:
  added: [tiktoken (cl100k_base encoding), tenacity (AsyncRetrying)]
  patterns:
    - Provider-agnostic synthesis engine (calls only provider.complete/stream)
    - Token budget enforced before LLM call, not at retrieval time
    - Async generator retry via manual loop (AsyncRetrying incompatible with yield)
    - Citation fallback guarantees non-empty sources list

key-files:
  created:
    - src/rag_server/llm/synthesis.py
  modified: []

key-decisions:
  - "stream_synthesize() uses manual retry loop (not AsyncRetrying) — Python async generators cannot yield inside a context manager; manual loop is the idiomatic workaround"
  - "Token budget always keeps at least 1 chunk — prevents edge case of empty context block when single chunk exceeds budget"
  - "Citation matching uses suffix fallback after exact match — handles path-prefix variations like 'doc.pdf' vs '/data/uploads/doc.pdf'"
  - "parse_result() fallback logs WARNING and includes all input chunks when 0 citations extracted — never return empty sources when answer exists"

patterns-established:
  - "Provider-agnostic synthesis: SynthesisEngine calls only provider.complete() and provider.stream() — all RAG logic contained here"
  - "Token budget before LLM: apply_token_budget() called after context_chunks slice, before building messages"
  - "Formula chunk rendering: display_content (raw LaTeX) used when chunk_type=='formula' and display_content present"

requirements-completed: [LLM-02]

# Metrics
duration: 5min
completed: 2026-02-19
---

# Phase 4 Plan 03: SynthesisEngine Summary

**SynthesisEngine with tiktoken token budget, lenient citation parsing, fallback source attribution, and tenacity retry for both complete() and stream() provider calls**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-19T19:47:03Z
- **Completed:** 2026-02-19T19:52:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- SynthesisEngine class with full RAG orchestration: context assembly, token budget, LLM call, citation parsing
- Token budget enforcement via tiktoken cl100k_base — chunks dropped lowest-score-first, always at least 1 kept
- Lenient citation regex matching `[Source: file.pdf, p.12]` and variants (no comma, alternate spacing)
- Citation fallback: when zero citations extracted, all input chunks included as sources with WARNING log
- Tenacity AsyncRetrying (3 attempts, exponential jitter 1-10s) wrapping provider.complete()
- Manual retry loop for stream_synthesize() — async generators cannot yield inside context managers

## Task Commits

Each task was committed atomically:

1. **Task 1: SynthesisEngine with prompt assembly, token budget, citation parsing, and retry** - `adc2fab` (feat)

**Plan metadata:** (docs commit — see final_commit below)

## Files Created/Modified

- `src/rag_server/llm/synthesis.py` - SynthesisEngine class (296 lines): token budget enforcement, context block formatting, citation parsing, synthesize()/stream_synthesize() with retry

## Decisions Made

- **stream_synthesize() uses manual retry loop:** Python async generators cannot `yield` inside a `with attempt:` context manager block used by AsyncRetrying. Manual `for attempt_num in range(1, 4)` loop is the correct idiomatic pattern.
- **Token budget always keeps at least 1 chunk:** Guard `if i == 0 or used_tokens + chunk_tokens <= budget` ensures the synthesis engine always has at least one context chunk even if the single chunk exceeds the token budget.
- **Citation suffix matching fallback:** After exact `source_filename` match, checks if either name ends with the other — handles uploads stored as `/data/uploads/doc.pdf` but cited as `doc.pdf`.
- **Fallback to all-chunks sources:** When citation regex finds 0 matches, includes all input chunks as SourceItem objects with a WARNING log, preventing empty sources list in AskResponse.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SynthesisEngine complete and importable; ready for 04-04 (Ask endpoint)
- Phase 4 has 1 plan remaining: 04-04-ask-endpoint
- No blockers — all dependencies (providers, schemas, retrieval models) are in place

---
*Phase: 04-llm-integration*
*Completed: 2026-02-19*
