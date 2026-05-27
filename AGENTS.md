# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.12 package under `src/rag_server`. Core areas include `api/` for FastAPI routes and schemas, `cli/` for the `rag-server` command, `ingestion/` for parsers and chunking, `retrieval/` for hybrid search and reranking, `llm/` for provider adapters, `database/` for SQLAlchemy setup, and `vector_store/` for Qdrant integration. Tests live in `tests/`. Alembic migrations are in `alembic/versions/`. Operational scripts are in `scripts/`, docs in `docs/`, Postman assets in `postman/`, and runtime data defaults to `data/`.

## Build, Test, and Development Commands

- `uv sync`: install project dependencies from `pyproject.toml` and `uv.lock`.
- `docker compose up -d qdrant`: start the local Qdrant vector store.
- `uv run alembic upgrade head`: apply SQLite metadata migrations.
- `./scripts/start.sh`: run the FastAPI server on port `8001` with hot reload and logs in `.logs/rag_server.log`.
- `uv run rag-server start`: run the installed CLI server entry point.
- `uv run pytest`: run the test suite.
- `pre-commit run --all-files`: run Ruff lint fixes and formatting across the repository.
- `hatch build`: build distribution artifacts; PyPI publishing is triggered by `v*` tags.

## Coding Style & Naming Conventions

Use 4-space indentation, type hints for public interfaces, and clear module names in `snake_case`. Keep API schemas in `api/schemas.py`, route handlers in `api/*.py`, and provider-specific code in the matching package. Ruff is the formatter and linter via `.pre-commit-config.yaml`; install hooks with `pre-commit install`.

## Testing Guidelines

Tests are Python files named `test_*.py` in `tests/`. Existing tests use `unittest.TestCase`, but `uv run pytest` discovers them. Add focused tests for config defaults, CLI/setup behavior, packaging assumptions, API contracts, and migration-sensitive changes. For runtime verification against a live server, use scripts such as `python scripts/verify_api.py` and the ordered storage/ingestion/retrieval/LLM checks described in `README.md`.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit-style subjects such as `feat(rag-server): switch MCP to shared HTTP endpoint`, `fix(rag-server): add Docker image startup path`, and `chore(pre-commit): add ruff hook`. Keep commits scoped and imperative. Pull requests should describe the behavior change, list verification commands run, call out migrations or configuration changes, and link related issues or design docs when applicable.

## Security & Configuration Tips

Do not commit local secrets, real AWS credentials, or machine-specific `llm.yaml` values. Use `.env.example` and `llm.yaml.example` as templates. Treat `data/`, `.logs/`, and generated indexes as local runtime state unless a change explicitly requires fixture data.
