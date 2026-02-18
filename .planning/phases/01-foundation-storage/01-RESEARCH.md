# Phase 1: Foundation & Storage - Research

**Researched:** 2026-02-18
**Domain:** Qdrant (Docker), SQLAlchemy 2.0 + SQLite (async), Python project infrastructure
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Data location & portability
- Default data directory: `./data/` (project-relative)
- Override via `DATA_DIR` environment variable — `./data/` is the fallback default
- `./data/` must be added to `.gitignore` — document data never committed
- Internal layout:
  - `./data/qdrant/` — Qdrant persistence volume (mounted into Docker container)
  - `./data/rag.db` — SQLite database for document and chunk metadata

#### Document identity & deduplication
- Duplicate detection via SHA-256 content hash of the uploaded file bytes
- Hashing is fast enough even for large PDFs (I/O-bound, typically <1s)
- On duplicate upload: reject with HTTP 409 + existing document ID in response body
- No force-replace shortcut — user must explicitly DELETE the existing document before re-ingesting
- Hash stored in SQLite document table for fast lookup on every upload

#### Chunk metadata schema
Fields stored per chunk in SQLite:
- `document_id` — foreign key to source document
- `page_number` — page in PDF (or cell index for .ipynb)
- `section_heading` — nearest H1/H2/H3 above the chunk (null if none)
- `chunk_type` — enum: `text` | `formula` | `table` | `code`
- `chunk_index` — sequential position within the document (enables ordered reconstruction)
- `content` — the chunk text used for embedding (for formula chunks: enriched context = preceding paragraph + LaTeX)
- `display_content` — for formula chunks only: raw LaTeX stored separately for rendering in API responses; null for other chunk types

Character offsets not stored in v1 — page number + chunk_index is sufficient for citation.

#### Qdrant deployment mode
- Run Qdrant as a Docker container (not embedded in-process mode)
- Project includes `docker-compose.yml` managing both Qdrant and the RAG server
- Qdrant port 6333 exposed on `localhost` — enables inspection via Qdrant web dashboard at `http://localhost:6333/dashboard`
- Qdrant persistence volume mounted to `./data/qdrant/`
- Qdrant collection schema must support multi-vector storage from day one:
  - Dense vector field (1024d, cosine) — BGE-M3 dense embeddings
  - Sparse vector field — BGE-M3 learned sparse weights (for hybrid retrieval)
  - Payload fields: document_id, chunk_id, chunk_type, page_number, section_heading, chunk_index

### Claude's Discretion
- SQLite schema details (indexes, constraints, migration strategy)
- Qdrant collection naming convention
- SQLAlchemy model structure
- Docker Compose service naming and healthcheck configuration
- Environment variable naming beyond `DATA_DIR` (e.g., `QDRANT_URL`, `QDRANT_PORT`)

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| STORE-01 | System stores vector embeddings in a persistent vector database (Qdrant) for semantic similarity search | Qdrant Docker Compose with bind-mount volume; `qdrant-client` 1.16.2 async API; collection creation with dense + sparse named vectors; payload indexes on `document_id` for filtered retrieval |
| STORE-02 | System stores document metadata (title, author, page count, format, hash) in a relational database (SQLite) | SQLAlchemy 2.0 async ORM with aiosqlite; `Document` model with SHA-256 hash column; Alembic 1.18.4 async migrations; WAL mode for concurrent access |
| STORE-03 | System stores chunk metadata (document_id, page_number, section_header, chunk_type) linked to source documents | `Chunk` SQLAlchemy model with FK to `Document`; `PRAGMA foreign_keys=ON`; all fields from locked schema; SQLAlchemy `Enum` type for `chunk_type` |
| STORE-04 | System supports 100+ document corpus with performant indexing and retrieval | Qdrant HNSW index (default) + payload indexes on `document_id` and `chunk_type`; SQLite WAL mode + indexes on `hash`, `document_id`; no performance degradation at 100+ doc scale confirmed by Qdrant docs |
</phase_requirements>

---

## Summary

This phase builds the storage layer that every subsequent phase depends on. There are two storage systems: Qdrant (Docker container) for vector embeddings, and SQLite (via SQLAlchemy async ORM) for document and chunk metadata. The primary technical challenge is getting both systems wired up correctly with the right schemas from day one — especially the Qdrant multi-vector collection schema, which cannot be retroactively altered without dropping and recreating the collection.

