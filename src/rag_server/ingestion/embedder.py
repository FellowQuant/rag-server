"""BGE-M3 embedding wrapper for the ingestion pipeline.

Wraps BGEM3FlagModel (FlagEmbedding library) to produce dense (1024d) and
sparse (lexical weight) vectors from ParsedChunk content strings.

Key design decisions:
- Embedder is instantiated ONCE at worker startup and reused across all jobs.
  Do not instantiate inside per-document pipeline functions.
- lexical_weights keys are raw int token IDs from the XLM-RoBERTa tokenizer.
  They are used DIRECTLY as Qdrant SparseVector indices — do NOT call
  convert_id_to_token() which returns string keys (Qdrant needs ints).
- Default batch_size=8 balances throughput vs VRAM. Reduce to 4 if OOM.
- Empty content strings return a zero dense vector and empty sparse vectors
  rather than crashing, so the pipeline can still store the chunk.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from FlagEmbedding import BGEM3FlagModel

from rag_server.ingestion.chunker import ParsedChunk

logger = logging.getLogger(__name__)

DENSE_DIM = 1024          # BGE-M3 dense output dimensionality
DEFAULT_BATCH_SIZE = 8    # Reduce to 4 if CUDA OOM during embedding
MAX_LENGTH = 512          # Token limit per chunk (matches chunker.MAX_TOKENS)


@dataclass
class EmbeddingResult:
    """Dense + sparse vectors for a single chunk, ready for Qdrant upsert."""
    chunk_index: int
    dense_vector: list[float]       # 1024-dimensional float list
    sparse_indices: list[int]       # BGE-M3 lexical weight token IDs (raw ints)
    sparse_values: list[float]      # Corresponding lexical weight floats


class Embedder:
    """Stateful BGE-M3 embedder. Instantiate once per worker process.

    Usage:
        embedder = Embedder()
        embedder.load()                    # downloads/loads model (~1 GB VRAM)
        results = embedder.embed_chunks(chunks)
        # later, on shutdown:
        embedder.unload()                  # frees VRAM
    """

    def __init__(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self._batch_size = batch_size
        self._model: BGEM3FlagModel | None = None

    def load(self) -> None:
        """Load BGE-M3 model into memory. Blocks until model is ready (~5-10s)."""
        logger.info("Embedder: loading BAAI/bge-m3 (use_fp16=True)...")
        self._model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
        logger.info("Embedder: model loaded, batch_size=%d", self._batch_size)

    def unload(self) -> None:
        """Delete model reference to allow CUDA VRAM reclamation."""
        if self._model is not None:
            del self._model
            self._model = None
            logger.info("Embedder: model unloaded")

    def embed_chunks(self, chunks: list[ParsedChunk]) -> list[EmbeddingResult]:
        """Embed a list of ParsedChunk objects.

        Processes chunks in batches. Empty-content chunks receive a zero dense
        vector and empty sparse vectors — they are still stored in Qdrant so
        the chunk_index sequence remains intact for retrieval.

        Args:
            chunks: List of ParsedChunk from any parser.

        Returns:
            List of EmbeddingResult in the same order as input chunks.
        """
        if self._model is None:
            raise RuntimeError("Embedder.load() must be called before embed_chunks()")

        if not chunks:
            return []

        results: list[EmbeddingResult] = []

        # Process in batches to bound peak VRAM usage.
        for batch_start in range(0, len(chunks), self._batch_size):
            batch = chunks[batch_start : batch_start + self._batch_size]
            texts = [c.content for c in batch]

            # Separate empty texts to avoid model errors; they get zero vectors.
            non_empty_indices = [i for i, t in enumerate(texts) if t.strip()]
            non_empty_texts = [texts[i] for i in non_empty_indices]

            # Pre-populate with zero vectors for empty texts.
            batch_results: list[EmbeddingResult | None] = [None] * len(batch)
            for i, chunk in enumerate(batch):
                if i not in non_empty_indices:
                    batch_results[i] = EmbeddingResult(
                        chunk_index=chunk.chunk_index,
                        dense_vector=[0.0] * DENSE_DIM,
                        sparse_indices=[],
                        sparse_values=[],
                    )

            if non_empty_texts:
                output = self._model.encode(
                    non_empty_texts,
                    batch_size=self._batch_size,
                    max_length=MAX_LENGTH,
                    return_dense=True,
                    return_sparse=True,
                    return_colbert_vecs=False,  # not used in Phase 2; saves VRAM
                )
                dense_vecs: np.ndarray = output["dense_vecs"]        # shape (N, 1024)
                lexical_weights: list[dict[int, float]] = output["lexical_weights"]

                for result_pos, original_idx in enumerate(non_empty_indices):
                    raw: dict[int, float] = lexical_weights[result_pos]
                    # CRITICAL: raw keys are int token IDs — use directly as
                    # Qdrant sparse indices. Do NOT call convert_id_to_token().
                    batch_results[original_idx] = EmbeddingResult(
                        chunk_index=batch[original_idx].chunk_index,
                        dense_vector=dense_vecs[result_pos].tolist(),
                        sparse_indices=list(raw.keys()),
                        sparse_values=list(raw.values()),
                    )

            results.extend(r for r in batch_results if r is not None)

        logger.debug("Embedder: embedded %d chunks", len(results))
        return results
