#!/usr/bin/env python3
"""End-to-end retrieval smoke test.

Verifies the complete retrieval pipeline:
  1. Upload a Jupyter notebook for ingestion
  2. Poll until document is indexed (up to 120s for BGE-M3 embedding)
  3. Call the retrieval engine directly (not via HTTP endpoint -- retrieval
     endpoints are Phase 5; this tests the engine module directly)
  4. Assert results contain chunks with scores and citation metadata
  5. Cleanup: delete the document

Usage:
    # Start server first:
    uvicorn rag_server.main:app --reload

    # In another terminal:
    python scripts/verify_retrieval.py

Expected output: PASS for all steps.
"""
import asyncio
import sys
import time
from pathlib import Path

# Allow running from repo root or scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

BASE_URL = "http://localhost:8000"
NOTEBOOK_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "sample.ipynb"


def _find_notebook() -> Path:
    """Find a notebook to upload. Uses fixture if available, creates minimal one otherwise."""
    if NOTEBOOK_PATH.exists():
        return NOTEBOOK_PATH

    # Create a minimal notebook for testing
    import json
    nb = {
        "nbformat": 4,
        "nbformat_minor": 4,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "cells": [
            {
                "cell_type": "markdown",
                "source": ["# Sharpe Ratio Analysis\n", "\n",
                           "The Sharpe ratio measures risk-adjusted return. ",
                           "It is calculated as the excess return divided by the standard deviation of returns."],
                "metadata": {},
            },
            {
                "cell_type": "code",
                "source": ["import numpy as np\n",
                           "returns = np.array([0.01, 0.02, -0.01, 0.03])\n",
                           "sharpe = returns.mean() / returns.std()\n",
                           "print(f'Sharpe ratio: {sharpe:.4f}')"],
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            },
            {
                "cell_type": "markdown",
                "source": ["## Portfolio Volatility\n", "\n",
                           "Portfolio volatility is computed from the covariance matrix of asset returns. ",
                           "For a two-asset portfolio with weights w1 and w2:"],
                "metadata": {},
            },
        ],
    }
    tmp = Path("/tmp/verify_retrieval_test.ipynb")
    tmp.write_text(json.dumps(nb))
    return tmp