The stack is well-established and actively maintained. `qdrant-client` 1.16.2 (December 2025) natively supports async via `AsyncQdrantClient`, named dense vectors, and named sparse vectors in the same collection. SQLAlchemy 2.0.46 (January 2026) with `aiosqlite` 0.22.1 provides production-quality async SQLite access. Alembic 1.18.4 (February 2026) provides schema migration with an official async template. The entire stack uses `pyproject.toml` + `uv` as the package manager.

The key risk is the Qdrant collection schema: once created, adding a sparse vector field to an existing collection requires collection deletion and recreation. Since BGE-M3 sparse vectors are not used until Phase 3, there is temptation to defer the sparse field — do not. Define the full dual-vector schema (dense + sparse) in Phase 1, even though sparse will not be populated until Phase 3.

**Primary recommendation:** Create the Qdrant collection with both `dense` and `sparse_text` named vector spaces on first startup; use `create_if_not_exists` guard so restarts are idempotent; use SQLAlchemy async ORM with Alembic migrations for the SQLite schema.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `qdrant-client` | 1.16.2 | Python client for Qdrant vector DB (sync + async) | Official client; Apache 2.0; full async support since v1.6.1; named sparse vector support |
| `SQLAlchemy` | 2.0.46 | Async ORM for SQLite | Industry standard; `mapped_column` typed ORM; async session factory; 2.0 API is stable and fully typed |
| `aiosqlite` | 0.22.1 | Async SQLite driver for SQLAlchemy | Required for `sqlite+aiosqlite://` connection string; thin wrapper around stdlib sqlite3 |
| `alembic` | 1.18.4 | SQLite schema migrations | Official SQLAlchemy migration tool; async template available via `alembic init --template async` |
| `pydantic-settings` | 2.13.0 | Environment variable + `.env` file config | Standard for FastAPI projects; `BaseSettings` reads `DATA_DIR`, `QDRANT_URL`, etc. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `python-dotenv` | latest | Load `.env` file | pydantic-settings handles this automatically when `env_file=".env"` is set — install as transitive dep |
| `pytest-asyncio` | latest | Async test support | Required for testing async SQLAlchemy sessions and async Qdrant client |
| `pytest` | latest | Test runner | Standard |
| `httpx` | latest | HTTP client (async) | Used internally by `qdrant-client` for REST; install explicitly for testing FastAPI in later phases |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `aiosqlite` | `sqlite3` sync | Sync driver forces sync SQLAlchemy, incompatible with async FastAPI; not viable |
| Alembic migrations | `Base.metadata.create_all()` | `create_all()` is simpler but has no upgrade/downgrade history; Alembic is right for production-grade schema evolution |
| `qdrant-client` REST mode | gRPC mode | gRPC is faster but adds `grpcio` dep; REST is default and sufficient for this workload |
| `pydantic-settings` | `python-decouple` or `dynaconf` | pydantic-settings integrates natively with Pydantic models already used in the project |

**Installation:**
```bash
uv add qdrant-client sqlalchemy aiosqlite alembic pydantic-settings
uv add --dev pytest pytest-asyncio
```

---

## Architecture Patterns

### Recommended Project Structure

```
rag_server/
├── src/
│   └── rag_server/
│       ├── __init__.py
│       ├── main.py              # FastAPI app factory (Phase 5)
│       ├── config.py            # pydantic-settings Settings class
│       ├── database.py          # SQLAlchemy engine, session factory
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py          # DeclarativeBase with AsyncAttrs
│       │   ├── document.py      # Document ORM model
│       │   └── chunk.py         # Chunk ORM model
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── qdrant.py        # QdrantStore: create_collection, upsert, delete
│       │   └── sqlite.py        # DocumentStore, ChunkStore: CRUD operations
│       └── schemas/
│           ├── __init__.py
│           └── storage.py       # Pydantic schemas for document/chunk (Phase 5)
├── alembic/
│   ├── env.py                   # Async Alembic env (use official async template)
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── alembic.ini
├── tests/
│   ├── conftest.py              # Async engine fixtures, test Qdrant client
│   └── test_storage/
│       ├── test_qdrant.py
│       └── test_sqlite.py
├── docker-compose.yml
├── Dockerfile                   # RAG server image (Phase 5)
├── pyproject.toml
├── .env.example
└── .gitignore
```

### Pattern 1: SQLAlchemy Async Engine + Session Factory

