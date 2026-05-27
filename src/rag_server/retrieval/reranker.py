"""Qwen3-Reranker-0.6B cross-encoder reranker for retrieval pipeline.

Uses the official Qwen3-Reranker-0.6B inference pattern from
https://huggingface.co/Qwen/Qwen3-Reranker-0.6B:
  - AutoModelForCausalLM (NOT sequence classification — official weights require causal LM)
  - padding_side="left" on tokenizer — load-bearing: causal LM reads final token position
    (logits[:, -1, :]); right-padding shifts this position away from the meaningful token
  - yes/no logit extraction at final output position → log_softmax → relevance probability
  - Chat-format prompt with system message, <Instruct>, <Query>, <Document> tags, and
    <think> suffix block

CRITICAL: Do NOT use CrossEncoder from sentence-transformers for official Qwen3 weights.
CrossEncoder requires tomaarsen/Qwen3-Reranker-0.6B-seq-cls (converted weights, different
checkpoint). The inference pattern here uses the official Qwen/Qwen3-Reranker-0.6B weights.

VRAM: ~1.2 GB fp16 VRAM in FastAPI process. BGE-M3 in worker (~1 GB) is a separate
process. Shared GPU steady-state peak = ~2.2 GB. Monitor VRAM under load.

Threading: compute_scores() is synchronous and GPU-bound. Always call via:
    scores = await asyncio.to_thread(reranker.compute_scores, query, documents)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger(__name__)

_DEFAULT_INSTRUCTION = (
    "Given a search query, retrieve relevant passages that answer the query"
)

# Batch size for reranker inference. Reduce to 4 if CUDA OOM.
DEFAULT_BATCH_SIZE = 8


class Reranker:
    """Stateful Qwen3-Reranker-0.6B cross-encoder. Instantiate once per FastAPI app.

    Usage:
        reranker = Reranker()
        reranker.load()    # downloads/loads model (~1.2 GB VRAM), ~5-10s
        scores = reranker.compute_scores(query, documents)
        # later, on shutdown:
        reranker.unload()  # frees VRAM
    """

    MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"

    def __init__(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self._batch_size = batch_size
        self._model: "AutoModelForCausalLM | None" = None
        self._tokenizer: "AutoTokenizer | None" = None
        self._token_true_id: int | None = None
        self._token_false_id: int | None = None
        self._prefix_tokens: list[int] | None = None
        self._suffix_tokens: list[int] | None = None
        # 2048 is safe for our chunks (512 tiktoken ≈ 600-800 Qwen tokens + prefix/suffix).
        # The original 8192 caused padding to 8192 tokens even for short sequences.
        self._max_length: int = 2048

    def load(self, device: str | None = None) -> None:
        """Load Qwen3-Reranker-0.6B into memory.

        Args:
            device: Target device string (e.g. 'cuda', 'cpu'). Auto-detected
                    from torch.cuda.is_available() if None.
        """
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info("Reranker: loading %s (fp16, device=%s)...", self.MODEL_ID, device)

        # padding_side="left" is LOAD-BEARING:
        # causal LM reads logits[:, -1, :] (final token position).
        # Right-padding (default) shifts the model's output away from -1.
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.MODEL_ID,
            padding_side="left",
        )
        self._model = (
            AutoModelForCausalLM.from_pretrained(
                self.MODEL_ID,
                torch_dtype=torch.float16,
            )
            .to(device)
            .eval()
        )

        # Resolve yes/no token IDs once at load time.
        self._token_true_id = self._tokenizer.convert_tokens_to_ids("yes")
        self._token_false_id = self._tokenizer.convert_tokens_to_ids("no")

        # Pre-encode the fixed prefix and suffix to avoid re-tokenizing per batch.
        # The prompt structure mirrors the official Qwen3-Reranker README exactly.
        prefix = (
            "<|im_start|>system\n"
            "Judge whether the Document meets the requirements based on the Query and "
            'the Instruct provided. Note that the answer can only be "yes" or "no".'
            "<|im_end|>\n<|im_start|>user\n"
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self._prefix_tokens = self._tokenizer.encode(prefix, add_special_tokens=False)
        self._suffix_tokens = self._tokenizer.encode(suffix, add_special_tokens=False)

        logger.info(
            "Reranker: model loaded (yes_id=%d, no_id=%d, device=%s)",
            self._token_true_id,
            self._token_false_id,
            device,
        )

    def unload(self) -> None:
        """Delete model references to allow CUDA VRAM reclamation."""
        if self._model is not None:
            del self._model
            self._model = None
        self._tokenizer = None
        logger.info("Reranker: model unloaded")

    def _format_pair(self, query: str, document: str, instruction: str) -> str:
        return f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {document}"

    @torch.no_grad()
    def compute_scores(
        self,
        query: str,
        documents: list[str],
        instruction: str = _DEFAULT_INSTRUCTION,
    ) -> list[float]:
        """Compute relevance scores for (query, document) pairs.

        Synchronous and GPU-bound. Call via asyncio.to_thread():
            scores = await asyncio.to_thread(reranker.compute_scores, query, docs)

        Args:
            query: Plain text query string.
            documents: List of document/chunk content strings to score.
            instruction: Task instruction prepended to the prompt. Default
                         is tuned for passage retrieval.

        Returns:
            List of float scores in [0.0, 1.0] in the same order as documents.
            Higher = more relevant. Empty list if documents is empty.

        Raises:
            RuntimeError: If load() has not been called.
        """
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("Reranker.load() must be called before compute_scores()")

        if not documents:
            return []

        pairs = [self._format_pair(query, doc, instruction) for doc in documents]

        # Patch lm_head to compute logits only for the final token position.
        #
        # The default forward pass computes lm_head(hidden_states[:, ALL_POSITIONS, :])
        # producing (batch, seq_len, vocab_size). For batch=8, seq_len≈2000, vocab=151936
        # at fp16 that is ~4.87 GiB — causing OOM when the GPU is also running llama.cpp.
        #
        # The patch intercepts the lm_head input and slices to the last position only,
        # producing (batch, 1, vocab_size) = ~2.4 MB regardless of sequence length.
        # This is correct because Qwen3-Reranker only reads logits[:, -1, :] for scoring.
        #
        # num_logits_to_keep=1 is the official API for this but is silently ignored by
        # some transformers versions when called via __call__ rather than generate().
        orig_lm_head_fwd = self._model.lm_head.forward
        self._model.lm_head.forward = lambda x: orig_lm_head_fwd(x[:, -1:, :])

        batch_size = self._batch_size
        try:
            while True:
                # Pre-emptively free cached allocations so inference has maximum headroom.
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                try:
                    all_scores: list[float] = []
                    for i in range(0, len(pairs), batch_size):
                        batch_pairs = pairs[i : i + batch_size]

                        # Step 1: Tokenize body text only (no padding yet).
                        body_max = (
                            self._max_length
                            - len(self._prefix_tokens)
                            - len(self._suffix_tokens)
                        )
                        inputs = self._tokenizer(
                            batch_pairs,
                            padding=False,
                            truncation=True,
                            return_attention_mask=False,
                            max_length=body_max,
                        )

                        # Step 2: Wrap each body with pre-encoded prefix + suffix tokens.
                        for j in range(len(inputs["input_ids"])):
                            inputs["input_ids"][j] = (
                                self._prefix_tokens
                                + inputs["input_ids"][j]
                                + self._suffix_tokens
                            )

                        # Step 3: Pad batch to longest sequence in this batch only.
                        padded = self._tokenizer.pad(
                            inputs,
                            padding=True,
                            return_tensors="pt",
                        )
                        padded = {
                            k: v.to(self._model.device) for k, v in padded.items()
                        }

                        # Step 4: Forward pass. lm_head patch ensures output is
                        # (batch, 1, vocab) not (batch, seq_len, vocab). logits[:, -1, :]
                        # selects the single kept position → (batch, vocab_size).
                        logits = self._model(**padded).logits[:, -1, :]
                        true_logit = logits[:, self._token_true_id]
                        false_logit = logits[:, self._token_false_id]

                        stacked = torch.stack([false_logit, true_logit], dim=1)
                        log_probs = torch.nn.functional.log_softmax(stacked, dim=1)
                        all_scores.extend(log_probs[:, 1].exp().tolist())

                    return all_scores  # success

                except torch.cuda.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    next_batch_size = batch_size // 2
                    if next_batch_size < 1:
                        # GPU OOM even at batch_size=1. Return neutral scores so the
                        # server does not crash — RRF ordering is preserved upstream.
                        logger.error(
                            "Reranker: GPU OOM at batch_size=1 — returning neutral scores. "
                            "RRF ranking preserved. Consider setting RERANKER_DEVICE=cpu."
                        )
                        return [0.5] * len(documents)
                    logger.warning(
                        "Reranker: GPU OOM at batch_size=%d, retrying with batch_size=%d",
                        batch_size,
                        next_batch_size,
                    )
                    batch_size = next_batch_size
        finally:
            self._model.lm_head.forward = orig_lm_head_fwd
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
