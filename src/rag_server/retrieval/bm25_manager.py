"""BM25 keyword index manager for the retrieval pipeline.

Wraps rank-bm25 BM25Okapi with:
  - Async build from SQLite (CPU-bound -> asyncio.to_thread)
  - Atomic pickle persistence to DATA_DIR/bm25.pkl
  - Hot-swap under asyncio.Lock (readers never blocked during rebuild)
  - Synchronous search returning [(chunk_id, score)] list

Design decisions:
  - Corpus built from ALL indexed chunks globally (not per-document) --
    required for RETR-05 cross-document retrieval.
  - corpus_ids list is parallel to BM25 tokenized corpus -- ORDER BY chunk.id
    in build query keeps ordering stable across rebuilds.
  - Tokenizer: lowercase whitespace split. Simple and effective for English
    prose. LaTeX is NOT stripped here -- formula chunks have low BM25 weight
    naturally due to unusual tokens, which is acceptable for v1.
  - On startup: load from bm25.pkl if it exists; fall back to full SQLite
    rebuild. After each rebuild: atomic write to bm25.pkl.
  - Empty corpus (no indexed chunks yet) is handled: bm25 is None, search
    returns [].
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import pickle

import numpy as np

logger = logging.getLogger(__name__)


class BM25Manager:
    """Lifecycle manager for the in-process BM25 keyword index.

    Create one instance per FastAPI application in lifespan. Access from
    retrieval code via app.state.bm25_manager.

    Thread safety: asyncio.Lock guards hot-swap. Multiple concurrent reads
    can proceed simultaneously (lock only held during the index swap, not
    during search). The synchronous search() method reads self._bm25 and
    self._corpus_ids without holding the lock -- this is safe because Python
    object reference assignment is atomic (GIL-protected) and we only ever
    swap the reference, never mutate in place.
    """

    def __init__(self, pkl_path: pathlib.Path) -> None:
        self._path = pkl_path
        self._lock = asyncio.Lock()
        self._bm25 = None  # BM25Okapi | None
        self._corpus_ids: list[str] = []

    async def build(self, session) -> None:
        """Build BM25 index from all indexed chunks in SQLite.

        Fetches all (id, content) from chunks WHERE document.status IN
        ('indexed', 'indexed_partial'), builds BM25Okapi in a thread pool
        (CPU-bound), hot-swaps under asyncio.Lock, then persists to disk.

        Args:
            session: AsyncSession from async_session() context manager.
        """
        from sqlalchemy import select
        from rag_server.database.models import Chunk, Document

        result = await session.execute(
            select(Chunk.id, Chunk.content)
            .join(Chunk.document)
            .where(Document.status.in_(["indexed", "indexed_partial"]))
            .order_by(Chunk.id)  # stable ordering prevents corpus_ids drift
        )
        rows = result.all()

        corpus_ids: list[str] = [r.id for r in rows]
        tokenized: list[list[str]] = [r.content.lower().split() for r in rows]

        def _build():
            from rank_bm25 import BM25Okapi

            return BM25Okapi(tokenized) if tokenized else None

        bm25 = await asyncio.to_thread(_build)

        async with self._lock:
            self._bm25 = bm25
            self._corpus_ids = corpus_ids

        logger.info(
            "BM25Manager: index built with %d chunks, persisting to %s",
            len(corpus_ids),
            self._path,
        )
        await asyncio.to_thread(self._atomic_write, bm25, corpus_ids)

    def load_from_disk(self) -> bool:
        """Load BM25 index from pickle file if it exists.

        Synchronous -- call before the event loop starts (in lifespan before
        the first await) or via asyncio.to_thread.

        Returns:
            True if loaded successfully, False if file does not exist.
        """
        if not self._path.exists():
            logger.info(
                "BM25Manager: no pickle at %s, will build from SQLite", self._path
            )
            return False
        try:
            with open(self._path, "rb") as f:
                data = pickle.load(f)
            self._bm25 = data["bm25"]
            self._corpus_ids = data["corpus_ids"]
            logger.info(
                "BM25Manager: loaded from disk (%d chunks)", len(self._corpus_ids)
            )
            return True
        except Exception:
            logger.exception(
                "BM25Manager: failed to load pickle, will rebuild from SQLite"
            )
            return False

    def search(self, query: str, top_n: int) -> list[tuple[str, float]]:
        """Search the BM25 index for a query string.

        Synchronous -- call via asyncio.to_thread() from async retrieval code.

        Args:
            query: Plain text query string.
            top_n: Number of top results to return.

        Returns:
            List of (chunk_id, bm25_score) tuples sorted by score descending.
            Returns [] if index is empty or corpus is empty.
        """
        if self._bm25 is None or not self._corpus_ids:
            return []

        tokens = query.lower().split()
        if not tokens:
            return []

        scores: np.ndarray = self._bm25.get_scores(tokens)
        # np.argsort returns ascending; reverse for descending score order
        top_indices = np.argsort(scores)[::-1][:top_n]
        return [
            (self._corpus_ids[i], float(scores[i]))
            for i in top_indices
            if float(scores[i]) > 0.0  # skip zero-score chunks
        ]

    def _atomic_write(self, bm25, corpus_ids: list[str]) -> None:
        """Write BM25 + corpus_ids to pickle atomically (write-to-tmp, rename)."""
        tmp = self._path.with_suffix(".tmp")
        try:
            with open(tmp, "wb") as f:
                pickle.dump({"bm25": bm25, "corpus_ids": corpus_ids}, f)
            tmp.rename(self._path)  # atomic on Linux (same filesystem)
        except Exception:
            logger.exception("BM25Manager: failed to write pickle to %s", self._path)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    @property
    def chunk_count(self) -> int:
        """Number of chunks currently indexed in BM25."""
        return len(self._corpus_ids)
