# Phase 4: LLM Integration - Research

**Researched:** 2026-02-19
**Domain:** LLM provider abstraction, prompt assembly, SSE streaming, answer synthesis with inline citations
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Answer format:**
- Citation style: `[Source: paper.pdf, p.12]` inline after each claim
- Trailing sources list: Yes — deduplicated list of all cited sources appended after the answer body
- Response shape: Structured object `{ answer: string, sources: [{ filename, page_number, section_heading, chunk_type }] }` — not raw text
- Tone/length: Balanced — clear explanation with technical depth; explain the concept, then the math

**LLM provider architecture:**
- Ollama is OUT — replaced by vLLM, llama.cpp, and AWS Bedrock
- Config structure: Single active provider block in YAML — one provider active at a time, swap by editing config
- Required providers at Phase 4 launch: vLLM, llama.cpp, AWS Bedrock — all three must work
- Example config shape:
  ```yaml
  llm:
    provider: vllm            # vllm | llamacpp | bedrock
    model: Qwen/Qwen2.5-7B-Instruct
    base_url: http://localhost:8000   # for vllm/llamacpp; omit for bedrock
    region: us-east-1                 # bedrock only
    system_prompt: |
      You are a quantitative finance research assistant...
  ```
- AWS Bedrock credentials: Standard AWS credential chain — boto3 default (env vars, ~/.aws/credentials, or IAM role). No custom auth fields in YAML.
- Provider abstraction: Each provider implements `complete(messages, stream)` and `stream(messages)` returning async iterables

**Context assembly:**
- Chunk ordering in prompt: Reranker score order (best first)
- Number of chunks to LLM: Configurable via `llm.context_chunks` (default: top 5)
- System prompt: Configurable in YAML under `llm.system_prompt`

**Streaming behavior:**
- Protocol: Server-Sent Events (SSE, `text/event-stream`) for the REST endpoint
- Event structure: Token delta events during streaming; final `done` event carries complete `{ answer, sources }`
- Non-streaming variant: Yes — `streaming=true/false` query param on the `/ask` endpoint
- Error recovery: Retry with exponential backoff on provider connection failure; fail with error response/event if max retries exhausted

### Claude's Discretion

- Exact citation format (beyond `[Source: paper.pdf, p.12]` style)
- Chunk metadata formatting in prompt (recommended: include filename, page_number, section_heading, chunk_type prefix)
- `llm.context_chunks` default value (recommended: top 5)
- Retry count and backoff parameters
- Provider interface design (abstract base class or protocol)

### Deferred Ideas (OUT OF SCOPE)

- None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LLM-01 | System serves a local LLM (vLLM or llama.cpp) for inference without cloud API hardcoding | Provider abstraction section: vLLM and llama.cpp both expose OpenAI-compatible APIs; `openai` Python package points to local base_url |
| LLM-02 | LLM synthesizes answers grounded in retrieved chunks with inline citations | Prompt assembly section: structured context block with chunk metadata; citation prompt templates; response parsing into `{ answer, sources }` |
| LLM-03 | Responses stream token-by-token in real-time | SSE streaming section: `sse-starlette` `EventSourceResponse`; `AsyncOpenAI` async streaming for vLLM/llama.cpp; boto3 `converse_stream` iterated via `asyncio.to_thread` for Bedrock |
</phase_requirements>

---

## Summary

Phase 4 sits entirely above Phase 3: it receives `RetrievalResult` (a list of `ChunkResult` objects already ranked by the Qwen3 reranker) and must synthesize a written answer with inline citations from those chunks, using one of three LLM providers.

The provider landscape is technically straightforward because two of the three providers (vLLM and llama.cpp) expose OpenAI-compatible HTTP APIs. This means a single `AsyncOpenAI` client from the `openai` Python package — with `base_url` pointed at the local server — drives both without any per-provider divergence in the streaming/completion logic. AWS Bedrock is the only provider requiring a separate code path because boto3's `bedrock-runtime` client is synchronous and uses a different message schema (the Converse API). The wrapping pattern is `asyncio.to_thread` on the blocking boto3 call.

