#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$ROOT_DIR/.logs"
LOG_FILE="$LOG_DIR/rag_server.log"

mkdir -p "$LOG_DIR"

CYAN='\033[0;36m'
BOLD='\033[1m'
YELLOW='\033[1;33m'
RESET='\033[0m'

printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "${BOLD}  FellowQuant RAG Server${RESET}\n"
printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "  URL  : ${YELLOW}http://0.0.0.0:8001${RESET}\n"
printf "  Docs : ${YELLOW}http://0.0.0.0:8001/docs${RESET}\n"
printf "  Log  : ${YELLOW}%s${RESET}\n" "$LOG_FILE"
printf "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n\n"

{
  echo "════════════════════════════════════════════════"
  echo "  RAG Server started — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════"
} | tee -a "$LOG_FILE"

cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

"$ROOT_DIR/.venv/bin/python" -m rag_server.cli.main start 2>&1 | tee -a "$LOG_FILE"
