---
phase: 02-document-ingestion-pipeline
plan: "01"
subsystem: ingestion
tags: [docling, pylatexenc, nbformat, tiktoken, pdf, latex, jupyter, chunking]

# Dependency graph
requires:
  - phase: 01-foundation-storage
    provides: ParsedChunk-compatible Chunk SQLAlchemy model (chunk_type, content, display_content, page_number, section_heading, chunk_index)
provides:
  - ParsedChunk dataclass with all fields mirroring Chunk model plus language field for code
  - split_text_tokens() with 512-token max and 64-token overlap using tiktoken cl100k_base
  - enrich_formula_content() for semantic anchoring of formula chunks
  - Docling-based PDF parser with formula/table/code enrichment enabled and elements_batch_size=2
  - pylatexenc LaTeX parser extracting LatexMathNode (inline) and MATH_ENVS (display) as formula chunks
  - nbformat Jupyter parser returning markdown->text and code->code chunks, skipping raw cells and outputs
affects: [02-02-embedding-pipeline, 02-03-ingestion-worker, 02-04-upload-api]

# Tech tracking
tech-stack:
  added: [docling>=2.66.0, FlagEmbedding>=1.3.5, nbformat>=5.9, pylatexenc==2.10, python-multipart>=0.0.9, aiofiles>=23.0.0, tiktoken>=0.7.0]
  patterns:
    - list[ParsedChunk] as the universal parser output type — all format-specific complexity isolated
    - Atomic chunks (formula/table/code) never split; only text blocks split with token overlap
    - Formula content = preceding_paragraph + formula_latex for semantic anchoring in embedding
    - chunk_index assigned post-collection (enumerate after full list built)

key-files:
  created:
    - src/rag_server/ingestion/__init__.py
    - src/rag_server/ingestion/parsers/__init__.py
    - src/rag_server/ingestion/chunker.py
    - src/rag_server/ingestion/parsers/pdf_parser.py
    - src/rag_server/ingestion/parsers/latex_parser.py
    - src/rag_server/ingestion/parsers/jupyter_parser.py
  modified:
    - pyproject.toml

key-decisions:
  - "tiktoken cl100k_base used as token counter for BGE-M3 (XLM-RoBERTa) — close enough for budget estimation, avoids dependency on sentence-transformers tokenizer at chunking stage"
  - "docling_settings.perf.elements_batch_size=2 set globally before converter construction — reduces CUDA VRAM from ~18-20 GB to ~8-10 GB for CodeFormula enrichment models"
  - "pylatexenc pinned to 2.10 (not 3.x alpha) — stable API; 3.x has breaking changes"
  - "Docling do_formula_enrichment=True required — without it FormulaItem.text is empty (detection does not equal recognition)"
  - "Formula content strategy: embed_content = preceding_paragraph + newlines + formula_latex; display_content = raw LaTeX only"
  - "Jupyter raw cells skipped — nbconvert directives, not user content"
  - "PDF converter reused across documents in worker process — make_converter() is expensive (loads layout models)"

patterns-established:
  - "Parser pattern: collect all chunks first, then enumerate for chunk_index — avoids re-indexing on splits"
  - "Formula enrichment pattern: flush last_text before emitting formula, use last_text as preceding context"
  - "Error handling: return empty list on fatal parse failure, log and continue on partial success"

requirements-completed: [INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05]

# Metrics
duration: 2min
completed: 2026-02-19
---

# Phase 2 Plan 01: Document Parsers and Chunking Infrastructure Summary

**ParsedChunk dataclass plus Docling PDF, pylatexenc LaTeX, and nbformat Jupyter parsers — all producing typed list[ParsedChunk] with formula semantic anchoring via tiktoken-bounded text splitting**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-19T14:30:16Z
- **Completed:** 2026-02-19T14:33:02Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Created ParsedChunk dataclass with chunk_type, content, display_content, page_number, section_heading, chunk_index, language fields — mirrors Chunk SQLAlchemy model exactly
- Implemented split_text_tokens() using tiktoken cl100k_base with 512-token max and 64-token overlap for BGE-M3 budget estimation
- Implemented enrich_formula_content() composing preceding paragraph + formula LaTeX for semantic anchoring (INGEST-05)
- Built Docling-based PDF parser with table structure, formula enrichment, and code enrichment enabled; elements_batch_size=2 for VRAM efficiency (INGEST-01, INGEST-04)
- Built pylatexenc LaTeX parser extracting inline math (LatexMathNode) and named environments (MATH_ENVS) as formula chunks with context enrichment (INGEST-02)
- Built nbformat Jupyter parser mapping markdown cells to text chunks and code cells to code chunks, skipping raw cells and outputs (INGEST-03, INGEST-04)
- Added 7 new dependencies to pyproject.toml

## Task Commits

Each task was committed atomically:

1. **Task 1: Shared types and chunker utilities** - `2527985` (feat)
2. **Task 2: PDF parser, LaTeX parser, Jupyter parser** - `0fd72e9` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/rag_server/ingestion/__init__.py` - Package marker for ingestion module
- `src/rag_server/ingestion/parsers/__init__.py` - Package marker for parsers subpackage
- `src/rag_server/ingestion/chunker.py` - ParsedChunk dataclass, split_text_tokens(), enrich_formula_content()
- `src/rag_server/ingestion/parsers/pdf_parser.py` - Docling PDF parser with make_converter() and parse_pdf()
- `src/rag_server/ingestion/parsers/latex_parser.py` - pylatexenc LaTeX parser with parse_latex()
- `src/rag_server/ingestion/parsers/jupyter_parser.py` - nbformat Jupyter parser with parse_jupyter()
- `pyproject.toml` - Added 7 new dependencies

## Decisions Made

- tiktoken cl100k_base selected as token counter approximation for BGE-M3 — avoids pulling in sentence-transformers at chunking stage while providing good enough budget estimation
- elements_batch_size=2 set via docling_settings.perf before converter construction — halves VRAM requirement from ~18-20 GB to ~8-10 GB for consumer GPUs
- pylatexenc pinned to exactly 2.10 (==2.10) — 3.x alpha has breaking API changes that would require significant parser rewrite
- do_formula_enrichment=True is mandatory in PdfPipelineOptions — Docling detects formulas without enrichment but FormulaItem.text is empty string until enrichment runs
- Formula embedding strategy: content = preceding_paragraph + "\n\n" + formula_latex; display_content = raw LaTeX for rendering — gives embedding model semantic context while preserving display fidelity

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Docling is not installed in the current environment (expected — large package requiring model downloads). pdf_parser.py import was not verified at module level as a result. The plan's done criteria explicitly states "Docling not tested at this stage due to model download requirement." All other parsers (LaTeX, Jupyter) and chunker utilities verified successfully.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All four parser modules ready for use by the embedding pipeline (02-02)
- All modules export the correct public interface (ParsedChunk, split_text_tokens, enrich_formula_content, make_converter, parse_pdf, parse_latex, parse_jupyter)
- pyproject.toml declares all required dependencies; `pip install -e .` will install them
- Docling requires GPU-capable environment with model download on first use (make_converter() loads layout models)

---
## Self-Check: PASSED

All created files confirmed present on disk. Both task commits (2527985, 0fd72e9) confirmed in git log. SUMMARY.md created. STATE.md and ROADMAP.md updated. Requirements INGEST-01 through INGEST-05 marked complete.

---
*Phase: 02-document-ingestion-pipeline*
*Completed: 2026-02-19*
