from collections.abc import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from rag_server.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.sqlite_url,
    echo=False,  # Set True for SQL debugging
)

# CRITICAL: expire_on_commit=False — prevents MissingGreenlet on post-commit attribute access
# (SQLAlchemy research finding #2a)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


# CRITICAL: Enable SQLite foreign key enforcement — off by default
# Must be set per connection via event listener (research finding #2b)
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency-injectable async session for FastAPI routes."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
