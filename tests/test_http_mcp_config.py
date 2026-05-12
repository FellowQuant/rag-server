import asyncio
import importlib
import unittest
from contextlib import asynccontextmanager

from rag_server.config import Settings


class HttpMcpConfigTest(unittest.TestCase):
    def test_mcp_url_defaults_to_local_8001(self) -> None:
        settings = Settings()
        self.assertEqual(settings.mcp_url, "http://127.0.0.1:8001/mcp")

    def test_main_app_mounts_mcp_endpoint(self) -> None:
        main = importlib.import_module("rag_server.main")
        mounted_paths = [getattr(route, "path", None) for route in main.app.routes]
        self.assertIn("/mcp", mounted_paths)


class HttpMcpRuntimeTest(unittest.TestCase):
    def test_parent_lifespan_enters_mcp_subapp_lifespan(self) -> None:
        main = importlib.import_module("rag_server.main")
        events: list[str] = []

        @asynccontextmanager
        async def fake_mcp_lifespan(app):
            events.append("mcp-enter")
            yield
            events.append("mcp-exit")

        @asynccontextmanager
        async def fake_rag_lifespan(app):
            events.append("rag-enter")
            yield
            events.append("rag-exit")

        from types import SimpleNamespace

        main.mcp_http_app = SimpleNamespace(lifespan=fake_mcp_lifespan)
        main.rag_lifespan = fake_rag_lifespan

        async def run() -> None:
            async with main.lifespan(main.app):
                events.append("inside")

        asyncio.run(run())
        self.assertEqual(
            events,
            ["mcp-enter", "rag-enter", "inside", "rag-exit", "mcp-exit"],
        )
