"""Result dataclasses for the retrieval pipeline.

These are the output types of RetrievalEngine.search(). All fields are
populated at retrieval time from SQLite + Qdrant + BM25 + Reranker.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChunkResult:
    """A single retrieved and reranked chunk with full citation metadata and scores.

    All score fields are included for debugging and tuning. Callers (LLM
    consumers) use ranked order, not raw scores.
    """

    # Identity
    chunk_id: str  # SQLite chunks.id (== Qdrant point ID)
    document_id: str  # SQLite documents.id
    chunk_index: int  # Position within document (0-based)

    # Content — fetched from SQLite (NOT stored in Qdrant)
    content: str  # Full chunk text (embedding text; never truncated)
    display_content: str | None  # Raw LaTeX for formula chunks; None for others

    # Citation metadata
    source_filename: str  # documents.filename (original uploaded filename)
    page_number: (
        int | None
    )  # Page in source document; None for notebooks/LaTeX sections
    section_heading: str | None  # Section heading above this chunk; None if not parsed
    chunk_type: str  # "text" | "formula" | "table" | "code"

    # Scores — all five retrieval legs
    bm25_score: float = 0.0  # BM25Okapi score (raw, not normalized)
    dense_score: float = 0.0  # BGE-M3 cosine similarity (0-1)
    sparse_score: float = 0.0  # BGE-M3 sparse dot product score
    rrf_score: float = 0.0  # Reciprocal Rank Fusion fused score
    reranker_score: float = 0.0  # Qwen3-Reranker relevance probability (0-1)


@dataclass
class RetrievalResult:
    """Full result set from one RetrievalEngine.search() call."""

    query: str  # Original query string
    results: list[ChunkResult]  # Ranked list (best first)
    total_candidates: int  # Candidate pool size before top_k cutoff
