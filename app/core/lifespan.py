# app/core/lifespan.py

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.runtime import Runtime
from app.infra.metrics import setup_tracing
from app.models import Base

logger = logging.getLogger("app.lifespan")


def _log_task_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("background_task_failed", extra={"task": task.get_name()}, exc_info=task.exception())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.SERVICE_NAME)
    runtime = await Runtime.create(settings)
    if settings.AUTO_CREATE_SCHEMA and not settings.is_production:
        async with runtime.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    state = app.state
    state.runtime, state.session_factory, state.cache, state.tmdb = (
        runtime,
        runtime.session_factory,
        runtime.cache,
        runtime.tmdb,
    )
    state.geo, state.recommender = runtime.geo, runtime.recommender
    setup_tracing(app, runtime.engine, settings.OTEL_EXPORTER_OTLP_ENDPOINT, settings.SERVICE_NAME)

    tasks = [asyncio.create_task(runtime.store.run(), name="model-poller")]
    if settings.RUN_WORKERS_IN_PROCESS:
        from app.workers.refresh import RefreshWorker

        tasks.append(asyncio.create_task(RefreshWorker(runtime).run_forever(), name="refresh-worker"))
    for task in tasks:
        task.add_done_callback(_log_task_failure)
    logger.info("startup_complete", extra={"env": settings.ENV})
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await runtime.close()
        logger.info("shutdown_complete")
