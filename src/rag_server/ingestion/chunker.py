"""Shared data types and chunking utilities for the ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

# cl100k_base is close enough to XLM-RoBERTa (BGE-M3's tokenizer) for token
# budget purposes. BGE-M3 max_length=512 tokens.
_enc = tiktoken.get_encoding("cl100k_base")

MAX_TOKENS = 512
OVERLAP_TOKENS = 64


@dataclass
class ParsedChunk:
    """A single content unit produced by a document parser.

    Fields mirror the Chunk SQLAlchemy model (models.py) plus a `language`
    field for code chunks. chunk_index is assigned by the parser after all
    chunks are collected.
    """

    chunk_type: str  # "text" | "formula" | "table" | "code"
    content: str  # text sent to the embedding model
    display_content: str | None = None  # raw LaTeX for formulas; code source for code
    page_number: int | None = None
    section_heading: str | None = None
    chunk_index: int = 0
    language: str | None = None  # populated for code chunks only


@dataclass
class ParsedChunkBatch:
    """A bounded group of parsed chunks emitted by a parser."""

    chunks: list[ParsedChunk]
    is_partial: bool = False
    page_count: int | None = None


def split_text_tokens(
    text: str,
    max_tokens: int = MAX_TOKENS,
    overlap: int = OVERLAP_TOKENS,
) -> list[str]:
    """Split text into token-bounded segments with overlap.

    Uses tiktoken cl100k_base encoding as a token counter for BGE-M3.
    Returns the original text in a list if it fits within max_tokens.
    """
    tokens = _enc.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    segments: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        segments.append(_enc.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += max_tokens - overlap
    return segments


def enrich_formula_content(formula_latex: str, preceding_paragraph: str) -> str:
    """Compose embedding text for a formula chunk.

    The embedding model sees surrounding paragraph + formula LaTeX, providing
    semantic anchoring. display_content stores only raw LaTeX for rendering.

    INGEST-05: Formula chunks enriched with surrounding paragraph context.
    """
    preceding = preceding_paragraph.strip()
    if preceding:
        return f"{preceding}\n\n{formula_latex}"
    return formula_latex