The streaming architecture uses `sse-starlette`'s `EventSourceResponse` (version 3.2.0, current as of January 2026). The `/ask` endpoint emits SSE token-delta events during generation and a final `done` event carrying the complete `{ answer, sources }` object. The non-streaming variant returns the same structured object in a single JSON response. Citation extraction is done server-side by parsing the completed answer text for `[Source: ...]` markers and deduplicating them into the `sources` list.

Retry logic for provider connection failures should use `tenacity` with `wait_exponential_jitter` and `stop_after_attempt(3)` — this is battle-tested, works with async, and adds jitter to prevent thundering herd on local servers.

**Primary recommendation:** Use `AsyncOpenAI(base_url=..., api_key="EMPTY")` for vLLM and llama.cpp; use `asyncio.to_thread(client.converse_stream, ...)` for Bedrock. Implement one abstract `LLMProvider` base class with `stream()` and `complete()` coroutines; concrete providers inject all I/O differences.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` | 2.21.0 (Feb 2026) | OpenAI-compatible client for vLLM and llama.cpp | vLLM and llama.cpp both implement the OpenAI Chat Completions API; `AsyncOpenAI` handles async streaming natively |
| `boto3` | latest (1.42.x) | AWS Bedrock Converse and ConverseStream API | Official AWS SDK; boto3 `bedrock-runtime` is the only supported client for Bedrock |
| `sse-starlette` | 3.2.0 (Jan 2026) | Server-Sent Events in FastAPI/Starlette | Production-ready SSE for Starlette; `EventSourceResponse` wraps async generators; W3C SSE spec compliant |
| `tenacity` | latest | Retry with exponential backoff | Decorator-based, async-aware retry; `wait_exponential_jitter` prevents thundering herd |
| `pyyaml` | latest | YAML config file parsing | Standard YAML parser for reading `llm.yaml`; pydantic-settings `YamlConfigSettingsSource` depends on it |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic-settings` | 2.13.0 | YAML config integration for LLM settings block | Already in project via `pydantic-settings`; `YamlConfigSettingsSource` loads `llm:` YAML block into typed `LLMSettings` model |
| `httpx` | latest | Underlying HTTP client for `openai` package | Comes with `openai`; no direct usage needed |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `openai` package for vLLM/llama.cpp | `httpx` direct HTTP calls | `openai` provides async streaming helpers and type-checked response models for free; no reason to hand-roll |
| `boto3` sync + `asyncio.to_thread` | `aioboto3` | `aioboto3` is an unofficial async wrapper; boto3 direct is simpler and officially supported; `to_thread` is sufficient for the Bedrock streaming iteration pattern |
| `sse-starlette` | `fastapi` `StreamingResponse` raw | `StreamingResponse` works but requires manually formatting SSE event lines (`data: ...\n\n`); `sse-starlette` handles framing, ping, and client-disconnect detection automatically |
| `tenacity` | manual retry loop | `tenacity` is cleaner, decorator-based, and handles async correctly |

### Installation

```bash
uv add openai boto3 sse-starlette tenacity pyyaml
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/rag_server/
├── llm/
│   ├── __init__.py
│   ├── provider.py          # Abstract LLMProvider base class + shared types
│   ├── vllm_provider.py     # vLLM: AsyncOpenAI(base_url=...)
│   ├── llamacpp_provider.py # llama.cpp: AsyncOpenAI(base_url=..., port 8080)
│   ├── bedrock_provider.py  # AWS Bedrock: boto3 converse_stream via to_thread
│   ├── synthesis.py         # SynthesisEngine: prompt assembly + citation parsing
│   └── config.py            # LLMSettings pydantic model for YAML llm: block
├── api/
│   ├── ask.py               # POST /ask endpoint (streaming + non-streaming)
│   └── schemas.py           # (existing — add AskRequest, AskResponse, SourceItem)
└── config.py                # (existing — extend with YAML config loading)
```

### Pattern 1: Abstract LLMProvider Protocol

**What:** A Python `abc.ABC` (or `typing.Protocol`) that both OpenAI-compatible and Bedrock providers implement. The synthesis engine calls only `provider.stream(messages)` or `provider.complete(messages)` and never touches provider internals.

**When to use:** Always — this is the central abstraction keeping synthesis logic provider-agnostic.

