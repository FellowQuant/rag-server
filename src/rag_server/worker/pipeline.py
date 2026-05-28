"""Ingestion pipeline: parse -> embed -> persist for a single document job.

Called by worker_main() for each IngestionJob. Uses synchronous SQLAlchemy
(not async) because the worker process has no asyncio event loop.

Rollback strategy on failure:
  1. Delete SQLite Chunk rows via Document CASCADE (deleting Document cascades
     to all its Chunk rows per models.py cascade="all, delete-orphan")
     -- but we do NOT delete the Document itself; we update its status to "failed"
     so the caller can still poll GET /documents/{id}
  2. Delete Qdrant points filtered by document_id
  3. Set Document.status = "failed" / "indexed_partial"

Status flow: pending -> indexing -> indexed | indexed_partial | failed

Design notes:
  - Chunk UUIDs are generated as a separate parallel list (chunk_ids) and
    passed to _upsert_chunks_qdrant(). The ParsedChunk dataclass is NEVER
    monkey-patched with extra attributes -- doing so would bypass the dataclass
    contract and make the code fragile.
  - DocumentConverter is constructed ONCE in worker_main() and passed to
    run_pipeline() as an argument. Constructing it per-document is extremely
    expensive (~10-20s) due to ML model loading.
"""

from __future__ import annotations

import gc
import logging
import multiprocessing
import os
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from rag_server.config import get_settings
from rag_server.database.models import Chunk, Document
from rag_server.ingestion.chunker import ParsedChunk, ParsedChunkBatch
from rag_server.ingestion.embedder import Embedder
from rag_server.worker.resource_guard import ResourceGuard, ResourceLimitExceeded

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)

# Qdrant upsert batch size. 100 points/batch balances throughput and memory.
QDRANT_BATCH_SIZE = 100


def _log_mem(label: str) -> None:
    """Log current process RSS in MB for memory profiling."""
    rss_kb = 0
    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break
    except Exception:
        pass
    logger.info("MEM [%s]: RSS=%.0f MB", label, rss_kb / 1024)


def _get_sync_engine(async_sqlite_url: str):
    """Convert aiosqlite URL to sync SQLite URL for worker process.

    FastAPI uses sqlite+aiosqlite:///path; worker needs sqlite:///path.
    """
    sync_url = async_sqlite_url.replace("sqlite+aiosqlite://", "sqlite://")
    return create_engine(sync_url)


def _dispatch_parser(
    file_format: str,
    file_path: str,
    converter: "DocumentConverter | None" = None,
) -> tuple[list[ParsedChunk], bool]:
    """Route to the correct parser based on file format.

    Returns:
        (chunks, is_partial) -- chunks is the parsed chunk list; is_partial
        is True if the parse was only partially successful (PDF partial
        conversion). For non-PDF formats, is_partial is always False.

    Args:
        converter: Pre-built DocumentConverter from worker_main(). Must be
                   provided when file_format == 'pdf'. Reusing the same
                   converter avoids reloading Docling ML models (~10-20s each).
    """
    if file_format == "pdf":
        from rag_server.ingestion.parsers.pdf_parser import parse_pdf

        if converter is None:
            from rag_server.ingestion.parsers.pdf_parser import make_converter

            converter = make_converter(use_gpu=True)

        _log_mem("before-convert")
        chunks, is_partial = parse_pdf(file_path, converter)
        _log_mem("after-convert")

        # Reclaim Docling per-document memory (page backends, image caches).
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass
        _log_mem("after-convert-gc")

        return chunks, is_partial

    elif file_format == "tex":
        from rag_server.ingestion.parsers.latex_parser import parse_latex

        return parse_latex(file_path), False

    elif file_format == "ipynb":
        from rag_server.ingestion.parsers.jupyter_parser import parse_jupyter

        return parse_jupyter(file_path), False

    elif file_format == "epub":
        from rag_server.ingestion.parsers.epub_parser import parse_epub

        return parse_epub(file_path)

    else:
        raise ValueError(f"Unsupported file_format: {file_format!r}")


