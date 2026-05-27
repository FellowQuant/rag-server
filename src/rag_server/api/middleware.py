"""HTTP middleware for the RAG Server API.

Two middleware classes:
- LoggingMiddleware: logs method, path, status code, and duration for every request
- UploadSizeLimitMiddleware: rejects uploads exceeding the configured size limit via Content-Length check
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log HTTP request method, path, status code, and duration in ms at INFO level.

    CRITICAL: never consume response body — SSE streaming must pass through unmodified.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class UploadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured max upload size.

    Returns RFC 7807 Problem Details JSON with status 413 if Content-Length is
    present, parseable as int, and exceeds the limit.  If Content-Length is
    absent or unparseable (chunked transfer), the request passes through.
    """

    def __init__(self, app, max_upload_size: int) -> None:
        super().__init__(app)
        self._max_size = max_upload_size

    async def dispatch(self, request: Request, call_next):
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                size = int(content_length_header)
            except ValueError:
                size = None

            if size is not None and size > self._max_size:
                return JSONResponse(
                    status_code=413,
                    content={
                        "type": "about:blank",
                        "title": "Request Entity Too Large",
                        "status": 413,
                        "detail": (
                            f"Upload size {size} bytes exceeds limit of {self._max_size} bytes. "
                            "Set MAX_UPLOAD_SIZE env var to increase."
                        ),
                    },
                )

        return await call_next(request)
