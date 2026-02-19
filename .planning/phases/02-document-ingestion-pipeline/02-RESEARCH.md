# Phase 2: Document Ingestion Pipeline - Research

**Researched:** 2026-02-19
**Domain:** Document parsing (Docling), embedding (BGE-M3/FlagEmbedding), async worker architecture, chunking, Qdrant sparse vectors
**Confidence:** MEDIUM-HIGH (Docling API verified via official docs + DeepWiki; BGE-M3 verified via HuggingFace model card + official README; Qdrant verified via official docs; pylatexenc/nbformat verified via official docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Async ingestion** — upload returns document ID immediately; status polled via GET /documents/{id}
- **Status states**: `pending` → `indexing` → `indexed` / `indexed_partial` / `failed`
- **Separate worker process** handles indexing — isolates CPU/VRAM-heavy pipeline from API process
- **Serial queue** — one document at a time; prevents VRAM/CPU contention
- **Always Docling for PDF** — no fast-path fallback
- **LaTeX**: direct text extraction preserving markup as-is (no pdflatex compilation)
- **Jupyter (.ipynb)**: markdown + code cells only; skip outputs (execution artifacts)
- **Page-level failures**: skip failed pages → status `indexed_partial`; store failed page numbers in `error_msg`
- **Whole document failures**: status = `failed`
- **On any failure**: rollback partial chunks/vectors already written
- **BGE-M3 loaded once at worker startup** — long-lived daemon process; VRAM freed on shutdown
- **Retry via re-upload**: content hash match on re-upload enables re-processing

### Claude's Discretion
- LaTeX parser implementation details (pylatexenc tokenization strategy, math environment extraction)
- Worker process communication mechanism (asyncio Queue, multiprocessing, or subprocess)
- BGE-M3 batch size for embedding (tune for available VRAM)
- Qdrant upsert batching strategy
- Exact error message format in API response vs logs

### Deferred Ideas (OUT OF SCOPE)
- None stated
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INGEST-01 | PDF ingestion with layout-aware parsing (Docling) preserving tables, formulas, multi-column layouts | Docling DocumentConverter + PdfPipelineOptions; iterate_items() yields TextItem/TableItem/FormulaItem/CodeItem/SectionHeaderItem |
| INGEST-02 | LaTeX (.tex) ingestion preserving LaTeX markup, extracting math environments | pylatexenc 2.x LatexWalker; regex fallback for simple math; raw text extraction for non-math blocks |
| INGEST-03 | Jupyter (.ipynb) ingestion — markdown + code cells only, skip outputs | nbformat.read(as_version=4); cell.cell_type checks; cell.source for content |
| INGEST-04 | Code block chunks preserve syntax and language metadata | Docling CodeItem.code_language; nbformat cell.cell_type == 'code' with language from kernel metadata |
| INGEST-05 | Formula chunks enriched with surrounding paragraph context; raw LaTeX in display_content | Paragraph-tracking during Docling iterate_items(); FormulaItem.text contains LaTeX after enrichment |
| INGEST-06 | Async job queue — upload returns doc ID immediately, caller polls GET /documents/{id} | asyncio.Queue + worker coroutine started in FastAPI lifespan; multiprocessing.Queue for process boundary |
</phase_requirements>

---

## Summary

The ingestion pipeline requires six coordinated components: (1) a FastAPI upload endpoint that saves files and enqueues jobs, (2) an async worker process that processes jobs serially, (3) document parsers (Docling for PDF, pylatexenc for .tex, nbformat for .ipynb), (4) a chunker that produces typed chunks with metadata, (5) BGE-M3 embedding for dense+sparse vectors, and (6) Qdrant upsert with rollback on failure.

The most critical architectural constraint is **VRAM isolation**: Docling's formula enrichment model (CodeFormula) requires up to 18-20 GB VRAM at default batch sizes, and BGE-M3 requires ~1.06 GB for the model weights plus inference overhead. Running them in the same process risks OOM. The serial queue prevents two documents from being processed simultaneously, but the worker must sequence Docling parsing before BGE-M3 embedding within a single document job.

Docling's native HybridChunker can handle text/table chunking with token awareness, but formula and code blocks require custom handling: formulas must be detected as single atomic chunks with context enrichment, and code blocks must carry language metadata. The recommended approach is to **bypass HybridChunker for formula/code blocks** and use direct iterate_items() traversal instead, applying HybridChunker only for text blocks.

**Primary recommendation:** Use multiprocessing.Process for the worker (not asyncio.create_task) to achieve true VRAM isolation from the FastAPI event loop. Communicate via multiprocessing.Queue. Load BGE-M3 inside the worker process at startup.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `docling` | >=2.66.0 | PDF parsing with layout understanding | Only OSS tool with table structure + formula detection in one package |
| `FlagEmbedding` | 1.3.5 | BGE-M3 three-mode embedding | Official library from BAAI; required for BGEM3FlagModel |
| `nbformat` | >=5.9 | Jupyter notebook parsing | Official Jupyter library; handles all nbformat versions |
| `pylatexenc` | 2.10 (stable) | LaTeX math environment extraction | Stable release; 3.0alpha has API changes |
| `python-multipart` | any | FastAPI multipart file upload | Required by FastAPI for UploadFile |
| `tiktoken` | any | Token counting for text chunking | Fast, accurate; BGE-M3 max 8192 tokens |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiofiles` | any | Async file write for uploaded files | Saving uploaded files without blocking event loop |
| `docling-core` | (installed with docling) | HybridChunker, DocChunk types | Chunking PDFs with token-aware splitting |
| `pandas` | any | TableItem.export_to_dataframe() | Converting Docling tables to text for embedding |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pylatexenc` for .tex | regex-based extraction | pylatexenc handles nested envs and edge cases; regex fails on `\begin{align}` inside `\begin{equation}` |
| multiprocessing.Process worker | asyncio.create_task | asyncio shares GIL and event loop; GPU-heavy inference blocks async IO; process gives true isolation |
| Docling HybridChunker | LangChain TokenTextSplitter | HybridChunker is structure-aware (headings, tables); LangChain doesn't know Docling block types |

**Installation:**
```bash
pip install "docling>=2.66.0" "FlagEmbedding>=1.3.5" nbformat pylatexenc python-multipart aiofiles tiktoken
```

---

## Architecture Patterns

### Recommended Project Structure
```
src/rag_server/
├── ingestion/
│   ├── __init__.py
│   ├── worker.py          # Long-lived worker process: queue consumer, BGE-M3 loader
│   ├── pipeline.py        # Orchestrates parse → chunk → embed → upsert for one document
│   ├── parsers/
│   │   ├── pdf.py         # Docling-based PDF parser → typed chunks
│   │   ├── latex.py       # pylatexenc .tex parser → typed chunks
│   │   └── jupyter.py     # nbformat .ipynb parser → typed chunks
│   ├── embedder.py        # BGE-M3 wrapper: encode() → dense + sparse vectors
│   └── chunker.py         # Chunk dataclass + type-specific chunking logic
├── api/
│   └── upload.py          # POST /documents endpoint: save file, enqueue job, return doc ID
└── queue.py               # multiprocessing.Queue singleton + job dataclass
```

### Pattern 1: Worker Process with multiprocessing.Queue
**What:** A separate OS process consumes jobs from a queue, loads BGE-M3 once at startup, and processes documents serially.
**When to use:** When CPU/GPU-heavy workloads must not block the async API event loop and VRAM must be isolated.

```python
# src/rag_server/ingestion/worker.py
import multiprocessing
import logging
from FlagEmbedding import BGEM3FlagModel
from rag_server.ingestion.pipeline import run_pipeline

logger = logging.getLogger(__name__)

def worker_main(job_queue: multiprocessing.Queue, stop_event: multiprocessing.Event) -> None:
    """Entry point for the worker process. Loads BGE-M3 once, then processes jobs serially."""
    logger.info("Worker: loading BGE-M3 model...")
    model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)
    logger.info("Worker: BGE-M3 loaded, ready for jobs")

    while not stop_event.is_set():
        try:
            job = job_queue.get(timeout=1.0)  # blocks up to 1s, then loops to check stop_event
            if job is None:  # poison pill sentinel
                break
            run_pipeline(job, model)
        except Exception:
            logger.exception("Worker: uncaught error on job %s", job)

    logger.info("Worker: shutting down, releasing VRAM")
    del model  # allows CUDA to reclaim VRAM


# src/rag_server/queue.py
import multiprocessing
from dataclasses import dataclass

@dataclass
class IngestionJob:
    document_id: str
    file_path: str          # absolute path to saved upload
    file_format: str        # "pdf" | "tex" | "ipynb"
    original_filename: str

_job_queue: multiprocessing.Queue | None = None
_worker_process: multiprocessing.Process | None = None
_stop_event: multiprocessing.Event | None = None

def get_queue() -> multiprocessing.Queue:
    assert _job_queue is not None, "Queue not initialized"
    return _job_queue
```

### Pattern 2: FastAPI Lifespan with Worker Process
**What:** Start/stop the worker process in FastAPI lifespan so it lives for exactly the duration of the server.
**When to use:** Every FastAPI app with a long-running background subprocess.

```python
# src/rag_server/main.py (lifespan section)
from contextlib import asynccontextmanager
import multiprocessing
from rag_server import queue as q
from rag_server.ingestion.worker import worker_main

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create queue and launch worker process
    q._job_queue = multiprocessing.Queue(maxsize=100)
    q._stop_event = multiprocessing.Event()
    q._worker_process = multiprocessing.Process(
        target=worker_main,
        args=(q._job_queue, q._stop_event),
        daemon=True,
    )
    q._worker_process.start()
    yield
    # Shutdown: signal worker to stop, wait up to 30s
    q._stop_event.set()
    q._job_queue.put(None)  # poison pill in case blocked on get()
    q._worker_process.join(timeout=30)
    if q._worker_process.is_alive():
        q._worker_process.terminate()

app = FastAPI(lifespan=lifespan)
```

### Pattern 3: Docling PDF Parsing with Block Iteration
**What:** Convert a PDF and iterate over typed blocks to produce chunks.
**When to use:** Always for PDF ingestion.

```python
# Source: docling-project.github.io/docling/reference/document_converter/ + deepwiki.com/docling-project
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling_core.types.doc import (
    SectionHeaderItem, TableItem, FormulaItem, CodeItem, TextItem,
    DocItemLabel, ContentLayer,
)

def make_converter(use_gpu: bool = True, enable_formula: bool = True) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_formula_enrichment = enable_formula   # requires CodeFormula model
    pipeline_options.do_code_enrichment = True
    pipeline_options.do_table_structure = True

    if use_gpu:
        pipeline_options.accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice.CUDA
        )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

def parse_pdf(file_path: str, converter: DocumentConverter):
    """Convert PDF and return ConversionResult."""
    result = converter.convert(
        file_path,
        raises_on_error=False,   # PARTIAL_SUCCESS returned instead of exception
    )
    return result

# Iterating blocks:
def iterate_pdf_blocks(result):
    doc = result.document
    current_heading = None

    for item, level in doc.iterate_items(
        included_content_layers={ContentLayer.BODY}
    ):
        page_no = item.prov[0].page_no if item.prov else None

        if isinstance(item, SectionHeaderItem):
            current_heading = item.text   # track most recent heading
            # level 1-100: item.level

        elif isinstance(item, FormulaItem):
            # item.text contains LaTeX (if do_formula_enrichment=True, filled by CodeFormula model)
            # item.text may be empty string if formula enrichment not enabled or detection failed
            yield {
                "chunk_type": "formula",
                "content": item.text or "",         # embed this (enriched with context later)
                "display_content": item.text or "",  # raw LaTeX for display
                "page_number": page_no,
                "section_heading": current_heading,
            }

        elif isinstance(item, TableItem):
            table_md = item.export_to_markdown()   # Markdown table string
            yield {
                "chunk_type": "table",
                "content": table_md,
                "display_content": table_md,
                "page_number": page_no,
                "section_heading": current_heading,
            }

        elif isinstance(item, CodeItem):
            lang = getattr(item, "code_language", None)  # set by do_code_enrichment
            yield {
                "chunk_type": "code",
                "content": item.text or "",
                "display_content": item.text or "",
                "page_number": page_no,
                "section_heading": current_heading,
                "language": str(lang) if lang else None,
            }

        elif isinstance(item, TextItem):
            yield {
                "chunk_type": "text",
                "content": item.text or "",
                "display_content": None,
                "page_number": page_no,
                "section_heading": current_heading,
            }
```

### Pattern 4: Formula Context Enrichment
**What:** Formula chunks embed a context string = preceding paragraph + formula LaTeX. Raw LaTeX goes to `display_content`.
**When to use:** Every formula chunk emitted by any parser.

```python
def enrich_formula_content(formula_latex: str, preceding_paragraph: str) -> str:
    """Compose the embeddable content for a formula chunk.

    The embedding model sees the surrounding text + the formula LaTeX,
    which gives it semantic anchoring for retrieval.
    display_content stores only the raw LaTeX for rendering.
    """
    if preceding_paragraph:
        return f"{preceding_paragraph.strip()}\n\n{formula_latex}"
    return formula_latex

# Usage during block iteration:
last_paragraph = ""
for item, level in doc.iterate_items():
    if isinstance(item, TextItem):
        last_paragraph = item.text or ""
    elif isinstance(item, FormulaItem):
        embed_content = enrich_formula_content(item.text or "", last_paragraph)
        display_content = item.text or ""
        # ... produce chunk
```

### Anti-Patterns to Avoid
- **Loading BGE-M3 inside the FastAPI process**: blocks async IO during model load (~5-10s) and shares VRAM with Docling.
- **Using asyncio.create_task for the worker loop**: asyncio workers share the event loop; GPU-bound inference blocks all async handlers.
- **Calling model.encode() directly from an async function**: encode() is synchronous and CPU/GPU-bound; must use run_in_executor or be in a separate process.
- **Using multiprocessing "fork" start method on Linux with CUDA**: fork after CUDA init causes undefined behavior; use "spawn" or "forkserver".
- **Upserting to Qdrant before writing to SQLite**: on failure, you'd have orphan vectors with no corresponding SQLite rows.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF layout detection | Custom PDF parser | Docling | Layout model + table structure model + reading order model = ~200k lines of ML code |
| Token counting | Word-split heuristics | tiktoken | BPE tokenization differs radically from word count; BGE-M3 uses subword tokens |
| LaTeX math segmentation | Regex on `\begin{...}` | pylatexenc LatexWalker | Nested environments, multiline, edge cases; regex breaks on `\begin{cases}` inside `\begin{equation}` |
| Table text extraction | Iterating HTML | TableItem.export_to_markdown() | Handles merged cells, multi-row headers, cell spans that raw iteration misses |
| Notebook cell parsing | JSON parsing of .ipynb | nbformat.read() | nbformat handles format version differences (v3/v4), auto-upgrades, validates structure |
| Sparse vector format conversion | Custom token → index mapping | Keep raw int keys from lexical_weights | BGE-M3 lexical_weights keys are already tokenizer vocabulary int IDs; they ARE the Qdrant sparse vector indices |

**Key insight:** Every "hand-rolled" solution in document processing eventually breaks on a real academic PDF with multi-column layout, spanning tables, or nested math environments. Libraries encode thousands of edge cases.

---

## Common Pitfalls

### Pitfall 1: Docling Formula Enrichment OOM
**What goes wrong:** Enabling `do_formula_enrichment=True` causes CUDA out-of-memory on GPUs with <24 GB VRAM. The CodeFormula model uses 18-20 GB VRAM at default batch size 5. An RTX 3090 (24 GB) OOMs when BGE-M3 (1 GB) is also loaded in the same process.
**Why it happens:** The CodeFormula model is a generative VLM; default batch size is too high for consumer GPUs.
**How to avoid:** Reduce batch size before converting:
```python
from docling.datamodel.settings import settings
settings.perf.elements_batch_size = 2  # reduces VRAM ~50% at cost of speed
```
Also: run Docling in the worker process and free the formula model before loading BGE-M3, OR keep them both loaded but accept the VRAM overhead.
**Warning signs:** `RuntimeError: CUDA out of memory` during Docling convert().

### Pitfall 2: FormulaItem.text is Empty Without Enrichment
**What goes wrong:** If `do_formula_enrichment=False`, `FormulaItem.text` is an empty string. Formula blocks are detected (layout model sees a formula region) but the LaTeX text is not extracted.
**Why it happens:** Formula detection and formula recognition are separate steps. Detection creates the FormulaItem; recognition (enrichment) fills `.text`.
**How to avoid:** Always set `pipeline_options.do_formula_enrichment = True` for documents that may contain formulas. For VRAM-constrained deployments, reduce batch size instead of disabling enrichment.
**Warning signs:** All formula chunks have empty `content` strings.

### Pitfall 3: lexical_weights Keys Are Int Token IDs, Not Strings
**What goes wrong:** Attempting to use `model.convert_id_to_token(output['lexical_weights'])` result (string keys) as Qdrant sparse vector indices fails because Qdrant needs integer indices.
**Why it happens:** The raw `lexical_weights` dict has `int` keys (tokenizer vocabulary IDs). `convert_id_to_token()` converts these to human-readable strings for display only.
**How to avoid:** Use the raw `lexical_weights` dict directly — the int keys ARE the sparse vector indices:
```python
raw_weights = output['lexical_weights'][0]   # dict[int, float]
sparse_vector = SparseVector(
    indices=list(raw_weights.keys()),         # list[int] — tokenizer IDs
    values=list(raw_weights.values()),        # list[float]
)
```
**Warning signs:** TypeError when constructing SparseVector, or Qdrant rejecting string indices.

### Pitfall 4: iterate_items() Omits Furniture (Headers/Footers)
**What goes wrong:** Page headers and footers appear in the document but not in the iteration, so heading detection may miss document-level titles.
**Why it happens:** `iterate_items()` defaults to `ContentLayer.BODY` only. Page headers are `ContentLayer.FURNITURE`.
**How to avoid:** For most RAG use cases, omitting furniture is correct (page headers are noise). Only include if you need to detect document-level metadata not in the body.
**Warning signs:** Document title is missing from all chunks' `section_heading`.

### Pitfall 5: TableItem.export_to_dataframe() Needs doc Argument
**What goes wrong:** `table_item.export_to_dataframe()` without the `doc` argument triggers a deprecation warning in recent docling-core releases (since ~2025) and may fail in future versions.
**Why it happens:** The method needs the parent DoclingDocument to resolve cross-references.
**How to avoid:** Always pass `doc`: `item.export_to_dataframe(doc=result.document)` or use `item.export_to_markdown()` which does not have this requirement.
**Warning signs:** `DeprecationWarning: export_to_dataframe() without doc argument is deprecated`.

### Pitfall 6: multiprocessing with CUDA — Must Use "spawn" Start Method
**What goes wrong:** On Linux, Python's default multiprocessing start method is "fork". Forking after CUDA has been initialized (even by import) causes hangs or memory corruption.
**Why it happens:** CUDA device contexts cannot be shared across forked processes.
**How to avoid:** Set start method at the top of the application entry point, before any CUDA imports:
```python
# In main.py, before any torch/cuda imports
import multiprocessing
multiprocessing.set_start_method("spawn", force=True)
```
**Warning signs:** Worker process hangs silently, or CUDA errors like "invalid device function".

### Pitfall 7: ConversionStatus.PARTIAL_SUCCESS vs Per-Page Error Tracking
**What goes wrong:** Assuming `result.status == ConversionStatus.PARTIAL_SUCCESS` means specific pages failed — but `result.errors` contains `ErrorItem` objects without a `page_no` field directly.
**Why it happens:** `ErrorItem` has `component_type` and `error_message`, not page numbers. Per-page status is in `result.pages`.
**How to avoid:** Iterate `result.pages` to find failed pages:
```python
failed_pages = [
    page.page_no
    for page in result.pages
    if not page.parsed  # or check page.error
]
```
Verify exact `Page` attribute name from docling source; this may be `page.is_successful` or similar.
**Warning signs:** Incorrectly reporting `indexed_partial` when all pages succeeded.

---

## Code Examples

Verified patterns from official sources:

### BGE-M3 Full Encoding (Dense + Sparse)
```python
# Source: huggingface.co/BAAI/bge-m3 + research/BGE_M3/README.md
from FlagEmbedding import BGEM3FlagModel

# Load once at worker startup — ~1 GB VRAM in fp16
model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

def embed_batch(texts: list[str]) -> list[dict]:
    """Returns list of {dense_vector, sparse_indices, sparse_values} per text."""
    output = model.encode(
        texts,
        batch_size=12,             # tune down if VRAM constrained (try 4-8)
        max_length=512,            # 512 for chunks; use 8192 only for very long docs
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,  # not needed for Phase 2
    )
    dense_vecs = output['dense_vecs']         # numpy array, shape (N, 1024)
    sparse_weights = output['lexical_weights'] # list of dict[int, float]

    results = []
    for i in range(len(texts)):
        raw = sparse_weights[i]  # dict[int, float] — int keys are vocab token IDs
        results.append({
            "dense_vector": dense_vecs[i].tolist(),   # list[float], len=1024
            "sparse_indices": list(raw.keys()),        # list[int]
            "sparse_values": list(raw.values()),       # list[float]
        })
    return results
```

### Qdrant Upsert with Dense + Sparse Vectors
```python
# Source: qdrant.tech/documentation/concepts/vectors/ (official Qdrant docs)
from qdrant_client.models import PointStruct, SparseVector

async def upsert_chunks_with_sparse(
    client: AsyncQdrantClient,
    collection: str,
    chunks: list[dict],
) -> None:
    """
    Each chunk dict must have:
        id: str
        dense_vector: list[float]      # 1024-dim
        sparse_indices: list[int]      # tokenizer vocab IDs
        sparse_values: list[float]     # corresponding weights
        payload: dict                  # document_id, chunk_type, etc.
    """
    points = [
        PointStruct(
            id=chunk["id"],
            vector={
                "dense": chunk["dense_vector"],
                "sparse": SparseVector(
                    indices=chunk["sparse_indices"],
                    values=chunk["sparse_values"],
                ),
            },
            payload=chunk["payload"],
        )
        for chunk in chunks
    ]
    await client.upsert(
        collection_name=collection,
        points=points,
        wait=True,   # wait=True ensures points are searchable before returning
    )
```

### Qdrant Rollback (Delete by document_id)
```python
# Source: existing qdrant.py in codebase + qdrant.tech/documentation/concepts/points/
from qdrant_client.models import Filter, FieldCondition, MatchValue

async def rollback_document(client: AsyncQdrantClient, collection: str, document_id: str) -> None:
    """Delete all Qdrant points for a document. Used for rollback on failure."""
    await client.delete(
        collection_name=collection,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        ),
        wait=True,
    )
```

### FastAPI File Upload with SHA-256
```python
# Source: fastapi.tiangolo.com/reference/uploadfile/
import hashlib
from pathlib import Path
from fastapi import UploadFile
import aiofiles

async def save_upload(upload: UploadFile, uploads_dir: Path) -> tuple[str, str, int]:
    """
    Reads, hashes, and saves an uploaded file.
    Returns (file_hash, saved_path, file_size).
    """
    contents = await upload.read()
    await upload.seek(0)   # reset if needed elsewhere

    file_hash = hashlib.sha256(contents).hexdigest()
    file_size = len(contents)

    dest = uploads_dir / f"{file_hash}{Path(upload.filename).suffix}"
    async with aiofiles.open(dest, "wb") as f:
        await f.write(contents)

    return file_hash, str(dest), file_size
```

### nbformat Jupyter Parsing
```python
# Source: nbformat.readthedocs.io/en/latest/api.html
import nbformat
from pathlib import Path

def parse_jupyter(file_path: str) -> list[dict]:
    """Extract markdown and code cells from .ipynb. Skip outputs."""
    with open(file_path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)  # auto-upgrades older formats

    chunks = []
    for cell in nb.cells:
        if cell.cell_type == "markdown":
            chunks.append({
                "chunk_type": "text",
                "content": cell.source,   # .source is a string (not list in v4)
                "display_content": None,
            })
        elif cell.cell_type == "code":
            # Get language from kernel metadata if available
            lang = nb.metadata.get("kernelspec", {}).get("language", "python")
            chunks.append({
                "chunk_type": "code",
                "content": cell.source,
                "display_content": cell.source,
                "language": lang,
            })
        # cell.cell_type == "raw" → skip
        # cell.outputs → skip (execution artifacts)
    return chunks
```

### pylatexenc LaTeX Parsing
```python
# Source: pylatexenc.readthedocs.io/en/v2.10/latexwalker/
from pylatexenc.latexwalker import LatexWalker, LatexMathNode, LatexEnvironmentNode

MATH_ENVS = {"equation", "equation*", "align", "align*", "gather", "gather*",
             "multline", "multline*", "eqnarray", "eqnarray*", "split", "cases"}

def parse_latex(file_path: str) -> list[dict]:
    """Split .tex file into text and formula chunks."""
    with open(file_path, "r", encoding="utf-8") as f:
        latex_content = f.read()

    w = LatexWalker(latex_content, tolerant_parsing=True)
    nodelist, _, _ = w.get_latex_nodes(pos=0)

    chunks = []
    last_text = ""

    for node in nodelist:
        if node is None:
            continue

        # Inline math: $...$  or display: $$...$$
        if isinstance(node, LatexMathNode):
            formula_latex = node.latex_verbatim()
            embed_content = f"{last_text.strip()}\n\n{formula_latex}" if last_text.strip() else formula_latex
            chunks.append({
                "chunk_type": "formula",
                "content": embed_content,         # includes surrounding paragraph
                "display_content": formula_latex,  # raw LaTeX only
            })
            last_text = ""

        # Named environments: \begin{equation}...\end{equation}
        elif isinstance(node, LatexEnvironmentNode):
            env_name = node.environmentname
            if env_name in MATH_ENVS:
                formula_latex = node.latex_verbatim()
                embed_content = f"{last_text.strip()}\n\n{formula_latex}" if last_text.strip() else formula_latex
                chunks.append({
                    "chunk_type": "formula",
                    "content": embed_content,
                    "display_content": formula_latex,
                })
                last_text = ""
            else:
                # Other environments (itemize, etc.) — treat as text
                last_text += node.latex_verbatim()

        else:
            # Text nodes
            text = getattr(node, "chars", None) or node.latex_verbatim()
            last_text += text

    # Flush trailing text
    if last_text.strip():
        chunks.append({
            "chunk_type": "text",
            "content": last_text.strip(),
            "display_content": None,
        })
    return chunks
```

### Docling PdfPipelineOptions Full Configuration
```python
# Source: docling-project.github.io/docling/usage/enrichments/ + docling-project.github.io/docling/getting_started/rtx/
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.settings import settings as docling_settings

# Reduce CodeFormula batch size to avoid OOM on consumer GPUs
docling_settings.perf.elements_batch_size = 2   # default is 5; reduces VRAM ~50%

pipeline_options = PdfPipelineOptions()
pipeline_options.do_table_structure = True
pipeline_options.do_formula_enrichment = True  # requires CodeFormula model; ~18-20 GB VRAM at batch=5
pipeline_options.do_code_enrichment = True
pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CUDA)

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)

result = converter.convert("/path/to/file.pdf", raises_on_error=False)
# result.status: ConversionStatus.SUCCESS | PARTIAL_SUCCESS | FAILURE
# result.errors: list[ErrorItem] — component-level errors
# result.document: DoclingDocument — the parsed doc
```

---

## Worker Architecture

### Recommended Pattern: multiprocessing.Process
The serial queue requirement and VRAM isolation requirement both point to a **separate OS process** (not asyncio task):

```
FastAPI Process                    Worker Process
─────────────────────────────────  ──────────────────────────────────
POST /documents                    worker_main():
  → save file                        model = BGEM3FlagModel(...)  # once
  → write SQLite (status=pending)    while not stop_event:
  → queue.put(job)                     job = queue.get(timeout=1)
  → return {doc_id, status}           update_status(indexing)
                                       chunks = parse(job)
GET /documents/{id}                    embeddings = embed(chunks)
  → read SQLite status                 upsert_qdrant(embeddings)
                                       update_status(indexed)
                                       # or rollback on error
```

**Why not asyncio.create_task?**
- `encode()` in FlagEmbedding is synchronous and CPU/GPU-bound
- Running it in the same event loop blocks all API requests
- Even with `run_in_executor`, it runs in a thread, sharing VRAM with Docling if they're in the same process

**Why not Celery/Redis?**
- Adds two infrastructure dependencies (Redis, worker service)
- Overkill for single-machine serial processing
- The requirement is a serial queue, not distributed workers

**multiprocessing start method:** Must be set to `"spawn"` on Linux before any CUDA-related imports (torch, docling, flagembedding).

### Status Update Pattern
The worker process needs to write to SQLite. Since it's a separate process, it cannot share the FastAPI SQLAlchemy session. Options:
1. **Recommended**: Worker creates its own SQLAlchemy engine using the same sqlite_url from config
2. Alternative: Pass status updates back via a result queue (more complex)

```python
# In worker process — create separate SQLAlchemy session
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from rag_server.database.models import Document

def update_document_status(sqlite_url: str, doc_id: str, status: str, error: str | None = None):
    # Worker uses sync SQLAlchemy (no event loop in worker)
    engine = create_engine(sqlite_url.replace("sqlite+aiosqlite", "sqlite"))
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        doc.status = status
        doc.error_msg = error
        session.commit()
```

---

## Chunking Implementation

### Text Block Chunking
For text blocks from Docling, use the **Docling HybridChunker** on the full document to get token-aware text chunks, then filter by `chunk.meta.doc_items` to detect chunk type:

```python
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer import HuggingFaceTokenizer

chunker = HybridChunker(
    tokenizer=HuggingFaceTokenizer(model_name="BAAI/bge-m3"),
    max_tokens=512,
    merge_peers=True,
)

for chunk in chunker.chunk(result.document):
    # chunk.text — the text to embed
    # chunk.meta.headings — list of SectionHeaderItem (nearest headings)
    # chunk.meta.doc_items — list of DocItem (source blocks)
    heading = chunk.meta.headings[-1].text if chunk.meta.headings else None

    # Detect if this chunk is purely a formula or table (HybridChunker may yield these too)
    item_labels = {item.label for item in chunk.meta.doc_items}
    # Use chunk.text for embedding content
```

**Caution:** HybridChunker may not correctly chunk formula/table blocks as atomic units. The safer approach is:
1. Use direct `iterate_items()` traversal (Pattern 3 above) for formula, table, code blocks → emit them as single atomic chunks
2. Collect only `TextItem` blocks and feed them through a simple token-splitting pass
3. This gives full control over `chunk_type` without relying on HybridChunker's internal classification

### Text Splitting for Long Text Blocks
```python
import tiktoken

enc = tiktoken.get_encoding("cl100k_base")  # close enough for BGE-M3; or use BAAI tokenizer

def split_text_tokens(text: str, max_tokens: int = 512, overlap: int = 64) -> list[str]:
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return [text]
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        start += max_tokens - overlap
    return chunks
```

### Formula Chunk Enrichment Rule
- `content` (for embedding) = preceding paragraph text + "\n\n" + formula LaTeX
- `display_content` (for UI) = raw formula LaTeX only
- This ensures retrieval queries like "equation for heat capacity" find the formula via its surrounding context

---

## Qdrant Sparse Upsert

### SparseVector Construction
```python
# Source: qdrant.tech/documentation/concepts/vectors/
from qdrant_client.models import PointStruct, SparseVector

# lexical_weights[i] is dict[int, float] — BGE-M3 raw output
raw = output['lexical_weights'][0]   # {1234: 0.083, 5678: 0.126, ...}

point = PointStruct(
    id="chunk-uuid-here",
    vector={
        "dense": dense_vec.tolist(),    # list[float], len=1024
        "sparse": SparseVector(
            indices=list(raw.keys()),   # list[int] — vocab token IDs
            values=list(raw.values()),  # list[float]
        ),
    },
    payload={
        "document_id": "doc-id",
        "chunk_type": "text",
        "page_number": 3,
        "section_heading": "Methodology",
        "chunk_index": 7,
    },
)
```

### Upsert Batch Size Recommendation
- Start with batches of 50-100 points
- Qdrant async upsert is not blocking CPU during vector indexing
- Larger batches reduce round-trip overhead; smaller batches reduce memory per request

### Rollback Pattern
On any failure during a document's pipeline:
1. Call `delete_document(document_id)` on `QdrantStore` (already implemented in codebase)
2. Delete SQLite Chunk rows via CASCADE (Document→Chunk cascade="all, delete-orphan" already set in models.py)
3. Set Document.status = "failed" and Document.error_msg = str(exception)

The existing `QdrantStore.delete_document()` uses `Filter(must=[FieldCondition(key="document_id", ...)])` which is the correct pattern.

---

## File Upload + Hashing

### Upload Endpoint Pattern
```python
# Source: fastapi.tiangolo.com/reference/uploadfile/
from fastapi import APIRouter, UploadFile, Depends
from pathlib import Path
import hashlib
import aiofiles

ALLOWED_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/x-tex": "tex",
    "text/x-tex": "tex",
    "application/json": "ipynb",   # .ipynb files are JSON
}
ALLOWED_EXTENSIONS = {".pdf", ".tex", ".ipynb"}

router = APIRouter()

async def save_upload_file(upload: UploadFile, uploads_dir: Path) -> dict:
    contents = await upload.read()
    file_hash = hashlib.sha256(contents).hexdigest()
    file_size = len(contents)
    suffix = Path(upload.filename).suffix.lower()
    dest = uploads_dir / f"{file_hash}{suffix}"

    if not dest.exists():
        async with aiofiles.open(dest, "wb") as f:
            await f.write(contents)

    return {
        "file_hash": file_hash,
        "file_path": str(dest),
        "file_size": file_size,
        "suffix": suffix,
    }
```

### Storage Location
Store uploaded files at: `{DATA_DIR}/uploads/{sha256_hash}.{ext}`

Using the hash as filename:
- Deduplication: same file uploaded twice reuses the existing file
- No collision: SHA-256 is 256-bit
- The worker reads from this path; file persists until document is deleted

---

## LaTeX + Jupyter Parsing

### pylatexenc Version Recommendation
Use **pylatexenc 2.10** (stable). Version 3.0alpha is still pre-release (as of 2025) with incomplete documentation and API changes. The 2.x `LatexWalker.get_latex_nodes()` API is stable.

### Math Environments Covered
pylatexenc detects:
- **Inline math**: `$...$` → `LatexMathNode`
- **Display math**: `$$...$$` → `LatexMathNode` (displaytype="display")
- **Named environments**: `\begin{equation}...\end{equation}` → `LatexEnvironmentNode` (environmentname="equation")
- All standard AMS environments: align, gather, multline, cases, split, eqnarray

Note: `\begin{equation}` is `LatexEnvironmentNode`, NOT `LatexMathNode`. Both must be checked.

### nbformat v4 Structure
```python
# cell.cell_type: "markdown" | "code" | "raw"
# cell.source: str (v4) — the cell content
# cell.outputs: list (code cells only) — SKIP these
# nb.metadata.kernelspec.language: "python" | "julia" | "r" etc.
# nb.metadata.kernelspec.display_name: "Python 3" etc.
```

Upgrade older notebooks automatically: `nbformat.read(f, as_version=4)` handles v3→v4 conversion.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PDF text extraction with pdfplumber/pdfminer | Docling with layout detection | 2024 (Docling OSS) | Tables, formulas, multi-column layout now work |
| Separate dense embedding only | BGE-M3 three-mode (dense+sparse+ColBERT) | 2024 (BGE-M3 paper) | Hybrid search enables keyword+semantic in one model |
| Celery for background tasks | multiprocessing.Process in lifespan | FastAPI 0.95+ (lifespan API) | Simpler for single-machine serial queues |
| BlockFix for sparse vectors | qdrant-client SparseVector type | qdrant-client 1.7+ | First-class sparse vector support |
| iterate_items without ContentLayer | iterate_items(included_content_layers=...) | docling-core 1.8+ | Explicit layer control; furniture deprecated |

**Deprecated/outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: replaced by `lifespan` parameter in FastAPI 0.95+
- `TableItem.export_to_dataframe()` without `doc` argument: deprecated in docling-core, pass `doc=result.document`
- pylatexenc 3.0alpha: `get_latex_nodes()` being replaced by parser objects; stick with 2.x

---

## Open Questions

1. **Per-page failure detection in Docling**
   - What we know: `ConversionStatus.PARTIAL_SUCCESS` indicates some pages failed; `result.errors` has `ErrorItem` objects; `result.pages` contains page-level data
   - What's unclear: Exact attribute name on `Page` object to check if a page failed (`.parsed`, `.is_successful`, or `.error`). Needs verification against Docling source code.
   - Recommendation: Check `docling_core.types.doc.Page` source in installed package before implementing page-failure detection.

2. **CodeItem is a floating object**
   - What we know: A 2025 comment mentions "CodeItem was recently redefined as a floating object with captions"
   - What's unclear: Whether CodeItem appears in `iterate_items()` body traversal or only in a separate collection (`doc.code_items`)
   - Recommendation: Test with a PDF containing code blocks; inspect both `doc.code_items` and `iterate_items()` output.

3. **HybridChunker with BAAI/bge-m3 tokenizer compatibility**
   - What we know: HuggingFaceTokenizer takes a model_name; HybridChunker uses it for token counting
   - What's unclear: Whether BAAI/bge-m3 tokenizer is compatible with HuggingFaceTokenizer (it uses XLM-RoBERTa tokenizer internally)
   - Recommendation: If using HybridChunker for text blocks, test with `model_name="BAAI/bge-m3"` first; fall back to tiktoken if it fails.

4. **Worker SQLite URL conversion**
   - What we know: FastAPI uses `sqlite+aiosqlite` URL; worker process needs sync SQLAlchemy
   - What's unclear: Whether replacing `aiosqlite` with `pysqlite` in the URL string is the cleanest approach
   - Recommendation: Use `sqlite_url.replace("sqlite+aiosqlite://", "sqlite:///")` in the worker.

---

## Sources

### Primary (HIGH confidence)
- [deepwiki.com/docling-project/docling-core/2.1-doclingdocument](https://deepwiki.com/docling-project/docling-core/2.1-doclingdocument) — DoclingDocument data model, item types, prov[0].page_no pattern
- [deepwiki.com/docling-project/docling/7.1-documentconverter-api](https://deepwiki.com/docling-project/docling/7.1-documentconverter-api) — DocumentConverter API, ConversionResult, ConversionStatus enum
- [deepwiki.com/docling-project/docling-core/3.1.1-hybrid-chunking](https://deepwiki.com/docling-project/docling-core/3.1.1-hybrid-chunking) — HybridChunker API, DocChunk fields
- [docling-project.github.io/docling/usage/enrichments/](https://docling-project.github.io/docling/usage/enrichments/) — do_formula_enrichment, do_code_enrichment configuration
- [docling-project.github.io/docling/getting_started/rtx/](https://docling-project.github.io/docling/getting_started/rtx/) — AcceleratorOptions, CUDA configuration
- [huggingface.co/BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) — BGEM3FlagModel encode() API, lexical_weights format, batch_size defaults
- [github.com/FlagOpen/FlagEmbedding/blob/master/research/BGE_M3/README.md](https://github.com/FlagOpen/FlagEmbedding/blob/master/research/BGE_M3/README.md) — encode() with return_sparse=True, convert_id_to_token()
- [qdrant.tech/documentation/concepts/vectors/](https://qdrant.tech/documentation/concepts/vectors/) — SparseVector(indices, values), PointStruct with named vectors
- [fastapi.tiangolo.com/reference/uploadfile/](https://fastapi.tiangolo.com/reference/uploadfile/) — UploadFile.read(), seek(), content_type
- [nbformat.readthedocs.io/en/latest/api.html](https://nbformat.readthedocs.io/en/latest/api.html) — nbformat.read(), cell structure, cell.source
- [pylatexenc.readthedocs.io/en/v2.10/latexwalker/](https://pylatexenc.readthedocs.io/en/v2.10/latexwalker/) — LatexWalker, LatexMathNode, LatexEnvironmentNode, latex_verbatim()

### Secondary (MEDIUM confidence)
- [github.com/docling-project/docling/issues/871](https://github.com/docling-project/docling/issues/871) — Formula enrichment VRAM requirements (18-20 GB at batch_size=5); docling_settings.perf.elements_batch_size
- [github.com/docling-project/docling/issues/2058](https://github.com/docling-project/docling/issues/2058) — iterate_items ContentLayer parameter (BODY vs FURNITURE)
- [github.com/docling-project/docling/discussions/807](https://github.com/docling-project/docling/discussions/807) — SectionHeaderItem.level, item.prov[0].page_no confirmed by maintainer
- WebSearch for lexical_weights raw format → confirmed int keys (token IDs) before convert_id_to_token

### Tertiary (LOW confidence — verify before use)
- DocChunk.meta.page attribute name (some sources say `meta.page`, others `meta.page_no`) — verify from installed package
- Per-page failure detection: exact `Page` attribute to check for failed pages — verify from Docling source
- CodeItem as "floating object with captions" — from a 2025 GitHub comment; behavior in iterate_items() unverified

---

## Metadata

**Confidence breakdown:**
- Docling API (DocumentConverter, ConversionResult, iterate_items): HIGH — verified via official docs + DeepWiki
- Docling formula enrichment VRAM requirements: MEDIUM — from GitHub issue reports
- BGE-M3 encode() / lexical_weights format: HIGH — verified via HuggingFace model card + official README
- Qdrant SparseVector construction: HIGH — verified via official Qdrant docs
- Worker architecture (multiprocessing vs asyncio): HIGH — well-established Python pattern
- HybridChunker DocChunk fields: MEDIUM — DeepWiki + chunking documentation; some field names unverified
- pylatexenc LatexWalker API: HIGH — official 2.x docs
- nbformat cell API: HIGH — official nbformat docs
- Per-page failure detection: LOW — ConversionStatus confirmed, but exact Page attribute unverified

**Research date:** 2026-02-19
**Valid until:** 2026-03-19 (Docling releases weekly; check changelog for breaking changes)
