"""Structured JSON logging to stdout, one object per line.

Every record carries the service name, version and the OpenTelemetry trace context that was
active when it was created, so a request can be followed across services by its trace id.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

# Attributes present on every LogRecord; anything else was passed via `extra=` and is emitted.
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}
_LEVEL_NAMES = {"WARNING": "WARN", "CRITICAL": "FATAL"}
_MAX_STACK_LINES = 12


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, version_getter: Any = None) -> None:
        super().__init__()
        self._service = service
        self._version_getter = version_getter

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": _LEVEL_NAMES.get(record.levelname, record.levelname),
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if self._version_getter is not None:
            payload["version"] = self._version_getter()

        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            payload["error_type"] = type(exc).__name__
            payload["error_message"] = str(exc)
            lines = "".join(traceback.format_exception(exc)).rstrip().splitlines()
            if len(lines) > _MAX_STACK_LINES:
                lines = [*lines[:2], "  ...", *lines[-(_MAX_STACK_LINES - 3) :]]
            payload["stack_trace"] = "\n".join(lines)

        return json.dumps(payload, default=str, separators=(",", ":"))


def _stamp_trace_context(
    factory: Callable[..., logging.LogRecord],
) -> Callable[..., logging.LogRecord]:
    """Record the active trace context when a record is created, not when it is formatted."""

    def create(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = factory(*args, **kwargs)
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            record.trace_id = format(span_context.trace_id, "032x")
            record.span_id = format(span_context.span_id, "016x")
        return record

    create.stamps_trace_context = True  # type: ignore[attr-defined]
    return create


def configure_logging(service: str, version_getter: Any = None, level: str = "INFO") -> None:
    """Route all logging (including uvicorn's) through the JSON formatter on stdout."""
    factory = logging.getLogRecordFactory()
    if not getattr(factory, "stamps_trace_context", False):
        logging.setLogRecordFactory(_stamp_trace_context(factory))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service, version_getter))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers[:] = []
        logger.propagate = True
    # Access logs are emitted by the telemetry middleware with richer fields.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
