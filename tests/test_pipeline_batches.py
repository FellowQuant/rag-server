from __future__ import annotations

import multiprocessing
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from rag_server.database.models import Base, Chunk, Document
from rag_server.ingestion.chunker import ParsedChunk, ParsedChunkBatch
from rag_server.worker import pipeline
from rag_server.worker.resource_guard import ResourceLimitExceeded


@dataclass
class FakeJob:
    document_id: str
    file_path: str
    file_format: str
    original_filename: str
    sqlite_url: str
    qdrant_url: str
    qdrant_collection: str


class FakeGuard:
    def __init__(self) -> None:
        self.labels: list[str] = []

    def checkpoint(self, label: str) -> None:
        self.labels.append(label)


def test_run_pipeline_processes_parse_batches_with_contiguous_chunk_indexes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "rag.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Document(
                id="doc-1",
                filename="book.pdf",
                file_format="pdf",
                file_hash="hash",
                file_size=1,
                status="pending",
            )
        )
        session.commit()

    batches = [
        ParsedChunkBatch(
            chunks=[
                ParsedChunk(chunk_type="text", content="first"),
                ParsedChunk(chunk_type="text", content="second"),
            ],
            page_count=1,
        ),
        ParsedChunkBatch(
            chunks=[ParsedChunk(chunk_type="text", content="third")],
            page_count=2,
        ),
    ]
    upserted_indexes: list[list[int]] = []

    def fake_dispatch_batches(file_format, file_path, converter=None):
        assert file_format == "pdf"
        assert file_path == "/tmp/book.pdf"
        return iter(batches)

    def fake_upsert_batch(**kwargs):
        upserted_indexes.append([chunk.chunk_index for chunk in kwargs["chunks"]])

    monkeypatch.setattr(pipeline, "_dispatch_parser_batches", fake_dispatch_batches)
    monkeypatch.setattr(pipeline, "_upsert_chunk_batch_qdrant", fake_upsert_batch)

    guard = FakeGuard()
    result_queue: multiprocessing.Queue = multiprocessing.Queue()
    job = FakeJob(
        document_id="doc-1",
        file_path="/tmp/book.pdf",
        file_format="pdf",
        original_filename="book.pdf",
        sqlite_url=f"sqlite+aiosqlite:///{db_path}",
        qdrant_url="http://localhost:6330",
        qdrant_collection="documents",
    )

    pipeline.run_pipeline(
        job,
        converter=None,
        embedder=object(),
        result_queue=result_queue,
        resource_guard=guard,
    )

    with Session(engine) as session:
        chunks = (
            session.execute(
                select(Chunk)
                .where(Chunk.document_id == "doc-1")
                .order_by(Chunk.chunk_index)
            )
            .scalars()
            .all()
        )
        doc = session.get(Document, "doc-1")

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert [chunk.content for chunk in chunks] == ["first", "second", "third"]
    assert upserted_indexes == [[0, 1], [2]]
    assert doc.status == "indexed"
    assert doc.page_count == 2
    assert "before-parse-batch" in guard.labels
    assert "after-qdrant-upsert" in guard.labels


def test_run_pipeline_rolls_back_when_resource_guard_trips(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "rag.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Document(
                id="doc-guard",
                filename="large.pdf",
                file_format="pdf",
                file_hash="hash",
                file_size=1,
                status="pending",
            )
        )
        session.commit()

    def fake_dispatch_batches(file_format, file_path, converter=None):
        return iter(
            [
                ParsedChunkBatch(
                    chunks=[ParsedChunk(chunk_type="text", content="first")],
                    page_count=1,
                )
            ]
        )

    def fake_upsert_batch(**kwargs):
        return None

    deleted_document_ids: list[str] = []

    def fake_delete_qdrant_document(document_id, qdrant_url, collection):
        deleted_document_ids.append(document_id)

    class FailingGuard(FakeGuard):
        def checkpoint(self, label: str) -> None:
            super().checkpoint(label)
            if label == "after-qdrant-upsert":
                raise ResourceLimitExceeded("unsafe at after-qdrant-upsert")

    monkeypatch.setattr(pipeline, "_dispatch_parser_batches", fake_dispatch_batches)
    monkeypatch.setattr(pipeline, "_upsert_chunk_batch_qdrant", fake_upsert_batch)
    monkeypatch.setattr(
        pipeline, "_delete_qdrant_document", fake_delete_qdrant_document
    )

    job = FakeJob(
        document_id="doc-guard",
        file_path="/tmp/large.pdf",
        file_format="pdf",
        original_filename="large.pdf",
        sqlite_url=f"sqlite+aiosqlite:///{db_path}",
        qdrant_url="http://localhost:6330",
        qdrant_collection="documents",
    )

    pipeline.run_pipeline(
        job,
        converter=None,
        embedder=object(),
        resource_guard=FailingGuard(),
    )

    with Session(engine) as session:
        doc = session.get(Document, "doc-guard")
        chunks = (
            session.execute(select(Chunk).where(Chunk.document_id == "doc-guard"))
            .scalars()
            .all()
        )

    assert chunks == []
    assert doc.status == "failed"
    assert "unsafe at after-qdrant-upsert" in doc.error_msg
    assert deleted_document_ids == ["doc-guard"]
