# app/workers/refresh.py

import argparse
import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

import numpy as np

from app.core.config import get_settings
from app.core.constants import (
    CRITICS_MIN_RATING,
    CRITICS_MIN_VOTES,
    FALLBACK_LANGS,
    INDIAN_LANGUAGES,
    NEW_RELEASE_WINDOW_DAYS,
)
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.runtime import Runtime
from app.recommender.items import day_number
from app.recommender.model import RecommenderModel, build_model
from app.recommender.trending import build_trending_lists
from app.repositories.content import ContentRepository
from app.repositories.interactions import InteractionRepository
from app.services.catalog import CatalogService
from app.services.recommendation import HALF_LIFE_DAYS, TYPE_WEIGHTS
from app.utils import today

logger = logging.getLogger("app.worker")
SESSION_CAP = 200
ENGAGEMENT_WINDOW_DAYS = 7


class RefreshWorker:
    def __init__(self, runtime: Runtime):
        self.rt = runtime
        self.model: RecommenderModel | None = None

    async def sync_catalog(self) -> dict[str, int]:
        settings, rt = self.rt.settings, self.rt
        gate = asyncio.Semaphore(settings.SYNC_CONCURRENCY)
        errors = 0

        async def fetch(call) -> list[dict]:
            nonlocal errors
            async with gate:
                try:
                    return (await call).get("results", [])
                except AppError as exc:
                    errors += 1
                    logger.warning("sync_fetch_failed", extra={"error": exc.code})
                    return []

        pages = range(1, settings.SYNC_PAGES_PER_QUERY + 1)
        stages = {
            "trending": (None, lambda: [rt.tmdb.trending("all", w, p) for w in ("day", "week") for p in pages]),
            "movie": (
                "movie",
                lambda: (
                    [rt.tmdb.new_releases("movie", lang, p) for lang in FALLBACK_LANGS for p in pages]
                    + [rt.tmdb.critics_choice(p) for p in pages]
                    + [rt.tmdb.upcoming(1, "IN")]
                    + [rt.tmdb.upcoming_discover(lang) for lang in INDIAN_LANGUAGES]
                ),
            ),
            "tv": ("tv", lambda: [rt.tmdb.new_releases("tv", lang, p) for lang in FALLBACK_LANGS for p in pages]),
        }
        trending_ids: set[int] = set()
        upserted = 0
        for name, (media, make_calls) in stages.items():
            batches = await asyncio.gather(*(fetch(call) for call in make_calls()))
            items = [item for batch in batches for item in batch]
            if not items:
                continue
            async with rt.session_factory() as session:
                contents = await CatalogService(session, rt.tmdb, rt.cache).ingest(items, media)
            upserted += len(contents)
            if name == "trending":
                trending_ids = {c.id for c in contents}
        async with rt.session_factory() as session:
            await ContentRepository(session).refresh_flags(
                trending_ids, today(), NEW_RELEASE_WINDOW_DAYS, CRITICS_MIN_RATING, CRITICS_MIN_VOTES
            )
            await session.commit()
        return {"upserted": upserted, "trending": len(trending_ids), "errors": errors}

    async def build_model(self) -> RecommenderModel | None:
        settings, rt = self.rt.settings, self.rt
        now = datetime.now(UTC)
        since = now - timedelta(days=settings.RECO_INTERACTION_DAYS)
        sessions: dict[str, int] = {}
        used: dict[int, int] = {}
        codes: list[int] = []
        items: list[int] = []
        weights: list[float] = []
        async with rt.session_factory() as session:
            async for partition in InteractionRepository(session).stream_for_model(
                since, settings.RECO_MAX_INTERACTIONS
            ):
                for session_id, content_id, kind, stamp in partition:
                    code = sessions.setdefault(session_id, len(sessions))
                    if used.get(code, 0) >= SESSION_CAP:
                        continue
                    used[code] = used.get(code, 0) + 1
                    age = max((now - stamp).total_seconds() / 86400, 0.0)
                    codes.append(code)
                    items.append(content_id)
                    weights.append(TYPE_WEIGHTS.get(kind, 1.0) * 0.5 ** (age / HALF_LIFE_DAYS))
        async with rt.session_factory() as session:
            rows = await ContentRepository(session).snapshot(settings.RECO_MAX_ITEMS, today())
        if not rows:
            logger.warning("model_build_skipped_empty_catalog")
            return None
        started = time.perf_counter()
        model = await asyncio.to_thread(
            build_model,
            rows,
            np.asarray(codes, dtype=np.int32),
            np.asarray(items, dtype=np.int64),
            np.asarray(weights, dtype=np.float32),
            neighbors=settings.RECO_NEIGHBORS,
            confidence=settings.RECO_CF_CONFIDENCE,
            shrinkage=settings.RECO_CF_SHRINKAGE,
        )
        logger.info(
            "model_built",
            extra={
                "items": len(model.table),
                "interactions": len(items),
                "seconds": round(time.perf_counter() - started, 2),
            },
        )
        await rt.store.publish_model(model)
        self.model = model
        return model

    async def refresh_trending(self) -> int:
        model = self.model
        if model is None:
            return 0
        since = datetime.now(UTC) - timedelta(days=ENGAGEMENT_WINDOW_DAYS)
        async with self.rt.session_factory() as session:
            counts = await InteractionRepository(session).engagement_since(since)
        engagement = np.zeros(len(model.table), dtype=np.float32)
        for content_id, kind, count in counts:
            idx = model.id_to_idx.get(content_id)
            if idx is not None:
                engagement[idx] += TYPE_WEIGHTS.get(kind, 1.0) * count
        lists = await asyncio.to_thread(build_trending_lists, model, engagement, day_number(today()))
        await self.rt.store.publish_trending(lists)
        return len(lists)

    async def run_once(self) -> None:
        logger.info("sync_finished", extra=await self.sync_catalog())
        await self.build_model()
        await self.refresh_trending()

    async def run_forever(self) -> None:
        settings, cache = self.rt.settings, self.rt.cache
        await asyncio.sleep(5)
        due = {"sync": 0.0, "model": 0.0, "trending": 0.0}
        every = {
            "sync": settings.SYNC_INTERVAL_SECONDS,
            "model": settings.MODEL_REFRESH_SECONDS,
            "trending": settings.TRENDING_REFRESH_SECONDS,
        }
        while True:
            now = time.monotonic()
            try:
                if now >= due["sync"]:
                    due["sync"] = now + every["sync"]
                    if await cache.try_lock("sync", every["sync"] - 30):
                        logger.info("sync_finished", extra=await self.sync_catalog())
                if now >= due["model"]:
                    due["model"] = now + every["model"]
                    if await cache.try_lock("model", every["model"] - 30):
                        await self.build_model()
                if now >= due["trending"]:
                    due["trending"] = now + every["trending"]
                    if await cache.try_lock("trending", every["trending"] - 30):
                        await self.refresh_trending()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker_cycle_failed")
            await asyncio.sleep(15)


async def run(once: bool) -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, f"{settings.SERVICE_NAME}-worker")
    runtime = await Runtime.create(settings)
    worker = RefreshWorker(runtime)
    try:
        await (worker.run_once() if once else worker.run_forever())
    finally:
        await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(parser.parse_args().once))


if __name__ == "__main__":
    main()
