"""REST endpoints for document lifecycle management.

POST   /documents          — upload file, enqueue ingestion, return 202
GET    /documents/{id}     — poll status and metadata
GET    /documents          — list all documents
DELETE /documents/{id}     — delete document (file + SQLite + Qdrant)

Session commit notes:
  get_db() in database/engine.py calls `await session.commit()` automatically
  after the route handler yields (see engine.py lines 36-41). Explicit
  `await db.commit()` calls below are defensive — they make the commit
  point unambiguous regardless of session context changes in the future,
  and ensure the Document row is visible to the worker before enqueue().
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_server.api.schemas import (
    DocumentListItem,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from rag_server.config import get_settings
from rag_server.database.engine import get_db
from rag_server.database.models import Document
from rag_server.worker.manager import IngestionJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".tex": "tex",
    ".ipynb": "ipynb",
}


def _get_uploads_dir() -> Path:
    settings = get_settings()
    uploads = settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    return uploads


@router.post("", status_code=202, response_model=DocumentUploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload a document for ingestion.

    Reads file bytes, computes SHA-256 hash for deduplication, saves to
    DATA_DIR/uploads/, creates Document record (status=pending), commits
    the record so the worker can find it, enqueues IngestionJob, and returns
    immediately with 202.

    Returns 409 if the file hash already exists.
    Returns 415 if the file extension is not .pdf, .tex, or .ipynb.

    Note on commit: get_db() auto-commits on exit, but we call db.commit()
    explicitly here before enqueue() to guarantee the Document row is
    durable and visible to the worker process before the job is dispatched.
    """
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: .pdf, .tex, .ipynb",
        )

    contents = await file.read()
    file_hash = hashlib.sha256(contents).hexdigest()
    file_size = len(contents)
    file_format = ALLOWED_EXTENSIONS[suffix]

    # Check for duplicate file hash.
    existing = await db.execute(
        select(Document).where(Document.file_hash == file_hash)
    )
    existing_doc = existing.scalar_one_or_none()
    if existing_doc is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Document already exists with id={existing_doc.id} status={existing_doc.status}",
        )

    # Save file to disk using hash as filename (enables deduplication).
    uploads_dir = _get_uploads_dir()
    dest = uploads_dir / f"{file_hash}{suffix}"
    if not dest.exists():
        async with aiofiles.open(dest, "wb") as f:
            await f.write(contents)

    # Create Document record.
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        filename=filename,
        file_format=file_format,
        file_hash=file_hash,
        file_size=file_size,
        status="pending",
    )
    db.add(doc)
    await db.flush()    # assigns created_at/updated_at via server defaults
    await db.commit()   # make row durable before enqueue() — worker must see it

    # Enqueue ingestion job.
    settings = get_settings()
    job = IngestionJob(
        document_id=doc_id,
        file_path=str(dest),
        file_format=file_format,
        original_filename=filename,
        sqlite_url=settings.sqlite_url,
        qdrant_url=settings.qdrant_url,
        qdrant_collection=settings.qdrant_collection,
    )

    try:
        worker_manager = request.app.state.worker_manager
        worker_manager.enqueue(job)
    except Exception as exc:
        logger.error("Failed to enqueue job for document %s: %s", doc_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Worker queue is full or unavailable. Try again shortly.",
        )

    logger.info("Uploaded %s → doc_id=%s, hash=%s", filename, doc_id, file_hash[:8])

    return DocumentUploadResponse(
        id=doc.id,
        status=doc.status,
        filename=doc.filename,
        file_size=doc.file_size,
        file_format=doc.file_format,
        created_at=doc.created_at,
    )


@router.get("/{document_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Return current status and metadata for a document."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    return DocumentStatusResponse(
        id=doc.id,
        status=doc.status,
        filename=doc.filename,
        file_format=doc.file_format,
        file_size=doc.file_size,
        page_count=doc.page_count,
        error_msg=doc.error_msg,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        indexed_at=getattr(doc, "indexed_at", None),
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """Return all documents with status and basic metadata."""
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    docs = result.scalars().all()

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                id=d.id,
                status=d.status,
                filename=d.filename,
                file_format=d.file_format,
                file_size=d.file_size,
                page_count=d.page_count,
                created_at=d.created_at,
                indexed_at=getattr(d, "indexed_at", None),
            )
            for d in docs
        ],
        total=len(docs),
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document and all associated data.

    Removes:
    1. Uploaded file from DATA_DIR/uploads/
    2. SQLite Document record (CASCADE deletes all Chunk rows)
    3. Qdrant vectors filtered by document_id

    Ordering note: SQLite delete is committed before Qdrant delete. If the
    Qdrant delete subsequently fails, vectors become orphaned — this is
    acceptable because SQLite is the authoritative store. Orphaned vectors
    will not appear in search results once the document_id payload is absent
    from active documents.

    Note on commit: get_db() auto-commits on exit, but we call db.commit()
    explicitly here before the Qdrant delete to ensure the SQLite record is
    durably removed regardless of what happens in the Qdrant call.
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    # Delete file from disk.
    settings = get_settings()
    uploads_dir = settings.data_dir / "uploads"
    suffix = f".{doc.file_format}" if doc.file_format != "ipynb" else ".ipynb"
    # Reconstruct filename from hash (saved as {hash}{ext}).
    file_path = uploads_dir / f"{doc.file_hash}{suffix}"
    if file_path.exists():
        file_path.unlink()
        logger.info("Deleted file %s for document %s", file_path, document_id)

    # Delete from SQLite (CASCADE removes Chunk rows automatically).
    await db.delete(doc)
    await db.commit()   # commit SQLite delete before Qdrant call
                        # If Qdrant delete fails, vectors are orphaned but
                        # SQLite (authoritative) no longer has the document.

    # Delete Qdrant vectors.
    qdrant_store = request.app.state.qdrant_store
    await qdrant_store.delete_document(document_id)

    logger.info("Deleted document %s (%s)", document_id, doc.filename)
