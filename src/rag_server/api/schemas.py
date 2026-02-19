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
