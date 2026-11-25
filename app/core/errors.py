# app/core/errors.py

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger("app.errors")

HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "Internal server error"

    def __init__(self, message: str | None = None, *, details: Any = None, headers: dict[str, str] | None = None):
        self.message = message or self.message
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code, code, message = 400, "BAD_REQUEST", "Bad request"


class UnauthorizedError(AppError):
    status_code, code, message = 401, "UNAUTHORIZED", "Not authenticated"


class NotFoundError(AppError):
    status_code, code, message = 404, "NOT_FOUND", "Resource not found"


class RateLimitedError(AppError):
    status_code, code, message = 429, "RATE_LIMITED", "Too many requests"


class UpstreamError(AppError):
    status_code, code, message = 502, "UPSTREAM_ERROR", "Upstream service error"


class UpstreamNotFound(UpstreamError):
    status_code, code, message = 404, "NOT_FOUND", "Resource not found"


class ServiceUnavailableError(AppError):
    status_code, code, message = 503, "SERVICE_UNAVAILABLE", "Service temporarily unavailable"


class CircuitOpenError(ServiceUnavailableError):
    code = "UPSTREAM_UNAVAILABLE"


def error_payload(status: int, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "success": False,
        "error": {"code": code, "message": message, "details": details},
        "meta": {"request_id": request_id_var.get(), "pagination": None},
    }


def error_response(
    status: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(error_payload(status, code, message, details), status_code=status, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("app_error", extra={"code": exc.code, "error": exc.message})
        return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return error_response(422, "VALIDATION_ERROR", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(SQLAlchemyError)
    async def handle_database(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("database_error", exc_info=exc)
        if isinstance(exc, DBAPIError) and exc.connection_invalidated:
            return error_response(503, "SERVICE_UNAVAILABLE", "Service temporarily unavailable")
        return error_response(500, "INTERNAL_ERROR", "Internal server error")

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "Internal server error")
