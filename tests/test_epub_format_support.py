from rag_server.api.documents import ALLOWED_EXTENSIONS
from rag_server.ingestion.chunker import ParsedChunk
from rag_server.worker import pipeline


def test_epub_upload_extension_is_registered() -> None:
    assert ALLOWED_EXTENSIONS[".epub"] == "epub"


def test_worker_dispatch_routes_epub_to_epub_parser(monkeypatch) -> None:
    expected_chunks = [ParsedChunk(chunk_type="text", content="epub text")]

    def fake_parse_epub(file_path: str):
        assert file_path == "/tmp/book.epub"
        return expected_chunks, True

    monkeypatch.setattr(
        "rag_server.ingestion.parsers.epub_parser.parse_epub",
        fake_parse_epub,
    )

    chunks, is_partial = pipeline._dispatch_parser("epub", "/tmp/book.epub")

    assert chunks == expected_chunks
    assert is_partial is True