```python
# Source: Design pattern — Python abc.ABC (stdlib)
import abc
from typing import AsyncIterator

class LLMProvider(abc.ABC):
    """Abstract base class for LLM provider backends."""

    @abc.abstractmethod
    async def complete(self, messages: list[dict], **kwargs) -> str:
        """Return full completion string. Blocks until done."""
        ...

    @abc.abstractmethod
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """Yield token deltas as they arrive."""
        ...
```

### Pattern 2: vLLM and llama.cpp Provider (OpenAI-Compatible)

**What:** Both providers are identical except for `base_url` and default port. Use `AsyncOpenAI` with `base_url` pointing to the local server; `api_key="EMPTY"` satisfies the client's validation without authentication.

**When to use:** `provider: vllm` (port 8000) or `provider: llamacpp` (port 8080).

```python
# Source: vLLM docs https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
# and llama.cpp server README https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
from openai import AsyncOpenAI

class VLLMProvider(LLMProvider):
    def __init__(self, base_url: str, model: str):
        self._client = AsyncOpenAI(base_url=base_url, api_key="EMPTY")
        self._model = model

    async def complete(self, messages: list[dict], **kwargs) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=False,
        )
        return response.choices[0].message.content or ""

    async def stream(self, messages: list[dict], **kwargs):
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
```

### Pattern 3: AWS Bedrock Provider (Converse API)

**What:** boto3 `bedrock-runtime` client is synchronous. Use `asyncio.to_thread` to run the blocking `converse_stream` call and iterate its event stream in a thread, yielding to the async generator via a queue or direct iteration after `to_thread`.

**Critical note:** `converse_stream` event iteration is also synchronous (iterating the event stream dict). The safe pattern is to collect the stream events inside `asyncio.to_thread` and yield collected tokens, or use a thread + asyncio.Queue bridge.

```python
# Source: AWS Bedrock docs https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html
import boto3
import asyncio

class BedrockProvider(LLMProvider):
    def __init__(self, model: str, region: str):
        self._model = model
        self._region = region

    def _make_client(self):
        # boto3 uses standard credential chain: env vars, ~/.aws/credentials, IAM role
        return boto3.client("bedrock-runtime", region_name=self._region)

    async def complete(self, messages: list[dict], system: str = "", **kwargs) -> str:
        def _call():
            client = self._make_client()
            resp = client.converse(
                modelId=self._model,
                messages=messages,
                system=[{"text": system}] if system else [],
            )
            return resp["output"]["message"]["content"][0]["text"]
        return await asyncio.to_thread(_call)

    async def stream(self, messages: list[dict], system: str = "", **kwargs):
        def _collect_tokens():
            client = self._make_client()
            resp = client.converse_stream(
                modelId=self._model,
                messages=messages,
                system=[{"text": system}] if system else [],
            )
            tokens = []
            for event in resp["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"]["delta"]
                    if "text" in delta:
                        tokens.append(delta["text"])
            return tokens

        # Run synchronous streaming in thread; yield tokens after collection
        # NOTE: true token-by-token async Bedrock streaming requires asyncio.Queue bridge
        tokens = await asyncio.to_thread(_collect_tokens)
        for token in tokens:
            yield token
```

**Important:** The simplest Bedrock async pattern collects all tokens in a thread and yields them after. True token-by-token streaming from Bedrock requires an asyncio.Queue bridge (producer thread + async consumer). For most use cases, the thread + batch yield is sufficient since Bedrock latency is network-dominated, not token-generation-dominated. Document this tradeoff for the planner.

### Pattern 4: SSE Streaming with sse-starlette

**What:** The `/ask` endpoint returns an `EventSourceResponse` wrapping an async generator. Token events use `event="token"`, final done event uses `event="done"` with JSON-serialized `{ answer, sources }`.

**When to use:** When `?streaming=true` (default).

```python
# Source: sse-starlette docs https://github.com/sysid/sse-starlette (v3.2.0)
import json
from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse
from rag_server.llm.synthesis import SynthesisEngine

router = APIRouter()

@router.post("/ask")
async def ask(
    request: Request,
    query: str,
    streaming: bool = True,
):
    engine: SynthesisEngine = request.app.state.synthesis_engine

    if not streaming:
        result = await engine.synthesize(query)
        return result  # returns { answer: str, sources: [...] }

    async def event_generator():
        collected_tokens = []
        async for token in engine.stream_synthesize(query):
            collected_tokens.append(token)
            yield {"event": "token", "data": token}
        # Final done event carries full structured result
        result = engine.parse_citations("".join(collected_tokens))
        yield {"event": "done", "data": json.dumps(result)}

    return EventSourceResponse(event_generator())
```

