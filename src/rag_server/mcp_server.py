import logging
import sys
from pathlib import Path

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from rag_server.config import MCP_PATH, get_settings

# CRITICAL: all logging must go to stderr — stdout is the JSON-RPC transport channel.
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("rag-server")


def create_http_mcp_app():
    """Create the lightweight HTTP MCP ASGI app mounted by FastAPI.

    The MCP app intentionally stays stateless and proxies tool calls to the
    already-running FastAPI REST endpoints. This keeps one shared retrieval
    runtime in the server process instead of loading a second copy for MCP.
    """
    return mcp.http_app(
        path="/",
        transport="streamable-http",
        stateless_http=True,
    )


def _api_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.app_base_url}{path}"


def _problem_detail(payload: object, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        title = payload.get("title")
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(title, str) and title:
            return title
    return fallback


async def _request_json(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    files: dict | None = None,
    timeout: float = 300.0,
) -> dict:
    url = _api_url(path)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, json=json_body, files=files)
    except httpx.ConnectError as exc:
        raise ToolError(
            f"RAG_SERVER_UNAVAILABLE: start the server first with `rag-server start` ({exc})"
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"HTTP_ERROR: {exc}") from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        detail = _problem_detail(payload, response.text)

        if response.status_code == 404:
            raise ToolError(f"NOT_FOUND: {detail}")
        if response.status_code == 409:
            raise ToolError(f"DUPLICATE: {detail}")
        if response.status_code == 413:
            raise ToolError(f"TOO_LARGE: {detail}")
        if response.status_code == 415:
            raise ToolError(f"UNSUPPORTED_FORMAT: {detail}")
        if response.status_code == 503:
            raise ToolError(f"SERVICE_UNAVAILABLE: {detail}")
        raise ToolError(f"HTTP_{response.status_code}: {detail}")

    if response.status_code == 204:
        return {}

    try:
        return response.json()
    except ValueError as exc:
        raise ToolError(f"INVALID_JSON_RESPONSE from {url}") from exc


@mcp.tool()
async def retrieve(
    ctx: Context,
    query: str,
    top_k: int = 10,
    document_ids: list[str] | None = None,
    min_score: float | None = None,
) -> dict:
    """Retrieve ranked chunks from the knowledge base with full citation metadata."""
    del ctx
    if top_k < 1 or top_k > 100:
        raise ToolError("INVALID_PARAM: top_k must be between 1 and 100")

    return await _request_json(
        "POST",
        "/api/v1/retrieve",
        json_body={
            "query": query,
            "top_k": top_k,
            "document_ids": document_ids,
            "min_score": min_score,
        },
    )


@mcp.tool()
async def ask(
    ctx: Context,
    query: str,
    top_k: int = 10,
    document_ids: list[str] | None = None,
    min_score: float | None = None,
) -> dict:
    """Ask a question and receive an LLM-synthesized answer with citations."""
    del ctx
    if top_k < 1 or top_k > 100:
        raise ToolError("INVALID_PARAM: top_k must be between 1 and 100")

    return await _request_json(
        "POST",
        "/api/v1/ask?streaming=false",
        json_body={
            "query": query,
            "top_k": top_k,
            "document_ids": document_ids,
            "min_score": min_score,
        },
    )


@mcp.tool()
async def list_documents(ctx: Context) -> dict:
    """List all documents in the knowledge base with metadata and indexing status."""
    del ctx
    return await _request_json("GET", "/api/v1/documents")


@mcp.tool()
async def get_document(document_id: str, ctx: Context) -> dict:
    """Get metadata for a specific document by ID."""
    del ctx
    return await _request_json("GET", f"/api/v1/documents/{document_id}")


@mcp.tool()
async def delete_document(document_id: str, ctx: Context) -> dict:
    """Delete a document and all associated data from the knowledge base."""
    del ctx
    await _request_json("DELETE", f"/api/v1/documents/{document_id}")
    return {"deleted": True, "document_id": document_id}


@mcp.tool()
async def upload_document(file_path: str, ctx: Context) -> dict:
    """Upload a local document file for indexing through the shared REST server."""
    del ctx
    path = Path(file_path).expanduser()
    if not path.exists():
        raise ToolError(f"FILE_NOT_FOUND: {file_path}")
    if not path.is_file():
        raise ToolError(f"NOT_A_FILE: {file_path}")

    file_bytes = path.read_bytes()
    files = {
        "file": (path.name, file_bytes, "application/octet-stream"),
    }
    return await _request_json("POST", "/api/v1/documents", files=files, timeout=1800.0)


if __name__ == "__main__":
    # Legacy compatibility mode: stdio remains available, but it now proxies to
    # the shared FastAPI runtime instead of loading its own retrieval stack.
    logger.info(
        "Starting rag-server MCP in compatibility mode; expects shared server at %s",
        _api_url(MCP_PATH).removesuffix(MCP_PATH),
    )
    mcp.run(transport="stdio")
