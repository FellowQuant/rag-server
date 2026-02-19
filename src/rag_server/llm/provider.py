"""Abstract LLMProvider base class and provider factory.

All LLM providers implement the same two coroutines:
  - complete(messages, system) -> str   — blocking full completion
  - stream(messages, system)   -> AsyncIterator[str]  — token deltas

The synthesis engine calls only these two methods and is provider-agnostic.
Provider selection and instantiation happens once in the FastAPI lifespan via
create_provider(settings).

Bedrock note: messages use OpenAI role/content format here; BedrockProvider
converts internally to the Converse API format {role, content: [{text: ...}]}.
"""
from __future__ import annotations

import abc
import logging
from typing import AsyncIterator

from rag_server.llm.config import LLMConfig, LLMSettings

logger = logging.getLogger(__name__)


class LLMProvider(abc.ABC):
    """Abstract base class for LLM provider backends.

    All implementations must be safe to call concurrently (multiple FastAPI
    request handlers may call stream() or complete() simultaneously).
    """

    @abc.abstractmethod
    async def complete(self, messages: list[dict], system: str = "") -> str:
        """Return the full completion string.

        Args:
            messages: List of {"role": "user"|"assistant", "content": str} dicts.
                      Do NOT include the system prompt here — pass it via `system`.
            system: System prompt text (empty string to use provider default or none).

        Returns:
            Complete response string.

        Raises:
            Exception: Any provider-level error after retries exhausted.
        """
        ...

    @abc.abstractmethod
    async def stream(self, messages: list[dict], system: str = "") -> AsyncIterator[str]:
        """Yield token deltas as they arrive from the provider.

        Args:
            messages: Same format as complete().
            system: System prompt text.

        Yields:
            str: Individual token delta strings (may be empty, skip those).

        Raises:
            Exception: Any provider-level error after retries exhausted.
        """
        ...


def create_provider(config: LLMConfig) -> LLMProvider:
    """Instantiate and return the configured LLM provider.

    Called once in FastAPI lifespan. The returned provider is stored on
    app.state.llm_provider and reused for all requests.

    Args:
        config: LLMConfig loaded from llm.yaml (via get_llm_settings().llm).

    Returns:
        Concrete LLMProvider instance for the configured provider.

    Raises:
        ValueError: If config.provider is not one of "vllm", "llamacpp", "bedrock".
    """
    # Import concrete providers here to avoid circular imports and delay
    # heavy SDK imports (boto3, openai) until actually needed.
    provider = config.provider.lower()

    if provider == "vllm":
        from rag_server.llm.vllm_provider import VLLMProvider
        logger.info("LLM provider: vLLM at %s (model=%s)", config.base_url, config.model)
        return VLLMProvider(base_url=config.base_url, model=config.model)

    elif provider == "llamacpp":
        from rag_server.llm.llamacpp_provider import LlamaCppProvider
        logger.info("LLM provider: llama.cpp at %s (model=%s)", config.base_url, config.model)
        return LlamaCppProvider(base_url=config.base_url, model=config.model)

    elif provider == "bedrock":
        from rag_server.llm.bedrock_provider import BedrockProvider
        logger.info("LLM provider: AWS Bedrock (model=%s, region=%s)", config.model, config.region)
        return BedrockProvider(model=config.model, region=config.region)

    else:
        raise ValueError(
            f"Unknown LLM provider: {config.provider!r}. "
            "Valid values: 'vllm', 'llamacpp', 'bedrock'."
        )