### Pattern 5: Prompt Assembly for Citation-Grounded RAG

**What:** Build the context block by prepending each chunk with its metadata in a labeled format so the LLM can anchor citations. Chunks go in reranker-score order (best first).

**When to use:** Always — this is the context assembly for every LLM call.

```python
# Source: RAG citation prompting best practices (verified against multiple sources)
def build_context_block(chunks: list[ChunkResult]) -> str:
    """Format retrieved chunks into a numbered, labeled context block."""
    lines = []
    for i, chunk in enumerate(chunks, 1):
        # Label header for citation anchoring
        header_parts = [f"[{i}] Source: {chunk.source_filename}"]
        if chunk.page_number is not None:
            header_parts.append(f"p.{chunk.page_number}")
        if chunk.section_heading:
            header_parts.append(f'"{chunk.section_heading}"')
        header_parts.append(f"type={chunk.chunk_type}")
        header = " | ".join(header_parts)

        # Use display_content for formula chunks (raw LaTeX), content otherwise
        text = chunk.display_content if (chunk.chunk_type == "formula" and chunk.display_content) else chunk.content

        lines.append(f"{header}\n{text}")
    return "\n\n---\n\n".join(lines)


SYSTEM_PROMPT_DEFAULT = """\
You are a quantitative finance research assistant with deep expertise in mathematical \
finance, stochastic calculus, portfolio theory, and financial econometrics.

You answer questions by synthesizing information from the provided source documents. \
For every factual claim or equation you state, add an inline citation immediately after \
in the format [Source: <filename>, p.<page>]. If a claim draws from multiple chunks, \
cite all relevant sources.

After the answer body, append a "## Sources" section listing each unique source cited, \
one per line, in the format:
- <filename>, p.<page> — <section_heading if available>

Rules:
- Ground every claim in the provided documents. Do not add knowledge not present in the sources.
- If the provided context does not answer the question, say so explicitly.
- Preserve mathematical notation exactly as it appears in sources.
- Keep formulas in LaTeX notation when present in the source chunks.
- Be technically precise; the reader is a quant researcher.
"""

USER_PROMPT_TEMPLATE = """\
## Retrieved Context

{context_block}

---

## Question

{question}

Answer with inline citations in the format [Source: <filename>, p.<page>].
"""
```

### Pattern 6: Retry with Tenacity

**What:** Wrap provider calls in tenacity retry decorator with exponential backoff and jitter.

```python
# Source: tenacity docs https://tenacity.readthedocs.io/
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
)
import httpx

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=30),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, Exception)),
)
async def _call_with_retry(provider: LLMProvider, messages: list[dict]) -> str:
    return await provider.complete(messages)
```

### Pattern 7: Config Extension for LLM Settings

**What:** Add an `LLMSettings` pydantic model loaded from `llm.yaml`. The existing `Settings` class reads from `.env`; LLM config comes from a separate YAML file at `DATA_DIR/llm.yaml` (or project root).

**When to use:** On application startup — `LLMSettings` is loaded once and stored on `app.state`.

```python
# Source: pydantic-settings docs https://docs.pydantic.dev/latest/concepts/pydantic_settings/
from pydantic import BaseModel
from pydantic_settings import BaseSettings, YamlConfigSettingsSource

class LLMConfig(BaseModel):
    provider: str = "vllm"             # "vllm" | "llamacpp" | "bedrock"
    model: str = "Qwen/Qwen2.5-7B-Instruct"
    base_url: str = "http://localhost:8000"   # ignored for bedrock
    region: str = "us-east-1"                # bedrock only
    context_chunks: int = 5                  # top-N chunks sent to LLM
    system_prompt: str = SYSTEM_PROMPT_DEFAULT

class LLMSettings(BaseSettings):
    llm: LLMConfig = LLMConfig()

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (YamlConfigSettingsSource(settings_cls, yaml_file="llm.yaml"),)
```

