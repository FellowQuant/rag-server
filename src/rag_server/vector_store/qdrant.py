"""Async Qdrant client wrapper for the RAG server vector store."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient  # NOT QdrantClient — sync causes deadlocks in FastAPI
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PointStruct,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

from rag_server.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Dense embedding dimension for BGE-M3
DENSE_DIM = 1024


@dataclass
class VectorSearchResult:
    """Single result from dense or sparse Qdrant search."""
    chunk_id: str           # UUID matching SQLite chunks.id
    score: float            # Cosine similarity (dense) or dot product (sparse)
    payload: dict           # document_id, chunk_type, page_number, section_heading, chunk_index


class QdrantStore:
    """Async wrapper around Qdrant for chunk storage and retrieval.

    The collection schema is set once in ensure_collection() and is immutable
    in Qdrant — sparse_vectors_config MUST be declared here even though Phase 1
    only writes dense vectors. Adding sparse fields later requires dropping the
    collection (data loss). See research finding #1.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # check_compatibility=False suppresses the UserWarning when client and server minor
        # versions differ. Server upgraded to v1.16.3 (matches client 1.16.2); kept as
        # belt-and-suspenders for any future drift.
        self._client = AsyncQdrantClient(
            url=self._settings.qdrant_url,
            check_compatibility=False,  # suppress version-mismatch UserWarning
        )
        self._collection = self._settings.qdrant_collection

    async def ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not exist.

        Idempotent — safe to call on every startup.
        Schema is fixed: dense (1024d, cosine) + sparse (on_disk=False).
        """
        try:
            await self._client.get_collection(self._collection)
            logger.info("Qdrant collection '%s' already exists", self._collection)
        except (UnexpectedResponse, Exception) as exc:
            # Collection does not exist — create it
            # CRITICAL: sparse_vectors_config must be set NOW — cannot add later without data loss
            logger.info("Creating Qdrant collection '%s'", self._collection)
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config={
                    "dense": VectorParams(size=DENSE_DIM, distance=Distance.COSINE)
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(
                        index=SparseIndexParams(on_disk=False)
                    )
                },
            )
            logger.info("Collection '%s' created successfully", self._collection)

    async def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
    ) -> None:
        """Upsert chunk points into Qdrant with dense + sparse vectors.

        Each chunk dict must contain:
            id: str                      — UUID matching chunks.id in SQLite
            dense_vector: list[float]    — 1024-element BGE-M3 dense embedding
            sparse_indices: list[int]    — BGE-M3 lexical weight token IDs (raw ints)
            sparse_values: list[float]   — corresponding lexical weight floats
            payload: dict                — document_id, chunk_type, page_number,
                                           section_heading, chunk_index

        Points are upserted in a single call. wait=True ensures points are
        searchable before this method returns.
        """
        from qdrant_client.models import SparseVector

        points = [
            PointStruct(
                id=chunk["id"],
                vector={
                    "dense": chunk["dense_vector"],
                    "sparse": SparseVector(
                        indices=chunk["sparse_indices"],
                        values=chunk["sparse_values"],
                    ),
                },
                payload=chunk["payload"],
            )
            for chunk in chunks
        ]
        await self._client.upsert(
            collection_name=self._collection,
            points=points,
            wait=True,
        )

    async def delete_document(self, document_id: str) -> None:
        """Delete all Qdrant points associated with a document.

        Uses payload filter on document_id field. Called when a document is
        deleted from SQLite — keeps both stores in sync.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        await self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            ),
        )

    async def get_collection_info(self) -> dict[str, Any]:
        """Return collection stats (points_count, indexed_vectors_count, etc.).

        Note: vectors_count was removed from CollectionInfo in qdrant-client >=1.14.
        Use points_count for the total number of indexed points.
        """
        info = await self._client.get_collection(self._collection)
        return {
            "name": self._collection,
            # vectors_count removed in qdrant-client >=1.14 — use points_count
            "points_count": info.points_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "segments_count": info.segments_count,
            "status": info.status,
        }

    async def query_dense(
        self,
        dense_vector: list[float],
        limit: int = 50,
        query_filter: Filter | None = None,
    ) -> list[VectorSearchResult]:
        """Search collection by dense (cosine) vector similarity.

        Args:
            dense_vector: 1024-dimensional BGE-M3 dense embedding for the query.
            limit: Maximum number of results to return (use candidate pool size,
                   e.g. 50, not final top_k — reranker narrows to top_k later).
            query_filter: Optional Qdrant Filter to restrict the search scope
                          (e.g. to specific document_ids). When None, global
                          search is performed (backward compatible default).

        Returns:
            List of VectorSearchResult sorted by score descending.
        """
        result = await self._client.query_points(
            collection_name=self._collection,
            query=dense_vector,
            using="dense",
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
        return [
            VectorSearchResult(
                chunk_id=str(p.id),
                score=p.score,
                payload=p.payload or {},
            )
            for p in result.points
        ]

    async def query_sparse(
        self,
        sparse_indices: list[int],
        sparse_values: list[float],
        limit: int = 50,
        query_filter: Filter | None = None,
    ) -> list[VectorSearchResult]:
        """Search collection by sparse (learned term weight) vector similarity.

        Args:
            sparse_indices: BGE-M3 lexical weight token IDs (raw ints).
            sparse_values: Corresponding lexical weight floats.
            limit: Maximum number of results to return.
            query_filter: Optional Qdrant Filter to restrict the search scope
                          (e.g. to specific document_ids). When None, global
                          search is performed (backward compatible default).

        Returns:
            List of VectorSearchResult sorted by score descending.
            Returns empty list if sparse_indices is empty (avoids Qdrant error
            on empty sparse vector).
        """
        if not sparse_indices:
            return []

        from qdrant_client.models import SparseVector

        result = await self._client.query_points(
            collection_name=self._collection,
            query=SparseVector(indices=sparse_indices, values=sparse_values),
            using="sparse",
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
        return [
            VectorSearchResult(
                chunk_id=str(p.id),
                score=p.score,
                payload=p.payload or {},
            )
            for p in result.points
        ]

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
