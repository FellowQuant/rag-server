"""Worker process entry point.

Loads BGE-M3 and DocumentConverter once at startup, then processes
IngestionJob objects from the multiprocessing.Queue serially until a None
sentinel is received or the stop_event is set.

CRITICAL: This module must NOT be imported in the FastAPI process before
multiprocessing.set_start_method("spawn") is called. The Process target
is specified as a string path or by importing after spawn is set.

The worker runs in a completely separate OS process:
  - No shared memory with FastAPI
  - No asyncio event loop (uses sync SQLAlchemy)
  - Owns VRAM for BGE-M3 and Docling models

Model loading strategy:
  - Embedder (BGE-M3): loaded via embedder.load() -- ~5-10s, ~1 GB VRAM
  - DocumentConverter (Docling): built via make_converter() -- ~10-20s, high
    VRAM. Both are loaded ONCE at startup and reused for every job.
    Per-document construction would make PDF indexing prohibitively slow.
"""

from __future__ import annotations

import logging
import multiprocessing

logger = logging.getLogger(__name__)


def worker_main(
    job_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
) -> None:
    """Entry point for the worker subprocess.

    Called as the target of multiprocessing.Process. Loads BGE-M3 and
    DocumentConverter once, then runs a blocking loop consuming jobs from
    job_queue.

    Args:
        job_queue: Shared queue populated by WorkerManager.enqueue() in the
                   FastAPI process. Jobs are IngestionJob dataclass instances.
                   A None sentinel signals shutdown.
        result_queue: Queue for sending signals back to the FastAPI process
                      (e.g., BM25 rebuild needed after successful indexing).
        stop_event: Set by WorkerManager.stop() to break the loop even if no
                    sentinel is in the queue.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [worker] %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "Worker process started (PID %d)", multiprocessing.current_process().pid
    )

    from rag_server.ingestion.embedder import Embedder

    from rag_server.config import get_settings

    settings = get_settings()
    embedder = Embedder(batch_size=settings.indexer_embed_batch_size)
    try:
        embedder.load()
    except Exception:
        logger.exception("Worker: failed to load BGE-M3 model -- exiting")
        return

    # Load DocumentConverter once. This is expensive (~10-20s, high VRAM) and
    # must NOT be done per-document. Pass to run_pipeline() for reuse.
    converter = None
    try:
        from rag_server.ingestion.parsers.pdf_parser import make_converter

        converter = make_converter(use_gpu=True)
        logger.info("Worker: DocumentConverter loaded")
    except Exception:
        logger.exception(
            "Worker: failed to load DocumentConverter -- PDF jobs will fail"
        )
        # Non-fatal: .tex, .ipynb, and .epub jobs can still proceed; PDF jobs will
        # fall back to on-demand construction (slow) inside _dispatch_parser.

    logger.info("Worker: ready to process jobs")

    while not stop_event.is_set():
        try:
            # Timeout allows stop_event to be checked periodically.
            job = job_queue.get(timeout=1.0)
        except Exception:
            # multiprocessing.queues.Empty raised on timeout -- loop and check stop_event.
            continue

        if job is None:
            # Poison pill sentinel -- clean shutdown requested.
            logger.info("Worker: received shutdown sentinel")
            break

        try:
            from rag_server.worker.pipeline import run_pipeline

            run_pipeline(job, converter, embedder, result_queue)
        except Exception:
            logger.exception(
                "Worker: uncaught error processing job %s",
                getattr(job, "document_id", "unknown"),
            )

    logger.info("Worker: shutting down, releasing models")
    embedder.unload()
    logger.info("Worker: shutdown complete")