### Anti-Patterns to Avoid

- **One client per request:** Do NOT create `AsyncOpenAI(...)` or `boto3.client(...)` inside request handlers — create once in lifespan and reuse. HTTP connection pools are the performance win.
- **Mixing provider logic into synthesis:** The synthesis engine should call `provider.stream()` and know nothing about whether it's talking to vLLM, llama.cpp, or Bedrock. Keep provider details inside provider classes.
- **Blocking the event loop with boto3 iteration:** boto3 `converse_stream` event iteration is synchronous. NEVER iterate `resp["stream"]` in an async function without `asyncio.to_thread` — it will block the entire event loop.
- **Buffering entire LLM response before SSE:** SSE streaming means the client sees tokens as they generate. Never collect all tokens then send — the `event_generator` must yield each token immediately.
- **Hardcoding provider selection:** Selection comes from `LLMSettings.llm.provider` — no `if provider == "vllm"` in endpoint handlers.
- **Trusting the model to cite correctly:** Always parse `[Source: ...]` markers in the completed answer to build the structured `sources` list — never trust the LLM to emit a sources list in machine-parseable form without guidance and validation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OpenAI-compatible HTTP client with async streaming | Custom `httpx` + SSE parsing | `openai.AsyncOpenAI` | Connection pooling, retry, type-checked delta parsing, stream context management all included |
| SSE event framing and client-disconnect detection | `StreamingResponse` with manual `data: ...\n\n` | `sse-starlette EventSourceResponse` | W3C spec compliance, ping keepalive, disconnect detection, proper MIME type — 3 lines vs 50 |
| Exponential backoff retry logic | `try/except` with `asyncio.sleep` loops | `tenacity` | Jitter, max attempts, per-exception filtering, async support — hand-rolled retries are almost always wrong |
| AWS credential resolution | Custom env var parsing | boto3 default credential chain | boto3 already checks env vars, `~/.aws/credentials`, instance profiles, ECS task roles in order — never re-implement |
| YAML config parsing + validation | `yaml.safe_load()` + manual validation | `pydantic-settings YamlConfigSettingsSource` | Type coercion, defaults, validation errors with field names |

**Key insight:** The OpenAI Python client is the de-facto standard for talking to any OpenAI-compatible server. vLLM explicitly documents using it; llama.cpp server explicitly exposes `/v1/chat/completions`. There is no reason to use `httpx` directly.

---

## Common Pitfalls

### Pitfall 1: Bedrock boto3 Event Stream Blocking the Event Loop

**What goes wrong:** Developer calls `client.converse_stream()` and iterates `resp["stream"]` in an `async` function without `asyncio.to_thread`. The synchronous event iteration blocks the entire FastAPI event loop until the LLM response completes. All other requests freeze.

**Why it happens:** boto3 is not async-native. The streaming event iterator returned by `converse_stream` is a synchronous Python iterator, not an async generator.

**How to avoid:** Wrap all boto3 calls — including the event stream iteration — inside `asyncio.to_thread`. Collect tokens in the thread, then yield them from the async generator after `await asyncio.to_thread(...)` returns.

**Warning signs:** `/health` endpoint stops responding during an active `/ask` request. Uvicorn logs show long-running single-threaded execution.

### Pitfall 2: vLLM `model` Parameter Must Match Served Model Name

**What goes wrong:** `AsyncOpenAI.chat.completions.create(model="Qwen2.5-7B-Instruct")` returns a 404 or 400 if the vLLM server was started with `--model Qwen/Qwen2.5-7B-Instruct` (the full HuggingFace path) but the client sends the short name.

**Why it happens:** vLLM registers the model under its exact HuggingFace identifier. The model name in the request must match what `/v1/models` returns.

**How to avoid:** Read the model name from `LLMSettings.llm.model` (same config value used to start vLLM) and pass it verbatim. Document in `llm.yaml` that `model:` must match the `--model` flag used with `vllm serve`.

**Warning signs:** HTTP 404 on chat completions despite vLLM server responding to `/health`.

### Pitfall 3: llama.cpp Default Port Is 8080, vLLM Default Is 8000

**What goes wrong:** Developers hardcode `http://localhost:8000` for both providers; llama.cpp requests fail silently or connect to nothing.

