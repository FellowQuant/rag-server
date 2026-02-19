---
phase: 04-llm-integration
plan: "02"
subsystem: llm
tags: [openai, asyncopenai, boto3, bedrock, vllm, llamacpp, async, provider]

# Dependency graph
requires:
  - phase: 04-01-llm-integration
    provides: LLMProvider ABC, LLMConfig, create_provider() factory, lazy imports
provides:
  - VLLMProvider concrete class using AsyncOpenAI (base_url, api_key='EMPTY')
  - LlamaCppProvider concrete class, structurally identical to VLLMProvider
  - BedrockProvider with asyncio.to_thread-wrapped boto3 Converse/ConverseStream API
  - _to_bedrock_messages() helper for OpenAI->Bedrock message format conversion
  - create_provider() factory now fully functional (all three providers wired)
affects: [04-03-synthesis-engine, 04-04-ask-endpoint]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - AsyncOpenAI reused as singleton (created at init, connection pool managed by httpx)
    - boto3 client created fresh per call (not thread-safe to share across asyncio threads)
    - asyncio.to_thread() for all synchronous boto3 calls to avoid blocking FastAPI event loop
    - Batch-then-yield streaming for Bedrock (all tokens collected in thread, then yielded)
    - System message prepended to message list for OpenAI providers, passed separately for Bedrock

key-files:
  created:
    - src/rag_server/llm/vllm_provider.py
    - src/rag_server/llm/llamacpp_provider.py
    - src/rag_server/llm/bedrock_provider.py
  modified: []

key-decisions:
  - "AsyncOpenAI client created once at VLLMProvider/LlamaCppProvider init — httpx manages connection pool; creating per-request would be wasteful"
  - "boto3 client created fresh per BedrockProvider call (not stored on self) — boto3 clients are NOT thread-safe when shared across threads in asyncio.to_thread"
  - "Bedrock streaming is batch-then-yield — ConverseStream event iteration is synchronous, runs entirely inside asyncio.to_thread; tokens arrive all at once after model finishes (acceptable for cloud fallback)"
  - "LlamaCppProvider is a separate class from VLLMProvider despite identical implementation — explicit class for logs, future parameter divergence (n_predict, grammar), and factory clarity"
  - "System prompt handled differently per provider: prepended as system message for OpenAI-compatible servers, passed as separate system block for Bedrock Converse API"

patterns-established:
  - "OpenAI-compatible providers: AsyncOpenAI(base_url=..., api_key='EMPTY') — api_key required by SDK validation, ignored by local servers"
  - "Bedrock sync wrapping: asyncio.to_thread(_inner_sync_fn) — always wrap synchronous boto3 in thread pool"
  - "_to_bedrock_messages(): strip system role, wrap content as [{'text': ...}] list"

requirements-completed: [LLM-01, LLM-03]

# Metrics
duration: 1min
completed: 2026-02-19
---

# Phase 4 Plan 02: LLM Providers Summary

**Three concrete LLM providers: VLLMProvider and LlamaCppProvider via AsyncOpenAI, and BedrockProvider via boto3 Converse API wrapped in asyncio.to_thread**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-19T19:43:01Z
- **Completed:** 2026-02-19T19:44:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- VLLMProvider and LlamaCppProvider using AsyncOpenAI with base_url pointing to local inference servers (port 8000 and 8080 respectively)
- BedrockProvider with boto3 Converse API — complete() and batch-then-yield stream() wrapped in asyncio.to_thread to never block FastAPI event loop
- All three providers implement LLMProvider ABC (complete + stream) and are fully instantiatable
- create_provider() factory from plan 04-01 now dispatches correctly to all three concrete classes
- ValueError raised for unknown providers (e.g., "ollama") confirmed working

## Task Commits

Each task was committed atomically:

1. **Task 1: vLLM and llama.cpp OpenAI-compatible providers** - `0c3e793` (feat)
2. **Task 2: AWS Bedrock provider with asyncio.to_thread wrapping** - `51cf4b8` (feat)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified
- `src/rag_server/llm/vllm_provider.py` - VLLMProvider using AsyncOpenAI; complete() and stream() with system message support
- `src/rag_server/llm/llamacpp_provider.py` - LlamaCppProvider, structurally identical to VLLMProvider (separate class for clarity and future divergence)
- `src/rag_server/llm/bedrock_provider.py` - BedrockProvider with _to_bedrock_messages() helper and asyncio.to_thread wrapping for all boto3 calls

## Decisions Made
- AsyncOpenAI client created once at init (not per-request) — httpx manages connection pool automatically; per-request creation is wasteful
- boto3 client created fresh per call inside asyncio.to_thread — boto3 clients are NOT thread-safe when shared across threads
- Bedrock streaming uses batch-then-yield pattern — ConverseStream iteration is synchronous, must run fully inside thread; all tokens arrive after model finishes (acceptable for cloud fallback; local providers stream in real-time)
- LlamaCppProvider is a separate class despite identical code — communicates provider type in logs, allows future parameter divergence (n_predict, grammar constraints), keeps factory unambiguous
- System prompts handled differently per provider type: prepended as {"role": "system"} message for OpenAI-compatible, passed as separate `system` list in Bedrock Converse API

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. AWS credentials for Bedrock use the standard boto3 credential chain (env vars, ~/.aws/credentials, IAM role).

## Next Phase Readiness
- All three providers complete and verified against LLMProvider ABC
- create_provider() factory fully functional for all three providers
- Ready for plan 04-03: SynthesisEngine that uses providers to generate answers from retrieved chunks
- Ready for plan 04-04: /ask endpoint wiring

---
*Phase: 04-llm-integration*
*Completed: 2026-02-19*
