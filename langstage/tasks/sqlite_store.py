"""SQLite-backed :class:`~langstage_core.tasks.TaskStore`.

Durable across restarts (the task board survives a bounce). Single-process by
design: an :class:`asyncio.Lock` serializes the claim so two workers never grab
the same row. That guarantee holds within one process / one event loop — which
is exactly the single-uvicorn-worker constraint the task board runs under. A
multi-worker deployment would need SQL-level locking (e.g. ``BEGIN IMMEDIATE``
+ a status guard) instead; documented, not implemented.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from langstage_core.tasks import Task
from langstage_core.tasks.state import ONGOING, QUEUED
from langstage_core.tasks.store import now_iso

_COLUMNS = [
    "task_id", "parent_id", "title", "prompt", "agent_spec", "state",
    "thread_id", "created_at", "started_at", "finished_at", "result",
    "artifacts", "error", "interrupt",
]
#: Columns stored as JSON text and decoded back to Python on read.
_JSON_COLUMNS = {"artifacts", "interrupt"}

_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    parent_id   TEXT,
    title       TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    agent_spec  TEXT,
    state       TEXT NOT NULL DEFAULT 'queued',
    thread_id   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    result      TEXT,
    artifacts   TEXT,
    error       TEXT,
    interrupt   TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_state  ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);

CREATE TABLE IF NOT EXISTS task_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_events ON task_events(task_id, id);
"""


def _encode(task: dict[str, Any]) -> dict[str, Any]:
    """Map a Task dict to a row dict (JSON-encode the structured columns)."""
    row: dict[str, Any] = {}
    for col in _COLUMNS:
        val = task.get(col)
        if col in _JSON_COLUMNS and val is not None:
            val = json.dumps(val)
        row[col] = val
    return row


def _decode(row: aiosqlite.Row) -> Task:
    """Map a DB row back to a Task (JSON-decode the structured columns)."""
    task: dict[str, Any] = {}
    for col in _COLUMNS:
        val = row[col]
        if col in _JSON_COLUMNS and val is not None:
            try:
                val = json.loads(val)
            except (ValueError, TypeError):  # pragma: no cover - defensive
                val = None
        task[col] = val
    return task  # type: ignore[return-value]


class SqliteTaskStore:
    """Durable :class:`TaskStore` on an aiosqlite database file."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def setup(self) -> None:
        if self._db is None:
            self._db = await aiosqlite.connect(self._path)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.executescript(_DDL)
            await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteTaskStore.setup() must be awaited first")
        return self._db

    async def create(self, task: Task) -> Task:
        row = _encode(dict(task))
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        db = self._conn()
        await db.execute(f"INSERT INTO tasks ({cols}) VALUES ({placeholders})", row)
        await db.commit()
        return task

    async def get(self, task_id: str) -> Optional[Task]:
        db = self._conn()
        async with db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
        return _decode(row) if row is not None else None

    async def list(
        self,
        *,
        state: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> list[Task]:
        clauses, params = [], []
        if state is not None:
            clauses.append("state = ?"); params.append(state)
        if parent_id is not None:
            clauses.append("parent_id = ?"); params.append(parent_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        db = self._conn()
        async with db.execute(
            f"SELECT * FROM tasks{where} ORDER BY created_at DESC", params
        ) as cur:
            rows = await cur.fetchall()
        return [_decode(r) for r in rows]

    async def claim_next(self) -> Optional[Task]:
        # Serialize the read-then-update so two workers can't claim one task.
        async with self._lock:
            db = self._conn()
            async with db.execute(
                "SELECT task_id FROM tasks WHERE state = ? ORDER BY created_at LIMIT 1",
                (QUEUED,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            task_id = row["task_id"]
            await db.execute(
                "UPDATE tasks SET state = ?, started_at = ? WHERE task_id = ?",
                (ONGOING, now_iso(), task_id),
            )
            await db.commit()
            return await self.get(task_id)

    async def update(self, task_id: str, **fields: Any) -> Optional[Task]:
        if not fields:
            return await self.get(task_id)
        sets, params = [], []
        for col, val in fields.items():
            if col not in _COLUMNS:
                raise ValueError(f"Unknown task column: {col!r}")
            if col in _JSON_COLUMNS and val is not None:
                val = json.dumps(val)
            sets.append(f"{col} = ?"); params.append(val)
        params.append(task_id)
        db = self._conn()
        await db.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?", params
        )
        await db.commit()
        return await self.get(task_id)

    async def requeue_orphans(self) -> int:
        db = self._conn()
        cur = await db.execute(
            "UPDATE tasks SET state = ?, started_at = NULL WHERE state = ?",
            (QUEUED, ONGOING),
        )
        await db.commit()
        return cur.rowcount or 0

    async def append_events(self, task_id: str, events: list[dict[str, Any]]) -> None:
        db = self._conn()
        await db.executemany(
            "INSERT INTO task_events (task_id, event) VALUES (?, ?)",
            [(task_id, json.dumps(e)) for e in events],
        )
        await db.commit()

    async def get_events(self, task_id: str) -> list[dict[str, Any]]:
        db = self._conn()
        async with db.execute(
            "SELECT event FROM task_events WHERE task_id = ? ORDER BY id", (task_id,)
        ) as cur:
            rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r["event"]))
            except (ValueError, TypeError):  # pragma: no cover - defensive
                continue
        return out
