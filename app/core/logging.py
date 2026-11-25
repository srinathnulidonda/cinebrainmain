# app/core/logging.py

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str, service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
            static_fields={"service": service},
        )
    )
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error", "gunicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    for name in ("uvicorn.access", "gunicorn.access"):
        logging.getLogger(name).disabled = True
    for name in ("httpx", "httpcore", "sqlalchemy.engine", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
