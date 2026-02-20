#!/usr/bin/env bash
# Start the FellowQuant RAG Server.
# Colored output on terminal; timestamped plain-text log in .logs/rag_server.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$ROOT_DIR/.logs"
LOG_FILE="$LOG_DIR/rag_server.log"

mkdir -p "$LOG_DIR"

# ── banner ──────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'
BOLD='\033[1m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "${BOLD}  FellowQuant RAG Server${RESET}\n"
printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "  URL  : ${YELLOW}http://0.0.0.0:8001${RESET}\n"
printf "  Docs : ${YELLOW}http://0.0.0.0:8001/docs${RESET}\n"
printf "  Log  : ${YELLOW}%s${RESET}\n" "$LOG_FILE"
printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n\n"

# ── session header in log ────────────────────────────────────────────────────
{
  echo "════════════════════════════════════════════════"
  echo "  RAG Server started — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════"
} >> "$LOG_FILE"

# ── run ──────────────────────────────────────────────────────────────────────
# tee splits output:
#   • left  → stdout (keeps ANSI colours for the terminal)
#   • right → strips ANSI, prepends timestamp, appends to log file
cd "$ROOT_DIR"
# Prevent CUDA memory fragmentation stalls in CodeFormulaV2 VLM.
# Without this, CUDA defragments mid-run causing ~77s stalls per fragmented batch.
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# Reranker runs on GPU (auto). Safe with Qwen2.5-7B Q4_K_M (~4.5 GB) — total ~7.6 GB.
# Set RERANKER_DEVICE=cpu if switching back to a large LLM (>10 GB).

uv run uvicorn rag_server.main:app \
    --host 0.0.0.0 \
    --port 8001 \
    --reload \
    2>&1 | tee >(
        while IFS= read -r line; do
            clean=$(printf '%s' "$line" | sed 's/\x1b\[[0-9;]*[mGKHFJA-Z]//g; s/\r//g')
            printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$clean"
        done >> "$LOG_FILE"
    )
