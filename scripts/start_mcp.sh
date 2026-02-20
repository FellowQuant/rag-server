#!/usr/bin/env bash
# Start the FellowQuant MCP RAG Server in dev/inspector mode.
# Launches the MCP inspector UI for interactive tool testing.
# Claude Code uses .mcp.json directly — this script is for manual testing.
# Colored output on terminal; timestamped plain-text log in .logs/mcp_server.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$ROOT_DIR/.logs"
LOG_FILE="$LOG_DIR/mcp_server.log"

mkdir -p "$LOG_DIR"

# ── banner ──────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'
BOLD='\033[1m'
YELLOW='\033[1;33m'
RESET='\033[0m'

printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "${BOLD}  FellowQuant MCP RAG Server${RESET}\n"
printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "  Inspector : ${YELLOW}http://localhost:5173${RESET}\n"
printf "  Log       : ${YELLOW}%s${RESET}\n" "$LOG_FILE"
printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n\n"

# ── session header in log ────────────────────────────────────────────────────
{
  echo "════════════════════════════════════════════════"
  echo "  MCP Server started — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════"
} >> "$LOG_FILE"

# ── run ──────────────────────────────────────────────────────────────────────
cd "$ROOT_DIR"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

uv run mcp dev src/rag_server/mcp_server.py \
    2>&1 | tee >(
        while IFS= read -r line; do
            clean=$(printf '%s' "$line" | sed 's/\x1b\[[0-9;]*[mGKHFJA-Z]//g; s/\r//g')
            printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$clean"
        done >> "$LOG_FILE"
    )
