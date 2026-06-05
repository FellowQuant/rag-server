from __future__ import annotations

import numpy as np
import torch

from rag_server.ingestion.chunker import ParsedChunk
from rag_server.ingestion.embedder import Embedder
from rag_server.retrieval.reranker import Reranker


class FakeBgeM3Model:
    def __init__(self) -> None:
        self.encode_kwargs = None
        self.encode_queries_kwargs = None

    def encode(self, texts, **kwargs):
        self.encode_kwargs = kwargs
        return {
            "dense_vecs": np.zeros((len(texts), 1024), dtype=np.float32),
            "lexical_weights": [{} for _ in texts],
        }

    def encode_queries(self, queries, **kwargs):
        self.encode_queries_kwargs = kwargs
        return {
            "dense_vecs": np.zeros((len(queries), 1024), dtype=np.float32),
            "lexical_weights": [{} for _ in queries],
        }


def test_embed_chunks_disables_upstream_fast_tokenizer_pad_warning() -> None:
    model = FakeBgeM3Model()
    embedder = Embedder(batch_size=2)
    embedder._model = model

    embedder.embed_chunks([ParsedChunk(chunk_type="text", content="content")])

    assert model.encode_kwargs["verbose"] is False


def test_encode_query_disables_upstream_fast_tokenizer_pad_warning() -> None:
    model = FakeBgeM3Model()
    embedder = Embedder()
    embedder._model = model

    embedder.encode_query("query")

    assert model.encode_queries_kwargs["verbose"] is False


class FakeRerankerTokenizer:
    def __init__(self) -> None:
        self.pad_kwargs = None

    def __call__(self, texts, **kwargs):
        return {
            "input_ids": [[10 + i] for i, _ in enumerate(texts)],
        }

    def pad(self, inputs, **kwargs):
        self.pad_kwargs = kwargs
        return {
            "input_ids": torch.tensor(inputs["input_ids"]),
            "attention_mask": torch.ones(
                (len(inputs["input_ids"]), len(inputs["input_ids"][0])),
                dtype=torch.long,
            ),
        }


class FakeLmHead:
    def __init__(self) -> None:
        self.forward = lambda x: x


class FakeRerankerModel:
    def __init__(self) -> None:
        self.device = torch.device("cpu")
        self.lm_head = FakeLmHead()

    def __call__(self, **kwargs):
        batch_size = kwargs["input_ids"].shape[0]
        logits = torch.zeros((batch_size, 1, 2), dtype=torch.float32)
        logits[:, :, 1] = 2.0
        return type("ModelOutput", (), {"logits": logits})()


def test_reranker_disables_fast_tokenizer_pad_warning() -> None:
    tokenizer = FakeRerankerTokenizer()
    reranker = Reranker(batch_size=2)
    reranker._tokenizer = tokenizer
    reranker._model = FakeRerankerModel()
    reranker._prefix_tokens = [1]
    reranker._suffix_tokens = [2]
    reranker._token_false_id = 0
    reranker._token_true_id = 1

    reranker.compute_scores("query", ["doc"])

    assert tokenizer.pad_kwargs["verbose"] is False