**What:** Single async engine created at startup; `async_sessionmaker` factory used for request-scoped sessions.
**When to use:** All SQLite reads/writes in this phase and all future phases.

```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
# src/rag_server/database.py

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event

from rag_server.config import settings


def _get_db_url() -> str:
    db_path = settings.data_dir / "rag.db"
    return f"sqlite+aiosqlite:///{db_path}"


engine = create_async_engine(
    _get_db_url(),
    echo=False,  # set True during development
)

# Enable foreign keys and WAL mode on every new connection
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_conn, conn_record):
    # foreign_keys requires autocommit=True to take effect in sqlite3
    ac = dbapi_conn.autocommit
    dbapi_conn.autocommit = True
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
    dbapi_conn.autocommit = ac


# expire_on_commit=False: attributes remain usable after commit in async context
AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """FastAPI dependency — yields a session per request."""
    async with AsyncSessionFactory() as session:
        yield session
```

### Pattern 2: SQLAlchemy ORM Models with AsyncAttrs

**What:** Typed ORM models using `mapped_column` and `Mapped` with `AsyncAttrs` mixin.
**When to use:** Document and Chunk table definitions.

```python
# Source: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
# src/rag_server/models/base.py

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    pass
```

```python
# src/rag_server/models/document.py

import enum
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from rag_server.models.base import Base


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)  # pdf | tex | ipynb
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default=DocumentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    chunks: Mapped[list["Chunk"]] = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
```

```python
# src/rag_server/models/chunk.py

import enum
import uuid
from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from rag_server.models.base import Base


class ChunkType(str, enum.Enum):
    TEXT = "text"
    FORMULA = "formula"
    TABLE = "table"
    CODE = "code"


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_type: Mapped[str] = mapped_column(String, nullable=False)  # ChunkType enum value
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    display_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # LaTeX for formula chunks only

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
```

### Pattern 3: Qdrant Collection Initialization (Idempotent)

**What:** Create the BGE-M3 dual-vector collection on startup; guard with `collection_exists` check so restarts are safe.
**When to use:** Application startup, before any ingestion.

```python
# Source: https://qdrant.tech/documentation/concepts/collections/
# src/rag_server/storage/qdrant.py

from qdrant_client import AsyncQdrantClient, models
from rag_server.config import settings

COLLECTION_NAME = "rag_chunks"  # recommended naming convention: app + entity

async def ensure_collection_exists(client: AsyncQdrantClient) -> None:
    """Idempotent: creates collection only if it does not already exist."""
    exists = await client.collection_exists(collection_name=COLLECTION_NAME)
    if exists:
        return

    await client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            # BGE-M3 dense: 1024 dimensions, cosine distance
            "dense": models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            # BGE-M3 learned sparse weights (used from Phase 3 onward)
            "sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=False)
            )
        },
    )

    # Payload indexes for fast filtering by document_id and chunk_type
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="document_id",
        field_schema="keyword",  # UUID stored as string
    )
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="chunk_type",
        field_schema="keyword",
    )
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="chunk_index",
        field_schema="integer",
    )
```

### Pattern 4: Qdrant Point Upsert with Named Vectors

**What:** Insert a chunk's dense embedding (and optionally sparse weights) as a named-vector point with metadata payload.
**When to use:** Phase 2+ ingestion pipeline — defined here so the Phase 1 schema is correct.

```python
# Source: https://qdrant.tech/documentation/concepts/points/
# Upsert with dense vector only (Phase 2); sparse added in Phase 3

await client.upsert(
    collection_name=COLLECTION_NAME,
    points=[
        models.PointStruct(
            id=chunk_id,          # use the SQLite chunk UUID (string UUID supported)
            vector={
                "dense": dense_embedding,  # list[float] of length 1024
                # "sparse" omitted until Phase 3
            },
            payload={
                "document_id": document_id,
                "chunk_id": chunk_id,
                "chunk_type": chunk_type,       # "text" | "formula" | "table" | "code"
                "page_number": page_number,
                "section_heading": section_heading,
                "chunk_index": chunk_index,
            },
        )
    ],
)
```

### Pattern 5: Qdrant Delete by document_id Filter

**What:** Remove all vectors belonging to a document when the document is deleted.
**When to use:** Document DELETE endpoint (Phase 5), but the pattern is needed now for tests.

```python
# Source: https://qdrant.tech/documentation/concepts/points/
await client.delete(
    collection_name=COLLECTION_NAME,
    points_selector=models.FilterSelector(
        filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        )
    ),
)
```

