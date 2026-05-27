"""vLLM provider using the OpenAI-compatible Chat Completions API.

vLLM exposes a fully OpenAI-compatible server at http://localhost:8000/v1 by default.
We use AsyncOpenAI with base_url pointing to the local vLLM server.

Key notes:
- api_key="EMPTY" is required by the openai client's validation but ignored by vLLM.
- The `model` value MUST match what vLLM was started with (e.g., vllm serve
  --model Qwen/Qwen2.5-7B-Instruct). A mismatch returns HTTP 404.
- The AsyncOpenAI client is reused across requests — it manages an underlying httpx
  connection pool automatically. Create once at startup, NOT per request.
- The `system` argument is prepended as a system message if non-empty.

Reference: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from rag_server.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class VLLMProvider(LLMProvider):
    """LLM provider for vLLM local inference server."""

    def __init__(self, base_url: str, model: str) -> None:
        """
        Args:
            base_url: Full base URL including /v1 suffix
                      (e.g., http://localhost:8000/v1).
            model: Exact model identifier as passed to `vllm serve --model`.
        """
        # api_key="EMPTY" satisfies openai client validation; vLLM ignores it.
        self._client = AsyncOpenAI(base_url=base_url, api_key="EMPTY")
        self._model = model
        logger.debug("VLLMProvider initialized: base_url=%s model=%s", base_url, model)

    def _build_messages(self, messages: list[dict], system: str) -> list[dict]:
        """Prepend system message if provided."""
        if system:
            return [{"role": "system", "content": system}] + messages
        return messages

    async def complete(self, messages: list[dict], system: str = "") -> str:
        """Non-streaming completion. Returns full response string."""
        full_messages = self._build_messages(messages, system)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            stream=False,
        )
        return response.choices[0].message.content or ""

    async def stream(
        self, messages: list[dict], system: str = ""
    ) -> AsyncIterator[str]:
        """Streaming completion. Yields token delta strings."""
        full_messages = self._build_messages(messages, system)
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
