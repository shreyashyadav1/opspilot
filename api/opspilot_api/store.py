"""SQLite storage for investigation records and their trace events.

Records are the read model and the audit trail; the LangGraph checkpoint (a separate file,
written by `AsyncSqliteSaver`) is what the graph resumes from. Each file has exactly one
connection, and every statement on this one runs under a lock, so a write never starts from a
stale read snapshot.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from opspilot_api.schemas import UNFINISHED, Alert, InvestigationRecord, TraceEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    seq INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_events (
    investigation_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (investigation_id, seq)
);
"""


def utcnow() -> datetime:
    return datetime.now(UTC)


class InvestigationStore:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: Path) -> InvestigationStore:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript(SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    async def create(self, alert: Alert, model: str) -> InvestigationRecord:
        async with self._lock:
            async with self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM investigations"
            ) as cur:
                row = await cur.fetchone()
            seq = int(row[0]) if row else 1
            now = utcnow()
            record = InvestigationRecord(
                id=f"inv-{seq:04d}",
                status="queued",
                alert=alert,
                model=model,
                created_at=now,
                updated_at=now,
            )
            await self._conn.execute(
                "INSERT INTO investigations (seq, id, status, created_at, document) "
                "VALUES (?, ?, ?, ?, ?)",
                (seq, record.id, record.status, now.isoformat(), record.model_dump_json()),
            )
            await self._conn.commit()
        return record

    async def save(self, record: InvestigationRecord) -> InvestigationRecord:
        record.updated_at = utcnow()
        async with self._lock:
            await self._conn.execute(
                "UPDATE investigations SET status = ?, document = ? WHERE id = ?",
                (record.status, record.model_dump_json(), record.id),
            )
            await self._conn.commit()
        return record

    async def _fetchall(self, sql: str, params: tuple[Any, ...]) -> list[Any]:
        async with self._lock, self._conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def get(self, investigation_id: str) -> InvestigationRecord | None:
        rows = await self._fetchall(
            "SELECT document FROM investigations WHERE id = ?", (investigation_id,)
        )
        return InvestigationRecord.model_validate_json(rows[0][0]) if rows else None

    async def list(self, limit: int = 100) -> list[InvestigationRecord]:
        rows = await self._fetchall(
            "SELECT document FROM investigations ORDER BY seq DESC LIMIT ?", (limit,)
        )
        return [InvestigationRecord.model_validate_json(row[0]) for row in rows]

    async def unfinished(self) -> list[InvestigationRecord]:
        marks = ", ".join("?" for _ in UNFINISHED)
        rows = await self._fetchall(
            f"SELECT document FROM investigations WHERE status IN ({marks}) ORDER BY seq",
            tuple(sorted(UNFINISHED)),
        )
        return [InvestigationRecord.model_validate_json(row[0]) for row in rows]

    async def add_event(self, investigation_id: str, kind: str, data: dict[str, Any]) -> TraceEvent:
        async with self._lock:
            async with self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_events WHERE investigation_id = ?",
                (investigation_id,),
            ) as cur:
                row = await cur.fetchone()
            seq = int(row[0]) if row else 1
            event = TraceEvent.model_validate(
                {"seq": seq, "at": utcnow(), "kind": kind, "data": data}
            )
            await self._conn.execute(
                "INSERT INTO trace_events (investigation_id, seq, at, kind, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    investigation_id,
                    event.seq,
                    event.at.isoformat(),
                    event.kind,
                    json.dumps(event.data, default=str),
                ),
            )
            await self._conn.commit()
        return event

    async def events(self, investigation_id: str) -> list[TraceEvent]:
        rows = await self._fetchall(
            "SELECT seq, at, kind, data FROM trace_events WHERE investigation_id = ? ORDER BY seq",
            (investigation_id,),
        )
        return [
            TraceEvent(seq=seq, at=datetime.fromisoformat(at), kind=kind, data=json.loads(data))
            for seq, at, kind, data in rows
        ]
