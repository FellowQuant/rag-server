#!/usr/bin/env bash
set -euo pipefail

SERVER_URL="${SERVER_URL:-http://localhost:8001}"
BIBLIOTECA_DIR="${BIBLIOTECA_DIR:-/home/jcanossa/workspace/fellow-quant/biblioteca}"
SUPPORTED_EXTENSIONS=("pdf" "ipynb" "tex" "epub")

tmp_docs_json="$(mktemp)"
tmp_upload_resp="$(mktemp)"
trap 'rm -f "$tmp_docs_json" "$tmp_upload_resp"' EXIT

require_server() {
  if ! curl -sf "${SERVER_URL}/health" >/dev/null 2>&1; then
    echo "ERROR: rag-server is not reachable at ${SERVER_URL}" >&2
    exit 1
  fi
}

list_non_indexed_doc_ids() {
  python3 - "$tmp_docs_json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

for doc in payload.get("documents", []):
    if doc.get("status") != "indexed":
        print(doc["id"])
PY
}

delete_non_indexed_docs() {
  echo "Fetching current documents from ${SERVER_URL}/api/v1/documents ..."
  curl -sf "${SERVER_URL}/api/v1/documents" -o "$tmp_docs_json"

  mapfile -t doc_ids < <(list_non_indexed_doc_ids)
  echo "Found ${#doc_ids[@]} document(s) with status != indexed"

  for doc_id in "${doc_ids[@]}"; do
    echo "Deleting document ${doc_id} ..."
    curl -sf --request DELETE "${SERVER_URL}/api/v1/documents/${doc_id}" >/dev/null
  done
}

upload_biblioteca_docs() {
  echo "Scanning ${BIBLIOTECA_DIR} for supported documents ..."

  mapfile -d '' -t files < <(
    find "${BIBLIOTECA_DIR}" -type f \
      \( -iname '*.pdf' -o -iname '*.ipynb' -o -iname '*.tex' -o -iname '*.epub' \) \
      -print0 | sort -z
  )

  echo "Found ${#files[@]} supported file(s) to upload"

  local idx=0
  for file_path in "${files[@]}"; do
    idx=$((idx + 1))
    filename="$(basename "$file_path")"
    status_code="$(
      curl -s -o "$tmp_upload_resp" -w '%{http_code}' \
        --location "${SERVER_URL}/api/v1/documents" \
        --form "file=@${file_path}"
    )"

    case "$status_code" in
      202)
        echo "[${idx}/${#files[@]}] ${filename} -> queued (202)"
        ;;
      409)
        echo "[${idx}/${#files[@]}] ${filename} -> duplicate, skipping (409)"
        ;;
      *)
        echo "[${idx}/${#files[@]}] ${filename} -> unexpected status ${status_code}" >&2
        echo "Response body:" >&2
        cat "$tmp_upload_resp" >&2
        ;;
    esac
  done
}

main() {
  require_server
  delete_non_indexed_docs
  upload_biblioteca_docs
}

main "$@"
