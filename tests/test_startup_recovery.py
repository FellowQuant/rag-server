from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rag_server.database.models import Base, Chunk, Document
from rag_server.worker.recovery import recover_interrupted_documents


class RecordingWorker:
    def __init__(self) -> None:
        self.jobs = []

    def enqueue_blocking(self, job) -> None:
        self.jobs.append(job)


class RecordingQdrant:
    def __init__(self) -> None:
        self.deleted_document_ids: list[str] = []

    async def delete_document(self, document_id: str) -> None:
        self.deleted_document_ids.append(document_id)


async def _make_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rag.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _settings(tmp_path):
    return SimpleNamespace(
        data_dir=tmp_path,
        sqlite_url=f"sqlite+aiosqlite:///{tmp_path / 'rag.db'}",
        qdrant_url="http://localhost:6330",
        qdrant_collection="documents",
    )


def _write_upload(tmp_path, file_hash: str, file_format: str) -> None:
    suffix = ".ipynb" if file_format == "ipynb" else f".{file_format}"
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / f"{file_hash}{suffix}").write_bytes(b"payload")


async def _insert_doc(session_factory, **kwargs) -> Document:
    async with session_factory() as session:
        doc = Document(**kwargs)
        session.add(doc)
        await session.commit()
        return doc


def test_recovery_enqueues_pending_documents_fifo(tmp_path) -> None:
    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path)
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        docs = [
            {
                "id": "later",
                "filename": "later.pdf",
                "file_format": "pdf",
                "file_hash": "hash_later",
                "file_size": 1,
                "status": "pending",
                "created_at": base_time + timedelta(seconds=5),
            },
            {
                "id": "earlier",
                "filename": "earlier.pdf",
                "file_format": "pdf",
                "file_hash": "hash_earlier",
                "file_size": 1,
                "status": "pending",
                "created_at": base_time,
            },
        ]
        for doc in docs:
            _write_upload(tmp_path, doc["file_hash"], doc["file_format"])
            await _insert_doc(session_factory, **doc)

        worker = RecordingWorker()
        async with session_factory() as session:
            recovered = await recover_interrupted_documents(
                session,
                worker,
                _settings(tmp_path),
                RecordingQdrant(),
            )

        assert recovered == 2
        assert [job.document_id for job in worker.jobs] == ["earlier", "later"]
        await engine.dispose()

    asyncio.run(run())


def test_recovery_resets_stale_indexing_and_removes_existing_chunks(tmp_path) -> None:
    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path)
        _write_upload(tmp_path, "hash_indexing", "pdf")
        async with session_factory() as session:
            doc = Document(
                id="stale",
                filename="stale.pdf",
                file_format="pdf",
                file_hash="hash_indexing",
                file_size=1,
                status="indexing",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            session.add(doc)
            session.add(
                Chunk(
                    id="chunk-1",
                    document_id="stale",
                    chunk_index=0,
                    chunk_type="text",
                    content="old",
                )
            )
            await session.commit()

        worker = RecordingWorker()
        qdrant = RecordingQdrant()
        async with session_factory() as session:
            recovered = await recover_interrupted_documents(
                session,
                worker,
                _settings(tmp_path),
                qdrant,
            )

        async with session_factory() as session:
            doc = await session.get(Document, "stale")
            chunks = (
                (
                    await session.execute(
                        select(Chunk).where(Chunk.document_id == "stale")
                    )
                )
                .scalars()
                .all()
            )

        assert recovered == 1
        assert doc.status == "pending"
        assert "Recovered interrupted indexing job" in doc.error_msg
        assert chunks == []
        assert qdrant.deleted_document_ids == ["stale"]
        assert [job.document_id for job in worker.jobs] == ["stale"]
        await engine.dispose()

    asyncio.run(run())


def test_recovery_marks_missing_upload_failed_without_enqueue(tmp_path) -> None:
    async def run() -> None:
        engine, session_factory = await _make_session(tmp_path)
        await _insert_doc(
            session_factory,
            id="missing",
            filename="missing.pdf",
            file_format="pdf",
            file_hash="hash_missing",
            file_size=1,
            status="pending",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        worker = RecordingWorker()
        async with session_factory() as session:
            recovered = await recover_interrupted_documents(
                session,
                worker,
                _settings(tmp_path),
                RecordingQdrant(),
            )

        async with session_factory() as session:
            doc = await session.get(Document, "missing")

        assert recovered == 0
        assert worker.jobs == []
        assert doc.status == "failed"
        assert "Upload file missing during startup recovery" in doc.error_msg
        await engine.dispose()

    asyncio.run(run())