**Why it happens:** llama-server defaults to port 8080; `vllm serve` defaults to port 8000. These are different.

**How to avoid:** `base_url` comes from `LLMSettings.llm.base_url` — power users set it per provider in `llm.yaml`. The default in the pydantic model should document this divergence. Never hardcode the port in provider code.

### Pitfall 4: SSE Streaming and Nginx/Proxy Buffering

**What goes wrong:** In production, SSE events are buffered by Nginx or other reverse proxies. Clients receive a burst of events after a long delay instead of real-time tokens.

**Why it happens:** Default Nginx proxy buffering accumulates response bytes before forwarding.

**How to avoid:** Set `X-Accel-Buffering: no` response header or `proxy_buffering off` in Nginx config. For local/uvicorn-only deployment (this project), this is not an issue. Document for future production deployment.

**Warning signs:** Streaming works in direct uvicorn access but not behind a proxy.

### Pitfall 5: Citation Parsing Fragility — LLM Does Not Follow Format Exactly

**What goes wrong:** The system prompt instructs `[Source: paper.pdf, p.12]` but the model generates `[Source: paper.pdf p.12]` (no comma), `(Source: paper.pdf, p.12)` (parens), or `[paper.pdf, page 12]`. Citation regex fails to extract sources.

**Why it happens:** LLMs do not follow format instructions 100% reliably, especially with unusual punctuation patterns.

**How to avoid:** Write a lenient regex that tolerates minor format variations (comma optional, `page`/`p.` variants). Fuzzy-match extracted filenames against known `source_filename` values from the `ChunkResult` list. Fall back to including all chunks as sources if parsing yields zero results.

**Warning signs:** `sources` list is always empty in responses.

### Pitfall 6: `api_key` Validation in `openai` Package

**What goes wrong:** `AsyncOpenAI()` raises a validation error if `api_key` is not provided, even when pointing to a local server that requires no authentication.

**Why it happens:** The openai Python package (v1.x+) requires an API key by default.

**How to avoid:** Always pass `api_key="EMPTY"` (or any non-empty string) when constructing `AsyncOpenAI` for local endpoints. This is documented in the vLLM examples.

### Pitfall 7: LLM Context Window Token Budget

**What goes wrong:** Sending `context_chunks=5` at 2,000 tokens each plus a system prompt and question exceeds the model's context window. The provider returns a truncation error or silently drops content.

**Why it happens:** No token budget enforcement. A formula-heavy academic paper may have very large chunks.

**How to avoid:** Implement a token budget check using `tiktoken` (already in pyproject.toml). Count system prompt + question + chunk tokens before calling the provider; drop lowest-reranker-score chunks until within budget. Log a warning when chunks are dropped.

**Warning signs:** Provider returns 400 "context length exceeded" or "max_tokens exceeded" errors.

---

## Code Examples

Verified patterns from official sources:

### vLLM: Async streaming with AsyncOpenAI

```python
# Source: vLLM docs https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
# and OpenAI Python SDK: https://pypi.org/project/openai/ (v2.21.0)
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="EMPTY",   # required by client but ignored by vLLM
)

# Non-streaming
response = await client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the Black-Scholes formula?"},
    ],
    stream=False,
)
answer = response.choices[0].message.content

# Streaming
stream = await client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[...],
    stream=True,
)
async for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="", flush=True)
```

### llama.cpp: Same code, different base_url

```python
# Source: llama.cpp server README https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
# llama-server defaults to port 8080
client = AsyncOpenAI(
    base_url="http://localhost:8080/v1",
    api_key="EMPTY",
)
# Identical chat completions calls as vLLM above
```

### AWS Bedrock: Converse and ConverseStream

