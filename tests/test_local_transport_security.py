from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware

from rag_server.api.middleware import OriginDenyMiddleware
from rag_server.config import APP_BIND_HOST, LOCALHOST, Settings
from rag_server.mcp_server import mcp


def test_server_binds_to_loopback_by_default() -> None:
    assert APP_BIND_HOST == LOCALHOST == "127.0.0.1"
    assert Settings(_env_file=None).app_bind_host == LOCALHOST


def test_http_mcp_does_not_expose_server_side_path_upload() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert "upload_document" not in {tool.name for tool in tools}


def test_browser_origin_is_rejected_before_mutating_routes() -> None:
    app = FastAPI()

    @app.post("/api/v1/documents")
    async def upload() -> dict[str, bool]:
        return {"uploaded": True}

    app.add_middleware(OriginDenyMiddleware)
    client = TestClient(app)

    rejected = client.post(
        "/api/v1/documents",
        headers={"Origin": "https://attacker.example"},
        files={"file": ("hostile.pdf", b"payload", "application/pdf")},
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "Browser-origin requests are not allowed"

    local_client = client.post(
        "/api/v1/documents",
        files={"file": ("research.pdf", b"payload", "application/pdf")},
    )
    assert local_client.status_code == 200


def test_main_has_no_wildcard_cors_middleware() -> None:
    from rag_server.main import app

    assert all(
        middleware.cls is not CORSMiddleware for middleware in app.user_middleware
    )