def _dispatch_parser_batches(
    file_format: str,
    file_path: str,
    converter: "DocumentConverter | None" = None,
):
    settings = get_settings()
    if file_format == "pdf":
        from rag_server.ingestion.parsers.pdf_parser import iter_pdf_batches

        if converter is None:
            from rag_server.ingestion.parsers.pdf_parser import make_converter

            converter = make_converter(use_gpu=True)

        _log_mem("before-convert")
        for batch in iter_pdf_batches(
            file_path,
            converter,
            pages_per_batch=settings.indexer_pdf_pages_per_batch,
            large_file_bytes=settings.indexer_large_file_bytes,
        ):
            yield batch
            gc.collect()
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:
                pass
            _log_mem("after-convert-batch-gc")
        return

    if file_format == "epub":
        from rag_server.ingestion.parsers.epub_parser import iter_epub_batches

        yield from iter_epub_batches(file_path)
        return

    chunks, is_partial = _dispatch_parser(file_format, file_path, converter)
    page_numbers = [c.page_number for c in chunks if c.page_number is not None]
    yield ParsedChunkBatch(
        chunks=chunks,
        is_partial=is_partial,
        page_count=max(page_numbers) if page_numbers else None,
    )


def _upsert_chunk_batch_qdrant(
    document_id: str,
    chunks: list[ParsedChunk],
    chunk_ids: list[str],
    embedder: Embedder,
    qdrant_url: str,
    collection: str,
) -> None:
    """Embed chunks and upsert to Qdrant using synchronous QdrantClient.

    The worker process has no asyncio event loop, so we use the sync
    QdrantClient (not AsyncQdrantClient) here.

    Args:
        document_id: UUID of the owning document.
        chunks: ParsedChunk list from the parser (parallel to chunk_ids).
        chunk_ids: Pre-generated UUID strings for each chunk, in the same
                   order as chunks. chunk_ids[i] is the SQLite id for chunks[i].
                   Passed as a separate parallel structure -- ParsedChunk is
                   never monkey-patched with extra attributes.
        embedder: Pre-loaded Embedder instance from worker_main().
        qdrant_url: Full http://host:port URL for Qdrant.
        collection: Qdrant collection name.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct, SparseVector

    embedding_results = embedder.embed_chunks(chunks)
    client = QdrantClient(url=qdrant_url)

    try:
        for batch_start in range(0, len(embedding_results), QDRANT_BATCH_SIZE):
            batch_emb = embedding_results[batch_start : batch_start + QDRANT_BATCH_SIZE]
            batch_chunks = chunks[batch_start : batch_start + QDRANT_BATCH_SIZE]
            batch_ids = chunk_ids[batch_start : batch_start + QDRANT_BATCH_SIZE]
            points = []
            for emb, chunk, chunk_id in zip(batch_emb, batch_chunks, batch_ids):
                # chunk_id is the same UUID written to SQLite so cross-store
                # lookup works: Qdrant point id == SQLite chunks.id
                point = PointStruct(
                    id=chunk_id,
                    vector={
                        "dense": emb.dense_vector,
                        "sparse": SparseVector(
                            indices=emb.sparse_indices,
                            values=emb.sparse_values,
                        ),
                    },
                    payload={
                        "document_id": document_id,
                        "chunk_id": chunk_id,
                        "chunk_type": chunk.chunk_type,
                        "page_number": chunk.page_number,
                        "section_heading": chunk.section_heading,
                        "chunk_index": chunk.chunk_index,
                    },
                )
                points.append(point)
            client.upsert(collection_name=collection, points=points, wait=True)
    finally:
        client.close()


def _upsert_chunks_qdrant(
    document_id: str,
    chunks: list[ParsedChunk],
    chunk_ids: list[str],
    embedder: Embedder,
    qdrant_url: str,
    collection: str,
) -> None:
    _upsert_chunk_batch_qdrant(
        document_id=document_id,
        chunks=chunks,
        chunk_ids=chunk_ids,
        embedder=embedder,
        qdrant_url=qdrant_url,
        collection=collection,
    )


def _delete_qdrant_document(document_id: str, qdrant_url: str, collection: str) -> None:
    """Delete all Qdrant points for a document (rollback helper)."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = QdrantClient(url=qdrant_url)
    try:
        client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            ),
            wait=True,
        )
    finally:
        client.close()


