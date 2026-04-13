#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# batch_ingest.sh — Upload PDFs in batches of BATCH_SIZE, wait for
# each batch to finish, restart the server to free RAM, then repeat.
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

BATCH_SIZE=${1:-5}
UPLOAD_DIR="/tmp/ingest-upload"
SERVER_URL="http://localhost:8001"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="$PROJECT_DIR/.logs/rag_server.log"
DB_FILE="$PROJECT_DIR/data/rag.db"

# ── Collect files to upload ──────────────────────────────────────
# Only files not yet indexed (compare against DB filenames)
INDEXED=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_FILE')
for r in conn.execute(\"SELECT filename FROM documents WHERE status='indexed'\"):
    print(r[0])
conn.close()
")

FILES=()
for f in "$UPLOAD_DIR"/book_*.pdf; do
    fname=$(basename "$f")
    if ! echo "$INDEXED" | grep -qx "$fname"; then
        FILES+=("$f")
    fi
done

TOTAL=${#FILES[@]}
if [ "$TOTAL" -eq 0 ]; then
    echo "✓ Nothing to upload — all files already indexed."
    exit 0
fi

echo "Found $TOTAL files to ingest in batches of $BATCH_SIZE"
echo "─────────────────────────────────────────────────────"

# ── Helper: start server ─────────────────────────────────────────
start_server() {
    echo "[*] Starting Qdrant..."
    sg docker -c "docker start rag-qdrant" >/dev/null 2>&1
    sleep 3

    echo "[*] Starting RAG server..."
    cd "$PROJECT_DIR"
    nohup uv run rag-server start >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "    PID=$SERVER_PID"

    # Wait for server to be ready (models take time to load)
    for i in $(seq 1 90); do
        if curl -s "$SERVER_URL/health" >/dev/null 2>&1; then
            echo "    Server ready."
            return 0
        fi
        sleep 3
    done
    echo "    ERROR: Server did not start in 270s"
    return 1
}

# ── Helper: stop server ─────────────────────────────────────────
stop_server() {
    echo "[*] Stopping RAG server..."
    pkill -f "rag.server" 2>/dev/null || true
    sleep 3
    # Make sure worker subprocess is also dead
    pkill -f "rag.server" 2>/dev/null || true
    sleep 1

    echo "[*] Stopping Qdrant..."
    sg docker -c "docker stop rag-qdrant" >/dev/null 2>&1 || true
    sleep 2
}

# ── Helper: wait for batch to finish ─────────────────────────────
wait_for_batch() {
    local expected=$1
    local poll_interval=30
    echo "[*] Waiting for $expected documents to finish indexing..."

    while true; do
        local counts
        counts=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_FILE')
rows = conn.execute('SELECT status, COUNT(*) FROM documents GROUP BY status').fetchall()
d = dict(rows)
indexed = d.get('indexed', 0)
indexing = d.get('indexing', 0)
pending = d.get('pending', 0)
failed = d.get('failed', 0)
partial = d.get('indexed_partial', 0)
print(f'{indexed} {indexing} {pending} {failed} {partial}')
conn.close()
")
        read -r indexed indexing pending failed partial <<< "$counts"
        echo "    indexed=$indexed  indexing=$indexing  pending=$pending  failed=$failed  partial=$partial"

        if [ "$indexing" -eq 0 ] && [ "$pending" -eq 0 ]; then
            echo "    Batch complete."
            return 0
        fi

        # Check if server is still alive
        if ! curl -s "$SERVER_URL/health" >/dev/null 2>&1; then
            echo "    WARNING: Server appears down (OOM?). Aborting batch."
            return 1
        fi

        sleep "$poll_interval"
    done
}

# ── Main loop ────────────────────────────────────────────────────
batch_num=0
for ((i=0; i<TOTAL; i+=BATCH_SIZE)); do
    batch_num=$((batch_num + 1))
    batch_files=("${FILES[@]:i:BATCH_SIZE}")
    batch_count=${#batch_files[@]}

    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo " BATCH $batch_num: files $((i+1))-$((i+batch_count)) of $TOTAL"
    echo "═══════════════════════════════════════════════════════"

    # Start fresh server
    start_server
    if [ $? -ne 0 ]; then
        echo "FATAL: Could not start server. Exiting."
        exit 1
    fi

    # Upload batch
    echo "[*] Uploading $batch_count files..."
    for f in "${batch_files[@]}"; do
        fname=$(basename "$f")
        status=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$SERVER_URL/api/v1/documents" \
            -F "file=@${f}")
        echo "    $fname → HTTP $status"
        if [ "$status" != "202" ]; then
            echo "    WARNING: unexpected status for $fname"
        fi
    done

    # Wait for processing
    if ! wait_for_batch "$batch_count"; then
        echo "WARNING: Batch $batch_num did not complete cleanly."
        echo "Check logs: tail -100 $LOG_FILE"
    fi

    # Show RAM before stopping
    echo "[*] Memory before restart:"
    free -h | head -2 | sed 's/^/    /'

    # Stop everything to free RAM
    stop_server

    echo "[*] Memory after restart:"
    free -h | head -2 | sed 's/^/    /'
done

echo ""
echo "═══════════════════════════════════════════════════════"
echo " ALL DONE"
echo "═══════════════════════════════════════════════════════"
python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_FILE')
for r in conn.execute('SELECT status, COUNT(*) FROM documents GROUP BY status'):
    print(f'  {r[0]}: {r[1]}')
conn.close()
"
