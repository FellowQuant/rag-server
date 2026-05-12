"""Docling-based PDF parser.

Produces a list[ParsedChunk] from a PDF file using Docling's DocumentConverter
with layout detection, table structure, formula enrichment, and code enrichment.

INGEST-01: PDF ingestion with layout-aware parsing preserving tables, formulas,
           multi-column layouts.
INGEST-04: Code block chunks preserve syntax and language metadata.
INGEST-05: Formula chunks enriched with surrounding paragraph context.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import settings as docling_settings
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import (
    CodeItem,
    ContentLayer,
    FormulaItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
)

from rag_server.ingestion.chunker import (
    ParsedChunk,
    enrich_formula_content,
    split_text_tokens,
)

logger = logging.getLogger(__name__)

# Matches PDF /uniXXXX glyph name artifacts that Docling emits when ToUnicode
# CMap entries use the /uniXXXX naming convention instead of standard glyph names.
# Example: "/uniFB01" → "ﬁ" (U+FB01, fi ligature), then NFKC maps it to "fi".
_UNI_GLYPH_RE = re.compile(r'/uni([0-9A-Fa-f]{4})')


def _normalize_text(text: str) -> str:
    """Normalize PDF-extracted text: resolve /uniXXXX escapes and decompose ligatures."""
    text = _UNI_GLYPH_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    return unicodedata.normalize("NFKC", text)


def _patch_pdf_hyperlink() -> None:
    """Make PdfHyperlink.uri accept any string, skipping strict URL format validation.

    Root cause analysis:
    - PdfHyperlink is defined in docling_core.types.doc.page (NOT .document)
    - SegmentedPage.hyperlinks: list[PdfHyperlink] — the parent model, same module
    - The C extension (pdf_parsers.so) extracts raw hyperlink dicts; Pydantic
      validates them when constructing SegmentedPdfPage. AnyUrl rejects bare
      URLs ('www.example.com') or URLs with spaces ('https://ssrn. com/...'),
      failing the entire page preprocess stage.

    Fix strategy — modify the ORIGINAL class in-place (not a subclass):
    1. Change model_fields['uri'] annotation to str | None (accepts any string)
    2. Rebuild PdfHyperlink so its own compiled schema changes
    3. Rebuild all BaseModel subclasses in docling_core.types.doc.page so that
       SegmentedPage and SegmentedPdfPage recompile with the updated schema

    Replacing PdfHyperlink with a subclass does NOT work because Pydantic v2
    inlines parent model schemas at class-definition time.
    """
    try:
        from pydantic import BaseModel
        from pydantic.fields import FieldInfo
        import docling_core.types.doc.page as _page

        cls = _page.PdfHyperlink

        if "uri" not in cls.model_fields:
            logger.warning("PdfHyperlink.uri field not found — patch skipped")
            return

        # Change uri to plain Optional[str] — no URL format validation
        cls.model_fields["uri"] = FieldInfo(annotation=str | None, default=None)
        cls.__annotations__["uri"] = str | None
        cls.model_rebuild(force=True)

        # Rebuild all BaseModel subclasses in docling_core.types.doc.page so that
        # SegmentedPage / SegmentedPdfPage recompile with the updated PdfHyperlink.
        rebuilt = 0
        for _name in dir(_page):
            _obj = getattr(_page, _name, None)
            if (
                isinstance(_obj, type)
                and issubclass(_obj, BaseModel)
                and _obj is not cls
                and _obj is not BaseModel
            ):
                try:
                    _obj.model_rebuild(force=True)
                    rebuilt += 1
                except Exception:
                    pass

        logger.info(
            "PdfHyperlink patched — uri accepts any string; %d sibling models rebuilt",
            rebuilt,
        )
    except Exception as exc:
        logger.warning("PdfHyperlink patch skipped: %s", exc)


_patch_pdf_hyperlink()

# Reduce CodeFormula model batch size to avoid CUDA OOM on consumer GPUs.
# Default batch_size=5 requires ~18-20 GB VRAM; batch_size=2 reduces to ~8-10 GB.
# Must be set before DocumentConverter is constructed (affects pipeline options).
docling_settings.perf.elements_batch_size = 2


def make_converter(use_gpu: bool = True) -> DocumentConverter:
    """Construct a Docling DocumentConverter with full enrichment enabled.

    Creates a single converter instance to be reused across documents in the
    worker process. Constructing the converter is expensive (loads layout models).

    Args:
        use_gpu: If True, use CUDA acceleration. Set False for CPU-only deployments.
    """
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    # INGEST-05: Formula enrichment fills FormulaItem.text with LaTeX.
    # Without this, FormulaItem.text is empty string (detection ≠ recognition).
    pipeline_options.do_formula_enrichment = True
    pipeline_options.do_code_enrichment = True
    # Disable OCR: finance PDFs are born-digital; OCR loads RapidOCR on GPU
    # (~1 GB VRAM) and causes CUBLAS_STATUS_ALLOC_FAILED when combined with
    # BGE-M3 + CodeFormulaV2 + layout models on consumer GPUs.
    pipeline_options.do_ocr = False

    if use_gpu:
        pipeline_options.accelerator_options = AcceleratorOptions(
            device=AcceleratorDevice.CUDA
        )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


def _teardown_conversion_result(result) -> None:
    """Explicitly release all heavy objects inside a ConversionResult.

    Docling's _unload() (called in base_pipeline.execute's finally block)
    unloads page and document backends, but the ConversionResult itself —
    with all Page objects, image caches, parsed_page data, the assembled
    DoclingDocument, and the InputDocument wrapper — remains alive as long
    as the caller holds a reference.

    When keep_backend=True (required for formula/code enrichment), Docling's
    _integrate_results() SKIPS per-page backend cleanup during the pipeline.
    The _unload() at the end does call unload(), but the Python wrapper
    objects persist with all their Pydantic model data.

    This function aggressively breaks references so gc.collect() can reclaim
    the memory immediately after we've extracted our chunks.

    See: docs/docling-memory-leak.md for full analysis.
    """
    try:
        # 1. Clear all page-level data (image caches, parsed pages, backends).
        for page in getattr(result, 'pages', []):
            page._image_cache = {}
            page.predictions = None
            page.assembled = None
            if hasattr(page, 'parsed_page'):
                page.parsed_page = None
            if page._backend is not None:
                try:
                    page._backend.unload()
                except Exception:
                    pass
                page._backend = None
        result.pages.clear()

        # 2. Unload the document-level backend (pypdfium2/docling-parse handles).
        input_doc = getattr(result, 'input', None)
        if input_doc is not None:
            backend = getattr(input_doc, '_backend', None)
            if backend is not None:
                try:
                    backend.unload()
                except Exception:
                    pass
                input_doc._backend = None

        # 3. Drop the assembled DoclingDocument (contains all extracted content
        #    nodes, tables, formulas — can be tens of MB for large documents).
        result.document = None
        result.assembled = None

        # 4. Clear error list and timings (minor, but breaks reference cycles).
        if hasattr(result, 'errors'):
            result.errors.clear()
        if hasattr(result, 'timings'):
            result.timings.clear()

    except Exception as exc:
        logger.debug("_teardown_conversion_result: ignoring cleanup error: %s", exc)


def parse_pdf(
    file_path: str | Path, converter: DocumentConverter,
) -> tuple[list[ParsedChunk], bool]:
    """Convert a PDF file to a list of typed ParsedChunk objects.

    Uses Docling's iterate_items() to walk the document in reading order,
    emitting atomic chunks for formulas, tables, and code, and split chunks
    for long text blocks.

    Args:
        file_path: Absolute path to the saved PDF file.
        converter: DocumentConverter instance (reused across documents in worker).

    Returns:
        (chunks, is_partial) tuple. chunks has chunk_index populated
        sequentially from 0. is_partial is True when Docling reports
        PARTIAL_SUCCESS. Returns ([], False) on total failure.
    """
    result = converter.convert(str(file_path), raises_on_error=False)

    from docling.datamodel.base_models import ConversionStatus
    if result.status == ConversionStatus.FAILURE:
        logger.error("Docling: total failure on %s — %s", file_path, result.errors)
        _teardown_conversion_result(result)
        del result
        return [], False

    is_partial = result.status == ConversionStatus.PARTIAL_SUCCESS
    if is_partial:
        logger.warning("Docling: partial success on %s — %s", file_path, result.errors)

    doc = result.document
    raw_chunks: list[ParsedChunk] = []
    current_heading: str | None = None
    last_paragraph: str = ""

    for item, _level in doc.iterate_items(
        included_content_layers={ContentLayer.BODY}
    ):
        page_no = item.prov[0].page_no if item.prov else None

        if isinstance(item, SectionHeaderItem):
            current_heading = _normalize_text(item.text) if item.text else current_heading
            # Section headers are navigation context, not standalone chunks.
            # Update last_paragraph so formulas after a heading have some context.
            last_paragraph = current_heading or last_paragraph

        elif isinstance(item, FormulaItem):
            formula_latex = item.text or ""
            if not formula_latex:
                logger.debug("Empty FormulaItem on page %s — enrichment may have failed", page_no)
            embed_content = enrich_formula_content(formula_latex, last_paragraph)
            raw_chunks.append(
                ParsedChunk(
                    chunk_type="formula",
                    content=embed_content,
                    display_content=formula_latex,
                    page_number=page_no,
                    section_heading=current_heading,
                )
            )
            # Reset paragraph tracker after formula so next formula gets fresh context.
            last_paragraph = ""

        elif isinstance(item, TableItem):
            # export_to_markdown() handles merged cells, multi-row headers, spans.
            # Do NOT use export_to_dataframe() without doc= argument (deprecated).
            table_md = item.export_to_markdown()
            raw_chunks.append(
                ParsedChunk(
                    chunk_type="table",
                    content=table_md,
                    display_content=table_md,
                    page_number=page_no,
                    section_heading=current_heading,
                )
            )

        elif isinstance(item, CodeItem):
            # code_language is set by do_code_enrichment=True pipeline option.
            lang = getattr(item, "code_language", None)
            code_text = item.text or ""
            raw_chunks.append(
                ParsedChunk(
                    chunk_type="code",
                    content=code_text,
                    display_content=code_text,
                    page_number=page_no,
                    section_heading=current_heading,
                    language=str(lang) if lang else None,
                )
            )

        elif isinstance(item, TextItem):
            text = _normalize_text(item.text) if item.text else ""
            last_paragraph = text  # track for formula context enrichment
            if not text.strip():
                continue
            # Split long text blocks; atomic chunks (formula/table/code) are never split.
            segments = split_text_tokens(text)
            for seg in segments:
                raw_chunks.append(
                    ParsedChunk(
                        chunk_type="text",
                        content=seg,
                        display_content=None,
                        page_number=page_no,
                        section_heading=current_heading,
                    )
                )

    # Assign sequential chunk_index after all chunks are collected.
    for idx, chunk in enumerate(raw_chunks):
        chunk.chunk_index = idx

    logger.info("parse_pdf: %d chunks from %s (status=%s)", len(raw_chunks), file_path, result.status)

    # Explicitly tear down the ConversionResult now that all data has been
    # extracted into ParsedChunk objects. This breaks the reference chain:
    #   ConversionResult -> InputDocument -> PdfDocumentBackend (pypdfium2/docling-parse)
    #   ConversionResult -> pages[] -> Page._backend, _image_cache, parsed_page
    #   ConversionResult -> document (DoclingDocument with all content nodes)
    # Without this, the entire ConversionResult stays alive until the caller's
    # gc.collect(), and even then Pydantic model reference cycles may prevent
    # full collection. See docs/docling-memory-leak.md.
    _teardown_conversion_result(result)
    del result

    return raw_chunks, is_partial
