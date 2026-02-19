"""pylatexenc-based LaTeX (.tex) parser.

Produces a list[ParsedChunk] from a .tex source file. Math environments and
inline math are extracted as formula chunks; all other content becomes text
chunks. Preserves LaTeX markup as-is (no pdflatex compilation).

INGEST-02: LaTeX ingestion preserving markup, extracting math environments.
INGEST-05: Formula chunks enriched with surrounding paragraph context.

Uses pylatexenc 2.10 (stable). Do NOT upgrade to 3.x alpha (API changes).
"""
from __future__ import annotations

import logging
from pathlib import Path

from pylatexenc.latexwalker import (
    LatexEnvironmentNode,
    LatexMathNode,
    LatexWalker,
)

from rag_server.ingestion.chunker import (
    ParsedChunk,
    enrich_formula_content,
    split_text_tokens,
)

logger = logging.getLogger(__name__)

# Standard AMS math environments that should become formula chunks.
MATH_ENVS: frozenset[str] = frozenset({
    "equation", "equation*",
    "align", "align*",
    "gather", "gather*",
    "multline", "multline*",
    "eqnarray", "eqnarray*",
    "split",
    "cases",
    "array",
})


def parse_latex(file_path: str | Path) -> list[ParsedChunk]:
    """Parse a .tex file into typed ParsedChunk objects.

    Walks the top-level node list from pylatexenc LatexWalker. Inline math
    ($...$, $$...$$) becomes LatexMathNode; named environments become
    LatexEnvironmentNode. Non-math content accumulates in last_text and is
    flushed as text chunks between math regions.

    Args:
        file_path: Absolute path to the .tex file.

    Returns:
        List of ParsedChunk with chunk_index populated sequentially from 0.
    """
    path = Path(file_path)
    try:
        latex_content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.error("Cannot read LaTeX file %s: %s", file_path, exc)
        return []

    # tolerant_parsing=True skips malformed regions instead of raising.
    w = LatexWalker(latex_content, tolerant_parsing=True)
    try:
        nodelist, _, _ = w.get_latex_nodes(pos=0)
    except Exception as exc:
        logger.error("LatexWalker failed on %s: %s", file_path, exc)
        return []

    raw_chunks: list[ParsedChunk] = []
    last_text: str = ""

    def _flush_text() -> None:
        """Emit accumulated text as split text chunks."""
        nonlocal last_text
        stripped = last_text.strip()
        if stripped:
            for seg in split_text_tokens(stripped):
                raw_chunks.append(
                    ParsedChunk(
                        chunk_type="text",
                        content=seg,
                        display_content=None,
                    )
                )
        last_text = ""

    def _emit_formula(formula_latex: str) -> None:
        """Emit a formula chunk with preceding paragraph context."""
        preceding = last_text.strip()
        embed_content = enrich_formula_content(formula_latex, preceding)
        raw_chunks.append(
            ParsedChunk(
                chunk_type="formula",
                content=embed_content,
                display_content=formula_latex,
            )
        )

    for node in nodelist:
        if node is None:
            continue

        if isinstance(node, LatexMathNode):
            # Inline $...$ or display $$...$$ math.
            formula_latex = node.latex_verbatim()
            _flush_text()
            _emit_formula(formula_latex)

        elif isinstance(node, LatexEnvironmentNode):
            env_name = node.environmentname
            if env_name in MATH_ENVS:
                formula_latex = node.latex_verbatim()
                _flush_text()
                _emit_formula(formula_latex)
            else:
                # Non-math environments (itemize, figure, etc.) — keep as text.
                last_text += node.latex_verbatim()

        else:
            # Ordinary text and command nodes — accumulate.
            chars = getattr(node, "chars", None)
            last_text += chars if chars is not None else node.latex_verbatim()

    # Flush any trailing text after the last math region.
    _flush_text()

    for idx, chunk in enumerate(raw_chunks):
        chunk.chunk_index = idx

    logger.info("parse_latex: %d chunks from %s", len(raw_chunks), file_path)
    return raw_chunks
