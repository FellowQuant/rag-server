"""Pydantic request/response models for the documents API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    """Response for POST /documents — returned immediately (202)."""
    id: str
    status: str          # "pending"
    filename: str
    file_size: int       # bytes
    file_format: str     # "pdf" | "tex" | "ipynb"
    created_at: datetime


class DocumentStatusResponse(BaseModel):
    """Response for GET /documents/{id}."""
    id: str
    status: str          # "pending" | "indexing" | "indexed" | "indexed_partial" | "failed"
    filename: str
    file_format: str
    file_size: int
    page_count: int | None
    error_msg: str | None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


class DocumentListItem(BaseModel):
    """Single item in the GET /documents list response."""
    id: str
    status: str
    filename: str
    file_format: str
    file_size: int
    page_count: int | None
    created_at: datetime
    indexed_at: datetime | None


class DocumentListResponse(BaseModel):
    """Response for GET /documents."""
    documents: list[DocumentListItem]
    total: int


# ---------------------------------------------------------------------------
# Ask endpoint schemas (Phase 4)
# ---------------------------------------------------------------------------

class SourceItem(BaseModel):
    """Internal intermediate model used by SynthesisEngine during citation parsing."""
    filename: str
    page_number: int | None = None
    section_heading: str | None = None
    chunk_type: str | None = None


class CitationPage(BaseModel):
    """A single cited page within a document."""
    page_number: int | None = None
    section_heading: str | None = None
    chunk_type: str | None = None


class CitationGroup(BaseModel):
    """All cited pages from a single document, grouped for readability.

    pages are sorted by page_number ascending.
    Groups are ordered by first citation appearance in the answer.
    """
    filename: str
    pages: list[CitationPage]


class AskRequest(BaseModel):
    """Request body for POST /ask."""
    query: str
    top_k: int = 10     # retrieval top_k (before context_chunks LLM limit)


class AskResponse(BaseModel):
    """Non-streaming response for POST /ask?streaming=false.

    Also the payload of the final SSE 'done' event in streaming mode.

    answer    — clean LLM answer text with inline citation markers removed.
    citations — sources grouped by document, pages sorted ascending.
    """
    answer: str
    citations: list[CitationGroup]


# ---------------------------------------------------------------------------
# Retrieve endpoint schemas (Phase 5)
# ---------------------------------------------------------------------------

class RetrieveRequest(BaseModel):
    """Request body for POST /retrieve."""
    query: str
    top_k: int = 10                          # default 10, same as /ask (Claude's discretion)
    document_ids: list[str] | None = None    # optional: scope to specific documents
    min_score: float | None = None           # optional: reranker score threshold (0.0-1.0)


class ChunkResultItem(BaseModel):
    """Serialized ChunkResult for the /retrieve response.

    Maps directly from retrieval.models.ChunkResult dataclass fields.
    All five retrieval scores included per locked CONTEXT.md decision.
    """
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    display_content: str | None
    source_filename: str
    page_number: int | None
    section_heading: str | None
    chunk_type: str
    bm25_score: float
    dense_score: float
    sparse_score: float
    rrf_score: float
    reranker_score: float


class RetrieveResponse(BaseModel):
    """Response for POST /retrieve."""
    query: str
    results: list[ChunkResultItem]
    total_candidates: int