def _delete_sqlite_chunks(document_id: str, engine) -> None:
    """Delete all Chunk rows for a document (rollback helper).

    Note: We delete Chunk rows explicitly rather than relying on CASCADE
    because we want to keep the Document row (to preserve failed status).
    """
    with Session(engine) as session:
        session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        session.commit()


def _set_document_status(
    document_id: str,
    status: str,
    engine,
    error_msg: str | None = None,
) -> None:
    """Update Document.status and optionally Document.error_msg."""
    from datetime import datetime, timezone

    with Session(engine) as session:
        doc = session.get(Document, document_id)
        if doc is None:
            logger.error(
                "Document %s not found in SQLite during status update", document_id
            )
            return
        doc.status = status
        doc.error_msg = error_msg
        doc.updated_at = datetime.now(timezone.utc)
        if status in ("indexed", "indexed_partial"):
            doc.indexed_at = datetime.now(timezone.utc)
        elif status in ("pending", "failed"):
            doc.indexed_at = None
        session.commit()


def _rollback_partial_index(document_id: str, job, engine) -> None:
    """Remove partial SQLite/Qdrant data written before a pipeline failure."""
    try:
        _delete_sqlite_chunks(document_id, engine)
    except Exception:
        logger.exception("Pipeline: rollback SQLite chunks failed for %s", document_id)

    try:
        _delete_qdrant_document(document_id, job.qdrant_url, job.qdrant_collection)
    except Exception:
        logger.exception("Pipeline: rollback Qdrant delete failed for %s", document_id)


