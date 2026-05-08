import contextvars
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response

from app.core.config import settings


trace_id_var = contextvars.ContextVar("trace_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": settings.service_name,
            "trace_id": getattr(record, "trace_id", trace_id_var.get()),
            "message": record.getMessage(),
        }
        if hasattr(record, "extra"):
            payload.update(record.extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=settings.log_level.upper(), handlers=[handler], force=True)


def log_event(message: str, **extra: Any) -> None:
    logging.getLogger(settings.service_name).info(message, extra={"extra": extra})


async def tracing_middleware(request: Request, call_next: Callable) -> Response:
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    token = trace_id_var.set(trace_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logging.getLogger(settings.service_name).exception(
            "request.failed",
            extra={"extra": {"method": request.method, "path": request.url.path}},
        )
        trace_id_var.reset(token)
        raise

    response.headers["x-trace-id"] = trace_id
    log_event(
        "request.completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    trace_id_var.reset(token)
    return response
