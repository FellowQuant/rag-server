"""llama.cpp provider using the OpenAI-compatible Chat Completions API.

llama-server (llama.cpp) exposes an OpenAI-compatible server at
http://localhost:8080/v1 by default (note: port 8080, NOT 8000).

The implementation is structurally identical to VLLMProvider. It exists as a
separate class to:
1. Communicate the provider type clearly in logs
2. Allow future divergence (llama.cpp-specific parameters like n_predict, grammar)
3. Make the factory function in provider.py unambiguous

Reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from rag_server.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class LlamaCppProvider(LLMProvider):
    """LLM provider for llama.cpp local inference server."""

    def __init__(self, base_url: str, model: str) -> None:
        """
        Args:
            base_url: Full base URL including /v1 suffix.
                      Default for llama-server: http://localhost:8080/v1.
            model: Model identifier (llama.cpp accepts any non-empty string,
                   but should match the loaded model for clarity).
        """
        self._client = AsyncOpenAI(base_url=base_url, api_key="EMPTY")
        self._model = model
        logger.debug(
            "LlamaCppProvider initialized: base_url=%s model=%s", base_url, model
        )

    def _build_messages(self, messages: list[dict], system: str) -> list[dict]:
        if system:
            return [{"role": "system", "content": system}] + messages
        return messages

    async def complete(self, messages: list[dict], system: str = "") -> str:
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
        full_messages = self._build_messages(messages, system)
        stream_resp = await self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            stream=True,
        )
        async for chunk in stream_resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
