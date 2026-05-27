"""WorkerManager: lifecycle management for the ingestion worker process.

Used by FastAPI lifespan to start and stop the worker process. The FastAPI
app holds a single WorkerManager instance and calls:
  - manager.start() in lifespan startup
  - manager.enqueue(job) in POST /documents
  - manager.stop() in lifespan shutdown

CRITICAL: multiprocessing.set_start_method("spawn", force=True) must be
called at the top of main.py BEFORE any torch/cuda imports (including
docling and FlagEmbedding). The "spawn" method creates a fresh Python
interpreter for the worker, avoiding CUDA fork undefined behavior on Linux.
"""

from __future__ import annotations

import logging
import multiprocessing
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class IngestionJob:
    """Data passed from FastAPI process to worker process via multiprocessing.Queue.

    All fields are serializable (strings, ints) -- no SQLAlchemy objects or
    file handles.
    """

    document_id: str  # UUID string matching documents.id in SQLite
    file_path: str  # Absolute path to uploaded file on disk
    file_format: str  # "pdf" | "tex" | "ipynb" | "epub"
    original_filename: str  # For logging/error messages
    sqlite_url: str  # Full sqlite+aiosqlite:// URL from Settings
    qdrant_url: str  # Full http://host:port URL from Settings
    qdrant_collection: str  # Collection name from Settings


class WorkerManager:
    """Manages the lifecycle of the ingestion worker subprocess.

    Create one instance per FastAPI application (typically at module level
    or in lifespan). Thread-safe for enqueue() calls from concurrent requests.
    """

    def __init__(self) -> None:
        self._queue: multiprocessing.Queue | None = None
        self._result_queue: multiprocessing.Queue | None = None
        self._stop_event: multiprocessing.Event | None = None
        self._process: multiprocessing.Process | None = None

    def start(self) -> None:
        """Start the worker process. Call once from FastAPI lifespan startup.

        Creates the multiprocessing Queue and Event, then spawns the worker.
        The worker loads BGE-M3 asynchronously -- it is ready when BGE-M3 log
        message "Embedder: model loaded" appears.
        """
        self._queue = multiprocessing.Queue(maxsize=200)
        self._result_queue = multiprocessing.Queue(
            maxsize=200
        )  # worker->FastAPI signals
        self._stop_event = multiprocessing.Event()

        from rag_server.worker.process import worker_main

        self._process = multiprocessing.Process(
            target=worker_main,
            args=(
                self._queue,
                self._result_queue,
                self._stop_event,
            ),  # result_queue added
            daemon=True,
            name="rag-ingestion-worker",
        )
        self._process.start()
        logger.info("WorkerManager: worker process started (PID %d)", self._process.pid)

    def enqueue(self, job: IngestionJob) -> None:
        """Add an ingestion job to the worker queue.

        Non-blocking (queue maxsize=200 prevents unbounded growth). Raises
        queue.Full if the queue is at capacity -- caller should return 503.

        Args:
            job: IngestionJob with all fields populated.
        """
        if self._queue is None:
            raise RuntimeError("WorkerManager.start() must be called before enqueue()")
        self._queue.put_nowait(job)
        logger.debug("WorkerManager: enqueued job for document %s", job.document_id)

    def enqueue_blocking(self, job: IngestionJob) -> None:
        """Add an ingestion job and wait if the worker queue is temporarily full."""
        if self._queue is None:
            raise RuntimeError("WorkerManager.start() must be called before enqueue()")
        self._queue.put(job, block=True)
        logger.debug(
            "WorkerManager: enqueued recovery job for document %s", job.document_id
        )

    def stop(self) -> None:
        """Stop the worker process gracefully. Call from FastAPI lifespan shutdown.

        Sends stop signal and poison pill, waits up to 30s, then terminates.
        """
        if self._process is None:
            return

        logger.info("WorkerManager: stopping worker process")
        if self._stop_event:
            self._stop_event.set()
        if self._queue:
            try:
                self._queue.put_nowait(
                    None
                )  # poison pill in case blocked on queue.get()
            except Exception:
                pass

        self._process.join(timeout=30)
        if self._process.is_alive():
            logger.warning("WorkerManager: worker did not stop in 30s, terminating")
            self._process.terminate()
            self._process.join(timeout=5)

        logger.info("WorkerManager: worker stopped")

    @property
    def result_queue(self) -> multiprocessing.Queue:
        """Queue carrying worker->FastAPI signals (e.g., BM25 rebuild needed)."""
        if self._result_queue is None:
            raise RuntimeError(
                "WorkerManager.start() must be called before result_queue access"
            )
        return self._result_queue

    @property
    def is_running(self) -> bool:
        """True if the worker process is alive."""
        return self._process is not None and self._process.is_alive()
