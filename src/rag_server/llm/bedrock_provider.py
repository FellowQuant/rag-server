"""AWS Bedrock provider using the Converse and ConverseStream APIs.

boto3 is synchronous. All calls are wrapped in asyncio.to_thread() to avoid
blocking the FastAPI event loop.

Streaming behavior:
- ConverseStream event iteration is synchronous (iterating resp["stream"] blocks).
- The streaming implementation collects all tokens inside asyncio.to_thread(),
  then yields them from the async generator (batch-then-yield pattern).
- This means client sees all tokens at once after the model finishes, not in real-time.
- For vLLM/llama.cpp (local primary providers), streaming IS real-time.
- Bedrock is the cloud fallback; batch-then-yield is acceptable for v1.

Message format:
- OpenAI: messages[i] = {"role": "user", "content": "text"}
- Bedrock Converse: messages[i] = {"role": "user", "content": [{"text": "text"}]}
- This class converts between formats internally.

Credentials:
- boto3 uses the standard credential chain: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars,
  ~/.aws/credentials file, or IAM instance role. No credentials in llm.yaml.

Reference:
- https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference-examples.html
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from rag_server.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


def _to_bedrock_messages(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format messages to Bedrock Converse API format.

    OpenAI:  {"role": "user", "content": "text"}
    Bedrock: {"role": "user", "content": [{"text": "text"}]}

    System messages are stripped here — callers pass system separately.
    """
    converted = []
    for msg in messages:
        if msg["role"] == "system":
            continue  # system handled separately in Converse API
        converted.append({
            "role": msg["role"],
            "content": [{"text": msg["content"]}],
        })
    return converted


class BedrockProvider(LLMProvider):
    """LLM provider for AWS Bedrock using the Converse API."""

    def __init__(self, model: str, region: str) -> None:
        """
        Args:
            model: Bedrock model ID (e.g., 'anthropic.claude-3-5-sonnet-20241022-v2:0',
                   'amazon.nova-pro-v1:0', 'us.amazon.nova-pro-v1:0').
            region: AWS region (e.g., 'us-east-1').
        """
        self._model = model
        self._region = region
        logger.debug("BedrockProvider initialized: model=%s region=%s", model, region)

    def _make_client(self):
        """Create a boto3 bedrock-runtime client.

        IMPORTANT: boto3 clients are NOT thread-safe when shared across threads.
        Create a fresh client per call inside asyncio.to_thread.
        boto3 automatically uses the standard AWS credential chain.
        """
        import boto3
        return boto3.client("bedrock-runtime", region_name=self._region)

    async def complete(self, messages: list[dict], system: str = "") -> str:
        """Non-streaming completion via Bedrock Converse API."""
        bedrock_messages = _to_bedrock_messages(messages)
        system_block = [{"text": system}] if system else []

        def _call() -> str:
            client = self._make_client()
            resp = client.converse(
                modelId=self._model,
                messages=bedrock_messages,
                system=system_block,
            )
            return resp["output"]["message"]["content"][0]["text"]

        return await asyncio.to_thread(_call)

    async def stream(self, messages: list[dict], system: str = "") -> AsyncIterator[str]:
        """Streaming completion via Bedrock ConverseStream API.

        IMPORTANT: boto3 event stream iteration is synchronous. Entire collection
        runs inside asyncio.to_thread (batch-then-yield pattern). Tokens are yielded
        after collection completes — not in real-time. Acceptable for cloud fallback.
        """
        bedrock_messages = _to_bedrock_messages(messages)
        system_block = [{"text": system}] if system else []

        def _collect_tokens() -> list[str]:
            """Run synchronous Bedrock streaming inside a thread."""
            client = self._make_client()
            resp = client.converse_stream(
                modelId=self._model,
                messages=bedrock_messages,
                system=system_block,
            )
            tokens: list[str] = []
            for event in resp["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        tokens.append(text)
            return tokens

        tokens = await asyncio.to_thread(_collect_tokens)
        logger.debug("BedrockProvider: collected %d token segments", len(tokens))
        for token in tokens:
            yield token
