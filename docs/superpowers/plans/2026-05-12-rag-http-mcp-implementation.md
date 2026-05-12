# RAG Server HTTP MCP + Stable Data Directory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-client stdio MCP with a shared HTTP MCP endpoint and make `rag-server/data` the deterministic default data directory.

**Architecture:** Extract shared MCP/REST configuration around the existing FastAPI app, expose a local HTTP MCP endpoint at `/mcp`, and make settings derive an absolute repo-local data path when `DATA_DIR` is not explicitly set. Align compose/setup output with the canonical app port `8001`.

**Tech Stack:** Python 3.12+, FastAPI, FastMCP, Pydantic Settings, unittest, Docker Compose

---

### Task 1: Add regression tests for settings and MCP setup output

**Files:**
- Create: `tests/test_config_defaults.py`
- Create: `tests/test_setup_wizard_http.py`
- Modify: `src/rag_server/config.py`
- Modify: `src/rag_server/cli/setup_wizard.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_default_data_dir_is_repo_local_data():
    ...

def test_write_mcp_json_uses_http_url():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m unittest tests.test_config_defaults tests.test_setup_wizard_http -v`
Expected: FAIL because settings still default to relative `./data` and setup still emits stdio MCP config.

- [ ] **Step 3: Write minimal implementation**

```python
# config.py
DEFAULT_DATA_DIR = ...

# setup_wizard.py
config["mcpServers"]["rag-server"] = {"type": "http", "url": "..."}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m unittest tests.test_config_defaults tests.test_setup_wizard_http -v`
Expected: PASS

### Task 2: Add HTTP MCP URL helpers and port alignment tests

**Files:**
- Create: `tests/test_http_mcp_config.py`
- Modify: `src/rag_server/config.py`
- Modify: `src/rag_server/cli/commands.py`
- Modify: `docker-compose.yml`
- Modify: `src/rag_server/assets/docker-compose.yml`

- [ ] **Step 1: Write the failing test**

```python
def test_mcp_url_defaults_to_local_8001():
    ...

def test_start_command_uses_canonical_port():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m unittest tests.test_http_mcp_config -v`
Expected: FAIL until canonical URL/port helpers exist and compose aligns with port `8001`.

- [ ] **Step 3: Write minimal implementation**

```python
@property
def mcp_url(self) -> str:
    return "http://127.0.0.1:8001/mcp"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m unittest tests.test_http_mcp_config -v`
Expected: PASS

### Task 3: Expose HTTP MCP from the app

**Files:**
- Modify: `src/rag_server/main.py`
- Modify: `src/rag_server/mcp_server.py`
- Modify: `src/rag_server/cli/commands.py`

- [ ] **Step 1: Write the failing test**

```python
def test_app_exposes_http_mcp_endpoint():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m unittest tests.test_http_mcp_config -v`
Expected: FAIL because `/mcp` is not mounted yet.

- [ ] **Step 3: Write minimal implementation**

```python
mcp_app = mcp.http_app(path="/mcp", transport="streamable-http")
app.mount("/mcp", mcp_app)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m unittest tests.test_http_mcp_config -v`
Expected: PASS

### Task 4: Verify targeted behavior

**Files:**
- Modify: `README.md`
- Modify: `.mcp.json` (if keeping repo example in sync)

- [ ] **Step 1: Run targeted tests**

Run: `./.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 2: Run lightweight runtime verification**

Run: `./.venv/bin/python -m compileall src/rag_server`
Expected: PASS

- [ ] **Step 3: Update docs/config examples**

```json
{"type":"http","url":"http://127.0.0.1:8001/mcp"}
```

- [ ] **Step 4: Summarize any manual follow-up**

Document that running compose with the `app` profile is still required for the containerized app service.
