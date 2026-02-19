"""FellowQuant RAG Server — FastAPI application entry point.

CRITICAL: multiprocessing.set_start_method("spawn", force=True) must be called
BEFORE any imports of torch, docling, or FlagEmbedding. The spawn method creates
a fresh Python interpreter for worker subprocesses, preventing CUDA fork issues
on Linux (forking after CUDA init causes undefined behavior).

This file is the only place set_start_method is called; it must be the first
import in any process that starts the FastAPI app.
"""
import multiprocessing

# MUST be before any CUDA-related imports (torch, docling, FlagEmbedding).
multiprocessing.set_start_method("spawn", force=True)

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rag_server.config import get_settings
from rag_server.database.engine import async_session, engine
from rag_server.database.models import Base
from rag_server.vector_store.qdrant import QdrantStore
from rag_server.worker.manager import WorkerManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: startup → yield → shutdown.

    Startup:
      1. Create DATA_DIR subdirectories (data/, data/uploads/, data/qdrant/)
      2. Create SQLite tables (idempotent — does not migrate, only creates)
      3. Ensure Qdrant collection exists with dense+sparse schema
      4. Start ingestion worker process (loads BGE-M3 and DocumentConverter)

    Shutdown:
      5. Stop worker process (waits up to 30s, then terminates)
      6. Close Qdrant HTTP client
    """
    settings = get_settings()
    settings.ensure_data_dirs()

    # Create SQLite tables if they don't exist.
    # In production, use Alembic migrations instead. This is a safety fallback.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize Qdrant collection (idempotent).
    qdrant_store = QdrantStore(settings)
    await qdrant_store.ensure_collection()
    app.state.qdrant_store = qdrant_store

    # Start ingestion worker process.
    worker_manager = WorkerManager()
    worker_manager.start()
    app.state.worker_manager = worker_manager

    logger.info("RAG Server started (DATA_DIR=%s)", settings.data_dir)
    yield

    # Shutdown.
    worker_manager.stop()
    await qdrant_store.close()
    await engine.dispose()
    logger.info("RAG Server shutdown complete")


app = FastAPI(
    title="FellowQuant RAG Server",
    description="Document ingestion and retrieval for quantitative finance research",
    version="0.2.0",
    lifespan=lifespan,
)

# Mount document lifecycle router.
from rag_server.api.documents import router as documents_router  # noqa: E402
app.include_router(documents_router)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
