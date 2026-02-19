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

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rag_server.api.errors import register_exception_handlers
from rag_server.api.middleware import LoggingMiddleware, UploadSizeLimitMiddleware
from rag_server.config import get_settings
from rag_server.database.engine import async_session, engine
from rag_server.database.models import Base
from rag_server.ingestion.embedder import Embedder
from rag_server.llm.config import get_llm_settings
from rag_server.llm.provider import create_provider
from rag_server.llm.synthesis import SynthesisEngine
from rag_server.retrieval.bm25_manager import BM25Manager
from rag_server.retrieval.engine import RetrievalEngine
from rag_server.retrieval.reranker import Reranker
from rag_server.vector_store.qdrant import QdrantStore
from rag_server.worker.manager import WorkerManager

logger = logging.getLogger(__name__)


async def _poll_bm25_updates(
    result_queue: multiprocessing.Queue,
    bm25_manager: BM25Manager,
) -> None:
    """Background asyncio task: poll worker result_queue and rebuild BM25 on signals.

    Runs as a long-lived asyncio.Task created in lifespan. Cancelled on shutdown.
    Uses asyncio.to_thread for the queue.get_nowait() call to avoid blocking
    the event loop on a busy-wait.
    """
    while True:
        try:
            def _get_nowait():
                try:
                    return result_queue.get_nowait()
                except Exception:
                    return None

            msg = await asyncio.to_thread(_get_nowait)
            if msg and msg.get("type") == "indexed":
                logger.info(
                    "BM25 update signal received for document %s, rebuilding index",
                    msg.get("document_id"),
                )
                async with async_session() as session:
                    await bm25_manager.build(session)
                logger.info("BM25 index rebuilt (%d chunks)", bm25_manager.chunk_count)
            else:
                # No message -- sleep briefly before polling again
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("BM25 poll task cancelled -- shutting down")
            break
        except Exception:
            logger.exception("BM25 poll task: unexpected error, continuing")
            await asyncio.sleep(1.0)


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

    # Initialize BM25 index.
    bm25_pkl = settings.data_dir / "bm25.pkl"
    bm25_manager = BM25Manager(bm25_pkl)

    # Try loading from disk first (fast path); rebuild from SQLite if not found.
    disk_loaded = await asyncio.to_thread(bm25_manager.load_from_disk)
    if not disk_loaded:
        logger.info("BM25: no pickle found, building from SQLite...")
        async with async_session() as session:
            await bm25_manager.build(session)

    app.state.bm25_manager = bm25_manager
    logger.info("BM25 index ready (%d chunks)", bm25_manager.chunk_count)

    # Start background task that rebuilds BM25 when worker signals new documents.
    bm25_poll_task = asyncio.create_task(
        _poll_bm25_updates(worker_manager.result_queue, bm25_manager),
        name="bm25-poll",
    )

    # Load query-side BGE-M3 embedder in the FastAPI process.
    # IMPORTANT: This is a SEPARATE instance from the worker process's embedder.
    # The worker's instance lives in a different OS process (multiprocessing.spawn).
    # FastAPI needs its own instance for query-time encode_query() calls.
    query_embedder = Embedder()
    await asyncio.to_thread(query_embedder.load)
    logger.info("Query embedder (BGE-M3) loaded in FastAPI process")

    # Load Qwen3-Reranker-0.6B in FastAPI process.
    # VRAM: ~1.2 GB fp16. BGE-M3 worker uses ~1 GB in separate process.
    # Shared GPU steady-state peak ~2.2 GB — monitor with nvidia-smi under load.
    reranker = Reranker()
    await asyncio.to_thread(reranker.load)
    logger.info("Reranker (Qwen3-Reranker-0.6B) loaded in FastAPI process")

    # Wire the RetrievalEngine from all loaded components.
    retrieval_engine = RetrievalEngine(
        embedder=query_embedder,
        qdrant_store=qdrant_store,
        bm25_manager=bm25_manager,
        reranker=reranker,
    )
    app.state.retrieval_engine = retrieval_engine
    logger.info("RetrievalEngine ready")

    # ---------------------------------------------------------------------------
    # Phase 4: LLM Integration
    # ---------------------------------------------------------------------------
    # Load LLM settings from llm.yaml (project root)
    llm_settings = get_llm_settings()
    logger.info(
        "LLM provider: %s (model=%s)",
        llm_settings.llm.provider,
        llm_settings.llm.model,
    )

    # Instantiate the configured provider (AsyncOpenAI client or BedrockProvider)
    # Provider is lightweight to create — no network connection at init time.
    llm_provider = create_provider(llm_settings.llm)
    app.state.llm_provider = llm_provider

    # Wire SynthesisEngine with provider and LLM config
    synthesis_engine = SynthesisEngine(
        provider=llm_provider,
        config=llm_settings.llm,
    )
    app.state.synthesis_engine = synthesis_engine
    logger.info(
        "SynthesisEngine ready (context_chunks=%d, max_context_tokens=%d)",
        llm_settings.llm.context_chunks,
        llm_settings.llm.max_context_tokens,
    )

    logger.info("RAG Server started (DATA_DIR=%s)", settings.data_dir)
    yield

    # Shutdown: cancel BM25 poll task first, then stop worker.
    bm25_poll_task.cancel()
    try:
        await bm25_poll_task
    except asyncio.CancelledError:
        pass

    worker_manager.stop()

    # Unload retrieval models to free VRAM.
    await asyncio.to_thread(reranker.unload)
    await asyncio.to_thread(query_embedder.unload)

    await qdrant_store.close()
    await engine.dispose()
    logger.info("RAG Server shutdown complete")


app = FastAPI(
    title="FellowQuant RAG Server",
    description="Document ingestion and retrieval for quantitative finance research",
    version="0.5.0",
    lifespan=lifespan,
)

# Register RFC 7807 exception handlers (before middleware and routers)
register_exception_handlers(app)

# Add middleware (LIFO order — last added becomes outermost)
# Desired runtime order: CORS → Logging → UploadSizeLimit → Router
# Add in reverse: UploadSizeLimit first (innermost), CORS last (outermost)
app.add_middleware(UploadSizeLimitMiddleware, max_upload_size=get_settings().max_upload_size)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount document lifecycle router.
from rag_server.api.documents import router as documents_router  # noqa: E402
app.include_router(documents_router, prefix="/api/v1")

from rag_server.api.ask import router as ask_router  # noqa: E402
app.include_router(ask_router, prefix="/api/v1")

from rag_server.api.retrieve import router as retrieve_router  # noqa: E402
app.include_router(retrieve_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
