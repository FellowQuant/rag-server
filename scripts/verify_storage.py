#!/usr/bin/env python3
"""End-to-end smoke test for Phase 1 storage layer.

Run from project root (with Qdrant running via docker compose up qdrant):
    python scripts/verify_storage.py
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root without installation
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rag_server.config import get_settings
from rag_server.vector_store.qdrant import QdrantStore
from rag_server.database.engine import async_session, engine
from rag_server.database.models import Base, Chunk, Document
from sqlalchemy import select, text


async def verify_settings() -> None:
    settings = get_settings()
    assert str(settings.data_dir) != "", "data_dir must not be empty"
    assert "sqlite+aiosqlite" in settings.sqlite_url, f"Bad sqlite_url: {settings.sqlite_url}"
    assert settings.qdrant_url.startswith("http"), f"Bad qdrant_url: {settings.qdrant_url}"
    print(f"  [OK] Settings: data_dir={settings.data_dir}, qdrant={settings.qdrant_url}")


async def verify_qdrant() -> None:
    store = QdrantStore()
    try:
        # Step 1: Create collection (idempotent)
        await store.ensure_collection()
        print("  [OK] Qdrant collection ensured")

        # Step 2: Upsert a synthetic point (1024-dim zero vector)
        test_id = str(uuid.uuid4())
        doc_id = str(uuid.uuid4())
        await store.upsert_chunks([{
            "id": test_id,
            "dense_vector": [0.0] * 1024,
            "payload": {
                "chunk_id": test_id,
                "document_id": doc_id,
                "chunk_type": "text",
                "page_number": 1,
                "section_heading": "Test Section",
                "chunk_index": 0,
            },
        }])
        print(f"  [OK] Upserted test point id={test_id[:8]}...")

        # Step 3: Retrieve the point by ID
        from qdrant_client.models import PointIdsList
        results = await store._client.retrieve(
            collection_name=store._collection,
            ids=[test_id],
            with_payload=True,
        )
        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert results[0].payload["document_id"] == doc_id
        print(f"  [OK] Retrieved point — payload.document_id matches")

        # Step 4: Delete via delete_document (filter by document_id)
        await store.delete_document(doc_id)
        results_after = await store._client.retrieve(
            collection_name=store._collection,
            ids=[test_id],
        )
        assert len(results_after) == 0, "Point should be deleted"
        print(f"  [OK] Deleted point via delete_document — gone from collection")

        # Step 5: Collection info
        info = await store.get_collection_info()
        print(f"  [OK] Collection info: {info}")

    finally:
        await store.close()


async def verify_sqlite() -> None:
    settings = get_settings()
    db_path = Path(settings.data_dir.resolve()) / "rag.db"
    assert db_path.exists(), f"SQLite DB not found at {db_path}. Run: alembic upgrade head"
    print(f"  [OK] SQLite DB exists at {db_path}")

    async with async_session() as session:
        # Verify FK pragma is enabled
        result = await session.execute(text("PRAGMA foreign_keys"))
        fk_enabled = result.scalar()
        assert fk_enabled == 1, f"PRAGMA foreign_keys should be 1, got {fk_enabled}"
        print("  [OK] PRAGMA foreign_keys=ON (FK enforcement active)")

        # Insert Document + Chunk
        now = datetime.now(timezone.utc)
        doc = Document(
            id=str(uuid.uuid4()),
            filename="test.pdf",
            file_format="pdf",
            file_hash=f"sha256-{uuid.uuid4().hex}",
            file_size=1024,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        session.add(doc)
        await session.flush()  # Get doc.id before adding chunk

        chunk = Chunk(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            chunk_index=0,
            chunk_type="text",
            content="Test chunk content",
            created_at=now,
        )
        session.add(chunk)
        await session.commit()
        print(f"  [OK] Inserted Document id={doc.id[:8]}... + Chunk id={chunk.id[:8]}...")

        # Query back
        doc_result = await session.execute(select(Document).where(Document.id == doc.id))
        loaded_doc = doc_result.scalar_one()
        assert loaded_doc.filename == "test.pdf"
        print(f"  [OK] Document query: filename={loaded_doc.filename}, status={loaded_doc.status}")

        chunk_result = await session.execute(select(Chunk).where(Chunk.document_id == doc.id))
        loaded_chunk = chunk_result.scalar_one()
        assert loaded_chunk.chunk_type == "text"
        print(f"  [OK] Chunk query: chunk_type={loaded_chunk.chunk_type}, index={loaded_chunk.chunk_index}")

        # Delete document — chunks must cascade
        await session.delete(loaded_doc)
        await session.commit()

        orphan_result = await session.execute(
            select(Chunk).where(Chunk.document_id == doc.id)
        )
        orphans = orphan_result.scalars().all()
        assert len(orphans) == 0, f"Cascade delete failed: {len(orphans)} orphan chunks remain"
        print("  [OK] ON DELETE CASCADE: chunk deleted when document deleted")


async def main() -> None:
    print("\n=== Phase 1 Storage Verification ===\n")
    print("[1/3] Settings...")
    await verify_settings()

    print("\n[2/3] Qdrant (requires `docker compose up qdrant`)...")
    try:
        await verify_qdrant()
    except Exception as exc:
        print(f"  [FAIL] Qdrant: {exc}")
        print("         Is Qdrant running? Try: docker compose up -d qdrant")
        sys.exit(1)

    print("\n[3/3] SQLite (requires `alembic upgrade head`)...")
    try:
        await verify_sqlite()
    except Exception as exc:
        print(f"  [FAIL] SQLite: {exc}")
        print("         Did you run: alembic upgrade head ?")
        sys.exit(1)

    print("\n=== All storage checks passed ===\n")


if __name__ == "__main__":
    asyncio.run(main())
