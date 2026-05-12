#!/usr/bin/env bash
set -euo pipefail

echo "=== FellowQuant RAG CLI Smoke Test ==="

# Find the most recent wheel
WHEEL=$(ls dist/*.whl 2>/dev/null | sort -V | tail -1)
if [ -z "$WHEEL" ]; then
  echo "ERROR: No wheel found in dist/. Run 'hatch build' first." >&2
  exit 1
fi
echo "Testing wheel: $WHEEL"

# Create a temporary virtualenv
TMPVENV=$(mktemp -d)
trap "rm -rf $TMPVENV" EXIT
python -m venv "$TMPVENV"
source "$TMPVENV/bin/activate"

# Install the wheel (no extras — just the package)
pip install --quiet "$WHEEL"

# Verify entry point exists
if ! command -v rag-server &>/dev/null; then
  echo "ERROR: rag-server entry point not found on PATH after install." >&2
  exit 1
fi
echo "  [OK] rag-server entry point found at: $(which rag-server)"

# Verify it exits with usage message (no args = usage + exit 1 is acceptable)
# We capture the output and check it mentions expected subcommands
OUTPUT=$(rag-server 2>&1 || true)
for CMD in start mcp start-qdrant setup; do
  if echo "$OUTPUT" | grep -q "$CMD"; then
    echo "  [OK] subcommand '$CMD' mentioned in usage"
  else
    echo "  [WARN] subcommand '$CMD' not found in usage output"
  fi
done

# Verify importlib.resources can read assets (no CUDA/GPU needed — pure stdlib)
python -c "
from importlib.resources import files
dc = files('rag_server.assets').joinpath('docker-compose.yml').read_text()
assert 'qdrant/qdrant' in dc, 'docker-compose.yml asset missing qdrant service'
assert 'build:' not in dc, 'embedded docker-compose.yml must not have rag-server build service'
lly = files('rag_server.assets').joinpath('llm.yaml.example').read_text()
assert len(lly) > 10, 'llm.yaml.example is empty'
print('  [OK] Embedded assets accessible via importlib.resources')
"

echo ""
echo "=== Smoke test PASSED ==="
