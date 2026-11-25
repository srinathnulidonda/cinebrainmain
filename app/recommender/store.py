# app/recommender/store.py

import asyncio
import logging
import time

from app.infra.cache import Cache
from app.infra.metrics import MODEL_AGE
from app.recommender.model import RecommenderModel

logger = logging.getLogger("app.reco.store")
META_KEY = "reco:model:meta"
MODEL_TTL = 6 * 3600
TRENDING_TTL = 2 * 3600


class ModelStore:
    def __init__(self, cache: Cache, bulk_cache: Cache, poll_seconds: int = 60):
        self.cache = cache
        self.bulk_cache = bulk_cache
        self.poll_seconds = poll_seconds
        self.model: RecommenderModel | None = None

    async def publish_model(self, model: RecommenderModel) -> None:
        blob = await asyncio.to_thread(model.to_bytes)
        await self.bulk_cache.set_bytes(f"reco:model:{model.version}", blob, MODEL_TTL)
        await self.cache.set_json(
            META_KEY, {"version": model.version, "built_at": model.built_at, "items": len(model.table)}, MODEL_TTL
        )

    async def publish_trending(self, lists: dict[str, list[list[float]]]) -> None:
        for key, ranked in lists.items():
            await self.cache.set_json(f"reco:trending:{key}", ranked, TRENDING_TTL)

    async def trending(self, scope: str, kind: str) -> list[list[float]] | None:
        return await self.cache.get_json(f"reco:trending:{scope}:{kind}")

    async def refresh(self) -> bool:
        meta = await self.cache.get_json(META_KEY)
        if not meta or (self.model and self.model.version == meta["version"]):
            if self.model:
                MODEL_AGE.set(time.time() - self.model.built_at)
            return False
        blob = await self.bulk_cache.get_bytes(f"reco:model:{meta['version']}")
        if blob is None:
            return False
        self.model = await asyncio.to_thread(RecommenderModel.from_bytes, blob)
        MODEL_AGE.set(time.time() - self.model.built_at)
        logger.info("model_loaded", extra={"version": self.model.version, "items": len(self.model.table)})
        return True

    async def run(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("model_refresh_failed")
            await asyncio.sleep(self.poll_seconds)
