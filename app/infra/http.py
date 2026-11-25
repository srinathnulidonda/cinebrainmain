# app/infra/http.py

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from app.core.errors import CircuitOpenError, UpstreamError, UpstreamNotFound
from app.infra.metrics import BREAKER_STATE, UPSTREAM_LATENCY, UPSTREAM_REQUESTS

logger = logging.getLogger("app.http")
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_STATE_VALUE = {"closed": 0, "half_open": 1, "open": 2}


class CircuitBreaker:
    def __init__(
        self, name: str, failure_threshold: int = 5, recovery_seconds: float = 20.0, half_open_probes: int = 1
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.half_open_probes = half_open_probes
        self.state = "closed"
        self._failures = 0
        self._opened_at = 0.0
        self._probes = 0
        BREAKER_STATE.labels(name).set(0)

    def _set(self, state: str) -> None:
        if state != self.state:
            logger.warning("circuit_state_change", extra={"breaker": self.name, "from": self.state, "to": state})
        self.state = state
        BREAKER_STATE.labels(self.name).set(_STATE_VALUE[state])

    def allow(self) -> bool:
        if self.state == "open":
            if time.monotonic() - self._opened_at < self.recovery_seconds:
                return False
            self._set("half_open")
            self._probes = 0
        if self.state == "half_open":
            if self._probes >= self.half_open_probes:
                return False
            self._probes += 1
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._set("closed")

    def record_failure(self) -> None:
        self._failures += 1
        if self.state == "half_open" or self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            self._set("open")


class ResilientClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        name: str,
        breaker: CircuitBreaker,
        retries: int = 2,
        backoff_base: float = 0.3,
        backoff_cap: float = 4.0,
    ):
        self.client = client
        self.name = name
        self.breaker = breaker
        self.retries = retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.backoff_cap)
            except ValueError:
                pass
        return random.uniform(0, min(self.backoff_cap, self.backoff_base * 2**attempt))

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.breaker.allow():
            UPSTREAM_REQUESTS.labels(self.name, "circuit_open").inc()
            raise CircuitOpenError()
        last_error = "unknown"
        for attempt in range(self.retries + 1):
            retry_after = None
            started = time.perf_counter()
            try:
                response = await self.client.get(path, params=params)
            except httpx.TransportError as exc:
                last_error = type(exc).__name__
                UPSTREAM_REQUESTS.labels(self.name, "transport_error").inc()
            else:
                UPSTREAM_LATENCY.labels(self.name).observe(time.perf_counter() - started)
                status = response.status_code
                if status < 400:
                    self.breaker.record_success()
                    UPSTREAM_REQUESTS.labels(self.name, "ok").inc()
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise UpstreamError() from exc
                if status in RETRYABLE_STATUS:
                    last_error = f"http_{status}"
                    retry_after = response.headers.get("Retry-After")
                    UPSTREAM_REQUESTS.labels(self.name, "retryable_error").inc()
                else:
                    self.breaker.record_success()
                    UPSTREAM_REQUESTS.labels(self.name, f"client_error_{status}").inc()
                    if status == 404:
                        raise UpstreamNotFound()
                    raise UpstreamError()
            if attempt < self.retries:
                await asyncio.sleep(self._delay(attempt, retry_after))
        self.breaker.record_failure()
        logger.error("upstream_failed", extra={"upstream": self.name, "reason": last_error})
        raise UpstreamError()
