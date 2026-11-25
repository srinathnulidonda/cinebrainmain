# app/infra/cache.py

import asyncio
import hashlib
import json
import logging
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infra.http import CircuitBreaker
from app.infra.metrics import CACHE_OPS

logger = logging.getLogger("app.cache")

_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]) * 2) end
local previous = tonumber(redis.call('GET', KEYS[2]) or '0')
return {current, previous}
"""


def cache_key(*parts: Any) -> str:
    key = ":".join("-" if p in (None, "") else str(p) for p in parts)
    return key if len(key) <= 180 else f"{parts[0]}:h:{hashlib.sha256(key.encode()).hexdigest()[:32]}"


class LocalTTLCache:
    def __init__(self, maxsize: int = 4096):
        self.maxsize = maxsize
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        if item[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return item[1]

    def set(self, key: str, value: Any, ttl: float) -> None:
        self._data[key] = (time.monotonic() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)


class Cache:
    def __init__(self, client: Redis | None, namespace: str = "cb"):
        self.client = client
        self.namespace = namespace
        self.breaker = CircuitBreaker("redis", failure_threshold=3, recovery_seconds=10.0)
        self._window = client.register_script(_WINDOW_SCRIPT) if client else None

    @classmethod
    async def connect(cls, url: str, namespace: str = "cb", socket_timeout: float = 1.5) -> "Cache":
        client = Redis.from_url(
            url,
            decode_responses=False,
            max_connections=50,
            socket_connect_timeout=1.5,
            socket_timeout=socket_timeout,
            health_check_interval=30,
            retry_on_timeout=False,
        )
        cache = cls(client, namespace)
        if not await cache.ping():
            logger.warning("redis_unavailable_at_startup")
        return cache

    def _k(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def _run(self, op: str, call: Callable[[], Awaitable[Any]], default: Any = None) -> Any:
        if self.client is None or not self.breaker.allow():
            CACHE_OPS.labels(op, "skipped").inc()
            return default
        try:
            result = await call()
        except (TimeoutError, RedisError, OSError):
            self.breaker.record_failure()
            CACHE_OPS.labels(op, "error").inc()
            return default
        self.breaker.record_success()
        return result

    async def ping(self) -> bool:
        if self.client is None:
            return False
        try:
            return bool(await self.client.ping())
        except (TimeoutError, RedisError, OSError):
            return False

    @property
    def available(self) -> bool:
        return self.client is not None and self.breaker.state != "open"

    async def get_bytes(self, key: str) -> bytes | None:
        value = await self._run("get", lambda: self.client.get(self._k(key)))
        CACHE_OPS.labels("get", "hit" if value is not None else "miss").inc()
        return value

    async def set_bytes(self, key: str, value: bytes, ttl: int) -> None:
        await self._run("set", lambda: self.client.set(self._k(key), value, ex=ttl))

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get_bytes(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        await self.set_bytes(key, json.dumps(value, default=str, separators=(",", ":")).encode(), ttl)

    async def delete(self, key: str) -> None:
        await self._run("delete", lambda: self.client.delete(self._k(key)))

    async def try_lock(self, name: str, ttl: int) -> bool:
        if not self.available:
            return True
        return bool(
            await self._run("lock", lambda: self.client.set(self._k(f"lock:{name}"), b"1", ex=ttl, nx=True), None)
        )

    async def single_flight(
        self,
        key: str,
        ttl: int,
        builder: Callable[[], Awaitable[Any]],
        wait: float = 6.0,
        cacheable: Callable[[Any], bool] = lambda value: value is not None,
    ) -> Any:
        cached = await self.get_json(key)
        if cached is not None:
            return cached
        if not self.available:
            return await builder()
        lock = f"lock:{key}"
        acquired = await self._run("lock", lambda: self.client.set(self._k(lock), b"1", ex=20, nx=True), None)
        if acquired:
            try:
                value = await builder()
                if cacheable(value):
                    await self.set_json(key, value, ttl)
                return value
            finally:
                await self.delete(lock)
        deadline = time.monotonic() + wait
        delay = 0.05
        while time.monotonic() < deadline:
            await asyncio.sleep(delay)
            delay = min(delay * 1.6, 0.5)
            cached = await self.get_json(key)
            if cached is not None:
                return cached
        return await builder()

    async def window_hit(self, identity: str, limit: int, window: int = 60) -> tuple[bool, int, int] | None:
        if self._window is None:
            return None
        now = time.time()
        slot = int(now // window)
        keys = [self._k(f"rl:{identity}:{slot}"), self._k(f"rl:{identity}:{slot - 1}")]
        result = await self._run("ratelimit", lambda: self._window(keys=keys, args=[window]))
        if result is None:
            return None
        current, previous = int(result[0]), int(result[1])
        elapsed = (now % window) / window
        estimated = current + previous * (1.0 - elapsed)
        return estimated <= limit, max(0, int(limit - estimated)), max(1, math.ceil(window - (now % window)))

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
