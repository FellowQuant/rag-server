"""RetrievalEngine: three-leg hybrid search with RRF fusion and Qwen3 reranking.

Pipeline:
  1. Embed query via BGE-M3 encode_queries() (dense + sparse)
  2. Parallel retrieval: BM25 keyword + Qdrant dense ANN + Qdrant sparse
     (all three run concurrently via asyncio.gather)
  3. RRF fusion: merge three ranked lists using standard RRF formula (k=60)
  4. Bulk SQLite fetch: retrieve content + display_content + citation metadata
     for all candidates (chunk content lives ONLY in SQLite, not in Qdrant)
  5. Qwen3-Reranker-0.6B cross-encoder reranking of top candidates
  6. Apply min_score threshold and top_k cutoff; return ChunkResult list

Design decisions:
  - candidate_k=50: pool size passed to each retrieval leg before RRF and
    reranking. Configurable per-call. Larger pool improves recall but
    increases reranker latency (linear in pool size).
  - RRF k=60: standard constant from Cormack 2009. Not tunable per-call.
  - No deduplication: if two chunks from the same page appear in results,
    both are returned (per user decision in CONTEXT.md).
  - Adaptive instruction: if query contains quotes or LaTeX patterns
    (\\, $, ^), use a more specific retrieval instruction. Claude's discretion.
  - All scores always returned (LOCKED: per CONTEXT.md decisions).
  - Reranker always runs (LOCKED: not skippable per CONTEXT.md).
  - Engine embeds query internally (LOCKED: plain text in, no pre-embedding).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from rag_server.retrieval.models import ChunkResult, RetrievalResult

logger = logging.getLogger(__name__)

# RRF constant from Cormack 2009 paper
_RRF_K = 60

# Regex to detect LaTeX-like content in the query (triggers precise instruction)
_LATEX_PATTERN = re.compile(r"[\\$\^_{}]|\\[a-zA-Z]+")

_DEFAULT_INSTRUCTION = (
    "Given a search query, retrieve relevant passages that answer the query"
)
_PRECISE_INSTRUCTION = (
    "Given a search query containing specific terms, mathematical notation, or "
    "quoted phrases, retrieve passages that contain or closely relate to those exact terms"
)


def _detect_instruction(query: str) -> str:
    """Choose reranker instruction based on query characteristics."""
    if '"' in query or _LATEX_PATTERN.search(query):
        return _PRECISE_INSTRUCTION
    return _DEFAULT_INSTRUCTION


def _rrf_merge(
    bm25_ranking: list[tuple[str, float]],
    dense_ranking: list[tuple[str, float]],
    sparse_ranking: list[tuple[str, float]],
    k: int = _RRF_K,
    top_n: int = 50,
) -> list[tuple[str, float, dict[str, float]]]:
    """Merge three ranked lists via Reciprocal Rank Fusion.

    Args:
        bm25_ranking: [(chunk_id, bm25_score), ...] from BM25Manager.search()
        dense_ranking: [(chunk_id, cosine_score), ...] from QdrantStore.query_dense()
        sparse_ranking: [(chunk_id, sparse_score), ...] from QdrantStore.query_sparse()
        k: RRF constant (60 per standard; not tunable here)
        top_n: Maximum candidates to return

    Returns:
        List of (chunk_id, rrf_score, {leg: score}) sorted by rrf_score desc
    """
    all_legs = {
        "bm25": bm25_ranking,
        "dense": dense_ranking,
        "sparse": sparse_ranking,
    }
    rrf_scores: dict[str, float] = {}
    individual: dict[str, dict[str, float]] = {}

    for leg, ranked in all_legs.items():
        for rank, (chunk_id, score) in enumerate(ranked):
            rrf_scores.setdefault(chunk_id, 0.0)
            rrf_scores[chunk_id] += 1.0 / (k + rank + 1)  # rank is 0-indexed
            individual.setdefault(chunk_id, {"bm25": 0.0, "dense": 0.0, "sparse": 0.0})
            individual[chunk_id][leg] = score

    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return [(cid, rrf_score, individual[cid]) for cid, rrf_score in merged[:top_n]]


class RetrievalEngine:
    """Hybrid retrieval engine: BM25 + BGE-M3 dense + BGE-M3 sparse -> RRF -> Qwen3.

    Create one instance per FastAPI application. Stored on app.state.retrieval_engine.

    The engine holds references to pre-loaded components:
      - embedder: Embedder (BGE-M3) for query embedding
      - qdrant_store: QdrantStore for dense+sparse vector search
      - bm25_manager: BM25Manager for keyword search
      - reranker: Reranker (Qwen3-Reranker-0.6B) for cross-encoder reranking

    All four must be loaded before search() is called.
    """

    def __init__(
        self,
        embedder,  # Embedder instance (must have encode_query())
        qdrant_store,  # QdrantStore instance (must have query_dense, query_sparse)
        bm25_manager,  # BM25Manager instance (must have search())
        reranker,  # Reranker instance (must have compute_scores())
    ) -> None:
        self._embedder = embedder
        self._qdrant = qdrant_store
        self._bm25 = bm25_manager
        self._reranker = reranker

    async def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float | None = None,
        candidate_k: int = 50,
        document_ids: list[str] | None = None,
        session: "AsyncSession | None" = None,
    ) -> RetrievalResult:
        """Execute full hybrid retrieval pipeline.

        Args:
            query: Plain text query string. Engine embeds internally.
            top_k: Number of results to return after reranking (default 10).
            min_score: Optional reranker score threshold (0.0-1.0). Results
                       below threshold are dropped BEFORE top_k cutoff.
            candidate_k: Candidate pool size passed to each retrieval leg.
                         RRF merges candidates from all three legs; top-50
                         by RRF score are passed to the reranker. Default 50.
            document_ids: Optional list of document UUIDs to scope the search.
                          When provided, only chunks belonging to these documents
                          are returned. When None, global search is performed
                          (backward compatible — /ask endpoint unaffected).
            session: AsyncSession for SQLite content fetch. If None, a new
                     session is created from async_session().

        Returns:
            RetrievalResult with ranked ChunkResult list.
        """
        from sqlalchemy import select
        from rag_server.database.engine import async_session as _async_session
        from rag_server.database.models import Chunk, Document
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        # --- Step 1: Embed query (GPU-bound, in thread pool) ---
        query_emb = await asyncio.to_thread(self._embedder.encode_query, query)
        dense_vec = query_emb.dense_vector
        sparse_indices = query_emb.sparse_indices
        sparse_values = query_emb.sparse_values

        # --- Step 1b: Build document_ids filter (when scoped search requested) ---
        qdrant_filter: Filter | None = None
        allowed_chunk_ids: set[str] | None = None

        if document_ids is not None:
            # Build Qdrant payload filter to restrict dense+sparse search to these documents.
            qdrant_filter = Filter(
                must=[
                    FieldCondition(key="document_id", match=MatchAny(any=document_ids))
                ]
            )

            # Pre-fetch allowed chunk_ids from SQLite to post-filter BM25 results.
            # BM25 is corpus-wide; we must filter its results manually since it
            # has no native document_id filter (unlike Qdrant payload filter).
            async def _fetch_allowed_ids(sess):
                result = await sess.execute(
                    select(Chunk.id).where(Chunk.document_id.in_(document_ids))
                )
                return {row.id for row in result.all()}

            if session is not None:
                allowed_chunk_ids = await _fetch_allowed_ids(session)
            else:
                async with _async_session() as sess:
                    allowed_chunk_ids = await _fetch_allowed_ids(sess)

        # --- Step 2: Parallel three-leg retrieval ---
        def _bm25_search():
            return self._bm25.search(query, top_n=candidate_k)

        bm25_task = asyncio.to_thread(_bm25_search)
        dense_task = self._qdrant.query_dense(
            dense_vec, limit=candidate_k, query_filter=qdrant_filter
        )
        sparse_task = self._qdrant.query_sparse(
            sparse_indices, sparse_values, limit=candidate_k, query_filter=qdrant_filter
        )

        bm25_results, dense_results, sparse_results = await asyncio.gather(
            bm25_task, dense_task, sparse_task
        )

        # Normalize to [(chunk_id, score)] tuples
        bm25_ranking = bm25_results  # already [(chunk_id, float)]

        # Post-filter BM25 results when document_ids scope is active.
        # BM25 index is global — Qdrant filter doesn't apply here.
        if allowed_chunk_ids is not None:
            bm25_ranking = [
                (cid, score) for cid, score in bm25_ranking if cid in allowed_chunk_ids
            ]

        dense_ranking = [(r.chunk_id, r.score) for r in dense_results]
        sparse_ranking = [(r.chunk_id, r.score) for r in sparse_results]

        # --- Step 3: RRF fusion ---
        rrf_candidates = _rrf_merge(
            bm25_ranking,
            dense_ranking,
            sparse_ranking,
            k=_RRF_K,
            top_n=candidate_k,
        )
        # rrf_candidates: [(chunk_id, rrf_score, {leg: score})]

        if not rrf_candidates:
            return RetrievalResult(query=query, results=[], total_candidates=0)

        candidate_ids = [cid for cid, _, _ in rrf_candidates]

        # --- Step 4: Bulk SQLite fetch (content + citation metadata) ---
        # CRITICAL: chunk content lives ONLY in SQLite; must fetch before reranking.
        # Reranker needs content strings; citation metadata needed for ChunkResult.
        use_session = session is not None

        async def _fetch(sess):
            result = await sess.execute(
                select(
                    Chunk.id,
                    Chunk.content,
                    Chunk.display_content,
                    Chunk.chunk_type,
                    Chunk.page_number,
                    Chunk.section_heading,
                    Chunk.chunk_index,
                    Chunk.document_id,
                    Document.filename,
                )
                .join(Document, Chunk.document_id == Document.id)
                .where(Chunk.id.in_(candidate_ids))
            )
            return {row.id: row for row in result.all()}

        if use_session:
            chunk_rows = await _fetch(session)
        else:
            async with _async_session() as sess:
                chunk_rows = await _fetch(sess)

        # --- Step 5: Reranker (always runs -- not skippable per spec) ---
        # Build ordered list matching rrf_candidates order for score alignment.
        ordered_ids = [cid for cid, _, _ in rrf_candidates if cid in chunk_rows]
        documents_text = [chunk_rows[cid].content for cid in ordered_ids]

        instruction = _detect_instruction(query)
        reranker_scores = await asyncio.to_thread(
            self._reranker.compute_scores, query, documents_text, instruction
        )
        # reranker_scores[i] corresponds to ordered_ids[i]

        # --- Step 6: Build ChunkResult list and apply filters ---
        # Index rrf candidates by chunk_id for score lookup
        rrf_by_id = {
            cid: (rrf_score, leg_scores)
            for cid, rrf_score, leg_scores in rrf_candidates
        }

        chunk_results: list[ChunkResult] = []
        for chunk_id, reranker_score in zip(ordered_ids, reranker_scores):
            row = chunk_rows[chunk_id]
            rrf_score, leg_scores = rrf_by_id[chunk_id]

            if min_score is not None and reranker_score < min_score:
                continue

            chunk_results.append(
                ChunkResult(
                    chunk_id=chunk_id,
                    document_id=row.document_id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    display_content=row.display_content,
                    source_filename=row.filename,
                    page_number=row.page_number,
                    section_heading=row.section_heading,
                    chunk_type=row.chunk_type,
                    bm25_score=leg_scores.get("bm25", 0.0),
                    dense_score=leg_scores.get("dense", 0.0),
                    sparse_score=leg_scores.get("sparse", 0.0),
                    rrf_score=rrf_score,
                    reranker_score=reranker_score,
                )
            )

        # Sort by reranker score descending (reranker is the final ranker)
        chunk_results.sort(key=lambda r: r.reranker_score, reverse=True)

        total_candidates = len(ordered_ids)
        final_results = chunk_results[:top_k]

        logger.info(
            "RetrievalEngine: query=%r top_k=%d candidates=%d returned=%d",
            query[:80],
            top_k,
            total_candidates,
            len(final_results),
        )

        return RetrievalResult(
            query=query,
            results=final_results,
            total_candidates=total_candidates,
        )
