# app/middleware.py

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import error_response
from app.core.logging import request_id_var
from app.infra.metrics import RATE_LIMITED

logger = logging.getLogger("app.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_DOC_PATHS = {"/docs", "/redoc", "/openapi.json"}
_EXEMPT = {"/health", "/ready", "/metrics"}
_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'"
_DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; img-src 'self' data: fastapi.tiangolo.com"
)
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inbound = Headers(scope=scope).get("x-request-id", "")
        request_id = inbound if _REQUEST_ID.match(inbound) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        started_response = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, started_response
            if message["type"] == "http.response.start":
                started_response = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", _DOCS_CSP if scope["path"] in _DOC_PATHS else _STRICT_CSP)
                if scope.get("scheme") == "https":
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            logger.error("unhandled_exception", exc_info=exc)
            if not started_response:
                await error_response(500, "INTERNAL_ERROR", "Internal server error")(scope, receive, send_wrapper)
        finally:
            if scope["path"] not in _EXEMPT:
                client = scope.get("client")
                logger.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "client": client[0] if client else None,
                    },
                )
            request_id_var.reset(token)


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        prefix = settings.API_PREFIX
        self.search_paths = (f"{prefix}/content/search", f"{prefix}/content/feels-like")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not self.settings.RATE_LIMIT_ENABLED
            or scope["method"] == "OPTIONS"
            or path in _EXEMPT
            or path in _DOC_PATHS
        ):
            await self.app(scope, receive, send)
            return
        search = path.startswith(self.search_paths)
        bucket, limit = (
            ("search", self.settings.RATE_LIMIT_SEARCH_PER_MINUTE)
            if search
            else ("general", self.settings.RATE_LIMIT_GENERAL_PER_MINUTE)
        )
        client = scope.get("client")
        outcome = await scope["app"].state.cache.window_hit(f"{bucket}:{client[0] if client else 'unknown'}", limit)
        if outcome is None:
            await self.app(scope, receive, send)
            return
        allowed, remaining, reset = outcome
        if not allowed:
            RATE_LIMITED.labels(bucket).inc()
            response = error_response(
                429,
                "RATE_LIMITED",
                "Too many requests",
                headers={
                    "Retry-After": str(max(reset, 1)),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
            await response(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-RateLimit-Limit"] = str(limit)
                headers["X-RateLimit-Remaining"] = str(remaining)
                headers["X-RateLimit-Reset"] = str(reset)
            await send(message)

        await self.app(scope, receive, send_wrapper)