### Pattern 6: Pydantic Settings for Configuration

**What:** Centralized typed configuration from environment variables and `.env` file.
**When to use:** Everywhere — imported by `database.py`, `qdrant.py`, etc.

```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
# src/rag_server/config.py

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Data directory — locked decision
    data_dir: Path = Path("./data")

    # Qdrant connection — Claude's discretion
    qdrant_url: str = "http://localhost:6333"

    # SQLite — derived from data_dir, not a separate env var
    @property
    def db_path(self) -> Path:
        return self.data_dir / "rag.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def qdrant_data_dir(self) -> Path:
        return self.data_dir / "qdrant"

    def ensure_data_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.qdrant_data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
```

### Pattern 7: Alembic Async Migration Setup

**What:** Initialize Alembic with the official async template so migrations run against the async engine.
**When to use:** Once during project setup; all schema changes go through Alembic after this.

```bash
# Bootstrap with the official async template
alembic init --template async alembic
```

```python
# alembic/env.py — key section (official async template pattern)
# Source: https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py

import asyncio
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# Import ALL models so Alembic can autogenerate
from rag_server.models.base import Base
from rag_server.models.document import Document  # noqa: F401
from rag_server.models.chunk import Chunk        # noqa: F401

target_metadata = Base.metadata

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # CRITICAL for SQLite — enables batch migrations for ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        context.config.get_section(context.config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())
```

### Pattern 8: Docker Compose for Qdrant

**What:** Minimal Docker Compose service for Qdrant with volume mount and bash-based healthcheck.
**When to use:** Foundation for running the full stack; RAG server service added in Phase 5.

```yaml
# docker-compose.yml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"   # HTTP REST API + web dashboard
      - "6334:6334"   # gRPC API
    volumes:
      - ${DATA_DIR:-./data}/qdrant:/qdrant/storage
    healthcheck:
      # bash /dev/tcp trick — curl/wget not available in Qdrant container
      test: ["CMD", "bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/6333 && echo -e 'GET /readyz HTTP/1.1\\r\\nHost: localhost\\r\\n\\r\\n' >&3 && grep -q 'HTTP/1.1 200' <&3"]
      interval: 10s
      timeout: 5s
      start_period: 30s
      retries: 5
```

### Anti-Patterns to Avoid

- **Using `qdrant-client` embedded/in-memory mode for production:** In-process mode stores data in memory or a local path without Docker, bypassing the dashboard and the locked Docker deployment decision. Always connect to `http://localhost:6333`.
- **Creating the collection without sparse vector field:** BGE-M3 sparse vectors cannot be added to an existing collection without dropping it. Build the full schema now.
- **Using `Base.metadata.create_all()` instead of Alembic:** This works initially but provides no migration history. Alembic is mandatory given that later phases add columns.
- **Omitting `render_as_batch=True` in Alembic env.py for SQLite:** SQLite does not support `ALTER TABLE ADD COLUMN ... NOT NULL` without a default. Batch mode rewrites the table, enabling full migrations. Without this, migrations will fail.
- **Omitting `PRAGMA foreign_keys=ON`:** SQLite does not enforce foreign key constraints by default. Without this pragma, `ondelete="CASCADE"` on `Chunk.document_id` does nothing.
- **Setting `expire_on_commit=True` (the default) with async sessions:** After `await session.commit()`, accessing any mapped attribute triggers implicit lazy load, which raises `MissingGreenlet` in async context. Always use `expire_on_commit=False`.
- **Using `PRAGMA foreign_keys=ON` inside a transaction:** The sqlite3 driver ignores this pragma when `autocommit=False`. The event listener must temporarily set `autocommit=True` before executing the pragma.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema migrations | Custom `ALTER TABLE` scripts | Alembic | Handles SQLite batch migrations, autogenerate, rollback, history |
| Env/config management | `os.environ.get()` sprinkled across codebase | `pydantic-settings` `BaseSettings` | Type validation, `.env` file support, centralized defaults |
| Qdrant collection setup | Inline `create_collection` calls in multiple places | Centralized `ensure_collection_exists()` on startup | Idempotency, schema consistency, single source of truth |
| Async session lifecycle | Manual `session.close()` | `async with AsyncSessionFactory() as session` | Handles exceptions, ensures cleanup |
| Duplicate hash check | Query Qdrant for existing embeddings | `sha256_hash` column in SQLite `documents` table with UNIQUE index | O(1) lookup in SQLite vs O(n) scan in Qdrant; avoids cross-system query |