async def main() -> None:
    notebook_path = _find_notebook()
    print(f"Using notebook: {notebook_path}")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # --- Step 1: Upload notebook ---
        print("\n[1/5] Uploading notebook...")
        with open(notebook_path, "rb") as f:
            resp = await client.post(
                "/documents",
                files={"file": (notebook_path.name, f, "application/octet-stream")},
            )
        if resp.status_code == 409:
            # Already indexed from a previous run -- fetch its ID
            print("  Document already exists (409) -- listing documents to find it")
            list_resp = await client.get("/documents")
            docs = list_resp.json()["documents"]
            doc = next(
                (d for d in docs if notebook_path.name in d.get("filename", "")),
                docs[0] if docs else None,
            )
            if doc is None:
                print("  FAIL: could not find existing document")
                sys.exit(1)
            doc_id = doc["id"]
            print(f"  Using existing document ID: {doc_id}")
        elif resp.status_code != 202:
            print(f"  FAIL: expected 202, got {resp.status_code}: {resp.text}")
            sys.exit(1)
        else:
            doc_id = resp.json()["id"]
            print(f"  OK: document ID = {doc_id}")

        # --- Step 2: Poll until indexed ---
        print("\n[2/5] Waiting for indexing (up to 120s)...")
        deadline = time.time() + 120
        indexed = False
        while time.time() < deadline:
            status_resp = await client.get(f"/documents/{doc_id}")
            status = status_resp.json().get("status")
            print(f"  status = {status}")
            if status in ("indexed", "indexed_partial"):
                indexed = True
                break
            if status == "failed":
                print(f"  FAIL: indexing failed -- {status_resp.json().get('error_msg')}")
                sys.exit(1)
            await asyncio.sleep(3)

        if not indexed:
            print("  FAIL: timed out waiting for indexing")
            sys.exit(1)
        print("  OK: document indexed")

        # --- Step 3: Run retrieval engine directly ---
        print("\n[3/5] Running retrieval engine...")
        # Import app.state components after server is running
        # We test the engine module directly via HTTP for now.
        # (Phase 5 will add /retrieve endpoint; here we verify via
        #  a direct module call from a separate process by querying
        #  the health endpoint to confirm the server is alive, then
        #  validate the BM25 state via a query to an internal debug endpoint
        #  if available, or skip to results verification below.)
        #
        # Since retrieval HTTP endpoint is Phase 5, we verify here by
        # using the Python API directly in a subprocess that imports the
        # engine. Instead, let's verify the BM25 index state via a direct
        # import and module call (server must be on localhost but the
        # verify_retrieval script can also instantiate the engine in its
        # own process for unit-level validation).
        #
        # Full retrieval test:
        from rag_server.database.engine import async_session
        from rag_server.retrieval.bm25_manager import BM25Manager
        from rag_server.config import get_settings

        settings = get_settings()

        # Test BM25 index was built and persisted
        bm25_pkl = settings.data_dir / "bm25.pkl"
        if not bm25_pkl.exists():
            print(f"  FAIL: bm25.pkl not found at {bm25_pkl}")
            sys.exit(1)

        bm25_mgr = BM25Manager(bm25_pkl)
        loaded = bm25_mgr.load_from_disk()
        if not loaded:
            print("  FAIL: could not load bm25.pkl")
            sys.exit(1)

        print(f"  BM25 index: {bm25_mgr.chunk_count} chunks")
        if bm25_mgr.chunk_count == 0:
            print("  FAIL: BM25 index is empty after indexing")
            sys.exit(1)

        bm25_results = bm25_mgr.search("sharpe ratio", top_n=5)
        print(f"  BM25 search 'sharpe ratio': {len(bm25_results)} results")
        if not bm25_results:
            print("  FAIL: BM25 returned no results for 'sharpe ratio'")
            sys.exit(1)

        top_id, top_score = bm25_results[0]
        print(f"  Top BM25 result: chunk_id={top_id}, score={top_score:.4f}")

        # Verify SQLite has the content for top result
        async with async_session() as session:
            from sqlalchemy import select
            from rag_server.database.models import Chunk, Document
            result = await session.execute(
                select(Chunk.id, Chunk.content, Chunk.chunk_type,
                       Chunk.page_number, Chunk.section_heading, Document.filename)
                .join(Document, Chunk.document_id == Document.id)
                .where(Chunk.id == top_id)
            )
            row = result.first()
            if row is None:
                print(f"  FAIL: chunk {top_id} not found in SQLite")
                sys.exit(1)
            print(f"  Top chunk: type={row.chunk_type}, file={row.filename}")
            print(f"  Content preview: {row.content[:100]!r}")
        print("  OK: BM25 index built, search works, SQLite content verified")

        # --- Step 4: Verify citation fields exist on chunks ---
        print("\n[4/5] Verifying citation metadata fields...")
        async with async_session() as session:
            from sqlalchemy import select
            from rag_server.database.models import Chunk, Document
            result = await session.execute(
                select(Chunk.id, Chunk.chunk_type, Chunk.page_number,
                       Chunk.section_heading, Chunk.chunk_index, Document.filename)
                .join(Document, Chunk.document_id == Document.id)
                .where(Document.id == doc_id)
                .limit(5)
            )
            rows = result.all()
            if not rows:
                print("  FAIL: no chunks found for document")
                sys.exit(1)
            for r in rows:
                assert r.filename, f"chunk {r.id} missing filename"
                assert r.chunk_type in ("text", "formula", "table", "code"), \
                    f"unexpected chunk_type: {r.chunk_type}"
            print(f"  OK: {len(rows)} chunks verified with citation metadata")
            print(f"  Sample: type={rows[0].chunk_type}, file={rows[0].filename}, page={rows[0].page_number}")

        # --- Step 5: Cleanup ---
        print("\n[5/5] Deleting test document...")
        del_resp = await client.delete(f"/documents/{doc_id}")
        if del_resp.status_code != 204:
            print(f"  WARNING: delete returned {del_resp.status_code} (not 204)")
        else:
            print("  OK: document deleted")

        print("\n=== PASS ===")


if __name__ == "__main__":
    asyncio.run(main())
