import os
import unittest
from unittest.mock import patch

from rag_server.cli.commands import cmd_start
from rag_server.config import get_settings


class CliAskModeTest(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_cmd_start_no_ask_sets_env_before_uvicorn(self) -> None:
        get_settings.cache_clear()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAG_ASK_ENABLED", None)
            with patch("uvicorn.run") as run:
                cmd_start(ask_enabled=False)

            run.assert_called_once()
            self.assertEqual(os.environ["RAG_ASK_ENABLED"], "false")
            self.assertFalse(get_settings().rag_ask_enabled)

    def test_cmd_start_ask_sets_env_before_uvicorn(self) -> None:
        get_settings.cache_clear()
        with patch.dict(os.environ, {"RAG_ASK_ENABLED": "false"}, clear=False):
            with patch("uvicorn.run") as run:
                cmd_start(ask_enabled=True)

            run.assert_called_once()
            self.assertEqual(os.environ["RAG_ASK_ENABLED"], "true")
            self.assertTrue(get_settings().rag_ask_enabled)
