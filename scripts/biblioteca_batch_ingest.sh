#!/usr/bin/env bash
set -euo pipefail

BATCH_SIZE="${BATCH_SIZE:-8}"
BASE_DIR="/home/jcanossa/workspace/fellow-quant/biblioteca"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_URL="http://127.0.0.1:8001"
LOG_DIR="$PROJECT_DIR/.logs"
RUN_LOG="$LOG_DIR/biblioteca_batch_ingest.log"
STATE_FILE="$LOG_DIR/biblioteca_batch_ingest.state"
DB_FILE="$PROJECT_DIR/data/rag.db"
mkdir -p "$LOG_DIR"

mapfile -d '' FILES < <(find "$BASE_DIR" -type f \( -iname '*.pdf' -o -iname '*.ipynb' -o -iname '*.tex' \) -print0 | sort -z)
TOTAL=${#FILES[@]}
if [ "$TOTAL" -eq 0 ]; then
  echo "No supported files found under $BASE_DIR" | tee -a "$RUN_LOG"
  exit 1
fi

echo "=== biblioteca batch ingest started $(date -Is) ===" | tee -a "$RUN_LOG"
echo "TOTAL_SUPPORTED=$TOTAL BATCH_SIZE=$BATCH_SIZE" | tee -a "$RUN_LOG"

start_server() {
  docker start rag-qdrant >/dev/null 2>&1 || true
  if curl -sf "$SERVER_URL/health" >/dev/null 2>&1; then
    echo "server already healthy" | tee -a "$RUN_LOG"
    return 0
  fi
  nohup bash "$PROJECT_DIR/scripts/start.sh" >> "$RUN_LOG" 2>&1 &
  for _ in $(seq 1 180); do
    if curl -sf "$SERVER_URL/health" >/dev/null 2>&1; then
      echo "server ready" | tee -a "$RUN_LOG"
      return 0
    fi
    sleep 2
  done
  echo "ERROR: server did not become healthy" | tee -a "$RUN_LOG"
  return 1
}

stop_server() {
  pkill -f '/home/jcanossa/workspace/fellow-quant/core/rag-server/.venv/bin/python -m rag_server.cli.main start' 2>/dev/null || true
  pkill -f 'rag_server.worker.process' 2>/dev/null || true
  sleep 5
  docker stop rag-qdrant >/dev/null 2>&1 || true
  sleep 2
}

wait_for_doc_ids() {
  local max_rounds=${1:-240}
  shift
  if [ "$#" -eq 0 ]; then
    echo "no accepted documents in this batch; skipping wait" | tee -a "$RUN_LOG"
    return 0
  fi
  local ids=($*)
  echo "waiting on ${#ids[@]} accepted document(s)" | tee -a "$RUN_LOG"
  for _ in $(seq 1 "$max_rounds"); do
    if [ ! -f "$DB_FILE" ]; then
      sleep 2
      continue
    fi
    COUNTS_RAW=$(DOC_IDS="${ids[*]}" DB_FILE="$DB_FILE" python3 - <<'PY'
import os, sqlite3
ids = [x for x in os.environ['DOC_IDS'].split() if x]
con = sqlite3.connect(os.environ['DB_FILE'])
cur = con.cursor()
status_counts = {'indexed': 0, 'indexing': 0, 'pending': 0, 'failed': 0, 'indexed_partial': 0, 'missing': 0}
for doc_id in ids:
    cur.execute('select status from documents where id=?', (doc_id,))
    row = cur.fetchone()
    if row is None:
        status_counts['missing'] += 1
    else:
        status_counts[row[0]] = status_counts.get(row[0], 0) + 1
con.close()
print(status_counts['indexed'])
print(status_counts['indexing'])
print(status_counts['pending'])
print(status_counts['failed'])
print(status_counts['indexed_partial'])
print(status_counts['missing'])
PY
)
    readarray -t arr <<< "$COUNTS_RAW"
    indexed=${arr[0]:-0}; indexing=${arr[1]:-0}; pending=${arr[2]:-0}; failed=${arr[3]:-0}; partial=${arr[4]:-0}; missing=${arr[5]:-0}
    echo "batch_status indexed=$indexed indexing=$indexing pending=$pending failed=$failed partial=$partial missing=$missing" | tee -a "$RUN_LOG"
    if [ "$indexing" -eq 0 ] && [ "$pending" -eq 0 ]; then
      return 0
    fi
    if ! curl -sf "$SERVER_URL/health" >/dev/null 2>&1; then
      echo "WARNING: server appears down while waiting on batch docs" | tee -a "$RUN_LOG"
      return 1
    fi
    sleep 15
  done
  return 1
}

for ((i=0; i<TOTAL; i+=BATCH_SIZE)); do
  batch=$((i/BATCH_SIZE+1))
  end=$((i+BATCH_SIZE)); [ "$end" -gt "$TOTAL" ] && end=$TOTAL
  echo "batch=$batch start_index=$i end_index=$end" > "$STATE_FILE"
  echo "--- BATCH $batch ($(date -Is)) files $((i+1))-$end/$TOTAL ---" | tee -a "$RUN_LOG"
  start_server
  accepted_ids=()
  for ((j=i; j<end; j++)); do
    f="${FILES[$j]}"
    status=$(curl -s -o /tmp/rag_upload_resp.json -w '%{http_code}' -X POST "$SERVER_URL/api/v1/documents" -F "file=@${f}")
    fname=$(basename "$f")
    if [ "$status" = "202" ]; then
      doc_id=$(python3 - <<'PY'
import json
try:
    data=json.load(open('/tmp/rag_upload_resp.json'))
    print(data.get('id',''))
except Exception:
    print('')
PY
)
      accepted_ids+=("$doc_id")
      echo "upload [$((j+1))/$TOTAL] $fname -> HTTP 202 id=$doc_id" | tee -a "$RUN_LOG"
    elif [ "$status" = "409" ]; then
      detail=$(python3 - <<'PY'
import json
try:
    data=json.load(open('/tmp/rag_upload_resp.json'))
    print(data.get('detail','duplicate'))
except Exception:
    print('duplicate')
PY
)
      echo "upload [$((j+1))/$TOTAL] $fname -> HTTP 409 SKIP ($detail)" | tee -a "$RUN_LOG"
      continue
    else
      echo "upload [$((j+1))/$TOTAL] $fname -> HTTP $status" | tee -a "$RUN_LOG"
    fi
    sleep 1
  done
  if ! wait_for_doc_ids 240 "${accepted_ids[@]}"; then
    echo "WARNING: batch $batch did not settle cleanly" | tee -a "$RUN_LOG"
  fi
  stop_server
  echo "batch=$batch completed $(date -Is) accepted=${#accepted_ids[@]}" | tee -a "$RUN_LOG"
  sleep 5
done

echo "=== biblioteca batch ingest completed $(date -Is) ===" | tee -a "$RUN_LOG"
rm -f "$STATE_FILE"
