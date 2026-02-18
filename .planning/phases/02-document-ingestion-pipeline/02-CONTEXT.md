# Phase 2: Document Ingestion Pipeline - Context

**Gathered:** 2026-02-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Users submit documents (PDF, LaTeX, Jupyter notebook) and the system parses, chunks, embeds with BGE-M3, and stores vectors in Qdrant — making chunks immediately searchable. This phase covers the full ingestion pipeline: upload → async worker → parse → chunk → embed → index. The query/retrieval API is Phase 3; the REST endpoint surface is Phase 5.

</domain>

<decisions>
## Implementation Decisions

### Ingestion mode
- **Async** — upload returns a document ID immediately; caller polls status via GET /documents/{id}
- Status states: `pending` → `indexing` → `indexed` / `indexed_partial` / `failed`
- Status granularity: simple states only (no percentage progress)
- **Separate worker process** handles indexing — isolates CPU/VRAM-heavy pipeline from API process
- **Serial queue** — one document processed at a time; prevents VRAM/CPU contention with Docling + BGE-M3

### Parser selection
- **Always Docling** for PDF — maximum fidelity, no fast-path fallback for PDFs
- **LaTeX (.tex)**: Claude's discretion — direct text extraction preserving LaTeX markup as-is (no pdflatex compilation required)
- **Jupyter (.ipynb)**: markdown cells + code cells only — skip outputs (execution artifacts add noise)

### Failure handling
- **Page-level failures**: skip failed pages, index the rest → document status becomes `indexed_partial`
- **Whole document failures** (e.g., corrupt file, unsupported format): status = `failed`
- **On partial failure**: failed page numbers stored in `error_msg` field of the Document record
- **On any failure**: roll back any partial chunks/vectors already written — clean failure state
- **Retry mechanism**: re-upload the same file; system detects `indexed_partial` status via content hash match and re-processes only the missing/failed pages
- **Error visibility**: summary in GET /documents/{id} response + full traceback in server logs

### Embedding at ingestion time
- BGE-M3 embeddings generated **during ingestion** — single-pass pipeline: parse → chunk → embed → upsert Qdrant
- When document status = `indexed`, chunks are immediately queryable (no separate embedding step)
- BGE-M3 loaded **once at worker startup** and kept in memory across all ingestion jobs — fastest per-document throughput; VRAM freed when worker shuts down

### Claude's Discretion
- LaTeX parser implementation details (pylatexenc tokenization strategy, math environment extraction)
- Worker process communication mechanism (asyncio Queue, multiprocessing, or subprocess)
- BGE-M3 batch size for embedding (tune for available VRAM)
- Qdrant upsert batching strategy
- Exact error message format in API response vs logs

</decisions>

<specifics>
## Specific Ideas

- The `indexed_partial` status is critical — it distinguishes "fully searchable" from "searchable but with gaps". Callers (Phase 5 API, Phase 6 MCP) need to communicate this distinction to users.
- Content hash match on re-upload (already in Phase 1 SQLite schema via `file_hash`) enables intelligent retry — the system already knows which pages succeeded and can skip them.
- BGE-M3 loaded at worker startup means the worker process is a long-lived daemon, not a one-shot script. Shutdown should unload models cleanly.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-document-ingestion-pipeline*
*Context gathered: 2026-02-18*
