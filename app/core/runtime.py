# app/core/runtime.py

from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.infra.cache import Cache, LocalTTLCache
from app.infra.http import CircuitBreaker, ResilientClient
from app.infra.metrics import instrument_pool
from app.infra.tmdb import TMDBClient
from app.recommender.engine import Recommender
from app.recommender.store import ModelStore
from app.services.geo import GeoService


@dataclass(slots=True)
class Runtime:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    cache: Cache
    bulk_cache: Cache
    tmdb: TMDBClient
    geo: GeoService
    store: ModelStore
    recommender: Recommender
    http_clients: list[httpx.AsyncClient] = field(default_factory=list)

    @classmethod
    async def create(cls, settings: Settings) -> "Runtime":
        engine = make_engine(settings)
        instrument_pool(engine)
        redis_url = settings.REDIS_URL.get_secret_value()
        cache = await Cache.connect(redis_url)
        bulk_cache = await Cache.connect(redis_url, socket_timeout=30.0)
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
        tmdb_http = httpx.AsyncClient(
            base_url=settings.TMDB_BASE_URL,
            limits=limits,
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(
                connect=settings.HTTP_CONNECT_TIMEOUT,
                read=settings.HTTP_READ_TIMEOUT,
                write=settings.HTTP_READ_TIMEOUT,
                pool=settings.HTTP_CONNECT_TIMEOUT,
            ),
        )
        geo_http = httpx.AsyncClient(base_url=settings.GEO_API_URL, limits=limits, timeout=httpx.Timeout(2.0))
        tmdb = TMDBClient(
            ResilientClient(
                tmdb_http,
                "tmdb",
                CircuitBreaker("tmdb", settings.CB_FAILURE_THRESHOLD, settings.CB_RECOVERY_SECONDS),
                settings.HTTP_MAX_RETRIES,
                settings.HTTP_BACKOFF_BASE,
                settings.HTTP_BACKOFF_CAP,
            ),
            settings.TMDB_API_KEY.get_secret_value(),
        )
        geo = GeoService(
            ResilientClient(geo_http, "geo", CircuitBreaker("geo", 3, 60.0), retries=0),
            cache,
            LocalTTLCache(),
            settings.TRUST_PROXY_HEADERS,
        )
        store = ModelStore(cache, bulk_cache, settings.MODEL_POLL_SECONDS)
        return cls(
            settings=settings,
            engine=engine,
            session_factory=make_session_factory(engine),
            cache=cache,
            bulk_cache=bulk_cache,
            tmdb=tmdb,
            geo=geo,
            store=store,
            recommender=Recommender(store),
            http_clients=[tmdb_http, geo_http],
        )

    async def close(self) -> None:
        for client in self.http_clients:
            await client.aclose()
        await self.cache.close()
        await self.bulk_cache.close()
        await self.engine.dispose()
