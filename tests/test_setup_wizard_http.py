import json
import tempfile
import unittest
from pathlib import Path

from rag_server.cli.setup_wizard import write_mcp_json


class SetupWizardHttpConfigTest(unittest.TestCase):
    def test_write_mcp_json_uses_http_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            write_mcp_json(cwd, "./data")

            config = json.loads((cwd / ".mcp.json").read_text())
            rag_server = config["mcpServers"]["rag-server"]

        self.assertEqual(rag_server["type"], "http")
        self.assertEqual(rag_server["url"], "http://127.0.0.1:8001/mcp")
        self.assertNotIn("command", rag_server)
        self.assertNotIn("env", rag_server)
