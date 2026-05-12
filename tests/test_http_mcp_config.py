import importlib
import unittest

from rag_server.config import Settings


class HttpMcpConfigTest(unittest.TestCase):
    def test_mcp_url_defaults_to_local_8001(self) -> None:
        settings = Settings()
        self.assertEqual(settings.mcp_url, "http://127.0.0.1:8001/mcp")

    def test_main_app_mounts_mcp_endpoint(self) -> None:
        main = importlib.import_module("rag_server.main")
        mounted_paths = [getattr(route, "path", None) for route in main.app.routes]
        self.assertIn("/mcp", mounted_paths)
