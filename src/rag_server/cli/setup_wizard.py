"""FellowQuant RAG Server — idempotent setup wizard.

Handles:
  - Global MCP registration via `claude mcp add-json ... --scope user`
  - Local MCP registration via read-modify-write .mcp.json
  - llm.yaml copy from embedded asset
  - Sentinel file to prevent repeated auto-trigger on first run
  - Non-TTY safe: all prompts return defaults when stdin is not a tty
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

SENTINEL = Path.home() / ".fellowquant-rag" / "setup-done"
CONFIG_DIR = Path.home() / ".fellowquant-rag"


def safe_input(prompt: str, default: str = "") -> str:
    """Prompt the user and return their input.

    If stdin is not a TTY (CI/pipe/non-interactive), print a note to stderr
    and return ``default`` immediately without blocking.
    """
    if not sys.stdin.isatty():
        print(f"[non-interactive] using default for: {prompt!r} -> {default!r}", file=sys.stderr)
        return default
    return input(prompt)


def mcp_json_exists(cwd: Path) -> bool:
    """Return True if .mcp.json in cwd already has an mcpServers.rag-server entry."""
    mcp_file = cwd / ".mcp.json"
    if not mcp_file.exists():
        return False
    try:
        config = json.loads(mcp_file.read_text())
        return "rag-server" in config.get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        return False


def claude_mcp_registered() -> bool:
    """Return True if `claude` CLI is available and lists rag-server as registered."""
    if not shutil.which("claude"):
        return False
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "rag-server" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def write_mcp_json(cwd: Path, data_dir: str) -> None:
    """Write (or update) .mcp.json in cwd with the rag-server MCP entry.

    Uses a read-modify-write pattern: existing keys under mcpServers are
    preserved; only the rag-server entry is added/overwritten.
    """
    mcp_file = cwd / ".mcp.json"
    config: dict = {}
    if mcp_file.exists():
        try:
            config = json.loads(mcp_file.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}
    config.setdefault("mcpServers", {})
    config["mcpServers"]["rag-server"] = {
        "type": "stdio",
        "command": "rag-server",
        "args": ["mcp"],
        "env": {"DATA_DIR": data_dir},
    }
    mcp_file.write_text(json.dumps(config, indent=2) + "\n")


def register_mcp_global(data_dir: str) -> bool:
    """Register rag-server globally via `claude mcp add-json ... --scope user`.

    Uses `claude mcp add-json` (not `claude mcp add`) because the env block
    containing DATA_DIR requires a full JSON payload — the positional-arg form
    does not support env injection.

    Returns True on success, False if claude CLI is absent or the command fails.
    """
    if not shutil.which("claude"):
        return False
    payload = json.dumps({
        "type": "stdio",
        "command": "rag-server",
        "args": ["mcp"],
        "env": {"DATA_DIR": data_dir},
    })
    result = subprocess.run(
        ["claude", "mcp", "add-json", "rag-server", payload, "--scope", "user"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def cmd_setup(first_run: bool = False) -> None:
    """Idempotent setup wizard: MCP registration, llm.yaml copy, sentinel write.

    Args:
        first_run: When True, prints a "First-run setup" header instead of the
                   standard header. Behaviour is otherwise identical.

    Flow:
        1. Print header
        2. Prompt for scope (global / local)
        3. Prompt for DATA_DIR
        4. MCP registration (global or local path)
        5. llm.yaml copy from embedded asset
        6. Write sentinel (TTY only)
        7. Print summary
    """
    if first_run:
        print("=== First-run setup: FellowQuant RAG Server ===")
    else:
        print("=== FellowQuant RAG Server Setup ===")

    # --- 1. Scope prompt ---
    scope_raw = safe_input("Register MCP globally (g) or locally for this project (l)? [g/l]: ", default="l")
    scope = scope_raw.strip().lower() or "l"
    use_global = scope.startswith("g")

    # --- 2. DATA_DIR prompt ---
    data_dir_raw = safe_input("Data directory [./data/]: ", default="./data/")
    data_dir = data_dir_raw.strip().rstrip("/") or "./data"

    cwd = Path.cwd()
    mcp_scope_description = ""

    # --- 3. MCP registration ---
    if use_global:
        already = claude_mcp_registered()
        do_register = True
        if already:
            ans = safe_input("rag-server already registered globally. Update? [y/N]: ", default="n")
            do_register = ans.strip().lower().startswith("y")

        if do_register:
            if not shutil.which("claude"):
                # Fallback: write .mcp.json locally, print instructions
                print(
                    "\nNote: `claude` CLI not found. Cannot register globally.\n"
                    "Install Claude Code first: https://claude.ai/download\n"
                    "Falling back to local .mcp.json registration.",
                    file=sys.stderr,
                )
                _do_local = True
                mcp_scope_description = f"local (fallback): {cwd / '.mcp.json'}"
            else:
                ok = register_mcp_global(data_dir)
                if ok:
                    print("Registered globally in ~/.claude.json")
                    mcp_scope_description = "global (~/.claude.json)"
                    _do_local = False
                else:
                    print(
                        "Warning: `claude mcp add-json` failed. "
                        "Try manually:\n"
                        f"  claude mcp add-json rag-server "
                        f"'{{\"type\":\"stdio\",\"command\":\"rag-server\",\"args\":[\"mcp\"],"
                        f"\"env\":{{\"DATA_DIR\":\"{data_dir}\"}}}}' --scope user",
                        file=sys.stderr,
                    )
                    _do_local = True
                    mcp_scope_description = f"local (fallback): {cwd / '.mcp.json'}"
        else:
            print("Skipping global MCP registration.")
            _do_local = False
            mcp_scope_description = "global (existing, kept)"

        if _do_local:
            if mcp_json_exists(cwd):
                ans = safe_input(".mcp.json already has rag-server. Update? [y/N]: ", default="n")
                if ans.strip().lower().startswith("y"):
                    write_mcp_json(cwd, data_dir)
                    print(f".mcp.json updated in {cwd}")
                else:
                    print("Skipping .mcp.json update.")
            else:
                write_mcp_json(cwd, data_dir)
                print(f".mcp.json written in {cwd}")
    else:
        # Local scope
        if mcp_json_exists(cwd):
            ans = safe_input(".mcp.json already has rag-server. Update? [y/N]: ", default="n")
            if ans.strip().lower().startswith("y"):
                write_mcp_json(cwd, data_dir)
                print(f".mcp.json updated in {cwd}")
            else:
                print("Skipping .mcp.json update.")
                mcp_scope_description = f"local (existing, kept): {cwd / '.mcp.json'}"
        else:
            write_mcp_json(cwd, data_dir)
            print(f".mcp.json written in {cwd}")
        if not mcp_scope_description:
            mcp_scope_description = f"local: {cwd / '.mcp.json'}"

    # --- 4. llm.yaml copy ---
    from importlib.resources import files

    llm_yaml_path = cwd / "llm.yaml"
    do_copy_llm = True
    if llm_yaml_path.exists():
        ans = safe_input("llm.yaml already exists. Overwrite? [y/N]: ", default="n")
        do_copy_llm = ans.strip().lower().startswith("y")

    if do_copy_llm:
        llm_yaml_path.write_text(
            files("rag_server.assets").joinpath("llm.yaml.example").read_text()
        )
        print("llm.yaml copied — edit it to configure your LLM provider")

    # --- 5. Sentinel write (TTY only) ---
    if sys.stdin.isatty():
        SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        SENTINEL.touch()

    # --- 6. Summary ---
    print(
        f"\nSetup complete!\n"
        f"  MCP scope:  {mcp_scope_description}\n"
        f"  Data dir:   {data_dir}/\n"
        f"  llm.yaml:   {llm_yaml_path} (edit to configure LLM)\n"
        f"\nNext steps:\n"
        f"  rag-server start-qdrant   # start vector database\n"
        f"  rag-server start          # start FastAPI server"
    )
