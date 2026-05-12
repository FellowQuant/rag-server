import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_server.config import Settings


class SettingsDefaultsTest(unittest.TestCase):
    def test_default_data_dir_is_repo_local_data(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        expected = (repo_root / "data").resolve()

        with tempfile.TemporaryDirectory() as tmp:
            original_cwd = Path.cwd()
            try:
                os.chdir(tmp)
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("DATA_DIR", None)
                    settings = Settings()
            finally:
                os.chdir(original_cwd)

        self.assertEqual(settings.data_dir, expected)

    def test_explicit_data_dir_override_is_respected(self) -> None:
        custom_dir = Path("/tmp/rag-server-custom-data")

        with patch.dict(os.environ, {"DATA_DIR": str(custom_dir)}, clear=False):
            settings = Settings()

        self.assertEqual(settings.data_dir.resolve(), custom_dir.resolve())
