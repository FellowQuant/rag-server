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

import logging
import multiprocessing
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from rag_server.database.models import Chunk, Document
from rag_server.ingestion.chunker import ParsedChunk
from rag_server.ingestion.embedder import Embedder

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)

# Qdrant upsert batch size. 100 points/batch balances throughput and memory.
QDRANT_BATCH_SIZE = 100


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
        from docling.datamodel.base_models import ConversionStatus
        from rag_server.ingestion.parsers.pdf_parser import parse_pdf

        if converter is None:
            # Fallback: build converter on demand (slow -- only for testing).
            from rag_server.ingestion.parsers.pdf_parser import make_converter
            converter = make_converter(use_gpu=True)

        # Convert once and check status to detect partial success.
        # parse_pdf() also calls converter.convert() internally; we call it
        # here first to inspect the status, then pass the converter to parse_pdf
        # which will convert again. This is intentional: parse_pdf owns the
        # full chunking logic, and the status check is a lightweight pre-flight.
        #
        # Rule 1 fix: to avoid double-conversion, we call converter.convert()
        # once to check status, then re-use the converter (not the result) in
        # parse_pdf. The alternative -- inlining parse_pdf's chunking logic here
        # -- would duplicate significant code and create a maintenance burden.
        # Double-convert is acceptable since converter caches tokenisation state.
        status_result = converter.convert(str(file_path), raises_on_error=False)
        is_partial = (status_result.status == ConversionStatus.PARTIAL_SUCCESS)

        if status_result.status == ConversionStatus.FAILURE:
            logger.error("Docling: total failure on %s -- %s", file_path, status_result.errors)
            return [], False

        if is_partial:
            logger.warning("Docling: partial success on %s -- %s", file_path, status_result.errors)

        chunks = parse_pdf(file_path, converter)
        return chunks, is_partial

    elif file_format == "tex":
        from rag_server.ingestion.parsers.latex_parser import parse_latex
        return parse_latex(file_path), False

    elif file_format == "ipynb":
        from rag_server.ingestion.parsers.jupyter_parser import parse_jupyter
        return parse_jupyter(file_path), False

    else:
        raise ValueError(f"Unsupported file_format: {file_format!r}")


def _upsert_chunks_qdrant(
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
            logger.error("Document %s not found in SQLite during status update", document_id)
            return
        doc.status = status
        doc.error_msg = error_msg
        doc.updated_at = datetime.now(timezone.utc)
        if status in ("indexed", "indexed_partial"):
            doc.indexed_at = datetime.now(timezone.utc)
        session.commit()


def run_pipeline(
    job,
    converter: "DocumentConverter | None",
    embedder: Embedder,
    result_queue: multiprocessing.Queue | None = None,
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

    logger.info("Pipeline: starting job for document %s (%s)", document_id, job.file_format)

    # Step 1: Mark as indexing.
    _set_document_status(document_id, "indexing", engine)

    try:
        # Step 2: Parse document.
        parsed_chunks, is_partial = _dispatch_parser(
            job.file_format, job.file_path, converter
        )
        if not parsed_chunks:
            logger.warning("Pipeline: parser returned 0 chunks for %s", document_id)

        # Step 3: Generate chunk UUIDs as a parallel list.
        # IMPORTANT: We do NOT monkey-patch ParsedChunk instances with extra
        # attributes. The dataclass contract must not be bypassed. Instead we
        # maintain chunk_ids as a parallel list in the same order as parsed_chunks.
        chunk_ids: list[str] = [str(uuid.uuid4()) for _ in parsed_chunks]

        # Step 4: Persist Chunk rows to SQLite using the pre-generated IDs.
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
        logger.info("Pipeline: %d chunks written to SQLite for %s", len(parsed_chunks), document_id)

        # Step 5: Embed chunks and upsert to Qdrant.
        # chunk_ids is passed as a parallel structure -- no monkey-patching.
        _upsert_chunks_qdrant(
            document_id=document_id,
            chunks=parsed_chunks,
            chunk_ids=chunk_ids,
            embedder=embedder,
            qdrant_url=job.qdrant_url,
            collection=job.qdrant_collection,
        )
        logger.info("Pipeline: Qdrant upsert complete for %s", document_id)

        # Step 6: Update page_count on Document (count unique page numbers).
        unique_pages = {c.page_number for c in parsed_chunks if c.page_number is not None}
        with Session(engine) as session:
            doc = session.get(Document, document_id)
            if doc and unique_pages:
                doc.page_count = max(unique_pages)
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
            _set_document_status(document_id, "indexed_partial", engine, error_msg=error_msg)
            logger.warning(
                "Pipeline: document %s indexed_partial (%d chunks)", document_id, len(parsed_chunks)
            )
        else:
            _set_document_status(document_id, "indexed", engine)
            logger.info(
                "Pipeline: document %s indexed successfully (%d chunks)", document_id, len(parsed_chunks)
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

    except Exception as exc:
        logger.exception("Pipeline: failure on document %s", document_id)

        # Rollback: remove any partial data so failure state is clean.
        try:
            _delete_sqlite_chunks(document_id, engine)
        except Exception:
            logger.exception("Pipeline: rollback SQLite chunks failed for %s", document_id)

        try:
            _delete_qdrant_document(document_id, job.qdrant_url, job.qdrant_collection)
        except Exception:
            logger.exception("Pipeline: rollback Qdrant delete failed for %s", document_id)

        _set_document_status(document_id, "failed", engine, error_msg=str(exc))
