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
    """A single cited source extracted from the LLM answer.

    Populated by the SynthesisEngine from inline [Source: filename, p.N] markers.
    """
    filename: str
    page_number: int | None = None
    section_heading: str | None = None
    chunk_type: str | None = None


class AskRequest(BaseModel):
    """Request body for POST /ask."""
    query: str
    top_k: int = 10     # retrieval top_k (before context_chunks LLM limit)


class AskResponse(BaseModel):
    """Non-streaming response for POST /ask?streaming=false.

    Also the payload of the final SSE 'done' event in streaming mode.
    """
    answer: str
    sources: list[SourceItem]
