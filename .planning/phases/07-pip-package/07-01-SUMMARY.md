---
phase: 07-pip-package
plan: "01"
subsystem: infra
tags: [hatch, pyproject, importlib-resources, docker-compose, pip, wheel]

# Dependency graph
requires:
  - phase: 06-mcp-server
    provides: Full MCP server implementation that this packages for distribution
provides:
  - pyproject.toml configured as fellowquant-rag PyPI package with rag-server console_script
  - src/rag_server/assets/ package with embedded Qdrant-only docker-compose.yml and llm.yaml.example
  - src/rag_server/cli/ namespace package for CLI entry points (07-02)
  - Verified wheel and sdist built by hatch with assets embedded
affects:
  - 07-02 (CLI implementation uses assets and cli/ namespace created here)

# Tech tracking
tech-stack:
  added: [hatch (build tool)]
  patterns:
    - importlib.resources.files() for embedded asset access from installed wheel
    - PyPI name (fellowquant-rag) distinct from import name (rag_server) — intentional per Pattern 1

key-files:
  created:
    - src/rag_server/assets/__init__.py
    - src/rag_server/assets/docker-compose.yml
    - src/rag_server/assets/llm.yaml.example
    - src/rag_server/cli/__init__.py
  modified:
    - pyproject.toml

key-decisions:
  - "PyPI package name fellowquant-rag differs from import name rag_server — intentional namespace split"
  - "Assets embedded via hatchling automatic inclusion of non-.py files under src/rag_server/"
  - "Qdrant-only docker-compose.yml strips rag-server build service — prevents build: . failure on user machines"

patterns-established:
  - "Pattern 1: importlib.resources.files('rag_server.assets').joinpath(name) for runtime asset access"
  - "Pattern 2: cli/__init__.py namespace created ahead of implementation (07-02 adds cli/main.py)"

requirements-completed: [PKG-01]

# Metrics
duration: 1min
completed: 2026-02-21
---

# Phase 7 Plan 01: fellowquant-rag PyPI Package Setup Summary

**pyproject.toml renamed to fellowquant-rag with rag-server console_script; Qdrant-only docker-compose.yml and llm.yaml.example embedded in wheel via importlib.resources assets package; hatch build produces clean wheel and sdist**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-21T00:38:34Z
- **Completed:** 2026-02-21T00:39:40Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Updated pyproject.toml: package name changed to `fellowquant-rag`, added `[project.scripts]` with `rag-server = "rag_server.cli.main:main"`, added description/readme/license metadata
- Created `src/rag_server/assets/` package with `__init__.py` (importlib.resources marker), `docker-compose.yml` (Qdrant-only, no build service), and `llm.yaml.example` verbatim copy
- Created `src/rag_server/cli/__init__.py` namespace package ready for 07-02 CLI implementation
- Verified `hatch build` produces `fellowquant_rag-0.1.0-py3-none-any.whl` and `fellowquant_rag-0.1.0.tar.gz` with all assets inside

## Task Commits

Each task was committed atomically:

1. **Task 1: Update pyproject.toml for fellowquant-rag PyPI release** - `e942eea` (chore)
2. **Task 2: Create embedded assets package and Qdrant-only docker-compose** - `3cf69ef` (feat)
3. **Task 3: Verify wheel builds cleanly with hatch** - verification only, no files changed

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `pyproject.toml` - Renamed package to fellowquant-rag, added console_script entry point and metadata
- `src/rag_server/assets/__init__.py` - Package marker enabling importlib.resources access
- `src/rag_server/assets/docker-compose.yml` - Qdrant-only compose file (rag-server build service stripped)
- `src/rag_server/assets/llm.yaml.example` - LLM config template embedded in the wheel
- `src/rag_server/cli/__init__.py` - CLI package namespace placeholder for 07-02

## Decisions Made
- PyPI name `fellowquant-rag` differs from import name `rag_server` — standard Python packaging pattern, intentional per plan
- Qdrant-only `docker-compose.yml` strips `rag-server` build service to prevent `build: .` failures on user machines (no Dockerfile distributed via PyPI)
- Assets use hatchling automatic non-.py file inclusion under `src/rag_server/` — no explicit `include` config needed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- pyproject.toml fully configured as publishable PyPI package
- `src/rag_server/assets/` package accessible via `importlib.resources.files("rag_server.assets")` at runtime
- `src/rag_server/cli/` namespace ready for `cli/main.py` implementation in 07-02
- `hatch build` confirmed working — publish to PyPI ready after 07-02 adds CLI

---
*Phase: 07-pip-package*
*Completed: 2026-02-21*
