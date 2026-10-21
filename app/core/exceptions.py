"""Shared HTTP exception handlers."""

import logging
from datetime import UTC, datetime
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    def error_response(request, status, message, headers=None):
        return JSONResponse(
            {
                "statusCode": status,
                "path": request.url.path,
                "timestamp": datetime.now(UTC).isoformat(),
                "message": message,
                "error": HTTPStatus(status).phrase,
            },
            status_code=status,
            headers=headers,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(
            request, 400, [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error(
            "Unhandled error request_id=%s",
            getattr(request.state, "request_id", "unknown"),
            exc_info=exc,
        )
        return error_response(request, 500, "Internal server error")