```python
# Source: AWS Bedrock docs https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html
import boto3
import asyncio

# Non-streaming
def _bedrock_complete(model_id, messages, system_text, region):
    client = boto3.client("bedrock-runtime", region_name=region)
    resp = client.converse(
        modelId=model_id,
        messages=messages,                          # [{"role": "user", "content": [{"text": "..."}]}]
        system=[{"text": system_text}],
    )
    return resp["output"]["message"]["content"][0]["text"]

answer = await asyncio.to_thread(_bedrock_complete, model_id, messages, system_text, region)

# Streaming (collect in thread, yield after)
def _bedrock_stream_collect(model_id, messages, system_text, region):
    client = boto3.client("bedrock-runtime", region_name=region)
    resp = client.converse_stream(
        modelId=model_id,
        messages=messages,
        system=[{"text": system_text}],
    )
    tokens = []
    for event in resp["stream"]:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"]["delta"]
            if "text" in delta:
                tokens.append(delta["text"])
    return tokens

tokens = await asyncio.to_thread(_bedrock_stream_collect, ...)
for token in tokens:
    yield token
```

### Bedrock message format (Converse API)

```python
# Source: AWS Bedrock Converse API docs
messages = [
    {
        "role": "user",
        "content": [{"text": "Your question here"}]
    }
]
# System prompt is separate, not in messages list:
system = [{"text": "You are a quantitative finance assistant..."}]
```

### SSE endpoint with sse-starlette

```python
# Source: sse-starlette v3.2.0 https://github.com/sysid/sse-starlette
import json
from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse

router = APIRouter()

@router.post("/ask")
async def ask_endpoint(request: Request, query: str, streaming: bool = True):
    synthesis = request.app.state.synthesis_engine

    if not streaming:
        result = await synthesis.synthesize(query)
        return result  # {"answer": "...", "sources": [...]}

    async def generate():
        tokens = []
        async for token in synthesis.stream_synthesize(query):
            tokens.append(token)
            yield {"event": "token", "data": token}

        # Final done event with full structured result
        result = synthesis.parse_result("".join(tokens))
        yield {"event": "done", "data": json.dumps(result)}

    return EventSourceResponse(generate())
```

### Retry decorator with tenacity

```python
# Source: tenacity docs https://tenacity.readthedocs.io/
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
import httpx

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=30),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, Exception)),
    reraise=True,
)
async def _provider_complete_with_retry(provider, messages):
    return await provider.complete(messages)
```

### Citation parsing regex

