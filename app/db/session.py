# app/db/session.py

import ssl
import uuid
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings

_SSL_HOSTS = ("neon.tech", "render.com", "supabase", "aivencloud", "amazonaws", "digitalocean")


def make_engine(settings: Settings) -> AsyncEngine:
    url = settings.DATABASE_URL.get_secret_value()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix) :]
    wants_ssl = "sslmode=require" in url or "sslmode=verify-full" in url
    url = url.split("?", 1)[0]
    args: dict = {"command_timeout": settings.DB_COMMAND_TIMEOUT}
    if wants_ssl or settings.is_production or any(host in url for host in _SSL_HOSTS):
        args["ssl"] = ssl.create_default_context()
    if "-pooler" in url or "pgbouncer" in url:
        args.update(
            statement_cache_size=0,
            prepared_statement_cache_size=0,
            prepared_statement_name_func=lambda: f"__asyncpg_{uuid.uuid4()}__",
        )
    return create_async_engine(
        url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
        connect_args=args,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