def run_pipeline(
    job,
    converter: "DocumentConverter | None",
    embedder: Embedder,
    result_queue: multiprocessing.Queue | None = None,
    resource_guard: ResourceGuard | None = None,
) -> None:
    """Execute the full ingestion pipeline for one IngestionJob.

    Args:
        job: IngestionJob dataclass with document_id, file_path, file_format,
             original_filename, sqlite_url, qdrant_url, qdrant_collection.
        converter: Pre-built Docling DocumentConverter from worker_main().
                   Loaded once at worker startup to avoid per-document ~10-20s
                   model load cost. Pass None only in tests (falls back to
                   constructing on demand -- slow).
        embedder: Pre-loaded Embedder instance from worker_main().
        result_queue: Optional queue to send signals back to the FastAPI
                      process (e.g., BM25 rebuild needed after indexing).
    """
    document_id = job.document_id
    engine = _get_sync_engine(job.sqlite_url)
    if resource_guard is None:
        resource_guard = ResourceGuard.from_settings(get_settings())

    logger.info(
        "Pipeline: starting job for document %s (%s)", document_id, job.file_format
    )
    _log_mem("pipeline-start")

    # Step 1: Mark as indexing.
    _set_document_status(document_id, "indexing", engine)

    try:
        total_chunks = 0
        next_chunk_index = 0
        is_partial = False
        max_page_count: int | None = None

        resource_guard.checkpoint("before-parse-batch")
        for batch in _dispatch_parser_batches(
            job.file_format, job.file_path, converter
        ):
            resource_guard.checkpoint("after-parse")
            parsed_chunks = batch.chunks
            if batch.is_partial:
                is_partial = True
            if batch.page_count is not None:
                max_page_count = max(max_page_count or 0, batch.page_count)

            for chunk in parsed_chunks:
                chunk.chunk_index = next_chunk_index
                next_chunk_index += 1

            if not parsed_chunks:
                resource_guard.checkpoint("before-parse-batch")
                continue

            # Generate chunk UUIDs as a parallel list.
            # IMPORTANT: We do NOT monkey-patch ParsedChunk instances with extra
            # attributes. The dataclass contract must not be bypassed. Instead we
            # maintain chunk_ids as a parallel list in the same order as parsed_chunks.
            chunk_ids: list[str] = [str(uuid.uuid4()) for _ in parsed_chunks]

            # Persist Chunk rows to SQLite using the pre-generated IDs.
            with Session(engine) as session:
                for chunk, chunk_id in zip(parsed_chunks, chunk_ids):
                    row = Chunk(
                        id=chunk_id,
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        page_number=chunk.page_number,
                        section_heading=chunk.section_heading,
                        chunk_type=chunk.chunk_type,
                        content=chunk.content,
                        display_content=chunk.display_content,
                    )
                    session.add(row)
                session.commit()
            total_chunks += len(parsed_chunks)
            logger.info(
                "Pipeline: %d chunks written to SQLite for %s",
                len(parsed_chunks),
                document_id,
            )
            resource_guard.checkpoint("after-sqlite-write")

            # Embed chunks and upsert to Qdrant.
            # chunk_ids is passed as a parallel structure -- no monkey-patching.
            _upsert_chunk_batch_qdrant(
                document_id=document_id,
                chunks=parsed_chunks,
                chunk_ids=chunk_ids,
                embedder=embedder,
                qdrant_url=job.qdrant_url,
                collection=job.qdrant_collection,
            )
            logger.info("Pipeline: Qdrant upsert complete for %s", document_id)
            resource_guard.checkpoint("after-qdrant-upsert")
            gc.collect()
            resource_guard.checkpoint("before-parse-batch")

        _log_mem("after-parse")
        if total_chunks == 0:
            logger.warning("Pipeline: parser returned 0 chunks for %s", document_id)

        with Session(engine) as session:
            doc = session.get(Document, document_id)
            if doc and max_page_count is not None:
                doc.page_count = max_page_count
            session.commit()

        # Step 7: Mark indexed or indexed_partial.
        # LOCKED DECISION: Page-level failures -> status "indexed_partial";
        # store failed page info in error_msg. Successfully parsed pages are
        # still indexed so the document is partially usable.
        if is_partial:
            error_msg = (
                "Partial index: some pages failed to parse (Docling PARTIAL_SUCCESS). "
                "Successfully parsed pages are available for search."
            )
            _set_document_status(
                document_id, "indexed_partial", engine, error_msg=error_msg
            )
            logger.warning(
                "Pipeline: document %s indexed_partial (%d chunks)",
                document_id,
                total_chunks,
            )
        else:
            _set_document_status(document_id, "indexed", engine)
            logger.info(
                "Pipeline: document %s indexed successfully (%d chunks)",
                document_id,
                total_chunks,
            )

        # Signal FastAPI to rebuild BM25 index with newly indexed chunks.
        # Sent for both "indexed" and "indexed_partial" -- both statuses mean
        # the document's chunks are in SQLite and should be included in BM25.
        if result_queue is not None:
            try:
                result_queue.put_nowait({"type": "indexed", "document_id": document_id})
            except Exception:
                logger.warning(
                    "Pipeline: failed to send BM25 update signal for %s (queue full?)",
                    document_id,
                )

        _log_mem("pipeline-end")
        gc.collect()
        _log_mem("after-gc")

    except ResourceLimitExceeded as exc:
        logger.exception("Pipeline: resource exhaustion on document %s", document_id)
        _rollback_partial_index(document_id, job, engine)

        retry_limit = get_settings().indexer_resource_retry_limit
        attempts = getattr(job, "resource_attempts", 0)
        if attempts < retry_limit:
            next_attempt = attempts + 1
            _set_document_status(
                document_id,
                "pending",
                engine,
                error_msg=(
                    f"{exc}; retry {next_attempt}/{retry_limit} queued after "
                    "worker restart"
                ),
            )
        else:
            _set_document_status(document_id, "failed", engine, error_msg=str(exc))
        raise

    except Exception as exc:
        logger.exception("Pipeline: failure on document %s", document_id)

        # Rollback: remove any partial data so failure state is clean.
        _rollback_partial_index(document_id, job, engine)
        _set_document_status(document_id, "failed", engine, error_msg=str(exc))
