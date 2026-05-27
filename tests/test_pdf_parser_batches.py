from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from rag_server.ingestion.chunker import ParsedChunk
from rag_server.ingestion.parsers import pdf_parser


def _write_blank_pdf(path: Path, page_count: int) -> None:
    doc = pdfium.PdfDocument.new()
    try:
        for _ in range(page_count):
            doc.new_page(595, 842)
        doc.save(path)
    finally:
        doc.close()


def test_iter_pdf_batches_splits_large_pdf_and_offsets_page_numbers(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = tmp_path / "large.pdf"
    _write_blank_pdf(pdf_path, page_count=5)
    parsed_page_counts: list[int] = []

    def fake_parse_pdf(file_path: str | Path, converter):
        doc = pdfium.PdfDocument(str(file_path))
        try:
            parsed_page_counts.append(len(doc))
            return [
                ParsedChunk(
                    chunk_type="text",
                    content=f"batch with {len(doc)} pages",
                    page_number=1,
                )
            ], False
        finally:
            doc.close()

    monkeypatch.setattr(pdf_parser, "parse_pdf", fake_parse_pdf)

    batches = list(
        pdf_parser.iter_pdf_batches(
            pdf_path,
            converter=object(),
            pages_per_batch=2,
            large_file_bytes=0,
        )
    )

    assert parsed_page_counts == [2, 2, 1]
    assert [batch.page_count for batch in batches] == [5, 5, 5]
    assert [batch.chunks[0].page_number for batch in batches] == [1, 3, 5]
    assert [batch.chunks[0].content for batch in batches] == [
        "batch with 2 pages",
        "batch with 2 pages",
        "batch with 1 pages",
    ]
