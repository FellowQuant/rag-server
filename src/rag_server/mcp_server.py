import multiprocessing
multiprocessing.set_start_method("spawn", force=True)

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import select

from rag_server.config import get_settings
from rag_server.database.engine import async_session
from rag_server.database.models import Document
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


@mcp.tool()
async def list_documents(ctx: Context) -> dict:
    """List all documents in the knowledge base with metadata and indexing status.

    Returns full metadata for each document including id, filename, title,
    status (pending/indexing/indexed/indexed_partial/failed), page_count, and created_at.
    MCP server must be restarted after new documents are indexed via the REST API
    for BM25 keyword search to reflect newly added documents.

    Returns:
        dict with 'documents' (list of document metadata dicts) and 'total' count.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Document).order_by(Document.created_at.desc())
        )
        docs = result.scalars().all()

    return {
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "title": d.title,
                "status": d.status,
                "file_format": d.file_format,
                "file_size": d.file_size,
                "page_count": d.page_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "indexed_at": d.indexed_at.isoformat() if d.indexed_at else None,
            }
            for d in docs
        ],
        "total": len(docs),
    }


@mcp.tool()
async def get_document(document_id: str, ctx: Context) -> dict:
    """Get metadata for a specific document by ID.

    Returns document metadata only — no chunk list. Use the retrieve tool
    with document_ids=[id] to search within a specific document.

    Args:
        document_id: UUID of the document to retrieve.

    Returns:
        dict with full document metadata.

    Raises:
        ToolError: NOT_FOUND: <document_id> if no document with that ID exists.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()

    if doc is None:
        raise ToolError(f"NOT_FOUND: {document_id}")

    return {
        "id": doc.id,
        "filename": doc.filename,
        "title": doc.title,
        "author": doc.author,
        "status": doc.status,
        "file_format": doc.file_format,
        "file_size": doc.file_size,
        "file_hash": doc.file_hash,
        "page_count": doc.page_count,
        "error_msg": doc.error_msg,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "indexed_at": doc.indexed_at.isoformat() if doc.indexed_at else None,
    }


@mcp.tool()
async def delete_document(document_id: str, ctx: Context) -> dict:
    """Delete a document and all associated data from the knowledge base.

    Removes:
    1. Uploaded file from DATA_DIR/uploads/ (if present)
    2. SQLite Document record (CASCADE deletes all Chunk rows)
    3. Qdrant vectors filtered by document_id (failure non-fatal — orphaned
       vectors don't appear in search results once document is removed from SQLite)

    Args:
        document_id: UUID of the document to delete.

    Returns:
        dict with 'deleted': true and 'document_id' on success.

    Raises:
        ToolError: NOT_FOUND: <document_id> if no document with that ID exists.
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context

    async with async_session() as session:
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()

        if doc is None:
            raise ToolError(f"NOT_FOUND: {document_id}")

        settings = get_settings()
        uploads_dir = settings.data_dir / "uploads"
        suffix = f".{doc.file_format}"
        file_path = uploads_dir / f"{doc.file_hash}{suffix}"
        if file_path.exists():
            file_path.unlink()
            logger.info("MCP delete_document: deleted file %s", file_path)

        await session.delete(doc)
        await session.commit()
        logger.info("MCP delete_document: deleted SQLite record %s", document_id)

    # Delete Qdrant vectors — failure is non-fatal (orphaned vectors are invisible)
    try:
        await app_ctx.qdrant_store.delete_document(document_id)
        logger.info("MCP delete_document: deleted Qdrant vectors for %s", document_id)
    except Exception as exc:
        logger.warning(
            "MCP delete_document: Qdrant delete failed (non-fatal) for %s: %s",
            document_id, exc,
        )

    return {"deleted": True, "document_id": document_id}


if __name__ == "__main__":
    mcp.run(transport="stdio")
