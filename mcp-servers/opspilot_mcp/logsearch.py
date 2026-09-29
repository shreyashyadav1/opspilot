"""Log normalization and search.

Services log in two JSON shapes (the Python formatter and Spring Boot's Logstash format).
Both are normalized into `LogEntry`, then searched and summarized: counts by level, the most
frequent message shapes, and the most recent matching records with truncated stack traces.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from typing import Any

from opspilot_mcp.models import LEVEL_ORDER, LogEntry

_KNOWN = {
    "timestamp",
    "@timestamp",
    "@version",
    "level",
    "level_value",
    "message",
    "logger",
    "logger_name",
    "thread_name",
    "service",
    "trace_id",
    "traceId",
    "span_id",
    "spanId",
    "error_type",
    "error_message",
    "stack_trace",
    "version",
}
_FRACTION = re.compile(r"(\.\d{6})\d+")
_PATTERNS = (
    (re.compile(r"\b[0-9a-f]{12,}\b"), "<id>"),
    (re.compile(r"@[0-9a-f]{6,}"), "@<id>"),
    (re.compile(r"\d+(?:\.\d+)?"), "<n>"),
)
MAX_MESSAGE_CHARS = 300
STACK_LINES = 4
TOP_MESSAGES = 6


def parse_line(line: str, service: str) -> LogEntry | None:
    """Parse one JSON log line from either service format; non-JSON lines are skipped."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        raw: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return None
    timestamp = raw.get("timestamp") or raw.get("@timestamp")
    message = raw.get("message")
    if not timestamp or message is None:
        return None
    level = str(raw.get("level", "INFO")).upper()
    return LogEntry(
        timestamp=datetime.fromisoformat(_FRACTION.sub(r"\1", str(timestamp))),
        service=service,
        level={"WARNING": "WARN", "CRITICAL": "FATAL"}.get(level, level),
        message=str(message),
        logger=raw.get("logger") or raw.get("logger_name"),
        trace_id=raw.get("trace_id") or raw.get("traceId"),
        error_type=raw.get("error_type"),
        error_message=raw.get("error_message"),
        stack_trace=raw.get("stack_trace"),
        fields={k: v for k, v in raw.items() if k not in _KNOWN},
    )


def message_shape(message: str) -> str:
    for pattern, replacement in _PATTERNS:
        message = pattern.sub(replacement, message)
    return message


def _stack_head(stack: str | None) -> str | None:
    """Java traces lead with the exception; Python tracebacks end with it."""
    if not stack:
        return None
    lines = [line.strip()[:160] for line in stack.strip().splitlines() if line.strip()]
    head = lines[-(STACK_LINES - 1) :] if lines[0].startswith("Traceback") else lines[:STACK_LINES]
    return "\n".join(head)


def _compact(entry: LogEntry) -> dict[str, Any]:
    record: dict[str, Any] = {
        "time": entry.timestamp.strftime("%H:%M:%S"),
        "level": entry.level,
        "message": entry.message[:MAX_MESSAGE_CHARS],
    }
    if entry.logger:
        record["logger"] = entry.logger
    if entry.trace_id:
        record["trace_id"] = entry.trace_id
    if entry.error_type:
        record["error_type"] = entry.error_type
    if entry.error_message:
        record["error_message"] = entry.error_message[:200]
    if stack := _stack_head(entry.stack_trace):
        record["stack"] = stack
    return record


def _matches(entry: LogEntry, query: str | None, min_level: int, trace_id: str | None) -> bool:
    if LEVEL_ORDER.get(entry.level, 2) < min_level:
        return False
    if trace_id and entry.trace_id != trace_id:
        return False
    if query:
        parts = (entry.message, entry.error_type, entry.error_message, entry.stack_trace)
        haystack = " ".join(filter(None, parts))
        return query.lower() in haystack.lower()
    return True


def search_logs(
    entries: list[LogEntry],
    *,
    query: str | None = None,
    level: str | None = None,
    trace_id: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    min_level = LEVEL_ORDER[level] if level else 0
    matched = sorted(
        (e for e in entries if _matches(e, query, min_level, trace_id)),
        key=lambda e: e.timestamp,
    )
    groups: dict[tuple[str, str], list[LogEntry]] = {}
    for entry in matched:
        groups.setdefault((entry.level, message_shape(entry.message)), []).append(entry)
    ranked = sorted(groups.values(), key=lambda g: (-LEVEL_ORDER.get(g[0].level, 2), -len(g)))
    top = [
        {
            "level": group[-1].level,
            "count": len(group),
            "example": group[-1].message[:MAX_MESSAGE_CHARS],
            "last_seen": group[-1].timestamp.strftime("%H:%M:%S"),
        }
        for group in ranked[:TOP_MESSAGES]
    ]
    return {
        "total_matched": len(matched),
        "by_level": dict(Counter(e.level for e in matched)),
        "top_messages": top,
        "recent": [_compact(e) for e in reversed(matched[-limit:])],
    }
