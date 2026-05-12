"""FellowQuant RAG Server CLI — subcommand implementations.

cmd_start      : Launch FastAPI on port 8001 via uvicorn.
cmd_mcp        : Start legacy stdio MCP compatibility mode.
is_port_open   : stdlib socket port check.
cmd_start_qdrant: Check port 6330, skip if running; otherwise start via embedded docker-compose.
"""

import socket
import subprocess
import sys
from pathlib import Path

from rag_server.config import APP_BIND_HOST, get_settings


def is_port_open(
    host: str = "localhost", port: int = 6330, timeout: float = 1.0
) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout seconds."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def cmd_start() -> None:
    """Launch FastAPI server on port 8001 via uvicorn.

    multiprocessing.set_start_method("spawn") is called at module top level in
    rag_server.main — importing that module is sufficient; no explicit call needed here.
    reload=True is intentionally omitted: it is incompatible with the spawn start method
    on Linux and would cause undefined behavior.
    """
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "rag_server.main:app",
        host=APP_BIND_HOST,
        port=settings.app_port,
        log_level="info",
    )


def cmd_mcp() -> None:
    """Start the MCP stdio compatibility server.

    CRITICAL: This function must produce ZERO stdout output.
    stdout is the JSON-RPC transport channel for Claude Code integration.
    Any output before mcp.run() opens the channel corrupts the protocol.

    The stdio server is now lightweight and proxies to the shared FastAPI
    runtime. Start `rag-server start` first.
    """
    from rag_server.mcp_server import mcp

    mcp.run(transport="stdio")


def cmd_start_qdrant() -> None:
    """Start Qdrant via Docker if not already running on port 6330.

    Writes the embedded docker-compose.yml to ~/.rag-server/ (persistent
    location avoids tempfile issues with Docker volume paths on Linux).
    """
    from importlib.resources import files

    if is_port_open("localhost", 6330):
        print("Qdrant is already running on port 6330.")
        return

    # Write compose file to persistent location
    compose_dir = Path.home() / ".rag-server"
    compose_dir.mkdir(parents=True, exist_ok=True)
    compose_path = compose_dir / "docker-compose.yml"
    if not compose_path.exists():
        compose_path.write_text(
            files("rag_server.assets").joinpath("docker-compose.yml").read_text()
        )

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "up", "-d", "qdrant"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Failed to start Qdrant:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Qdrant started on port 6330.")
