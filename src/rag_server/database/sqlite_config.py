"""Shared SQLite concurrency settings for API and ingestion workers."""

SQLITE_BUSY_TIMEOUT_MS = 60_000


def configure_sqlite_connection(dbapi_connection, connection_record=None) -> None:
    """Enable safe concurrent reads and bounded waiting for SQLite writers."""
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()
