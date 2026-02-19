---
phase: 04-llm-integration
plan: "01"
subsystem: llm
tags: [openai, boto3, pyyaml, pydantic-settings, yaml-config, sse-starlette, tenacity]

# Dependency graph
requires:
  - phase: 03-retrieval-engine
    provides: RetrievalEngine and RetrievalResult types consumed by synthesis engine
provides:
  - LLMConfig + LLMSettings pydantic models loaded from llm.yaml via YamlConfigSettingsSource
  - LLMProvider ABC with complete() and stream() abstract methods
  - create_provider() factory dispatching on provider name string
  - AskRequest, AskResponse, SourceItem schemas for the /ask endpoint
affects: [04-02-vllm-provider, 04-03-bedrock-provider, 04-04-synthesis-endpoint]

# Tech tracking
tech-stack:
  added: [openai>=1.60.0, boto3>=1.42.0, sse-starlette>=1.8.0, tenacity>=9.0.0, pyyaml>=6.0.0]
  patterns:
    - YAML config loaded via pydantic-settings YamlConfigSettingsSource (llm.yaml separate from .env)
    - LLM providers interchangeable via ABC — synthesis engine calls only complete() and stream()
    - Lazy provider imports in create_provider() to delay heavy SDK loads until needed
    - get_llm_settings() lru_cache singleton — one YAML parse per process lifetime

key-files:
  created:
    - llm.yaml
    - llm.yaml.example
    - src/rag_server/llm/__init__.py
    - src/rag_server/llm/config.py
    - src/rag_server/llm/provider.py
  modified:
    - pyproject.toml
    - src/rag_server/api/schemas.py

key-decisions:
  - "llm.yaml separate from .env — LLM config changes frequently (swap provider, tune prompt) and YAML is human-friendly for multi-line system prompts"
  - "No secrets in llm.yaml — AWS credentials come from standard boto3 credential chain"
  - "YamlConfigSettingsSource as sole pydantic-settings source — no env var merging for LLM config"
  - "Lazy imports in create_provider() — delays openai/boto3 SDK initialization until provider actually constructed"
  - "LLMProvider ABC takes messages as list[dict] with OpenAI role/content format — providers convert internally (e.g. BedrockProvider to Converse API format)"

patterns-established:
  - "Provider-agnostic synthesis: synthesis engine depends only on LLMProvider.complete() and LLMProvider.stream()"
  - "YAML-driven provider selection: swapping provider requires only llm.yaml edit, no code changes"

requirements-completed: [LLM-01, LLM-02]

# Metrics
duration: 2min
completed: 2026-02-19
---

# Phase 4 Plan 01: LLM Deps, YAML Config, and Provider ABC Summary

**YAML-driven LLM provider abstraction: LLMSettings loaded from llm.yaml via pydantic-settings, LLMProvider ABC with complete()/stream(), create_provider() factory, and AskRequest/AskResponse schemas for the /ask endpoint**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-19T19:38:33Z
- **Completed:** 2026-02-19T19:40:37Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Installed 5 new dependencies (openai, boto3, sse-starlette, tenacity, pyyaml) via uv sync
- Created llm.yaml with vllm provider default and quant finance system prompt; llm.yaml.example as identical reference copy
- Defined LLMConfig + LLMSettings pydantic models loading from llm.yaml via YamlConfigSettingsSource
- Created LLMProvider ABC with complete() and stream() abstract methods; create_provider() factory dispatches on provider name
- Extended api/schemas.py with SourceItem, AskRequest, AskResponse without breaking existing document schemas

## Task Commits

Each task was committed atomically:

1. **Task 1: Install dependencies, create llm.yaml config, and LLMSettings model** - `7a52bc4` (feat)
2. **Task 2: Abstract LLMProvider ABC, factory function, and API schemas extension** - `566eed6` (feat)

**Plan metadata:** (docs commit pending)

## Files Created/Modified
- `pyproject.toml` - Added openai, boto3, sse-starlette, tenacity, pyyaml dependencies
- `llm.yaml` - Active LLM provider config: vllm provider, Qwen2.5-7B-Instruct, quant finance system prompt
- `llm.yaml.example` - Identical reference copy for users overriding llm.yaml
- `src/rag_server/llm/__init__.py` - Package marker (empty)
- `src/rag_server/llm/config.py` - LLMConfig + LLMSettings pydantic models; get_llm_settings() cached singleton
- `src/rag_server/llm/provider.py` - LLMProvider ABC (complete/stream); create_provider() factory with lazy imports
- `src/rag_server/api/schemas.py` - Added SourceItem, AskRequest, AskResponse schemas

## Decisions Made
- llm.yaml is separate from .env because LLM config changes frequently and YAML is human-friendly for multi-line system prompts; no secrets in llm.yaml (AWS credentials from boto3 credential chain)
- YamlConfigSettingsSource as sole source (no env var merging) — clean separation between app config and LLM config
- Lazy imports in create_provider() to delay heavy openai/boto3 SDK initialization until provider actually constructed
- LLMProvider ABC uses OpenAI role/content message format as canonical — concrete providers convert internally (e.g. BedrockProvider maps to Converse API format)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LLMProvider ABC and create_provider() factory ready for concrete implementations in 04-02 (vLLM/llama.cpp) and 04-03 (Bedrock)
- AskRequest/AskResponse schemas ready for the synthesis endpoint in 04-04
- No blockers

---
*Phase: 04-llm-integration*
*Completed: 2026-02-19*
