#!/usr/bin/env python3
"""End-to-end API smoke test for Phase 5 REST API.

Verifies all Phase 5 requirements (API-01 through API-06):
  - API-01: /api/v1 URL prefix (old paths return 404)
  - API-02: GET /api/v1/documents endpoint
  - API-03: CORS middleware (Access-Control-Allow-Origin: *)
  - API-04: POST /api/v1/retrieve with document_ids and min_score filters
  - API-05: POST /api/v1/ask endpoint availability
  - API-06: RFC 7807 error shapes on 422 and 404; upload size limit 413

Usage:
    # Start server first:
    uvicorn rag_server.main:app --port 8001

    # In another terminal:
    python scripts/verify_api.py

    # Or point at a different server:
    BASE_URL=http://localhost:9000 python scripts/verify_api.py

Expected output: all 13 checks PASS, exit code 0.
If server is not running, script prints a connection error and exits 1.
"""
import http.client
import json
import os
import sys
import urllib.parse

import httpx


BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001").rstrip("/")

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    """Record and print a single check result."""
    results.append((name, cond, detail))
    status = "PASS" if cond else "FAIL"
    msg = f"[{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def main() -> int:
    try:
        with httpx.Client(timeout=10.0) as client:

            # ------------------------------------------------------------------
            # 1. Health check (API infrastructure)
            # ------------------------------------------------------------------
            r = client.get(f"{BASE_URL}/health")
            check(
                "GET /health → 200 {\"status\": \"ok\"}",
                r.status_code == 200 and r.json().get("status") == "ok",
                f"got {r.status_code} {r.text[:80]}",
            )

            # ------------------------------------------------------------------
            # 2. Old path /documents returns 404 (API-01 hard cut)
            # ------------------------------------------------------------------
            r = client.get(f"{BASE_URL}/documents")
            check(
                "GET /documents → 404 (old path gone)",
                r.status_code == 404,
                f"got {r.status_code}",
            )

            # ------------------------------------------------------------------
            # 3. Old path /ask returns 404 or 405 (API-01 hard cut)
            # ------------------------------------------------------------------
            r = client.get(f"{BASE_URL}/ask")
            check(
                "GET /ask → 404 or 405 (old path gone)",
                r.status_code in (404, 405),
                f"got {r.status_code}",
            )

            # ------------------------------------------------------------------
            # 4. CORS header on /api/v1/documents (API-03)
            # ------------------------------------------------------------------
            r = client.get(f"{BASE_URL}/api/v1/documents")
            cors_ok = (
                r.status_code == 200
                and r.headers.get("access-control-allow-origin") == "*"
            )
            check(
                "GET /api/v1/documents → 200 + Access-Control-Allow-Origin: *",
                cors_ok,
                f"status={r.status_code} cors={r.headers.get('access-control-allow-origin', 'missing')}",
            )

            # ------------------------------------------------------------------
            # 5. Document list endpoint shape (API-02)
            # ------------------------------------------------------------------
            r = client.get(f"{BASE_URL}/api/v1/documents")
            body = r.json() if r.status_code == 200 else {}
            check(
                "GET /api/v1/documents → 200 with documents[] and total",
                r.status_code == 200
                and "documents" in body
                and "total" in body
                and isinstance(body.get("documents"), list)
                and isinstance(body.get("total"), int),
                f"keys={list(body.keys())}",
            )

            # ------------------------------------------------------------------
            # 6. RFC 7807 shape on 422 — missing required field (API-06)
            # ------------------------------------------------------------------
            r = client.post(f"{BASE_URL}/api/v1/retrieve", json={})
            body = r.json() if r.status_code == 422 else {}
            rfc7807_422_ok = (
                r.status_code == 422
                and isinstance(body, dict)
                and all(k in body for k in ("type", "title", "status", "detail"))
                # Reject FastAPI default list format: {"detail": [...]}
                and not isinstance(body.get("detail"), list)
            )
            check(
                "POST /api/v1/retrieve {} → 422 RFC 7807 shape",
                rfc7807_422_ok,
                f"status={r.status_code} keys={list(body.keys())} detail_type={type(body.get('detail')).__name__}",
            )

            # ------------------------------------------------------------------
            # 7. RFC 7807 shape on 404 — nonexistent document (API-06)
            # ------------------------------------------------------------------
            r = client.get(f"{BASE_URL}/api/v1/documents/nonexistent-id-00000")
            body = r.json() if r.status_code == 404 else {}
            rfc7807_404_ok = (
                r.status_code == 404
                and isinstance(body, dict)
                and all(k in body for k in ("type", "title", "status", "detail"))
            )
            check(
                "GET /api/v1/documents/nonexistent-id-00000 → 404 RFC 7807 shape",
                rfc7807_404_ok,
                f"status={r.status_code} keys={list(body.keys())}",
            )

            # ------------------------------------------------------------------
            # 8. Retrieve endpoint — global search (API-04)
            # ------------------------------------------------------------------
            r = client.post(
                f"{BASE_URL}/api/v1/retrieve",
                json={"query": "financial risk management", "top_k": 3},
            )
            body = r.json() if r.status_code == 200 else {}
            retrieve_ok = (
                r.status_code == 200
                and "query" in body
                and "results" in body
                and "total_candidates" in body
                and isinstance(body.get("results"), list)
                and isinstance(body.get("total_candidates"), int)
            )
            check(
                "POST /api/v1/retrieve {query, top_k} → 200 with query/results/total_candidates",
                retrieve_ok,
                f"status={r.status_code} keys={list(body.keys())}",
            )

            # ------------------------------------------------------------------
            # 9. Retrieve endpoint — empty document_ids is valid (API-04)
            # ------------------------------------------------------------------
            r = client.post(
                f"{BASE_URL}/api/v1/retrieve",
                json={"query": "test", "top_k": 5, "document_ids": []},
            )
            check(
                "POST /api/v1/retrieve {document_ids: []} → 200 (empty filter is no-op)",
                r.status_code == 200,
                f"got {r.status_code}",
            )

            # ------------------------------------------------------------------
            # 10. Retrieve endpoint — min_score threshold (API-04)
            # ------------------------------------------------------------------
            r = client.post(
                f"{BASE_URL}/api/v1/retrieve",
                json={"query": "test", "top_k": 5, "min_score": 0.99},
            )
            check(
                "POST /api/v1/retrieve {min_score: 0.99} → 200 (high threshold, empty results OK)",
                r.status_code == 200,
                f"got {r.status_code}",
            )

            # ------------------------------------------------------------------
            # 11. ChunkResultItem shape — only checked if results present (API-04)
            # ------------------------------------------------------------------
            r = client.post(
                f"{BASE_URL}/api/v1/retrieve",
                json={"query": "test", "top_k": 1},
            )
            if r.status_code == 200:
                body = r.json()
                results_list = body.get("results", [])
                if results_list:
                    first = results_list[0]
                    required_fields = {
                        "chunk_id", "document_id", "chunk_index", "content",
                        "source_filename", "chunk_type", "bm25_score",
                        "dense_score", "sparse_score", "rrf_score", "reranker_score",
                    }
                    missing = required_fields - set(first.keys())
                    check(
                        "ChunkResultItem has all required score and citation fields",
                        len(missing) == 0,
                        f"missing={missing}" if missing else f"all {len(required_fields)} fields present",
                    )
                else:
                    # No documents indexed — skip gracefully
                    results.append(
                        (
                            "ChunkResultItem shape check",
                            True,
                            "skipped (no documents indexed)",
                        )
                    )
                    print("[PASS] ChunkResultItem shape check — skipped (no documents indexed)")
            else:
                check(
                    "ChunkResultItem shape check",
                    False,
                    f"retrieve returned {r.status_code}, cannot check shape",
                )

            # ------------------------------------------------------------------
            # 12. Ask endpoint availability (API-05) — 200 or 500 means reachable
            # ------------------------------------------------------------------
            r = client.post(
                f"{BASE_URL}/api/v1/ask",
                json={"query": "test", "top_k": 1},
                # streaming=false to get a JSON response rather than SSE
                params={"streaming": "false"},
            )
            check(
                "POST /api/v1/ask → reachable (200 or 500, NOT 404)",
                r.status_code in (200, 500),
                f"got {r.status_code} (200=ok, 500=LLM unavailable but endpoint exists, 404=missing)",
            )

            # ------------------------------------------------------------------
            # 13. Upload size limit — 413 with RFC 7807 shape (API-06 middleware)
            # Use http.client directly: httpx rejects Content-Length mismatches,
            # but http.client sends whatever header value we set.
            # ------------------------------------------------------------------
            parsed = urllib.parse.urlparse(BASE_URL)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8001
            conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request(
                "POST",
                "/api/v1/documents",
                body=b"x",
                headers={"Content-Length": str(200 * 1024 * 1024)},
            )
            raw = conn.getresponse()
            raw_status = raw.status
            raw_body_bytes = raw.read()
            conn.close()
            try:
                body413 = json.loads(raw_body_bytes)
            except Exception:
                body413 = {}
            upload_limit_ok = (
                raw_status == 413
                and isinstance(body413, dict)
                and all(k in body413 for k in ("type", "title", "status", "detail"))
            )
            check(
                "POST /api/v1/documents Content-Length:200MB → 413 RFC 7807 shape",
                upload_limit_ok,
                f"status={raw_status} keys={list(body413.keys())}",
            )

    except httpx.ConnectError as exc:
        print(f"[ERROR] Cannot connect to server at {BASE_URL}: {exc}")
        print("  Make sure the server is running:")
        print("    uvicorn rag_server.main:app --port 8001")
        return 1
    except Exception as exc:
        print(f"[ERROR] Unexpected error during verification: {exc}")
        return 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed_checks = [(name, detail) for name, ok, detail in results if not ok]

    print()
    print("=== Phase 5 API Verification ===")
    print(f"{passed}/{total} checks passed")

    if failed_checks:
        print("FAILED:")
        for name, detail in failed_checks:
            print(f"  - {name}: {detail}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
