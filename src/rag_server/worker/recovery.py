"""Startup recovery for interrupted ingestion jobs."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_server.database.models import Chunk, Document
from rag_server.worker.manager import IngestionJob, WorkerManager

logger = logging.getLogger(__name__)

_RECOVERABLE_STATUSES = ("pending", "indexing")


def _upload_suffix(file_format: str) -> str:
    return ".ipynb" if file_format == "ipynb" else f".{file_format}"


def document_upload_path(data_dir: Path, doc: Document) -> Path:
    """Reconstruct the persisted upload path for a Document row."""
    return data_dir / "uploads" / f"{doc.file_hash}{_upload_suffix(doc.file_format)}"


async def recover_interrupted_documents(
    session: AsyncSession,
    worker_manager: WorkerManager,
    settings,
    qdrant_store,
) -> int:
    """Requeue pending/stale-indexing documents in FIFO created_at order."""
    result = await session.execute(
        select(Document)
        .where(Document.status.in_(_RECOVERABLE_STATUSES))
        .order_by(Document.created_at.asc())
    )
    docs = result.scalars().all()
    recovered_count = 0

    for doc in docs:
        upload_path = document_upload_path(settings.data_dir, doc)

        if doc.status == "indexing":
            await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            await qdrant_store.delete_document(doc.id)
            doc.status = "pending"
            doc.indexed_at = None
            doc.error_msg = "Recovered interrupted indexing job on server startup"
            await session.commit()

        if not upload_path.exists():
            doc.status = "failed"
            doc.error_msg = (
                f"Upload file missing during startup recovery: {upload_path}"
            )
            doc.indexed_at = None
            await session.commit()
            logger.error(
                "Startup recovery failed document %s: missing upload %s",
                doc.id,
                upload_path,
            )
            continue

        job = IngestionJob(
            document_id=doc.id,
            file_path=str(upload_path),
            file_format=doc.file_format,
            original_filename=doc.filename,
            sqlite_url=settings.sqlite_url,
            qdrant_url=settings.qdrant_url,
            qdrant_collection=settings.qdrant_collection,
        )
        worker_manager.enqueue_blocking(job)
        recovered_count += 1
        logger.info(
            "Startup recovery enqueued document %s (%s)",
            doc.id,
            doc.filename,
        )

    return recovered_count
