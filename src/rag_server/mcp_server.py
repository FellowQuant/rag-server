import multiprocessing
multiprocessing.set_start_method("spawn", force=True)

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.exceptions import ToolError

from rag_server.config import get_settings
from rag_server.database.engine import async_session
from rag_server.ingestion.embedder import Embedder
from rag_server.llm.config import get_llm_settings
from rag_server.llm.provider import create_provider
from rag_server.llm.synthesis import SynthesisEngine
from rag_server.retrieval.bm25_manager import BM25Manager
from rag_server.retrieval.engine import RetrievalEngine
from rag_server.retrieval.reranker import Reranker
from rag_server.vector_store.qdrant import QdrantStore

# CRITICAL: all logging must go to stderr — stdout is the JSON-RPC transport channel.
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Holds all shared resources created in the MCP server lifespan."""

    retrieval_engine: RetrievalEngine
    synthesis_engine: SynthesisEngine
    qdrant_store: QdrantStore


@asynccontextmanager
async def lifespan(server: FastMCP):
    """MCP server lifespan: startup → yield AppContext → shutdown.

    Loads all retrieval and synthesis components for query-time use.
    Does NOT start the ingestion WorkerManager — the MCP server is query-only.
    BM25 is loaded from disk only (no rebuild); restart the server after
    indexing new documents to pick up a fresh index.
    """
    settings = get_settings()
    settings.ensure_data_dirs()

    # Qdrant setup
    qdrant_store = QdrantStore(settings)
    await qdrant_store.ensure_collection()

    # BM25 — load from disk only (no rebuild on MCP start; restart after indexing)
    bm25_pkl = settings.data_dir / "bm25.pkl"
    bm25_manager = BM25Manager(bm25_pkl)
    loaded = await asyncio.to_thread(bm25_manager.load_from_disk)
    if not loaded:
        logger.warning(
            "BM25: no pickle found — keyword search disabled until FastAPI builds index"
        )

    # Query embedder (BGE-M3) and Reranker — same as FastAPI lifespan
    query_embedder = Embedder()
    await asyncio.to_thread(query_embedder.load)
    logger.info("Query embedder (BGE-M3) loaded in MCP process")

    reranker = Reranker()
    await asyncio.to_thread(reranker.load)
    logger.info("Reranker (Qwen3-Reranker-0.6B) loaded in MCP process")

    retrieval_engine = RetrievalEngine(
        embedder=query_embedder,
        qdrant_store=qdrant_store,
        bm25_manager=bm25_manager,
        reranker=reranker,
    )

    # LLM — same as FastAPI lifespan
    llm_settings = get_llm_settings()
    llm_provider = create_provider(llm_settings.llm)
    synthesis_engine = SynthesisEngine(provider=llm_provider, config=llm_settings.llm)

    logger.info("MCP RAG Server ready")
    yield AppContext(
        retrieval_engine=retrieval_engine,
        synthesis_engine=synthesis_engine,
        qdrant_store=qdrant_store,
    )

    # Cleanup
    await asyncio.to_thread(reranker.unload)
    await asyncio.to_thread(query_embedder.unload)
    await qdrant_store.close()
    from rag_server.database.engine import engine as db_engine
    await db_engine.dispose()
    logger.info("MCP RAG Server shutdown complete")


mcp = FastMCP("rag-server", lifespan=lifespan)


@mcp.tool()
async def retrieve(
    ctx: Context,
    query: str,
    top_k: int = 10,
    document_ids: list[str] | None = None,
    min_score: float | None = None,
) -> dict:
    """Retrieve ranked chunks from the knowledge base with full citation metadata.

    Returns raw reranked chunks without LLM synthesis. Use this when you need
    to see source material directly or perform custom reasoning over chunks.

    Args:
        query: Search query string.
        top_k: Maximum number of chunks to return (default 10).
        document_ids: Optional list of document IDs to scope search.
        min_score: Optional reranker score threshold (0.0-1.0).

    Returns:
        dict with 'query', 'results' (list of chunk dicts), 'total_candidates'.
        Each chunk includes: chunk_id, document_id, content, display_content,
        source_filename, page_number, section_heading, chunk_type, rrf_score, reranker_score.
    """
    if top_k < 1 or top_k > 100:
        raise ToolError("INVALID_PARAM: top_k must be between 1 and 100")

    app_ctx: AppContext = ctx.request_context.lifespan_context
    engine = app_ctx.retrieval_engine

    try:
        result = await engine.search(
            query=query,
            top_k=top_k,
            min_score=min_score,
            document_ids=document_ids,
        )
    except Exception as exc:
        err = str(exc).lower()
        if "connect" in err or "qdrant" in err or "refused" in err:
            raise ToolError("QDRANT_UNAVAILABLE")
        raise ToolError(f"RETRIEVAL_ERROR: {exc}")

    return {
        "query": result.query,
        "results": [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "display_content": c.display_content,
                "source_filename": c.source_filename,
                "page_number": c.page_number,
                "section_heading": c.section_heading,
                "chunk_type": c.chunk_type,
                "bm25_score": c.bm25_score,
                "dense_score": c.dense_score,
                "sparse_score": c.sparse_score,
                "rrf_score": c.rrf_score,
                "reranker_score": c.reranker_score,
            }
            for c in result.results
        ],
        "total_candidates": result.total_candidates,
    }


@mcp.tool()
async def ask(
    ctx: Context,
    query: str,
    top_k: int = 10,
    document_ids: list[str] | None = None,
    min_score: float | None = None,
) -> dict:
    """Ask a question and receive an LLM-synthesized answer with citations.

    Performs full RAG: retrieves relevant chunks, synthesizes an answer using
    the configured LLM provider, and extracts inline citations.

    If the LLM is unavailable, returns raw chunks as sources with answer=null
    and a note explaining the fallback.

    Args:
        query: Question to answer.
        top_k: Number of chunks to retrieve before synthesis (default 10).
        document_ids: Optional list of document IDs to scope retrieval.
        min_score: Optional reranker score threshold (0.0-1.0).

    Returns:
        dict with 'answer' (str or null), 'sources' (list of {filename, page}),
        and optionally 'note' when LLM is unavailable.
    """
    if top_k < 1 or top_k > 100:
        raise ToolError("INVALID_PARAM: top_k must be between 1 and 100")

    app_ctx: AppContext = ctx.request_context.lifespan_context
    retrieval_engine = app_ctx.retrieval_engine
    synthesis_engine = app_ctx.synthesis_engine

    try:
        result = await retrieval_engine.search(
            query=query,
            top_k=top_k,
            min_score=min_score,
            document_ids=document_ids,
        )
    except Exception as exc:
        err = str(exc).lower()
        if "connect" in err or "qdrant" in err or "refused" in err:
            raise ToolError("QDRANT_UNAVAILABLE")
        raise ToolError(f"RETRIEVAL_ERROR: {exc}")

    chunks = result.results

    # Attempt LLM synthesis; fall back to raw chunks if LLM unavailable
    try:
        ask_response = await synthesis_engine.synthesize(query=query, chunks=chunks)
        return {
            "answer": ask_response.answer,
            "sources": [
                {"filename": s.filename, "page": s.page_number}
                for s in ask_response.sources
            ],
        }
    except Exception as exc:
        logger.warning("LLM unavailable during ask tool: %s", exc)
        # Fallback: return raw chunks as sources with answer=null
        return {
            "answer": None,
            "sources": [
                {"filename": c.source_filename, "page": c.page_number}
                for c in chunks
            ],
            "note": "LLM unavailable — raw chunks returned",
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
