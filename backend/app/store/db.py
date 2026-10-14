"""Tiny SQLite store (stdlib only). One table of JSON records keyed by (kind, id).

Kinds used by the app: "job" (scrape jobs), "ad", "asset". The schema is deliberately generic so a
Postgres implementation with the same method names can replace this class without touching callers.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind       TEXT NOT NULL,
    id         TEXT NOT NULL,
    status     TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    data       TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS idx_records_kind_created ON records(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_records_kind_status ON records(kind, status);
"""


class Database:
    """Async facade over one SQLite connection; every call runs in a worker thread under a lock."""

    def __init__(self, path: Path | str):
        """Remember the file path; call init() before use."""
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    async def init(self) -> None:
        """Create the data folder, open the connection and create tables."""
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        """Open SQLite in WAL mode and ensure the schema exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        conn.commit()
        self._conn = conn

    async def close(self) -> None:
        """Close the connection."""
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        """Close the SQLite connection if open."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _exec(self, sql: str, params: Iterable[Any] = (), fetch: str = "none") -> Any:
        """Run one statement under the lock and commit; fetch is none, one or all."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database is not initialised")
            cur = self._conn.execute(sql, tuple(params))
            result = cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else None
            self._conn.commit()
            return result

    # ------------------------------------------------------------------ records

    async def ping(self) -> bool:
        """Return True when the database answers a trivial query."""
        try:
            row = await asyncio.to_thread(self._exec, "SELECT 1", (), "one")
            return bool(row)
        except Exception:
            return False

    async def put(self, kind: str, record_id: str, data: dict, status: Optional[str] = None) -> None:
        """Insert or replace one JSON record, keeping its original created_at."""
        now = time.time()
        payload = json.dumps(data, ensure_ascii=False, default=str)
        await asyncio.to_thread(
            self._exec,
            """INSERT INTO records (kind, id, status, created_at, updated_at, data) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(kind, id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, data=excluded.data""",
            (kind, record_id, status, now, now, payload),
        )

    async def get(self, kind: str, record_id: str) -> Optional[dict]:
        """Fetch one record's JSON or None."""
        row = await asyncio.to_thread(self._exec, "SELECT data FROM records WHERE kind=? AND id=?", (kind, record_id), "one")
        return json.loads(row[0]) if row else None

    async def delete(self, kind: str, record_id: str) -> None:
        """Delete one record if it exists."""
        await asyncio.to_thread(self._exec, "DELETE FROM records WHERE kind=? AND id=?", (kind, record_id))

    async def count_since(self, kind: str, since_ts: float) -> int:
        """Count records of a kind created at or after a unix timestamp."""
        row = await asyncio.to_thread(
            self._exec, "SELECT COUNT(*) FROM records WHERE kind=? AND created_at>=?", (kind, since_ts), "one"
        )
        return int(row[0]) if row else 0

    async def list_by_status(self, kind: str, statuses: list[str]) -> list[dict]:
        """Return records of a kind whose status is in the list."""
        if not statuses:
            return []
        marks = ",".join("?" for _ in statuses)
        rows = await asyncio.to_thread(
            self._exec, f"SELECT data FROM records WHERE kind=? AND status IN ({marks})", (kind, *statuses), "all"
        )
        return [json.loads(r[0]) for r in rows]

    async def pop_older_than(self, kind: str, older_than_ts: float) -> list[dict]:
        """Delete and return records of a kind created before a unix timestamp."""
        rows = await asyncio.to_thread(
            self._exec, "SELECT id, data FROM records WHERE kind=? AND created_at<?", (kind, older_than_ts), "all"
        )
        if rows:
            await asyncio.to_thread(self._exec, "DELETE FROM records WHERE kind=? AND created_at<?", (kind, older_than_ts))
        return [json.loads(r[1]) for r in rows]
