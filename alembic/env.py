# alembic/env.py

import asyncio
import ssl
from logging.config import fileConfig
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.models import Base


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: SecretStr
    MIGRATION_DATABASE_URL: SecretStr | None = None


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def ssl_argument(mode: str | None) -> ssl.SSLContext | None:
    if mode in (None, "disable", "allow", "prefer"):
        return None
    ctx = ssl.create_default_context()
    if mode == "require":
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    else:
        ctx.check_hostname, ctx.verify_mode = mode == "verify-full", ssl.CERT_REQUIRED
    return ctx


def database_target() -> tuple[str, dict[str, Any]]:
    settings = MigrationSettings()
    explicit = settings.MIGRATION_DATABASE_URL
    parts = urlsplit((explicit or settings.DATABASE_URL).get_secret_value())
    netloc = parts.netloc
    if explicit is None:
        userinfo, at, hostport = netloc.rpartition("@")
        netloc = f"{userinfo}{at}{hostport.replace('-pooler', '', 1)}"
    query = dict(parse_qsl(parts.query))
    mode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    args: dict[str, Any] = {"statement_cache_size": 0}
    if (context_ := ssl_argument(mode)) is not None:
        args["ssl"] = context_
    return urlunsplit(("postgresql+asyncpg", netloc, parts.path, urlencode(query), parts.fragment)), args


def run_migrations_offline() -> None:
    context.configure(
        url=database_target()[0],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def apply(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, args = database_target()
    engine = create_async_engine(url, poolclass=pool.NullPool, connect_args=args)
    async with engine.connect() as connection:
        await connection.run_sync(apply)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
