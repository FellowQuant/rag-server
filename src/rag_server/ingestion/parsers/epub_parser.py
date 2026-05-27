"""EPUB parser.

Reads the EPUB spine, converts each XHTML/HTML item with Docling's HTML
backend, and emits the same ParsedChunk model used by PDF ingestion.
"""

from __future__ import annotations

import logging
import posixpath
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.document_converter import DocumentConverter

from rag_server.ingestion.chunker import ParsedChunk, ParsedChunkBatch
from rag_server.ingestion.parsers.docling_chunks import chunks_from_docling_document

logger = logging.getLogger(__name__)

_CONTAINER_PATH = "META-INF/container.xml"
_SUPPORTED_SPINE_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
_SUPPORTED_SPINE_SUFFIXES = {".html", ".htm", ".xhtml"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_member_path(member: str) -> str:
    member = unquote(member).replace("\\", "/")
    normalized = posixpath.normpath(member)
    if (
        normalized in {"", "."}
        or normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in normalized
    ):
        raise ValueError(f"Unsafe EPUB path: {member!r}")
    return normalized


def _resolve_member_path(base_dir: str, href: str) -> str:
    href = href.split("#", 1)[0]
    return _safe_member_path(posixpath.join(base_dir, href))


def _parse_xml(data: bytes, label: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(f"Malformed EPUB XML in {label}") from exc


def _find_rootfile_path(container_root: ElementTree.Element) -> str:
    for element in container_root.iter():
        if _local_name(element.tag) == "rootfile":
            full_path = element.attrib.get("full-path")
            if full_path:
                return _safe_member_path(full_path)
    raise ValueError("EPUB container.xml does not declare a rootfile")


def _read_member(zf: zipfile.ZipFile, member: str) -> bytes:
    try:
        return zf.read(member)
    except KeyError as exc:
        raise ValueError(f"EPUB is missing required member: {member}") from exc


def _spine_members(opf_root: ElementTree.Element, opf_path: str) -> list[str]:
    opf_dir = posixpath.dirname(opf_path)
    manifest: dict[str, tuple[str, str]] = {}
    spine_ids: list[str] = []

    for element in opf_root.iter():
        name = _local_name(element.tag)
        if name == "item":
            item_id = element.attrib.get("id")
            href = element.attrib.get("href")
            media_type = element.attrib.get("media-type", "")
            if item_id and href:
                manifest[item_id] = (
                    _resolve_member_path(opf_dir, href),
                    media_type,
                )
        elif name == "itemref":
            idref = element.attrib.get("idref")
            if idref:
                spine_ids.append(idref)

    if not spine_ids:
        raise ValueError("EPUB OPF does not contain a spine")

    members: list[str] = []
    for idref in spine_ids:
        item = manifest.get(idref)
        if item is None:
            members.append("")
            continue

        member, media_type = item
        suffix = Path(member).suffix.lower()
        if (
            media_type in _SUPPORTED_SPINE_MEDIA_TYPES
            or suffix in _SUPPORTED_SPINE_SUFFIXES
        ):
            members.append(member)

    if not members:
        raise ValueError("EPUB spine does not contain supported HTML content")
    return members


def _teardown_conversion_result(result) -> None:
    """Release Docling result references after each spine item is chunked."""
    try:
        result.document = None
        if hasattr(result, "errors"):
            result.errors.clear()
        if hasattr(result, "timings"):
            result.timings.clear()
    except Exception as exc:
        logger.debug("EPUB conversion cleanup skipped: %s", exc)


def iter_epub_batches(file_path: str | Path):
    """Yield parsed EPUB content one spine item at a time.

    EPUB files are zip archives of HTML/XHTML chapters. Processing each spine
    item independently bounds memory use and lets the ingestion pipeline persist
    and embed a chapter before loading the next one.
    """
    path = Path(file_path)
    emitted_chunks = False

    try:
        with zipfile.ZipFile(path) as zf, tempfile.TemporaryDirectory() as tmp:
            names = set(zf.namelist())
            container_root = _parse_xml(
                _read_member(zf, _CONTAINER_PATH),
                _CONTAINER_PATH,
            )
            opf_path = _find_rootfile_path(container_root)
            opf_root = _parse_xml(_read_member(zf, opf_path), opf_path)
            spine_members = _spine_members(opf_root, opf_path)
            tmp_dir = Path(tmp)
            converter = DocumentConverter(allowed_formats=[InputFormat.HTML])

            for idx, member in enumerate(spine_members):
                if not member or member not in names:
                    logger.warning(
                        "EPUB spine item missing: %s", member or "<unresolved>"
                    )
                    yield ParsedChunkBatch(chunks=[], is_partial=True)
                    continue

                result = None
                try:
                    suffix = Path(member).suffix or ".xhtml"
                    chapter_path = tmp_dir / f"spine_{idx:04d}{suffix}"
                    chapter_path.write_bytes(zf.read(member))
                    result = converter.convert(str(chapter_path), raises_on_error=False)
                    if result.status == ConversionStatus.FAILURE:
                        logger.warning("Docling HTML conversion failed for %s", member)
                        yield ParsedChunkBatch(chunks=[], is_partial=True)
                        continue

                    chunks = chunks_from_docling_document(
                        result.document,
                        include_title_as_heading=True,
                        preserve_page_numbers=False,
                    )
                    emitted_chunks = emitted_chunks or bool(chunks)
                    yield ParsedChunkBatch(
                        chunks=chunks,
                        is_partial=result.status == ConversionStatus.PARTIAL_SUCCESS,
                    )
                except Exception:
                    logger.exception("Failed to parse EPUB spine item %s", member)
                    yield ParsedChunkBatch(chunks=[], is_partial=True)
                    continue
                finally:
                    if result is not None:
                        _teardown_conversion_result(result)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid EPUB archive: {path}") from exc

    if not emitted_chunks:
        raise ValueError("EPUB produced no parseable chunks")


def parse_epub(file_path: str | Path) -> tuple[list[ParsedChunk], bool]:
    """Parse an EPUB file into typed ParsedChunk objects.

    EPUB has no stable page model, so page_number remains None for all chunks.
    Missing or failed spine items mark the document partial if at least one
    supported spine item is parsed successfully.
    """
    parsed_chunks: list[ParsedChunk] = []
    is_partial = False

    for batch in iter_epub_batches(file_path):
        parsed_chunks.extend(batch.chunks)
        is_partial = is_partial or batch.is_partial

    for idx, chunk in enumerate(parsed_chunks):
        chunk.chunk_index = idx

    logger.info(
        "parse_epub: %d chunks from %s (partial=%s)",
        len(parsed_chunks),
        file_path,
        is_partial,
    )
    return parsed_chunks, is_partial
