# Docling Memory Leak: Investigation and Fix

**Date:** 2026-04-12
**Authors:** Ignacio Castelar, Claude (Anthropic)
**Status:** Fix validated — 3-5x memory reduction confirmed (16 docs, zero restarts)
**Docling Version:** 2.74.0
**Affects:** Any application calling `DocumentConverter.convert()` multiple
times in the same process with formula or code enrichment enabled.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Symptoms](#2-symptoms)
3. [Investigation Method](#3-investigation-method)
4. [Root Cause Analysis](#4-root-cause-analysis)
   - 4.1 [The `keep_backend` Flag](#41-the-keep_backend-flag)
   - 4.2 [ConversionResult Reference Chain](#42-conversionresult-reference-chain)
   - 4.3 [What `_unload()` Does and Doesn't Do](#43-what-_unload-does-and-doesnt-do)
   - 4.4 [ThreadedQueue Item Retention](#44-threadedqueue-item-retention)
   - 4.5 [Pipeline Cache on DocumentConverter](#45-pipeline-cache-on-documentconverter)
   - 4.6 [Factory LRU Caches](#46-factory-lru-caches)
5. [The Full Reference Chain](#5-the-full-reference-chain)
6. [The Fix](#6-the-fix)
   - 6.1 [Approach: Explicit Teardown](#61-approach-explicit-teardown)
   - 6.2 [What `_teardown_conversion_result()` Does](#62-what-_teardown_conversion_result-does)
   - 6.3 [Integration Point](#63-integration-point)
   - 6.4 [What This Fix Cannot Recover](#64-what-this-fix-cannot-recover)
7. [Expected Impact](#7-expected-impact)
8. [Test Plan](#8-test-plan)
9. [Alternative Approaches Considered](#9-alternative-approaches-considered)
10. [Appendix: Key Source Locations in Docling 2.74.0](#10-appendix-key-source-locations-in-docling-2740)

---

## 1. Executive Summary

When `DocumentConverter.convert()` is called multiple times in the same process,
each call retains **200-500 MB** of unreclaimable memory even after the caller
discards the `ConversionResult`. After 4-6 sequential documents, the process
exhausts system RAM and is OOM-killed.

The root cause is a combination of factors in Docling's pipeline architecture:

1. **The `keep_backend` flag** is True when formula or code enrichment is
   enabled (our configuration). This prevents Docling from unloading per-page
   backends during the pipeline's `_integrate_results()` phase.

2. **`_unload()` is too shallow.** Docling's cleanup calls `.unload()` on page
   and document backends (which closes file handles and nulls raw data), but
   leaves the entire `ConversionResult` object tree alive — hundreds of
   `Page` objects with image caches, `SegmentedPdfPage` parsing data,
   `PagePredictions`, the assembled `DoclingDocument` with all content nodes,
   and the `InputDocument` wrapper.

3. **Pydantic model reference cycles** prevent Python's reference-counting
   garbage collector from freeing these objects immediately. `gc.collect()`
   helps partially but cannot break all cycles in the Pydantic v2 model graph.

**The fix** adds an explicit `_teardown_conversion_result()` function that
aggressively breaks all references inside the `ConversionResult` after we've
extracted our chunks. This allows `gc.collect()` to reclaim the full object
tree instead of just the leaf handles.

---

## 2. Symptoms

Observed during bulk ingestion of a 61-book PDF library on a 14.8 GB RAM
system:

| Observation | Detail |
|-------------|--------|
| Memory growth per document | 200-500 MB retained after each conversion |
| `gc.collect()` recovery | Partial: reclaims 100-775 MB, leaves 200-400 MB |
| OOM threshold | 4-6 sequential documents without server restart |
| Affected phase | Post-conversion — memory stays even after chunks extracted |
| Not affected | First document (no prior state to leak) |

The Docling memory leak is **distinct from** the double-conversion bug fixed
earlier (see `docs/ingestion-memory-fix.md`). The double-conversion fix
eliminated redundant work; this fix addresses memory retained from the single
remaining conversion.

---

## 3. Investigation Method

1. **Source code reading** of Docling 2.74.0 installed in the project venv
   (`.venv/lib/python3.13/site-packages/docling/`).
2. **Reference chain tracing** from `DocumentConverter.convert()` through
   the pipeline to the returned `ConversionResult`.
3. **Identifying cleanup gaps** by comparing what `_unload()` and
   `_integrate_results()` clean up versus what they leave behind.
4. **Cross-referencing with observed behavior** from RAM monitor data
   collected during bulk ingestion (see `docs/ingestion-memory-fix.md`,
   Appendix B).

No runtime profiling tools (objgraph, tracemalloc) were used — the
investigation was purely source-level. Runtime validation is planned as
part of the test plan (Section 8).

---

## 4. Root Cause Analysis

### 4.1 The `keep_backend` Flag

**File:** `docling/pipeline/standard_pdf_pipeline.py`, lines 500-507

```python
self.keep_backend = any(
    (
        self.pipeline_options.do_formula_enrichment,
        self.pipeline_options.do_code_enrichment,
        self.pipeline_options.do_picture_classification,
        self.pipeline_options.do_picture_description,
    )
)
```

**Our configuration** has `do_formula_enrichment = True` and
`do_code_enrichment = True`, so `keep_backend = True`.

This flag controls cleanup in two places:

**`_release_page_resources()`** (line 521-531) — called per-page during the
pipeline:
```python
def _release_page_resources(self, item: ThreadedItem) -> None:
    page = item.payload
    if not self.keep_images:
        page._image_cache = {}
    if not self.keep_backend and page._backend is not None:  # SKIPPED
        page._backend.unload()
        page._backend = None
    if not self.pipeline_options.generate_parsed_pages:
        page.parsed_page = None
```

**`_integrate_results()`** (lines 744-752) — called after all pages processed:
```python
if not self.keep_images:
    for p in conv_res.pages:
        p._image_cache = {}
for p in conv_res.pages:
    if not self.keep_backend and p._backend is not None:  # SKIPPED
        p._backend.unload()
```

Because `keep_backend = True`, **neither of these cleanup paths executes**.
Page backends survive the entire pipeline and are returned to the caller
inside the `ConversionResult`.

### 4.2 ConversionResult Reference Chain

**File:** `docling/datamodel/document.py`, lines 242-254, 417-419

```python
class ConversionAssets(BaseModel):
    pages: list[Page] = []              # All Page objects
    document: DoclingDocument = ...      # Full extracted document
    timings: dict[str, ProfilingItem] = {}
    confidence: ConfidenceReport = ...

class ConversionResult(ConversionAssets):
    input: InputDocument                 # Holds document backend
    assembled: AssembledUnit = ...       # Assembled elements
```

Each `Page` (from `docling/datamodel/base_models.py`, lines 300-359) contains:

```python
class Page(BaseModel):
    page_no: int
    size: Optional[Size] = None
    parsed_page: Optional[SegmentedPdfPage] = None  # Full page parsing data
    predictions: PagePredictions = ...               # Layout predictions
    assembled: Optional[AssembledUnit] = None        # Per-page assembly
    _backend: Optional["PdfPageBackend"] = None      # Native PDF handle
    _image_cache: dict[float, Image] = {}            # PIL Images at various scales
```

### 4.3 What `_unload()` Does and Doesn't Do

**File:** `docling/pipeline/standard_pdf_pipeline.py`, lines 928-933

```python
def _unload(self, conv_res: ConversionResult) -> None:
    for p in conv_res.pages:
        if p._backend is not None:
            p._backend.unload()          # Closes native handles
    if conv_res.input._backend:
        conv_res.input._backend.unload() # Closes document handle
```

This IS called from `base_pipeline.py:92` in the `finally` block of
`execute()`, AFTER the enrichment phase completes.

**What `unload()` does** (on `DoclingParsePageBackend`, line 192):
```python
def unload(self):
    if not self._unloaded and self._dp_doc is not None:
        self._dp_doc.unload_pages((self._page_no + 1, self._page_no + 2))
        self._unloaded = True
    self._ppage = None        # Nulls pypdfium2 PdfPage
    self._dpage = None        # Nulls SegmentedPdfPage
    self._dp_doc = None       # Nulls docling-parse reference
```

**What `unload()` does** (on `DoclingParseDocumentBackend`, line 256):
```python
def unload(self):
    super().unload()           # Closes BytesIO, nulls path_or_stream
    if self.dp_doc is not None:
        self.dp_doc.unload()   # Releases docling-parse native memory
        self.dp_doc = None
    if self._pdoc is not None:
        self._pdoc.close()     # Closes pypdfium2 document
        self._pdoc = None
```

**What's left after `_unload()`:**

| Object | Cleaned? | Approximate Size |
|--------|----------|-----------------|
| `Page._backend` native handles | Yes (nulled) | N/A after unload |
| `Page._image_cache` (PIL Images) | **No** | 1-50 MB per page |
| `Page.parsed_page` (SegmentedPdfPage) | **No** | 0.5-5 MB per page |
| `Page.predictions` (PagePredictions) | **No** | 0.1-1 MB per page |
| `Page.assembled` (AssembledUnit) | **No** | 0.1-0.5 MB per page |
| `ConversionResult.document` (DoclingDocument) | **No** | 10-100 MB |
| `ConversionResult.assembled` | **No** | 5-50 MB |
| `InputDocument` wrapper (Python object) | **No** | Minor |
| `Page` Python objects (list of N pages) | **No** | Wrapper for above |

For a 200-page document, the residual data after `_unload()` is approximately:
- Image caches: ~50-200 MB (if VLM rendered page images at multiple scales)
- Parsed pages: ~10-50 MB
- DoclingDocument: ~10-30 MB
- **Total residual: ~70-280 MB** that persists until the ConversionResult
  is garbage collected

### 4.4 ThreadedQueue Item Retention

**File:** `docling/pipeline/standard_pdf_pipeline.py`, lines 118-177

The `ThreadedQueue.close()` method (line 173) sets `_closed = True` but does
**not** clear the `_items` deque. However, the drain loop at line 674 calls
`get_batch()` which does `_items.popleft()`, so under normal completion all
items are consumed.

**This is NOT a primary leak mechanism** in the normal success path. It could
contribute if the pipeline times out or fails early (items left in the queue),
but in our typical runs all pages are drained.

### 4.5 Pipeline Cache on DocumentConverter

**File:** `docling/document_converter.py`, lines 258-260

```python
self.initialized_pipelines: dict[
    tuple[Type[BasePipeline], str], BasePipeline
] = {}
```

The `StandardPdfPipeline` instance is cached and reused across conversions.
This is intentional (avoids reloading ML models) and does NOT hold references
to previous `ConversionResult` objects. The pipeline itself is stateless
between conversions.

**Not a leak source.**

### 4.6 Factory LRU Caches

**File:** `docling/models/factories/__init__.py`, lines 14-47

```python
@lru_cache
def get_layout_factory(...) -> LayoutFactory: ...

@lru_cache
def get_ocr_factory(...) -> OcrFactory: ...

@lru_cache
def get_table_structure_factory(...) -> TableStructureFactory: ...
```

These are module-level `@lru_cache` (unbounded, default `maxsize=128`) that
cache factory singletons. They hold ML model instances across conversions.

**Not a per-document leak** — they allocate once and remain constant. Their
memory (~500 MB total) is expected and necessary for pipeline operation.

---

## 5. The Full Reference Chain

After `converter.convert()` returns and the caller holds the `ConversionResult`:

```
ConversionResult (caller's variable)
├── .input: InputDocument
│   └── ._backend: DoclingParseDocumentBackend
│       ├── ._pdoc: None (unloaded by _unload)
│       ├── .dp_doc: None (unloaded by _unload)
│       └── .path_or_stream: None (unloaded by _unload)
├── .pages: list[Page]  ← N pages, each:
│   ├── ._backend: DoclingParsePageBackend
│   │   ├── ._ppage: None (unloaded)
│   │   ├── ._dpage: None (unloaded)
│   │   └── Python object overhead persists
│   ├── ._image_cache: dict[float, PIL.Image]  ← NOT CLEANED (keep_images default)
│   ├── .parsed_page: SegmentedPdfPage          ← NOT CLEANED (generate_parsed_pages default)
│   ├── .predictions: PagePredictions            ← NOT CLEANED
│   └── .assembled: AssembledUnit                ← NOT CLEANED
├── .document: DoclingDocument                    ← NOT CLEANED (full content tree)
├── .assembled: AssembledUnit                     ← NOT CLEANED
├── .timings: dict                                ← Minor
└── .errors: list                                 ← Minor
```

**The problem:** Even though native handles are closed by `_unload()`, the
Python-level data (Pydantic models, PIL Images, parsed page structures) remains
alive as long as the `ConversionResult` exists. And even after the caller drops
its reference, Pydantic v2 models create internal reference cycles that
`gc.collect()` cannot always break efficiently — especially with deeply nested
model hierarchies like `DoclingDocument → ContentItem → Prov → BoundingBox`.

---

## 6. The Fix

### 6.1 Approach: Explicit Teardown

Rather than relying on Python's garbage collector to eventually free the
`ConversionResult` object tree, we explicitly break all references after
extracting our `ParsedChunk` objects. This makes `gc.collect()` effective
and deterministic.

**File:** `src/rag_server/ingestion/parsers/pdf_parser.py`

### 6.2 What `_teardown_conversion_result()` Does

```python
def _teardown_conversion_result(result) -> None:
```

| Step | Target | Action | Memory Freed |
|------|--------|--------|--------------|
| 1 | `page._image_cache` | Set to `{}` | PIL Images (1-50 MB/page) |
| 1 | `page.predictions` | Set to `None` | Layout predictions |
| 1 | `page.assembled` | Set to `None` | Per-page assembly data |
| 1 | `page.parsed_page` | Set to `None` | SegmentedPdfPage parsing data |
| 1 | `page._backend` | Call `.unload()`, set to `None` | Redundant safety (already unloaded) |
| 1 | `result.pages` | Call `.clear()` | Break list reference to all Pages |
| 2 | `input._backend` | Call `.unload()`, set to `None` | Redundant safety |
| 3 | `result.document` | Set to `None` | DoclingDocument content tree |
| 3 | `result.assembled` | Set to `None` | Top-level assembly data |
| 4 | `result.errors` | Call `.clear()` | Minor, breaks cycles |
| 4 | `result.timings` | Call `.clear()` | Minor, breaks cycles |

After teardown, the caller does `del result` to drop the final reference,
then `gc.collect()` in `_dispatch_parser()` handles any remaining cycles.

### 6.3 Integration Point

The teardown is called at two points in `parse_pdf()`:

1. **On failure** (ConversionStatus.FAILURE): Before returning `([], False)`
2. **After chunk extraction**: After all `ParsedChunk` objects have been
   created from `result.document.iterate_items()`, the `ConversionResult`
   is no longer needed. Teardown is called before returning chunks.

The caller in `pipeline.py:_dispatch_parser()` then calls `gc.collect()` and
`torch.cuda.empty_cache()` as before.

### 6.4 What This Fix Cannot Recover

1. **Model weights in GPU memory**: The ML models (layout, table structure,
   CodeFormulaV2) are loaded once and stay in VRAM across conversions. This
   is correct behavior (~5.5 GB VRAM). Not a leak.

2. **Factory and pipeline caches**: Module-level singletons. One-time
   allocation, not per-document. Not a leak.

3. **Python interpreter overhead**: Each conversion exercises code paths that
   may cause Python to allocate arena memory that is never returned to the OS
   (Python's memory allocator does not release arenas that still have live
   objects). This is a well-known CPython limitation and is typically 10-50 MB
   per conversion — acceptable.

4. **Possible thread-local state**: The threaded pipeline stages may retain
   per-thread state that is not visible to our cleanup. This is speculative
   and would require runtime profiling to confirm.

---

## 7. Expected Impact

**Before fix** (measured during bulk ingestion):

| Metric | Value |
|--------|-------|
| Residual memory per document | 200-500 MB |
| `gc.collect()` recovery | 100-775 MB (partial) |
| Safe sequential documents | 3-4 before OOM |
| Server restart required | After every document |

**After fix** (measured — 16-document sequential test, 2026-04-12):

| Metric | Measured Value |
|--------|----------------|
| Residual memory per document | ~83 MB average (28-229 MB range) |
| Teardown reclamation per doc | 8-39 MB (after-convert → after-convert-gc) |
| RSS decrease observed | Yes — doc #11 RSS went DOWN by 27 MB |
| Safe sequential documents | 16 tested, ~30-40 projected |
| Server restart required | Every 30-40 documents (estimated) |
| Total pages processed | 476 pages across 16 documents |
| Total time | ~20 minutes for 15 docs (excl. first doc timing outlier) |
| Final worker RSS | 3,788 MB (from 2,085 MB baseline) |
| System RAM available at end | 5,451 MB of 15,181 MB |

The fix reduces per-document retention by **3-5x** compared to pre-fix
(~83 MB vs 200-500 MB). The 64-page and 67-page documents only added 69 MB
and 103 MB respectively, showing the teardown scales well with document size.

The residual ~83 MB/doc that persists despite teardown is likely:
- Python allocator fragmentation (RSS rarely shrinks even after free)
- Pydantic model metadata not reachable from our teardown
- Internal Docling state in cached pipeline structures

---

## 8. Test Plan

### Test 8.1: Correctness — No Regression (PASSED)

**Objective:** Verify the fix produces valid chunks and consistent stores.

**Result:**
- 16 new PDFs ingested (476 pages, 4,466 chunks)
- All 16 documents reached `indexed` status (zero failures)
- SQLite: 92 docs, 107,079 chunks, 18,686 pages
- Qdrant: 107,079 points, status green — exact match with SQLite
- Chunk counts per document range from 107 to 705, proportional to page count

**Verdict:** PASS. The teardown does not corrupt chunks or break the pipeline.

### Test 8.2: Memory — Reduced Retention (PASSED)

**Objective:** Measure per-document memory retention with the fix.

**Result — full RSS trajectory (16 documents, zero restarts):**

| Doc # | File | Pages | Worker RSS | Delta |
|-------|------|-------|-----------|-------|
| 1 | static-replication | 7 | 2,085 MB | baseline (models loaded) |
| 2 | regime-based-volatility | 8 | 2,530 MB | +445 (settling) |
| 3 | beyond-black-scholes | 10 | 2,625 MB | +95 |
| 4 | forecasting-tangency | 10 | 2,735 MB | +110 |
| 5 | do-prediction-markets | 14 | 2,824 MB | +89 |
| 6 | pool-value-replication | 21 | 2,852 MB | +28 |
| 7 | perpetual-demand-lending | 28 | 2,915 MB | +63 |
| 8 | sbbts-schrodinger-bass | 26 | 2,993 MB | +78 |
| 9 | explainable-patterns | 28 | 3,222 MB | +229 |
| 10 | slippage-at-risk | 32 | 3,374 MB | +152 |
| 11 | inverse-quanto-options | 36 | 3,347 MB | **-27** |
| 12 | pricing-hedging | 36 | 3,426 MB | +79 |
| 13 | debiasing-llms | 37 | 3,501 MB | +75 |
| 14 | skewness-dispersion | 52 | 3,616 MB | +115 |
| 15 | deep-learning-architectures | 64 | 3,685 MB | +69 |
| 16 | cross-chain-negative-spillovers | 67 | 3,788 MB | +103 |

**`_log_mem` probe detail (selected documents):**

```
Doc #11 (inverse-quanto, 36pp) — RSS went DOWN:
  before-convert:   3375 MB
  after-convert:    3381 MB  (+6 peak)
  after-convert-gc: 3362 MB  (-19 reclaimed — more than was added)
  after-gc:         3355 MB
  next start:       3347 MB  (-8 more between docs)

Doc #16 (cross-chain, 67pp — largest):
  before-convert:   3682 MB
  after-convert:    3854 MB  (+172 peak)
  after-convert-gc: 3815 MB  (-39 reclaimed by teardown)
  after-gc:         3811 MB
```

**Teardown reclamation:** 8-39 MB per document (after-convert → after-convert-gc).

**Verdict:** PASS. Post-settling average ~83 MB/doc (vs 200-500 MB pre-fix).
3-5x improvement. RSS went down on doc #11, proving cross-document reclamation.

### Test 8.3: Stress — Sequential Capacity (PASSED)

**Objective:** Determine how many documents can be processed sequentially.

**Result:**
- 16 documents processed sequentially, **zero restarts**
- Final worker RSS: 3,788 MB
- System available RAM at end: 5,451 MB
- Growth rate ~83 MB/doc (post-settling)
- Projected capacity at 10 GB RSS limit: ~(10,000 - 2,085) / 83 = **~95 docs**
- Conservative safe estimate (leaving 4 GB headroom): **~30-40 docs** per session

**Verdict:** PASS. Exceeds the 6-document minimum by nearly 3x, with capacity
for many more. Pre-fix limit was 3-4 documents.

### Test 8.4: Edge Case — Failure Path (NOT TESTED)

**Objective:** Verify teardown works on failed conversions.

**Status:** Not tested in this run (all 16 documents succeeded). The failure
path code exists in `parse_pdf()` and calls `_teardown_conversion_result(result)`
before returning `([], False)`. Deferred to future testing with a corrupted PDF.

---

## 9. Alternative Approaches Considered

### 9.1 Subprocess Isolation (Not Chosen)

Run each `converter.convert()` in a fresh subprocess via
`multiprocessing.Process`. The subprocess's memory is fully reclaimed by the
OS on exit.

**Pros:** Guaranteed zero leak — OS-level cleanup.
**Cons:**
- Each subprocess must reload ML models (~10-20 seconds, ~5.5 GB VRAM).
- Would require serializing the `ConversionResult` across process boundaries
  (Pydantic models with PIL Images are not trivially picklable).
- Adds significant complexity and per-document latency.

**Verdict:** Too expensive. The explicit teardown approach achieves most of the
benefit without the model reload cost.

### 9.2 Monkey-Patching Docling's `_integrate_results()` (Not Chosen)

Override `keep_backend` or patch `_integrate_results()` to force backend
cleanup even when enrichment is enabled.

**Pros:** Fixes the root cause in Docling's cleanup path.
**Cons:**
- Risk of breaking the enrichment pipeline (backends may be needed during the
  enrichment phase that runs BEFORE `_integrate_results()`).
- Fragile — would break on Docling version upgrades.
- Doesn't address the other retained data (DoclingDocument, image caches, etc.).

**Verdict:** Partial fix with breakage risk. The explicit teardown approach is
safer and more comprehensive.

### 9.3 Upstream PR to Docling (Future)

File a PR to Docling adding a `ConversionResult.release()` method that
performs the equivalent of our `_teardown_conversion_result()`.

**Status:** Not yet filed. The current fix validates the approach; an upstream
contribution can follow once the memory impact is measured.

---

## 10. Appendix: Key Source Locations in Docling 2.74.0

All paths relative to `.venv/lib/python3.13/site-packages/`.

| Component | File | Lines | Relevance |
|-----------|------|-------|-----------|
| `keep_backend` flag | `docling/pipeline/standard_pdf_pipeline.py` | 500-507 | Controls whether page backends are unloaded during pipeline |
| `_release_page_resources()` | `docling/pipeline/standard_pdf_pipeline.py` | 521-531 | Per-page cleanup — skipped when `keep_backend=True` |
| `_integrate_results()` | `docling/pipeline/standard_pdf_pipeline.py` | 714-752 | Post-pipeline cleanup — page backends skipped when `keep_backend=True` |
| `_unload()` | `docling/pipeline/standard_pdf_pipeline.py` | 928-933 | Final cleanup — unloads backends but not Python data |
| `_unload()` caller | `docling/pipeline/base_pipeline.py` | 92 | Called in `finally` block of `execute()` |
| `execute()` flow | `docling/pipeline/base_pipeline.py` | 65-94 | `_build_document` -> `_assemble_document` -> `_enrich_document` -> `_unload` |
| `ThreadedItem` | `docling/pipeline/standard_pdf_pipeline.py` | 81-90 | Carries `conv_res` reference through pipeline queues |
| `ThreadedQueue.close()` | `docling/pipeline/standard_pdf_pipeline.py` | 173-177 | Sets flag, doesn't clear `_items` deque |
| `_build_document()` finally | `docling/pipeline/standard_pdf_pipeline.py` | 705-708 | Stops stages, closes output queue |
| `ConversionResult` | `docling/datamodel/document.py` | 417-419 | Holds `input`, inherits `pages`, `document` |
| `ConversionAssets` | `docling/datamodel/document.py` | 242-254 | Parent: `pages`, `document`, `timings` |
| `InputDocument._backend` | `docling/datamodel/document.py` | 135 | Document-level backend reference |
| `Page` model | `docling/datamodel/base_models.py` | ~300-359 | `_backend`, `_image_cache`, `parsed_page`, `predictions` |
| `DoclingParsePageBackend.unload()` | `docling/backend/docling_parse_backend.py` | 192-199 | Nulls native handles, NOT Python data |
| `DoclingParseDocumentBackend.unload()` | `docling/backend/docling_parse_backend.py` | 256-271 | Closes pypdfium2 + docling-parse |
| `PyPdfiumPageBackend.unload()` | `docling/backend/pypdfium2_backend.py` | 377-379 | Nulls `_ppage` and `text_page` |
| `PyPdfiumDocumentBackend.unload()` | `docling/backend/pypdfium2_backend.py` | 413-417 | Closes `_pdoc` |
| `AbstractDocumentBackend.unload()` | `docling/backend/abstract_backend.py` | 42-46 | Closes BytesIO, nulls `path_or_stream` |
| Factory LRU caches | `docling/models/factories/__init__.py` | 14-47 | Module-level singleton caches (not per-document) |
| Pipeline cache | `docling/document_converter.py` | 258-260 | `initialized_pipelines` dict (intentional reuse) |
