#!/usr/bin/env bash
# External RAM monitor — polls every 5s and writes to persistent log.
# Survives OOM kills since it's a separate lightweight process.
LOG="$(cd "$(dirname "$0")/.." && pwd)/.logs/ram_monitor.log"

echo "=== RAM Monitor started $(date) ===" >> "$LOG"
while true; do
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    mem=$(free -m | awk '/Mem:/{printf "total=%sMB used=%sMB free=%sMB avail=%sMB", $2, $3, $4, $7}')

    # Find the heaviest rag-server related process by RSS
    best_pid=""
    best_rss=0
    for pid in $(pgrep -f "rag.server" 2>/dev/null); do
        rss_kb=$(awk '/VmRSS/{print $2}' /proc/$pid/status 2>/dev/null || echo 0)
        if [ "$rss_kb" -gt "$best_rss" ] 2>/dev/null; then
            best_rss=$rss_kb
            best_pid=$pid
        fi
    done

    if [ -n "$best_pid" ]; then
        rss_mb=$((best_rss / 1024))
        echo "$ts | $mem | worker_rss=${rss_mb}MB (pid=$best_pid)" >> "$LOG"
    else
        echo "$ts | $mem | worker=not_found" >> "$LOG"
    fi
    sleep 5
done
