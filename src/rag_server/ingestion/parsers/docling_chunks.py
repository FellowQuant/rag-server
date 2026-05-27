"""Utilities for turning Docling documents into ingestion chunks."""

from __future__ import annotations

import logging
import re
import unicodedata

from docling_core.types.doc import (
    CodeItem,
    ContentLayer,
    FormulaItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)

from rag_server.ingestion.chunker import (
    ParsedChunk,
    enrich_formula_content,
    split_text_tokens,
)

logger = logging.getLogger(__name__)

_UNI_GLYPH_RE = re.compile(r"/uni([0-9A-Fa-f]{4})")


def normalize_docling_text(text: str) -> str:
    """Normalize Docling-extracted text and decompose ligatures."""
    text = _UNI_GLYPH_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    return unicodedata.normalize("NFKC", text)


def chunks_from_docling_document(
    doc,
    *,
    include_title_as_heading: bool = False,
    preserve_page_numbers: bool = True,
) -> list[ParsedChunk]:
    """Convert a DoclingDocument into ParsedChunk objects in reading order."""
    raw_chunks: list[ParsedChunk] = []
    current_heading: str | None = None
    last_paragraph = ""

    for item, _level in doc.iterate_items(included_content_layers={ContentLayer.BODY}):
        page_no = None
        if preserve_page_numbers:
            prov = getattr(item, "prov", None)
            page_no = prov[0].page_no if prov else None

        is_heading = isinstance(item, SectionHeaderItem) or (
            include_title_as_heading and isinstance(item, TitleItem)
        )

        if is_heading:
            current_heading = (
                normalize_docling_text(item.text)
                if getattr(item, "text", None)
                else current_heading
            )
            last_paragraph = current_heading or last_paragraph

        elif isinstance(item, FormulaItem):
            formula_latex = item.text or ""
            if not formula_latex:
                logger.debug("Empty FormulaItem on page %s", page_no)
            raw_chunks.append(
                ParsedChunk(
                    chunk_type="formula",
                    content=enrich_formula_content(formula_latex, last_paragraph),
                    display_content=formula_latex,
                    page_number=page_no,
                    section_heading=current_heading,
                )
            )
            last_paragraph = ""

        elif isinstance(item, TableItem):
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
            text = normalize_docling_text(item.text) if item.text else ""
            last_paragraph = text
            if not text.strip():
                continue
            for segment in split_text_tokens(text):
                raw_chunks.append(
                    ParsedChunk(
                        chunk_type="text",
                        content=segment,
                        display_content=None,
                        page_number=page_no,
                        section_heading=current_heading,
                    )
                )

    for idx, chunk in enumerate(raw_chunks):
        chunk.chunk_index = idx

    return raw_chunks