**Key insight:** SQLite + SQLAlchemy has many gotchas in async context (pragma ordering, batch migrations, expire_on_commit). Use established patterns from official docs rather than improvising.

---

## Common Pitfalls

### Pitfall 1: Qdrant Collection Schema Cannot Be Altered

**What goes wrong:** Sparse vector field added to existing collection causes error: "Collection already exists with different config."
**Why it happens:** Qdrant does not support `ALTER COLLECTION` to add vector fields — you must drop and recreate.
**How to avoid:** Define both `dense` and `sparse` named vector spaces in `create_collection()` from Phase 1, even though sparse vectors are not populated until Phase 3.
**Warning signs:** `BadRequestError: Wrong input: Vectors configuration is not compatible with existing collection`

### Pitfall 2: SQLite Foreign Keys Not Enforced

**What goes wrong:** Deleting a `Document` does not cascade-delete its `Chunk` rows; orphaned chunks accumulate.
**Why it happens:** SQLite disables foreign key enforcement by default for backwards compatibility.
**How to avoid:** Register `PRAGMA foreign_keys=ON` via SQLAlchemy `"connect"` event on `engine.sync_engine`. Must run with `autocommit=True`.
**Warning signs:** Chunk count doesn't decrease after document deletion; test for orphaned chunks.

### Pitfall 3: MissingGreenlet Error on Attribute Access After Commit

**What goes wrong:** `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called` when reading a model attribute after `await session.commit()`.
**Why it happens:** Default `expire_on_commit=True` marks attributes as expired; accessing them triggers synchronous lazy load which is illegal in async context.
**How to avoid:** Create `async_sessionmaker(engine, expire_on_commit=False)`. Alternatively, eagerly load all needed data before commit.
**Warning signs:** Errors only appear after commit calls, not during initial reads.

### Pitfall 4: Alembic Migrations Fail on SQLite ALTER TABLE

**What goes wrong:** `alembic upgrade head` fails with `OperationalError: Cannot add a NOT NULL column with default value NULL`.
**Why it happens:** SQLite's ALTER TABLE is limited compared to PostgreSQL; it cannot add NOT NULL columns without defaults in-place.
**How to avoid:** Set `render_as_batch=True` in `context.configure()` in `alembic/env.py`. Batch mode creates a new table, copies data, drops old table, renames.
**Warning signs:** Migration succeeds on PostgreSQL test environment but fails on SQLite.

### Pitfall 5: Qdrant Healthcheck Fails (curl/wget Not Available)

**What goes wrong:** Docker Compose healthcheck using `curl -f http://localhost:6333/readyz` reports `executable not found`.
**Why it happens:** Qdrant Docker image intentionally excludes curl/wget for security hardening.
**How to avoid:** Use the `bash /dev/tcp` trick — explicitly invoke `bash` (not `sh`/`dash`) since `/dev/tcp` is bash-specific. Or skip container-internal healthcheck and rely on `depends_on: condition: service_started`.
**Warning signs:** `healthcheck` shows `unhealthy` even when Qdrant is running normally.

### Pitfall 6: Volume Mount Path Misalignment

**What goes wrong:** Qdrant starts but data is lost on container restart; or new data is not persisted.
**Why it happens:** The container writes to `/qdrant/storage` internally, but the Docker Compose volume mounts to a different path.
**How to avoid:** Mount must be `./data/qdrant:/qdrant/storage` (container-side path is `/qdrant/storage`, not `/qdrant/data`).
**Warning signs:** Collections present in dashboard are gone after `docker compose restart`.

### Pitfall 7: DATA_DIR Expansion in docker-compose.yml

**What goes wrong:** `${DATA_DIR:-./data}/qdrant:/qdrant/storage` does not expand correctly; Docker creates a literal `${DATA_DIR:-./data}` directory.
**Why it happens:** Docker Compose variable substitution syntax requires the variable to be set in the environment or `.env` file; `:-` fallback only works if the variable is exported.
**How to avoid:** Use a separate `.env` file at the project root with `DATA_DIR=./data`; Docker Compose reads `.env` automatically. Alternatively, use a named volume (`qdrant_storage`) and a separate init step to set the data path.
**Warning signs:** Data directory is `${DATA_DIR:-./data}` literally in the filesystem.

---

