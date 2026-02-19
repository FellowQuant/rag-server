"""End-to-end ingestion pipeline smoke test.

Tests the full pipeline without a real PDF (which would require Docling model
downloads). Uses a .ipynb notebook as the test document since it has no
model dependencies.

Prerequisites:
  1. Qdrant running: docker compose up -d qdrant
  2. Alembic migration applied: alembic upgrade head
  3. Dependencies installed: pip install -e .
  4. Server NOT running (test starts it in-process via TestClient)

Usage:
  python scripts/verify_ingestion.py

The test:
  1. Uploads a synthetic .ipynb notebook via POST /documents
  2. Polls GET /documents/{id} until status is "indexed" or "failed" (max 120s)
  3. Verifies SQLite has chunk records for the document
  4. Verifies Qdrant has vector points for the document
  5. Calls DELETE /documents/{id} and verifies cleanup
  6. Prints PASS or FAIL with details
"""
from __future__ import annotations

import json
import sys
import time

# NOTE: set_start_method is called in main.py at import time.
# Import main before anything else to ensure spawn method is set.
# This is safe to run from a non-server context.
import rag_server.main  # noqa: F401 — triggers set_start_method("spawn")

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from rag_server.config import get_settings
from rag_server.database.models import Chunk, Document

POLL_INTERVAL = 2   # seconds between status polls
POLL_TIMEOUT = 120  # maximum seconds to wait for indexing

# Minimal .ipynb notebook for testing — no real code, just cells.
TEST_NOTEBOOK = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        }
    },
    "cells": [
        {
            "cell_type": "markdown",
            "source": "# Sharpe Ratio\n\nThe Sharpe ratio measures risk-adjusted return: excess return per unit of volatility.",
            "metadata": {},
        },
        {
            "cell_type": "code",
            "source": "import numpy as np\n\ndef sharpe_ratio(returns, risk_free_rate=0.02):\n    excess = returns - risk_free_rate / 252\n    return np.sqrt(252) * excess.mean() / excess.std()\n",
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        },
        {
            "cell_type": "markdown",
            "source": "The formula above computes annualized Sharpe ratio from daily returns.",
            "metadata": {},
        },
    ],
}


def run_test() -> bool:
    settings = get_settings()
    settings.ensure_data_dirs()

    base_url = "http://localhost:8000"
    print(f"[verify_ingestion] Connecting to {base_url}")
    print("[verify_ingestion] NOTE: Server must be running (uvicorn rag_server.main:app)")
    print()

    # --- Step 1: Upload notebook ---
    print("Step 1: Upload test notebook...")
    notebook_bytes = json.dumps(TEST_NOTEBOOK).encode()
    with httpx.Client(base_url=base_url, timeout=30) as client:
        resp = client.post(
            "/documents",
            files={"file": ("test_sharpe.ipynb", notebook_bytes, "application/json")},
        )

    if resp.status_code == 409:
        # Already exists from a previous test run — extract the doc_id from error detail.
        print(f"  Document already exists (409): {resp.json()['detail']}")
        # Re-query the doc_id from SQLite.
        sync_url = settings.sqlite_url.replace("sqlite+aiosqlite://", "sqlite://")
        engine = create_engine(sync_url)
        import hashlib
        file_hash = hashlib.sha256(notebook_bytes).hexdigest()
        with Session(engine) as session:
            doc = session.execute(select(Document).where(Document.file_hash == file_hash)).scalar_one_or_none()
        if doc is None:
            print("FAIL: 409 but document not found in SQLite")
            return False
        doc_id = doc.id
        print(f"  Reusing existing document id={doc_id}")
    elif resp.status_code != 202:
        print(f"FAIL: Expected 202, got {resp.status_code}: {resp.text}")
        return False
    else:
        data = resp.json()
        doc_id = data["id"]
        print(f"  Uploaded: id={doc_id}, status={data['status']}, format={data['file_format']}")

    # --- Step 2: Poll status ---
    print(f"Step 2: Polling GET /documents/{doc_id} for up to {POLL_TIMEOUT}s...")
    start = time.time()
    final_status = None
    with httpx.Client(base_url=base_url, timeout=10) as client:
        while time.time() - start < POLL_TIMEOUT:
            resp = client.get(f"/documents/{doc_id}")
            if resp.status_code != 200:
                print(f"FAIL: GET /documents/{doc_id} returned {resp.status_code}")
                return False
            data = resp.json()
            status = data["status"]
            print(f"  status={status} (elapsed {time.time()-start:.0f}s)")
            if status in ("indexed", "indexed_partial", "failed"):
                final_status = status
                break
            time.sleep(POLL_INTERVAL)

    if final_status is None:
        print(f"FAIL: Timed out waiting for indexing after {POLL_TIMEOUT}s")
        return False

    if final_status == "failed":
        print(f"FAIL: Document indexing failed. error_msg={data.get('error_msg')}")
        return False

    print(f"  Final status: {final_status}")

    # --- Step 3: Verify SQLite has chunks ---
    print("Step 3: Verifying SQLite chunk records...")
    sync_url = settings.sqlite_url.replace("sqlite+aiosqlite://", "sqlite://")
    db_engine = create_engine(sync_url)
    with Session(db_engine) as session:
        chunks = session.execute(
            select(Chunk).where(Chunk.document_id == doc_id)
        ).scalars().all()
    print(f"  SQLite chunks: {len(chunks)}")
    if len(chunks) == 0:
        print("FAIL: No chunks in SQLite for document")
        return False

    chunk_types = {c.chunk_type for c in chunks}
    print(f"  Chunk types: {chunk_types}")
    assert "text" in chunk_types or "code" in chunk_types, "Expected text or code chunks"

    # --- Step 4: Verify Qdrant has vectors ---
    print("Step 4: Verifying Qdrant has vectors...")
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    qc = QdrantClient(url=settings.qdrant_url)
    try:
        search_result = qc.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]
            ),
            limit=10,
        )
        qdrant_points = search_result[0]
        print(f"  Qdrant points: {len(qdrant_points)}")
        if len(qdrant_points) == 0:
            print("FAIL: No Qdrant points for document")
            return False
    finally:
        qc.close()

    # --- Step 5: Delete and verify cleanup ---
    print("Step 5: DELETE /documents/{id} and verify cleanup...")
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.delete(f"/documents/{doc_id}")
    if resp.status_code != 204:
        print(f"FAIL: DELETE returned {resp.status_code}: {resp.text}")
        return False

    # Verify SQLite document is gone.
    with Session(db_engine) as session:
        doc = session.get(Document, doc_id)
    if doc is not None:
        print("FAIL: Document still in SQLite after DELETE")
        return False
    print("  SQLite record deleted OK")

    # Verify Qdrant vectors are gone.
    qc = QdrantClient(url=settings.qdrant_url)
    try:
        search_result = qc.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]
            ),
            limit=1,
        )
        remaining = search_result[0]
        if len(remaining) > 0:
            print(f"FAIL: {len(remaining)} Qdrant points remain after DELETE")
            return False
        print("  Qdrant points deleted OK")
    finally:
        qc.close()

    print()
    print("=" * 60)
    print("PASS: All ingestion pipeline checks passed")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
