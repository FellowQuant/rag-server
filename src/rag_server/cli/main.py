"""FellowQuant RAG Server CLI — single entry point for the `rag-server` command.

All subcommand imports are lazy (inside routing block) to avoid import-time
side effects — particularly important for the `mcp` subcommand which must not
emit any stdout before the JSON-RPC channel is established.
"""
import sys
from pathlib import Path

SENTINEL = Path.home() / ".fellowquant-rag" / "setup-done"

USAGE = """\
Usage: rag-server <command>

Commands:
  start          Launch FastAPI server (port 8001)
  mcp            Start MCP stdio server (used by Claude Code)
  start-qdrant   Start Qdrant via Docker
  setup          Configure MCP registration (re-runnable)
"""


def _maybe_run_setup(cmd: str) -> None:
    """Auto-trigger setup wizard on first run if sentinel is absent.

    Skipped entirely when cmd == "mcp" — stdout is the JSON-RPC transport
    channel; any output before the channel opens corrupts the protocol.

    In non-TTY environments (CI/pipe) prints a note to stderr and returns
    without blocking on interactive prompts.
    """
    if cmd == "mcp":
        return

    if not SENTINEL.exists():
        if sys.stdin.isatty():
            from rag_server.cli.setup_wizard import cmd_setup
            cmd_setup(first_run=True)
        else:
            print(
                "Note: first-run setup not yet complete. "
                "Run `rag-server setup` in an interactive terminal to configure.",
                file=sys.stderr,
            )


def main() -> None:
    """Dispatcher: parse first positional arg and route to the correct command."""
    if len(sys.argv) < 2:
        print(USAGE, end="")
        sys.exit(1)

    cmd = sys.argv[1]

    # mcp must be routed with ZERO setup checks — no sentinel, no print, no input.
    if cmd == "mcp":
        from rag_server.cli.commands import cmd_mcp
        cmd_mcp()
        return

    _maybe_run_setup(cmd)

    if cmd == "start":
        from rag_server.cli.commands import cmd_start
        cmd_start()
    elif cmd == "start-qdrant":
        from rag_server.cli.commands import cmd_start_qdrant
        cmd_start_qdrant()
    elif cmd == "setup":
        from rag_server.cli.setup_wizard import cmd_setup
        cmd_setup(first_run=False)
    else:
        print(f"Unknown command: {cmd!r}", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        sys.exit(1)
