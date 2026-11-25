# app/__init__.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.lifespan import lifespan
from app.infra.metrics import MetricsMiddleware
from app.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.routers import api_router
from app.routers.system import router as system_router


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.docs_enabled
    app = FastAPI(
        title="CineBrain API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    register_error_handlers(app)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=settings.CORS_ALLOW_HEADERS,
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
        max_age=600,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware, settings=settings)
    if settings.ALLOWED_HOSTS != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
    app.include_router(api_router, prefix=settings.API_PREFIX)
    app.include_router(system_router)
    return app
