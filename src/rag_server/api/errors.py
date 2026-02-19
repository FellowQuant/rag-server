"""RFC 7807 Problem Details exception handlers for the RAG Server API.

Replaces FastAPI's default error responses (plain {detail: ...}) with the
standardized Problem Details shape: {type, title, status, detail}.
"""
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_STATUS_TITLES: dict[int, str] = {
    400: "Bad Request",
    404: "Not Found",
    409: "Conflict",
    413: "Request Entity Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _problem(status: int, detail: str) -> JSONResponse:
    """Return an RFC 7807 Problem Details JSON response."""
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": _STATUS_TITLES.get(status, "Error"),
            "status": status,
            "detail": detail,
        },
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle Starlette/FastAPI HTTPException as RFC 7807 Problem Details."""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return _problem(exc.status_code, detail)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic RequestValidationError as RFC 7807 Problem Details (422)."""
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in exc.errors()
    )
    return _problem(422, detail)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions as RFC 7807 Problem Details (500)."""
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
    return _problem(500, str(exc))


def register_exception_handlers(app: FastAPI) -> None:
    """Register all RFC 7807 exception handlers on the FastAPI application."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
