# Phase 4: LLM Integration - Context

**Gathered:** 2026-02-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Given a user question and a set of retrieved + reranked chunks (from Phase 3 RetrievalEngine), a local or cloud LLM synthesizes a written answer with inline citations and a trailing sources list. The integration layer handles provider abstraction, prompt assembly, streaming, and error recovery. No new retrieval logic — this phase sits on top of Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Answer format
- **Citation style:** `[Source: paper.pdf, p.12]` inline after each claim — matches ROADMAP example and is parseable by downstream consumers (Claude's Discretion for exact formatting)
- **Trailing sources list:** Yes — deduplicated list of all cited sources appended after the answer body
- **Response shape:** Structured object `{ answer: string, sources: [{ filename, page_number, section_heading, chunk_type }] }` — not raw text; consumers can render citations separately
- **Tone/length:** Balanced — clear explanation with technical depth; explain the concept, then the math

### LLM provider architecture
- **Ollama is OUT** — replaced by vLLM, llama.cpp, and AWS Bedrock. ROADMAP entry "Ollama (v1) → vLLM (v2)" should be updated to reflect this decision.
- **Config structure:** Single active provider block in YAML — one provider active at a time, swap by editing config
- **Required providers at Phase 4 launch:** vLLM, llama.cpp, AWS Bedrock — all three must work
- **Example config shape:**
  ```yaml
  llm:
    provider: vllm            # vllm | llamacpp | bedrock
    model: Qwen/Qwen2.5-7B-Instruct
    base_url: http://localhost:8000   # for vllm/llamacpp; omit for bedrock
    region: us-east-1                 # bedrock only
    system_prompt: |
      You are a quantitative finance research assistant...
  ```
- **AWS Bedrock credentials:** Standard AWS credential chain — boto3 default (env vars AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN, ~/.aws/credentials, or IAM role). No custom auth fields in YAML.
- **Provider abstraction:** Claude designs the provider interface (abstract base class or protocol) — each provider implements `complete(messages, stream)` and `stream(messages)` returning async iterables

### Context assembly
- **Chunk ordering in prompt:** Reranker score order (best first) — most relevant evidence presented first to the model
- **Chunk metadata in prompt:** Claude's Discretion — recommended: include filename, page_number, section_heading, chunk_type prefix before each chunk so the model can reason about formula vs prose chunks
- **Number of chunks to LLM:** Claude's Discretion — recommended: configurable via `llm.context_chunks` (default: top 5) separate from retrieval's top_k; token budget cap is the practical constraint
- **System prompt:** Configurable in YAML under `llm.system_prompt` — power users can tune without code changes; a well-crafted default is provided in the example config

### Streaming behavior
- **Protocol:** Claude's Discretion — recommended Server-Sent Events (SSE, `text/event-stream`) for the REST endpoint; works with any HTTP client and is the standard for streaming AI responses
- **Event structure:** Token delta events during streaming; final `done` event carries the complete structured object `{ answer, sources }` — sources sent last so streaming starts immediately
- **Non-streaming variant:** Yes — `streaming=true/false` query param on the `/ask` endpoint; non-streaming returns the complete structured object at once (useful for MCP consumers that don't benefit from streaming)
- **Error recovery:** Retry with exponential backoff on provider connection failure; fail with error response/event if max retries are exhausted; Claude decides retry count and backoff parameters

</decisions>

<specifics>
## Specific Ideas

- vLLM and llama.cpp preferred over Ollama for performance — both expose OpenAI-compatible APIs which simplifies the provider abstraction significantly
- AWS Bedrock is the cloud fallback — standard boto3 credential chain keeps it production-safe without hardcoded secrets
- The provider abstraction should be thin enough that adding a new provider (e.g., OpenAI-compatible endpoint) requires only implementing one interface, not touching the synthesis logic
- System prompt should be tuned for quant finance RAG: instruct the model to ground answers in the provided sources, cite explicitly, and preserve mathematical notation

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-llm-integration*
*Context gathered: 2026-02-19*
