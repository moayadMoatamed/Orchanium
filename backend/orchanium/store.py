"""SQLite persistence: runs, event logs (for replay) and key/value caches
(PubChem, LLM, web fetch). Synchronous sqlite3 is fine at our volume."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import settings
from .events import Event

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, target TEXT, created_at REAL, status TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT, seq INTEGER, ts REAL, kind TEXT, data TEXT,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS cache (
    ns TEXT, key TEXT, value TEXT, created_at REAL,
    PRIMARY KEY (ns, key)
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, origin TEXT, product_smiles TEXT, clue TEXT,
    citation_status TEXT, run_id TEXT, created_at REAL
);
"""


def hash_key(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class Store:
    def __init__(self, path: Path | str = settings.db_path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    # ---- runs
    def create_run(self, run_id: str, target: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
                             (run_id, target, time.time(), "running", None))
            self._db.commit()

    def finish_run(self, run_id: str, status: str, summary: dict | None = None) -> None:
        with self._lock:
            self._db.execute("UPDATE runs SET status=?, summary=? WHERE id=?",
                             (status, json.dumps(summary or {}), run_id))
            self._db.commit()

    def update_summary(self, run_id: str, patch: dict) -> None:
        with self._lock:
            row = self._db.execute("SELECT summary FROM runs WHERE id=?", (run_id,)).fetchone()
            summary = {**(json.loads(row[0]) if row and row[0] else {}), **patch}
            self._db.execute("UPDATE runs SET summary=? WHERE id=?", (json.dumps(summary), run_id))
            self._db.commit()

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, target, created_at, status, summary FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [{"id": r[0], "target": r[1], "created_at": r[2], "status": r[3],
                 "summary": json.loads(r[4]) if r[4] else None} for r in rows]

    # ---- events
    def append_event(self, e: Event) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?)",
                             (e.run_id, e.seq, e.ts, e.kind, json.dumps(e.data)))
            self._db.commit()

    def events(self, run_id: str) -> list[Event]:
        rows = self._db.execute(
            "SELECT seq, ts, kind, data FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return [Event(seq=r[0], run_id=run_id, ts=r[1], kind=r[2], data=json.loads(r[3])) for r in rows]

    def last_seq(self, run_id: str) -> int:
        row = self._db.execute("SELECT MAX(seq) FROM events WHERE run_id=?", (run_id,)).fetchone()
        return row[0] or 0

    # ---- lasting evidence (see memory.py)
    def remember(self, rows: list[tuple[str, str, str, str, str | None, str]]) -> None:
        """rows: (id, origin, product_smiles, clue_json, citation_status, run_id). A clue
        keeps the run that first found it; only its citation status is refreshed."""
        with self._lock:
            self._db.executemany(
                "INSERT INTO evidence VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "citation_status=COALESCE(excluded.citation_status, evidence.citation_status)",
                [(*r, time.time()) for r in rows])
            self._db.commit()

    def evidence(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, origin, product_smiles, clue, citation_status, run_id, created_at FROM evidence").fetchall()
        return [{"id": r[0], "origin": r[1], "product_smiles": r[2], "clue": json.loads(r[3]),
                 "citation_status": r[4], "run_id": r[5], "created_at": r[6]} for r in rows]

    # ---- cache
    def cache_get(self, ns: str, key: str) -> Any | None:
        row = self._db.execute("SELECT value FROM cache WHERE ns=? AND key=?", (ns, key)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_set(self, ns: str, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)",
                             (ns, key, json.dumps(value), time.time()))
            self._db.commit()


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
