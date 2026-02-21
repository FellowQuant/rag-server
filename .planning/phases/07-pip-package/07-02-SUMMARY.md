---
phase: 07-pip-package
plan: "02"
subsystem: infra
tags: [cli, uvicorn, fastmcp, mcp, setup-wizard, importlib-resources, docker-compose]

# Dependency graph
requires:
  - phase: 07-01
    provides: pyproject.toml console_script entry point, embedded assets package, cli/ namespace
  - phase: 06-mcp-server
    provides: mcp_server.py with mcp.run(transport="stdio")
provides:
  - src/rag_server/cli/main.py — rag-server dispatcher with first-run sentinel auto-trigger
  - src/rag_server/cli/commands.py — cmd_start (uvicorn 8001), cmd_mcp (zero-stdout stdio), cmd_start_qdrant (port check + docker)
  - src/rag_server/cli/setup_wizard.py — idempotent MCP registration (global/local), llm.yaml copy, DATA_DIR prompt
affects:
  - End users installing `pip install fellowquant-rag` — full CLI now functional

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy imports in CLI routing — all subcommand imports inside routing block to avoid import-time side effects"
    - "SENTINEL pattern — ~/.fellowquant-rag/setup-done file gates first-run wizard auto-trigger"
    - "safe_input() — non-TTY aware prompt wrapper; returns default immediately in CI/pipe without blocking"
    - "read-modify-write .mcp.json — json.loads → setdefault → json.dumps; never clobbers existing mcpServers keys"
    - "claude mcp add-json payload form — required (not add) to embed DATA_DIR in env block with --scope user"

key-files:
  created:
    - src/rag_server/cli/main.py
    - src/rag_server/cli/commands.py
    - src/rag_server/cli/setup_wizard.py
  modified: []

key-decisions:
  - "Lazy imports for all CLI subcommands — prevents import-time side effects; critical for mcp (stdout is JSON-RPC channel)"
  - "mcp subcommand bypasses all setup checks — any stdout before mcp.run(stdio) corrupts the JSON-RPC protocol"
  - "cmd_mcp imports mcp_server which sets multiprocessing.set_start_method(spawn) at module level — no explicit call needed in cmd_mcp"
  - "claude mcp add-json used over claude mcp add — only add-json accepts full JSON payload with env block for DATA_DIR injection"
  - "Sentinel written only in TTY — non-interactive runs do not mark setup complete to force interactive setup on next TTY session"
  - "docker-compose.yml written to ~/.fellowquant-rag/ (persistent) not tempfile — Docker volume paths in compose files break with temp directories"

patterns-established:
  - "Pattern 3: _maybe_run_setup(cmd) guard — skip for mcp, check TTY, use SENTINEL to prevent repeat prompts"
  - "Pattern 4: safe_input(prompt, default) — all wizard prompts go through this for CI/non-TTY safety"

requirements-completed: [PKG-02, PKG-03, PKG-04]

# Metrics
duration: 2min
completed: 2026-02-21
---

# Phase 7 Plan 02: CLI Dispatcher, Commands, and Setup Wizard Summary

**`rag-server` CLI fully implemented: start/mcp/start-qdrant/setup subcommands with idempotent setup wizard, global/local MCP registration via `claude mcp add-json`, and first-run sentinel auto-trigger**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-21T00:42:34Z
- **Completed:** 2026-02-21T00:45:12Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Created `src/rag_server/cli/main.py`: dispatcher with SENTINEL-gated first-run auto-trigger, lazy imports, mcp short-circuit before any setup
- Created `src/rag_server/cli/commands.py`: `cmd_start` (uvicorn 8001), `cmd_mcp` (zero-stdout MCP stdio), `is_port_open` (stdlib socket), `cmd_start_qdrant` (port check + embedded docker-compose)
- Created `src/rag_server/cli/setup_wizard.py`: idempotent wizard with global (`claude mcp add-json --scope user`) and local (read-modify-write `.mcp.json`) MCP registration, DATA_DIR prompt, llm.yaml copy, fallback when claude CLI absent, non-TTY safe via `safe_input()`

## Task Commits

Each task was committed atomically:

1. **Task 1: CLI dispatcher main.py with subcommand routing and first-run sentinel** - `48c966c` (feat)
2. **Task 2: CLI commands start, mcp, start-qdrant** - `948e777` (feat)
3. **Task 3: Setup wizard idempotent MCP registration and llm.yaml copy** - `3b95dec` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/rag_server/cli/main.py` - Dispatcher: SENTINEL, _maybe_run_setup(), main() routing all four subcommands with lazy imports
- `src/rag_server/cli/commands.py` - cmd_start (uvicorn), cmd_mcp (zero-stdout stdio), is_port_open (socket), cmd_start_qdrant (docker compose)
- `src/rag_server/cli/setup_wizard.py` - cmd_setup idempotent wizard: scope selection, DATA_DIR, MCP registration, llm.yaml copy, sentinel

## Decisions Made
- Lazy imports for all subcommand routing — defers torch/CUDA imports until actually needed; avoids `mcp_server.py` module-level `set_start_method` firing during CLI help/routing
- `mcp` subcommand bypasses `_maybe_run_setup` entirely — stdout is the JSON-RPC transport; any output before `mcp.run()` corrupts the protocol
- `claude mcp add-json` (not `claude mcp add`) — `add-json` accepts full JSON payload enabling `env` block injection for DATA_DIR; positional-arg form cannot pass env
- Sentinel written only when `sys.stdin.isatty()` — non-interactive runs (CI, pipes) do not consume the first-run wizard slot; forces proper interactive setup
- `docker-compose.yml` written to `~/.fellowquant-rag/` (not tempfile) — Docker volume mount paths in compose files break when the file lives in a system temp directory

## Deviations from Plan

None — plan executed exactly as written.

Note: The plan's verify script for Task 2 used port 99999 (invalid: max is 65535). This is a test script error, not a code bug. Verified with port 19999 instead — behavior identical.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness
- Phase 7 complete: `fellowquant-rag` PyPI package is fully functional — `pip install fellowquant-rag` followed by `rag-server setup` delivers a configured, ready-to-run system
- `hatch build` from Phase 7-01 already verified; wheel now includes cli/main.py, cli/commands.py, cli/setup_wizard.py
- Ready for `hatch publish` or TestPyPI upload when distribution is desired

---
*Phase: 07-pip-package*
*Completed: 2026-02-21*
