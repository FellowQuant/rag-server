import unittest
from pathlib import Path

import yaml


class DockerPackagingTest(unittest.TestCase):
    def test_compose_rag_server_build_has_dockerfile(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text())

        build_context = compose["services"]["rag-server"]["build"]
        dockerfile = repo_root / build_context / "Dockerfile"

        self.assertTrue(dockerfile.exists(), f"Missing Dockerfile at {dockerfile}")

    def test_dockerfile_uses_start_script(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        dockerfile_text = (repo_root / "Dockerfile").read_text()

        self.assertIn("COPY scripts ./scripts", dockerfile_text)
        self.assertIn('CMD ["./scripts/start.sh"]', dockerfile_text)
