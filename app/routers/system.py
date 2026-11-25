# app/routers/system.py

import asyncio

from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import schemas as S
from app.core.config import get_settings
from app.core.errors import NotFoundError, UnauthorizedError
from app.core.security import safe_equals
from app.infra.metrics import render_metrics

router = APIRouter(tags=["system"])


@router.get("/health", response_model=S.HealthOut)
async def health():
    return S.HealthOut(status="ok")


@router.get("/ready", response_model=S.ReadinessOut)
async def ready(request: Request, response: Response):
    state = request.app.state
    checks: dict[str, str] = {}
    try:
        async with asyncio.timeout(2.0):
            async with state.session_factory() as session:
                await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        checks["database"] = f"error:{type(exc).__name__}"
    checks["redis"] = "ok" if await state.cache.ping() else "degraded"
    checks["tmdb_circuit"] = state.tmdb.http.breaker.state
    checks["recommender_model"] = "loaded" if state.recommender.ready else "absent"
    healthy = checks["database"] == "ok"
    response.status_code = 200 if healthy else 503
    return S.ReadinessOut(status="ready" if healthy else "not_ready", checks=checks)


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    settings = get_settings()
    configured = settings.METRICS_API_KEY.get_secret_value()
    if not configured:
        if settings.is_production:
            raise NotFoundError("Not found")
    elif not safe_equals(request.headers.get("X-API-Key", ""), configured):
        raise UnauthorizedError("Invalid API key")
    body, content_type = render_metrics()
    return Response(body, media_type=content_type)
