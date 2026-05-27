from __future__ import annotations

import asyncio
import hashlib

import pytest
from fastapi import HTTPException

from rag_server.api.documents import _stream_upload_to_temp


class FakeUpload:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_stream_upload_to_temp_hashes_and_writes_in_chunks(tmp_path) -> None:
    payload = b"abcdefghij"
    upload = FakeUpload(payload)

    result = asyncio.run(
        _stream_upload_to_temp(
            upload,
            tmp_path,
            ".pdf",
            max_upload_size=64,
            chunk_size=4,
        )
    )

    assert result.file_size == len(payload)
    assert result.file_hash == hashlib.sha256(payload).hexdigest()
    assert result.temp_path.read_bytes() == payload
    assert result.temp_path.parent == tmp_path / ".tmp"
    assert result.temp_path.suffix == ".pdf"


def test_stream_upload_to_temp_rejects_oversize_and_removes_temp(tmp_path) -> None:
    upload = FakeUpload(b"0123456789")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            _stream_upload_to_temp(
                upload,
                tmp_path,
                ".epub",
                max_upload_size=5,
                chunk_size=4,
            )
        )

    assert exc_info.value.status_code == 413
    assert list((tmp_path / ".tmp").glob("*")) == []
