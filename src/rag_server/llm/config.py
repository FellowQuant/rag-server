"""LLM provider configuration loaded from llm.yaml at the project root.

llm.yaml is separate from the main .env-based Settings because:
- LLM config changes frequently (swap provider, tune prompt)
- YAML is human-friendly for multi-line system prompts
- No secrets in llm.yaml (AWS credentials come from the standard boto3 credential chain)

Usage:
    settings = get_llm_settings()
    settings.llm.provider   # "vllm" | "llamacpp" | "bedrock"
    settings.llm.model      # "Qwen/Qwen2.5-7B-Instruct"
    settings.llm.base_url   # "http://localhost:8000/v1"
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, YamlConfigSettingsSource, SettingsConfigDict

# Default system prompt for quantitative finance RAG
_DEFAULT_SYSTEM_PROMPT = """\
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
- Be technically precise; the reader is a quant researcher.\
"""


class LLMConfig(BaseModel):
    """Single active LLM provider configuration block."""

    provider: str = Field(default="vllm", description="vllm | llamacpp | bedrock")
    model: str = Field(
        default="Qwen/Qwen2.5-7B-Instruct",
        description="Model identifier. For vLLM/llama.cpp must match --model flag exactly.",
    )
    base_url: str = Field(
        default="http://localhost:8000/v1",
        description=(
            "OpenAI-compatible base URL. vLLM default: http://localhost:8000/v1. "
            "llama.cpp default: http://localhost:8080/v1. Ignored for bedrock."
        ),
    )
    region: str = Field(
        default="us-east-1",
        description="AWS region for Bedrock. Ignored for vllm/llamacpp.",
    )
    context_chunks: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Top-N reranked chunks to include in LLM context. Token budget enforced separately.",
    )
    max_context_tokens: int = Field(
        default=8000,
        ge=1000,
        description=(
            "Maximum tiktoken cl100k_base tokens for the context block (chunks only). "
            "Chunks are dropped lowest-score-first until under budget. "
            "Set conservatively: total prompt = system_prompt + context + question + response headroom."
        ),
    )
    system_prompt: str = Field(
        default=_DEFAULT_SYSTEM_PROMPT,
        description="System prompt injected at the start of every LLM call. Configurable in llm.yaml.",
    )


class LLMSettings(BaseSettings):
    """Settings loaded from llm.yaml at the project root."""

    model_config = SettingsConfigDict()

    llm: LLMConfig = LLMConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        **kwargs,
    ):
        # Only source: llm.yaml at the project root (next to pyproject.toml)
        yaml_path = Path("llm.yaml")
        return (YamlConfigSettingsSource(settings_cls, yaml_file=yaml_path),)


@lru_cache
def get_llm_settings() -> LLMSettings:
    """Cached singleton. Returns default LLMConfig if llm.yaml not found."""
    return LLMSettings()
