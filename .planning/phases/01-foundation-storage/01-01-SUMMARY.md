---
phase: 01-foundation-storage
plan: "01"
subsystem: infra
tags: [python, pydantic-settings, docker, qdrant, fastapi, sqlalchemy, alembic]

# Dependency graph
requires: []
provides:
  - pyproject.toml with all Phase 1+ dependencies declared (qdrant-client, sqlalchemy, aiosqlite, alembic, pydantic-settings, fastapi, uvicorn, python-dotenv)
  - src/rag_server package root
  - Settings class loading DATA_DIR from environment with sqlite_url and qdrant_url properties
  - docker-compose.yml running Qdrant v1.13.4 with persistent ./data/qdrant/ volume and TCP healthcheck
  - .gitignore excluding /data/ and .env from version control
affects:
  - 01-02-foundation-storage
  - 01-03-foundation-storage
  - all future phases (dependency declarations and Settings class are project-wide)

# Tech tracking
tech-stack:
  added:
    - pydantic-settings>=2.0.0 (Settings class with env file support)
    - qdrant-client>=1.16.0 (vector store client)
    - sqlalchemy>=2.0.0 (async ORM)
    - aiosqlite>=0.20.0 (async SQLite driver)
    - alembic>=1.14.0 (DB migrations)
    - fastapi>=0.115.0 (REST API framework)
    - uvicorn[standard]>=0.34.0 (ASGI server)
    - python-dotenv>=1.0.0 (dotenv loading)
    - hatchling (build backend)
    - qdrant/qdrant:v1.13.4 (Docker image, pinned)
  patterns:
    - pydantic-settings BaseSettings with explicit DATA_DIR alias (no env_prefix) for configuration
    - lru_cache on get_settings() for single application-wide Settings instance
    - sqlite_url uses Path.resolve() for absolute path required by Alembic
    - Docker Compose profiles (app) to isolate rag-server from dev-only Qdrant startup
    - TCP socket healthcheck for Qdrant (no curl/wget in image)

key-files:
  created:
    - pyproject.toml
    - src/rag_server/__init__.py
    - src/rag_server/config.py
    - docker-compose.yml
    - .env.example
    - .gitignore
  modified: []

key-decisions:
  - "DATA_DIR env var uses Field(alias='DATA_DIR', validation_alias='DATA_DIR') with no env_prefix — user specified DATA_DIR not RAG_DATA_DIR"
  - "sqlite_url uses self.data_dir.resolve() for absolute path — required for Alembic offline mode compatibility"
  - "Qdrant image pinned to v1.13.4 (not latest) for reproducibility"
  - "rag-server Compose service under profiles: [app] so docker compose up alone starts only Qdrant during development"
  - "TCP socket healthcheck for Qdrant — bash exec 3<>/dev/tcp pattern because no curl/wget in qdrant image"

patterns-established:
  - "Settings pattern: pydantic-settings BaseSettings with lru_cache get_settings() for singleton access"
  - "Data path pattern: all data paths resolve through Settings.data_dir, never hardcoded"
  - "Docker pattern: pinned image versions, TCP healthchecks, :z volume mounts for SELinux compatibility"

requirements-completed: [STORE-01, STORE-02, STORE-03, STORE-04]

# Metrics
duration: 2min
completed: 2026-02-18
---

# Phase 1 Plan 01: Project Scaffold Summary

**hatchling Python package with pydantic-settings Settings class (DATA_DIR-driven data paths, absolute sqlite_url), Qdrant v1.13.4 Docker Compose with TCP healthcheck and ./data/qdrant/ persistent volume**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-18T21:31:43Z
- **Completed:** 2026-02-18T21:33:33Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Installable Python package (src layout, hatchling) with all 8 Phase 1+ dependencies declared in pyproject.toml
- pydantic-settings Settings class with DATA_DIR env var, lru_cache singleton, absolute sqlite_url, and ensure_data_dirs()
- Docker Compose running Qdrant v1.13.4 with persistent volume, TCP healthcheck, and app profile isolation
- .gitignore protecting /data/ and .env from accidental commits

## Task Commits

Each task was committed atomically:

1. **Task 1: Python package scaffold and dependencies** - `9dd89f7` (chore)
2. **Task 2: Settings class and Docker Compose** - `b114151` (feat)

## Files Created/Modified
- `pyproject.toml` - Project metadata, hatchling build system, 8 runtime dependencies
- `src/rag_server/__init__.py` - Package root marker (empty)
- `src/rag_server/config.py` - pydantic-settings Settings with DATA_DIR, sqlite_url, qdrant_url, ensure_data_dirs()
- `docker-compose.yml` - Qdrant v1.13.4 service + rag-server service (app profile)
- `.env.example` - Template documenting DATA_DIR and Qdrant connection vars
- `.gitignore` - Excludes /data/, .env, __pycache__, dist, venv

## Decisions Made
- DATA_DIR uses Field alias without env_prefix — user specified DATA_DIR not RAG_DATA_DIR; keeping it clean
- sqlite_url uses Path.resolve() to produce absolute path — Alembic offline mode requires non-relative URIs
- Qdrant pinned to v1.13.4 (not latest) — reproducible builds and avoids surprise breaking changes
- rag-server Compose service in profiles: [app] — `docker compose up` only starts Qdrant during development; full stack needs `docker compose --profile app up`
- TCP socket healthcheck via bash exec 3<>/dev/tcp — no curl or wget available in the Qdrant Docker image

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed pydantic-settings for verification**
- **Found during:** Task 2 (Settings class verification)
- **Issue:** pydantic-settings not installed in system Python; PEP 668 blocks pip install --break-system-packages; pyenv 3.13.3 available as alternative
- **Fix:** Installed pydantic-settings into pyenv 3.13.3 Python and used that interpreter for verification commands
- **Files modified:** None (runtime env only, not project files)
- **Verification:** `python3 -c "from src.rag_server.config import get_settings; ..."` passes with pyenv Python
- **Committed in:** Not committed (environment setup only)

---

**Total deviations:** 1 auto-fixed (1 blocking — environment setup)
**Impact on plan:** Deviation was verification-only; project files are correct and all assertions pass.

## Issues Encountered
- System Python (3.12) has PEP 668 restrictions preventing pip install; used pyenv 3.13.3 Python for verification. The pyproject.toml correctly declares requires-python>=3.12, so both versions are compatible.

## User Setup Required
None - no external service configuration required beyond running `docker compose up qdrant`.

## Next Phase Readiness
- pyproject.toml ready for `pip install -e .` in a virtualenv
- Settings class ready for import in 01-02 (SQLite layer) and 01-03 (Qdrant client wrapper)
- Docker Compose Qdrant service ready to start for 01-03 smoke test
- No blockers

---
*Phase: 01-foundation-storage*
*Completed: 2026-02-18*

## Self-Check: PASSED

- pyproject.toml: FOUND
- src/rag_server/__init__.py: FOUND
- src/rag_server/config.py: FOUND
- docker-compose.yml: FOUND
- .env.example: FOUND
- .gitignore: FOUND
- 01-01-SUMMARY.md: FOUND
- Commit 9dd89f7 (Task 1): FOUND
- Commit b114151 (Task 2): FOUND