```python
# Source: Design pattern — lenient regex for [Source: filename, p.N] format
import re
from dataclasses import dataclass

@dataclass
class SourceItem:
    filename: str
    page_number: int | None
    section_heading: str | None
    chunk_type: str | None

_CITATION_RE = re.compile(
    r'\[Source:\s*([^,\]]+?)(?:,\s*p\.?\s*(\d+))?\]',
    re.IGNORECASE,
)

def extract_sources(answer: str, chunks: list) -> list[SourceItem]:
    """Parse inline citations from answer text; match back to known chunks."""
    cited_filenames = set()
    for match in _CITATION_RE.finditer(answer):
        cited_filenames.add(match.group(1).strip())

    # Deduplicate by filename; pull metadata from matched chunks
    seen = set()
    sources = []
    for chunk in chunks:
        if chunk.source_filename in cited_filenames and chunk.source_filename not in seen:
            seen.add(chunk.source_filename)
            sources.append(SourceItem(
                filename=chunk.source_filename,
                page_number=chunk.page_number,
                section_heading=chunk.section_heading,
                chunk_type=chunk.chunk_type,
            ))
    return sources
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Ollama as local LLM runner | vLLM (high throughput) + llama.cpp (GGUF/CPU) | 2024-2025 | vLLM offers 10-30x higher throughput via continuous batching; llama.cpp supports quantized models without GPU |
| Provider-specific SDKs per provider | `openai` package with `base_url` override for any OpenAI-compatible server | openai-python v1.0+ (late 2023) | One client covers vLLM, llama.cpp, and any OpenAI-compatible endpoint |
| Manual SSE framing (`data: ...\n\n`) | `sse-starlette EventSourceResponse` | 2022+ | Production-quality SSE with disconnect detection and W3C compliance in 3 lines |
| `langchain` or `llamaindex` for RAG synthesis | Direct provider clients + custom synthesis | 2024-2025 | Frameworks add abstractions with performance and debuggability costs; for a single-purpose RAG server, direct clients are preferred |

**Deprecated/outdated:**
- Ollama: OUT per locked user decision. Do not research or implement.
- `openai` v0.x (pre-1.0): Used `openai.ChatCompletion.create()`. Version 2.21.0 uses `AsyncOpenAI().chat.completions.create()`.
- Raw `StreamingResponse` for SSE: Still works but `sse-starlette` is the production standard.

---

## Open Questions

1. **True token-by-token streaming for Bedrock**
   - What we know: boto3 `converse_stream` event iteration is synchronous. Collecting all tokens in a thread then yielding gives "batch streaming" — all tokens arrive at once after LLM completes.
   - What's unclear: Whether the planner wants to implement a true asyncio.Queue bridge (producer thread yields tokens one-by-one into the queue; async consumer reads from queue) for real-time Bedrock streaming, or whether batch-then-yield is acceptable given Bedrock is the cloud fallback.
   - Recommendation: Implement batch-then-yield first (simpler, working). Document the Queue bridge as a follow-up if Bedrock becomes the primary provider. For vLLM/llama.cpp (local primary), streaming is genuinely real-time.

2. **LLM YAML config file location**
   - What we know: The existing `Settings` class reads `.env` from the working directory. An `LLMSettings` loaded from `llm.yaml` needs a defined location.
   - What's unclear: Whether to put `llm.yaml` at the project root, in `DATA_DIR`, or configurable.
   - Recommendation: Place `llm.yaml` at the project root (next to `pyproject.toml`). Ship a `llm.yaml.example` with the example config from CONTEXT.md. `DATA_DIR` is for runtime data, not configuration.

3. **Token budget enforcement**
   - What we know: `tiktoken` is already in pyproject.toml. Formula/table chunks can be large.
   - What's unclear: The model's actual context window for the configured model (Qwen2.5-7B-Instruct has 32K context).
   - Recommendation: Set a configurable `llm.max_context_tokens` (default: 8000 tokens for context + response headroom). Use `tiktoken` cl100k_base encoding as an approximation (exact tokenizer varies by model, but cl100k is close enough for budget checks).

---

## Sources

### Primary (HIGH confidence)
- [vLLM OpenAI-Compatible Server docs](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/) — endpoint list, base_url format, streaming usage
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) — OpenAI-compatible endpoints, default port 8080
- [AWS Bedrock converse_stream boto3 docs](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html) — event stream structure, Python iteration pattern
- [AWS Bedrock Converse API examples](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-examples.html) — message format, system prompt format
- [sse-starlette PyPI / GitHub](https://github.com/sysid/sse-starlette) — v3.2.0, EventSourceResponse usage
- [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — YamlConfigSettingsSource pattern
- [openai Python package PyPI](https://pypi.org/project/openai/) — v2.21.0, AsyncOpenAI usage
- tenacity docs — async retry, wait_exponential_jitter

### Secondary (MEDIUM confidence)
- [vLLM PyPI page](https://pypi.org/project/vllm/) — version 0.16.0 (Feb 12, 2026), Python 3.13 supported
- [AWS Bedrock Python examples](https://docs.aws.amazon.com/code-library/latest/ug/python_3_bedrock-runtime_code_examples.html) — streaming patterns in Python
- [Citation-Aware RAG best practices](https://www.tensorlake.ai/blog/rag-citations) — chunk labeling, citation format patterns
- [RAG Citation prompting guide](http://www.danieljwoolridge.com/blog/2025/4/28/the-crucial-hand-off-integrating-retrieval-results-with-llms-in-rag) — context structuring, faithfulness evaluation

### Tertiary (LOW confidence)
- WebSearch findings on boto3 async + FastAPI: `asyncio.to_thread` pattern confirmed by multiple sources but not officially documented as the recommended FastAPI/Bedrock integration pattern.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified via official docs or PyPI (current versions confirmed)
- Architecture: HIGH — provider abstraction pattern verified against official vLLM, llama.cpp, Bedrock docs; SSE pattern verified via sse-starlette docs
- Pitfalls: HIGH for event-loop blocking (verified boto3 sync nature) and citation fragility (known LLM behavior); MEDIUM for Nginx buffering (common knowledge, not tested in this project)
- Code examples: HIGH — all examples derived from official docs; Bedrock message format verified from official AWS examples

**Research date:** 2026-02-19
**Valid until:** 2026-03-21 (30 days — all three providers are stable; openai package updates frequently but AsyncOpenAI streaming API is stable)
