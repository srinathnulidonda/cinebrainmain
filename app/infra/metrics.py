# app/infra/metrics.py

import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.metrics")

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_INFLIGHT = Gauge("http_requests_in_flight", "In-flight HTTP requests", multiprocess_mode="livesum")
UPSTREAM_REQUESTS = Counter("upstream_requests_total", "Upstream calls", ["upstream", "outcome"])
UPSTREAM_LATENCY = Histogram("upstream_request_duration_seconds", "Upstream latency", ["upstream"])
BREAKER_STATE = Gauge("circuit_breaker_state", "0 closed, 1 half-open, 2 open", ["name"], multiprocess_mode="max")
CACHE_OPS = Counter("cache_operations_total", "Cache operations", ["op", "result"])
RATE_LIMITED = Counter("rate_limited_requests_total", "Requests rejected by rate limiting", ["bucket"])
MODEL_AGE = Gauge("reco_model_age_seconds", "Age of the loaded recommender model", multiprocess_mode="max")
DB_POOL_IN_USE = Gauge("db_pool_connections_in_use", "Checked-out DB connections", multiprocess_mode="livesum")


class MetricsMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500
        HTTP_INFLIGHT.inc()

        async def wrapped(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            HTTP_INFLIGHT.dec()
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            HTTP_REQUESTS.labels(scope["method"], route, str(status)).inc()
            HTTP_LATENCY.labels(scope["method"], route).observe(time.perf_counter() - started)


def render_metrics() -> tuple[bytes, str]:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


def instrument_pool(engine: Any) -> None:
    DB_POOL_IN_USE.set_function(lambda: engine.sync_engine.pool.checkedout())


def setup_tracing(app: Any, engine: Any, endpoint: str, service: str) -> bool:
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("otel_packages_missing")
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics")
    HTTPXClientInstrumentor().instrument()
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    return True


AsyncCall = Callable[[], Awaitable[Any]]
