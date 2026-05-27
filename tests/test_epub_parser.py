from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from rag_server.ingestion.parsers.epub_parser import iter_epub_batches, parse_epub


def _write_epub(path: Path, *, missing_spine_item: bool = False) -> None:
    chapters = {
        "OEBPS/chapter1.xhtml": """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>One</title></head>
  <body>
    <h1>Sharpe Ratio</h1>
    <p>The Sharpe ratio measures excess return per unit of volatility.</p>
    <table>
      <tr><th>Metric</th><th>Value</th></tr>
      <tr><td>Sharpe</td><td>1.2</td></tr>
    </table>
  </body>
</html>
""",
        "OEBPS/chapter2.xhtml": """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Two</title></head>
  <body>
    <h2>Implementation</h2>
    <p>Backtesting code should avoid lookahead bias.</p>
    <pre><code>def sharpe(returns): return returns.mean() / returns.std()</code></pre>
  </body>
</html>
""",
    }

    manifest_items = [
        '<item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="chap2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine_refs = ['<itemref idref="chap1"/>', '<itemref idref="chap2"/>']
    if missing_spine_item:
        manifest_items.append(
            '<item id="missing" href="missing.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_refs.insert(1, '<itemref idref="missing"/>')

    content_opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <manifest>
    {"".join(manifest_items)}
  </manifest>
  <spine>
    {"".join(spine_refs)}
  </spine>
</package>
"""

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        zf.writestr("OEBPS/content.opf", content_opf)
        for name, body in chapters.items():
            zf.writestr(name, body)


def test_parse_epub_preserves_spine_order_and_chunk_metadata(tmp_path: Path) -> None:
    epub_path = tmp_path / "quant.epub"
    _write_epub(epub_path)

    chunks, is_partial = parse_epub(epub_path)

    assert is_partial is False
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page_number is None for chunk in chunks)
    assert any(
        "Sharpe ratio measures excess return" in chunk.content for chunk in chunks
    )
    assert any(
        "Backtesting code should avoid lookahead bias" in chunk.content
        for chunk in chunks
    )
    sharpe_idx = next(
        idx
        for idx, chunk in enumerate(chunks)
        if "Sharpe ratio measures" in chunk.content
    )
    backtest_idx = next(
        idx for idx, chunk in enumerate(chunks) if "Backtesting code" in chunk.content
    )
    assert sharpe_idx < backtest_idx
    assert any(chunk.section_heading == "Sharpe Ratio" for chunk in chunks)
    assert any(chunk.section_heading == "Implementation" for chunk in chunks)
    assert any(
        chunk.chunk_type == "table" and "Metric" in (chunk.display_content or "")
        for chunk in chunks
    )
    assert any(
        chunk.chunk_type == "code" and "def sharpe" in (chunk.display_content or "")
        for chunk in chunks
    )


def test_iter_epub_batches_emits_one_batch_per_spine_item(tmp_path: Path) -> None:
    epub_path = tmp_path / "quant.epub"
    _write_epub(epub_path)

    batches = list(iter_epub_batches(epub_path))

    assert len(batches) == 2
    assert all(batch.is_partial is False for batch in batches)
    assert any(
        "Sharpe ratio measures excess return" in chunk.content
        for chunk in batches[0].chunks
    )
    assert any("Backtesting code" in chunk.content for chunk in batches[1].chunks)
    assert all(chunk.page_number is None for batch in batches for chunk in batch.chunks)


def test_parse_epub_marks_partial_when_a_spine_item_is_missing(tmp_path: Path) -> None:
    epub_path = tmp_path / "partial.epub"
    _write_epub(epub_path, missing_spine_item=True)

    chunks, is_partial = parse_epub(epub_path)

    assert is_partial is True
    assert any(
        "Sharpe ratio measures excess return" in chunk.content for chunk in chunks
    )
    assert any(
        "Backtesting code should avoid lookahead bias" in chunk.content
        for chunk in chunks
    )


def test_iter_epub_batches_marks_missing_spine_item_partial(tmp_path: Path) -> None:
    epub_path = tmp_path / "partial.epub"
    _write_epub(epub_path, missing_spine_item=True)

    batches = list(iter_epub_batches(epub_path))

    assert len(batches) == 3
    assert batches[1].chunks == []
    assert batches[1].is_partial is True


def test_parse_epub_rejects_malformed_epub(tmp_path: Path) -> None:
    epub_path = tmp_path / "not-an-epub.epub"
    epub_path.write_text("not a zip file", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid EPUB archive"):
        parse_epub(epub_path)
