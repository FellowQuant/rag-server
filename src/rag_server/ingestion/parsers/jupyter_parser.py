"""nbformat-based Jupyter notebook (.ipynb) parser.

Produces a list[ParsedChunk] from a Jupyter notebook. Markdown cells become
text chunks; code cells become code chunks. All outputs are skipped (they are
execution artifacts and add noise to retrieval).

INGEST-03: Jupyter ingestion — markdown + code cells only, skip outputs.
INGEST-04: Code block chunks preserve syntax and language metadata.

Uses nbformat.read(as_version=4) which auto-upgrades older notebook formats.
"""
from __future__ import annotations

import logging
from pathlib import Path

import nbformat

from rag_server.ingestion.chunker import ParsedChunk, split_text_tokens

logger = logging.getLogger(__name__)


def parse_jupyter(file_path: str | Path) -> list[ParsedChunk]:
    """Parse a .ipynb file into typed ParsedChunk objects.

    Args:
        file_path: Absolute path to the .ipynb file.

    Returns:
        List of ParsedChunk with chunk_index populated sequentially from 0.
        Returns an empty list on parse failure.
    """
    path = Path(file_path)
    try:
        with path.open("r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)
    except Exception as exc:
        logger.error("Cannot parse Jupyter notebook %s: %s", file_path, exc)
        return []

    # Extract kernel language from metadata (e.g. "python", "julia", "r").
    kernelspec = nb.metadata.get("kernelspec", {})
    kernel_language: str = kernelspec.get("language", "python")

    raw_chunks: list[ParsedChunk] = []

    for cell in nb.cells:
        cell_type = cell.get("cell_type", "")
        source: str = cell.get("source", "")

        if not source.strip():
            continue

        if cell_type == "markdown":
            # Long markdown cells are split by token count like any text block.
            for seg in split_text_tokens(source):
                raw_chunks.append(
                    ParsedChunk(
                        chunk_type="text",
                        content=seg,
                        display_content=None,
                    )
                )

        elif cell_type == "code":
            # Code cells are always atomic — never split across chunks.
            # cell.outputs is intentionally skipped (execution artifacts).
            raw_chunks.append(
                ParsedChunk(
                    chunk_type="code",
                    content=source,
                    display_content=source,
                    language=kernel_language,
                )
            )

        # cell_type == "raw" → skip (directives for nbconvert, not user content)

    for idx, chunk in enumerate(raw_chunks):
        chunk.chunk_index = idx

    logger.info("parse_jupyter: %d chunks from %s", len(raw_chunks), file_path)
    return raw_chunks
