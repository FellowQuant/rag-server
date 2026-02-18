# Phase 1: Foundation & Storage - Context

**Gathered:** 2026-02-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish the persistent storage infrastructure that all future phases build on: Qdrant (local Docker) for vector embeddings, SQLite for document and chunk metadata. This phase delivers a working storage layer with the correct schema — no parsing, no retrieval logic, no API. Just storage that can be written to and read from correctly.

</domain>

<decisions>
## Implementation Decisions

### Data location & portability
- Default data directory: `./data/` (project-relative)
- Override via `DATA_DIR` environment variable — `./data/` is the fallback default
- `./data/` must be added to `.gitignore` — document data never committed
- Internal layout:
  - `./data/qdrant/` — Qdrant persistence volume (mounted into Docker container)
  - `./data/rag.db` — SQLite database for document and chunk metadata

### Document identity & deduplication
- Duplicate detection via SHA-256 content hash of the uploaded file bytes
- Hashing is fast enough even for large PDFs (I/O-bound, typically <1s)
- On duplicate upload: reject with HTTP 409 + existing document ID in response body
- No force-replace shortcut — user must explicitly DELETE the existing document before re-ingesting
- Hash stored in SQLite document table for fast lookup on every upload

### Chunk metadata schema
Fields stored per chunk in SQLite:
- `document_id` — foreign key to source document
- `page_number` — page in PDF (or cell index for .ipynb)
- `section_heading` — nearest H1/H2/H3 above the chunk (null if none)
- `chunk_type` — enum: `text` | `formula` | `table` | `code`
- `chunk_index` — sequential position within the document (enables ordered reconstruction)
- `content` — the chunk text used for embedding (for formula chunks: enriched context = preceding paragraph + LaTeX)
- `display_content` — for formula chunks only: raw LaTeX stored separately for rendering in API responses; null for other chunk types

Character offsets not stored in v1 — page number + chunk_index is sufficient for citation.

### Qdrant deployment mode
- Run Qdrant as a Docker container (not embedded in-process mode)
- Project includes `docker-compose.yml` managing both Qdrant and the RAG server
- Qdrant port 6333 exposed on `localhost` — enables inspection via Qdrant web dashboard at `http://localhost:6333/dashboard`
- Qdrant persistence volume mounted to `./data/qdrant/`
- Qdrant collection schema must support multi-vector storage from day one:
  - Dense vector field (1024d, cosine) — BGE-M3 dense embeddings
  - Sparse vector field — BGE-M3 learned sparse weights (for hybrid retrieval)
  - Payload fields: document_id, chunk_id, chunk_type, page_number, section_heading, chunk_index

### Claude's Discretion
- SQLite schema details (indexes, constraints, migration strategy)
- Qdrant collection naming convention
- SQLAlchemy model structure
- Docker Compose service naming and healthcheck configuration
- Environment variable naming beyond `DATA_DIR` (e.g., `QDRANT_URL`, `QDRANT_PORT`)

</decisions>

<specifics>
## Specific Ideas

- The Qdrant multi-vector schema must be correct from Phase 1 — retroactively adding sparse vector fields to an existing collection is painful. Build the full BGE-M3 schema (dense + sparse) even though sparse isn't used until Phase 3.
- SHA-256 hash stored in SQLite allows O(1) duplicate check on ingest without reading Qdrant.
- `display_content` field on formula chunks is the bridge between embedding-time enrichment (paragraph + LaTeX) and response-time rendering (raw LaTeX for display).

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-foundation-storage*
*Context gathered: 2026-02-18*