## Code Examples

Verified patterns from official sources:

### Create Collection with Dense + Sparse Named Vectors

```python
# Source: https://qdrant.tech/articles/sparse-vectors/ + https://qdrant.tech/documentation/concepts/collections/
from qdrant_client import AsyncQdrantClient, models

client = AsyncQdrantClient(url="http://localhost:6333")

await client.create_collection(
    collection_name="rag_chunks",
    vectors_config={
        "dense": models.VectorParams(
            size=1024,
            distance=models.Distance.COSINE,
        )
    },
    sparse_vectors_config={
        "sparse": models.SparseVectorParams(
            index=models.SparseIndexParams(on_disk=False)
        )
    },
)
```

### Create Payload Indexes

```python
# Source: https://qdrant.tech/documentation/concepts/indexing/
await client.create_payload_index(
    collection_name="rag_chunks",
    field_name="document_id",
    field_schema="keyword",
)
await client.create_payload_index(
    collection_name="rag_chunks",
    field_name="chunk_type",
    field_schema="keyword",
)
```

### Upsert Point with Dense Vector and Payload

```python
# Source: https://qdrant.tech/documentation/concepts/points/
await client.upsert(
    collection_name="rag_chunks",
    points=[
        models.PointStruct(
            id=chunk_id,
            vector={"dense": dense_vector_list},
            payload={
                "document_id": "doc-uuid",
                "chunk_id": chunk_id,
                "chunk_type": "text",
                "page_number": 3,
                "section_heading": "Introduction",
                "chunk_index": 0,
            },
        )
    ],
)
```

### Delete All Chunks for a Document

```python
# Source: https://qdrant.tech/documentation/concepts/points/
await client.delete(
    collection_name="rag_chunks",
    points_selector=models.FilterSelector(
        filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        )
    ),
)
```

### Async SQLAlchemy Engine with PRAGMAs

```python
# Source: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import event

engine = create_async_engine("sqlite+aiosqlite:///./data/rag.db", echo=False)

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_conn, conn_record):
    ac = dbapi_conn.autocommit
    dbapi_conn.autocommit = True
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
    dbapi_conn.autocommit = ac
```

### Run Alembic Migrations Programmatically (Startup)

