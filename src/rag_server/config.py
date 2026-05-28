from functools import lru_cache
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


APP_PORT = 8001
APP_BIND_HOST = "0.0.0.0"
LOCALHOST = "127.0.0.1"
MCP_PATH = "/mcp"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    return (_project_root() / "data").resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # DATA_DIR — user-specified env var name (not RAG_DATA_DIR — no prefix)
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        alias="DATA_DIR",
        validation_alias="DATA_DIR",
    )

    qdrant_host: str = "localhost"
    qdrant_port: int = 6330
    qdrant_collection: str = "documents"
    app_port: int = Field(
        default=APP_PORT, alias="APP_PORT", validation_alias="APP_PORT"
    )

    max_upload_size: int = Field(
        default=100 * 1024 * 1024
    )  # 100MB; set MAX_UPLOAD_SIZE env var to override

    indexer_upload_chunk_bytes: int = Field(
        default=1024 * 1024,
        alias="INDEXER_UPLOAD_CHUNK_BYTES",
        validation_alias="INDEXER_UPLOAD_CHUNK_BYTES",
    )

    # Device for retrieval models in the FastAPI process.
    # "auto" = use CUDA if available, else CPU.
    # Set RERANKER_DEVICE=cpu to free ~1.2 GB VRAM when running alongside a large LLM.
    reranker_device: str = Field(
        default="auto", alias="RERANKER_DEVICE", validation_alias="RERANKER_DEVICE"
    )

    indexer_worker_rss_soft_limit_mb: int = Field(
        default=0,
        alias="INDEXER_WORKER_RSS_SOFT_LIMIT_MB",
        validation_alias="INDEXER_WORKER_RSS_SOFT_LIMIT_MB",
    )
    indexer_min_available_ram_mb: int = Field(
        default=2048,
        alias="INDEXER_MIN_AVAILABLE_RAM_MB",
        validation_alias="INDEXER_MIN_AVAILABLE_RAM_MB",
    )
    indexer_large_file_bytes: int = Field(
        default=16 * 1024 * 1024,
        alias="INDEXER_LARGE_FILE_BYTES",
        validation_alias="INDEXER_LARGE_FILE_BYTES",
    )
    indexer_pdf_pages_per_batch: int = Field(
        default=25,
        alias="INDEXER_PDF_PAGES_PER_BATCH",
        validation_alias="INDEXER_PDF_PAGES_PER_BATCH",
    )
    indexer_embed_batch_size: int = Field(
        default=8,
        alias="INDEXER_EMBED_BATCH_SIZE",
        validation_alias="INDEXER_EMBED_BATCH_SIZE",
    )
    indexer_resource_retry_limit: int = Field(
        default=2,
        alias="INDEXER_RESOURCE_RETRY_LIMIT",
        validation_alias="INDEXER_RESOURCE_RETRY_LIMIT",
    )

    @field_validator("data_dir", mode="before")
    @classmethod
    def _normalize_data_dir(cls, value: Path | str) -> Path:
        return Path(value).expanduser().resolve()

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def app_base_url(self) -> str:
        return f"http://{LOCALHOST}:{self.app_port}"

    @property
    def mcp_url(self) -> str:
        return f"{self.app_base_url}{MCP_PATH}"

    @property
    def sqlite_url(self) -> str:
        # Must be absolute path for Alembic compatibility (research pitfall #4)
        return f"sqlite+aiosqlite:///{self.data_dir}/rag.db"

    def ensure_data_dirs(self) -> None:
        """Create data directory structure if it does not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "qdrant").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
