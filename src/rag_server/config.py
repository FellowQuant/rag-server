from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # DATA_DIR — user-specified env var name (not RAG_DATA_DIR — no prefix)
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR", validation_alias="DATA_DIR")

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "documents"

    max_upload_size: int = Field(default=100 * 1024 * 1024)  # 100MB; set MAX_UPLOAD_SIZE env var to override

    # Device for retrieval models in the FastAPI process.
    # "auto" = use CUDA if available, else CPU.
    # Set RERANKER_DEVICE=cpu to free ~1.2 GB VRAM when running alongside a large LLM.
    reranker_device: str = Field(default="auto", alias="RERANKER_DEVICE", validation_alias="RERANKER_DEVICE")

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def sqlite_url(self) -> str:
        # Must be absolute path for Alembic compatibility (research pitfall #4)
        abs_path = self.data_dir.resolve()
        return f"sqlite+aiosqlite:///{abs_path}/rag.db"

    def ensure_data_dirs(self) -> None:
        """Create data directory structure if it does not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "qdrant").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