```python
# Source: https://alembic.sqlalchemy.org/en/latest/cookbook.html
from alembic.config import Config
from alembic import command

def run_migrations():
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ChromaDB for vector storage | Qdrant (Docker) | Project decision — BGE-M3 requires named sparse vectors | ChromaDB cannot store named sparse vectors; Qdrant is required |
| SQLAlchemy 1.x `Column`/`relationship` syntax | SQLAlchemy 2.0 `Mapped`/`mapped_column` typed ORM | SQLAlchemy 2.0 (2023) | Full type inference; `mypy`/`pyright` support; IDE autocomplete |
| `setup.py` + `requirements.txt` | `pyproject.toml` + `uv` | PEP 621 / uv adoption 2024-2025 | Single config file; faster installs; lockfile for reproducibility |
| Alembic sync migrations | Alembic async template | Alembic added async template ~2022 | No more sync/async URL conversion hack; official support |
| `Config` inner class in Pydantic settings | `model_config = SettingsConfigDict(...)` | Pydantic v2 (2023) | Type-safe config; no deprecated `Config` class |
| `QdrantClient` (sync) for async apps | `AsyncQdrantClient` | qdrant-client v1.6.1 (2023) | Native async; no thread executor wrapping |

**Deprecated/outdated:**
- `SQLAlchemy.Column(...)` syntax: replaced by `mapped_column(...)` in 2.0; old syntax still works but is untyped
- Alembic `run_migrations_online()` using synchronous `engine_from_config`: replaced by async template with `async_engine_from_config`
- `QdrantClient` with `prefer_grpc=True` as default: REST is now default and recommended for local use

---

## Open Questions

1. **Qdrant version pinning vs `latest`**
   - What we know: Qdrant `latest` Docker tag tracks the most recent stable release; currently v1.14-v1.16 range
   - What's unclear: Exact latest tag as of Feb 2026 — GitHub showed v1.16.3 (Dec 2024) but may be out of date
   - Recommendation: Pin to a specific version tag (e.g., `qdrant/qdrant:v1.16.3`) in docker-compose.yml for reproducibility; update deliberately

2. **UUID vs integer for Qdrant point IDs**
   - What we know: Qdrant supports both UUID and unsigned 64-bit integer as point IDs; UUID maps naturally to SQLite chunk UUIDs
   - What's unclear: Whether string UUID (not `uuid.UUID` object) is accepted directly by qdrant-client
   - Recommendation: Pass `str(uuid.uuid4())` directly — qdrant-client accepts string UUIDs and converts internally; verify in Phase 1 tests

3. **AsyncQdrantClient connection lifetime**
   - What we know: `AsyncQdrantClient` should be instantiated once at app startup, not per-request
   - What's unclear: Whether `AsyncQdrantClient` requires explicit `.close()` or context manager on shutdown
   - Recommendation: Instantiate as a module-level singleton; use FastAPI `lifespan` context manager to call `await client.close()` on shutdown

4. **DATA_DIR with bind mount in docker-compose.yml**
   - What we know: `${DATA_DIR:-./data}` syntax works in Docker Compose when the variable is defined in `.env`
   - What's unclear: Behavior when `DATA_DIR` is an absolute path vs. relative path in the mount expression
   - Recommendation: Keep `DATA_DIR=./data` as default in `.env.example`; document that absolute paths work but relative paths are relative to the docker-compose.yml location

---

## Sources

### Primary (HIGH confidence)
- [Qdrant Collections Documentation](https://qdrant.tech/documentation/concepts/collections/) — dense + sparse vector creation API
- [Qdrant Points Documentation](https://qdrant.tech/documentation/concepts/points/) — upsert, delete by filter
- [Qdrant Indexing Documentation](https://qdrant.tech/documentation/concepts/indexing/) — `create_payload_index` API with field types
- [Qdrant Sparse Vectors Article](https://qdrant.tech/articles/sparse-vectors/) — hybrid search patterns with code examples
- [Qdrant Installation/Docker Guide](https://qdrant.tech/documentation/guides/installation/) — Docker Compose YAML
- [Qdrant Monitoring/Health Endpoints](https://qdrant.tech/documentation/guides/monitoring/) — `/healthz`, `/livez`, `/readyz`
- [SQLAlchemy Async I/O Docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) — `create_async_engine`, `async_sessionmaker`, `AsyncAttrs`
- [SQLAlchemy SQLite Dialect Docs](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) — PRAGMA configuration, WAL mode, foreign keys
- [Alembic Async Template](https://github.com/sqlalchemy/alembic/blob/main/alembic/templates/async/env.py) — Official async env.py pattern
- [qdrant-client PyPI](https://pypi.org/project/qdrant-client/) — version 1.16.2, Python >=3.10
- [SQLAlchemy PyPI/releases](https://github.com/sqlalchemy/sqlalchemy/releases) — version 2.0.46 (Jan 2026)
- [Alembic PyPI](https://pypi.org/project/alembic/) — version 1.18.4 (Feb 2026)
- [aiosqlite PyPI](https://pypi.org/project/aiosqlite/) — version 0.22.1 (Dec 2025)
- [pydantic-settings PyPI](https://pypi.org/project/pydantic-settings/) — version 2.13.0 (Feb 2026)
- [Pydantic Settings Docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — BaseSettings, SettingsConfigDict, env_file

### Secondary (MEDIUM confidence)
- [Qdrant Healthcheck GitHub Issue #4250](https://github.com/qdrant/qdrant/issues/4250) — bash /dev/tcp healthcheck workaround; issue still open as of Sep 2025
- [FastAPI Best Practices (zhanymkanov)](https://github.com/zhanymkanov/fastapi-best-practices) — project structure, router/service pattern
- [uv + FastAPI Guide](https://docs.astral.sh/uv/guides/integration/fastapi/) — pyproject.toml setup, uv add commands

### Tertiary (LOW confidence)
- WebSearch result: Qdrant v1.16.3 as latest version (Dec 2024) — may be outdated; verify against official releases before pinning

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified via PyPI with version numbers and official docs
- Architecture: HIGH — patterns sourced directly from official SQLAlchemy and Qdrant documentation
- Pitfalls: HIGH — SQLite PRAGMA pitfalls from official SQLAlchemy docs; Qdrant healthcheck from open GitHub issue; collection immutability from Qdrant docs
- Docker Compose: MEDIUM — volume mount path verified from Qdrant installation docs; healthcheck workaround from GitHub issue

**Research date:** 2026-02-18
**Valid until:** 2026-03-20 (30 days — stable libraries, slow-moving stack)
