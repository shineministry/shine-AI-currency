import json
import sqlite3
import time
from typing import Optional

import numpy as np

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base TEXT NOT NULL,
    quote TEXT NOT NULL,
    rate REAL NOT NULL,
    timestamp INTEGER NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_pair ON observations (base, quote, timestamp);
CREATE INDEX IF NOT EXISTS idx_obs_ts ON observations (timestamp);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    embedding TEXT NOT NULL,
    meta TEXT NOT NULL,
    timestamp INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    last_success INTEGER,
    last_error TEXT
);
"""


class Database:
    def __init__(self, path=None) -> None:
        self.path = path or str(settings.db_path)
        if self.path != ":memory:":
            from pathlib import Path

            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def store_observations(self, observations: list[dict]) -> int:
        with self._connect() as conn:
            now = int(time.time())
            rows = [
                (o["base"], o["quote"], o["rate"], now, o.get("source", "unknown"))
                for o in observations
            ]
            conn.executemany(
                "INSERT INTO observations (base, quote, rate, timestamp, source) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def latest_rates(self, base: str, limit: int = 64) -> dict[str, float]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT quote, rate, timestamp FROM observations "
                "WHERE base = ? AND timestamp = (SELECT MAX(timestamp) FROM observations WHERE base = ?) "
                "ORDER BY quote",
                (base, base),
            ).fetchall()
        return {r["quote"]: r["rate"] for r in rows}

    def latest_timestamp(self, base: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) AS ts FROM observations WHERE base = ?", (base,)
            ).fetchone()
        return row["ts"] if row and row["ts"] is not None else None

    def history(self, base: str, quote: str, days: int = 7) -> list[dict]:
        cutoff = int(time.time()) - days * 86400
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT rate, timestamp FROM observations "
                "WHERE base = ? AND quote = ? AND timestamp >= ? ORDER BY timestamp",
                (base, quote, cutoff),
            ).fetchall()
        return [{"rate": r["rate"], "timestamp": r["timestamp"]} for r in rows]

    def count_observations(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM observations").fetchone()
        return int(row["c"])

    def add_document(self, content: str, embedding: list[float], meta: dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO documents (content, embedding, meta, timestamp) VALUES (?, ?, ?, ?)",
                (content, json.dumps(embedding), json.dumps(meta), int(time.time())),
            )
            return int(cur.lastrowid)

    def clear_documents(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM documents")
            return cur.rowcount

    def all_documents(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, content, embedding, meta FROM documents"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "content": r["content"],
                "embedding": r["embedding"],
                "meta": json.loads(r["meta"]),
            }
            for r in rows
        ]

    def count_documents(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()
        return int(row["c"])

    def mark_source_ok(self, name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sources (name, last_success, last_error) VALUES (?, ?, NULL) "
                "ON CONFLICT(name) DO UPDATE SET last_success = excluded.last_success, last_error = NULL",
                (name, int(time.time())),
            )

    def mark_source_error(self, name: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sources (name, last_success, last_error) VALUES (?, NULL, ?) "
                "ON CONFLICT(name) DO UPDATE SET last_error = excluded.last_error",
                (name, error[:500]),
            )

    def source_status(self) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sources").fetchall()
        return {r["name"]: {"last_success": r["last_success"], "last_error": r["last_error"]} for r in rows}

    def latest_observation_window(self, base: str, hours: int = 48) -> list[dict]:
        cutoff = int(time.time()) - hours * 3600
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT quote, rate, timestamp, source FROM observations "
                "WHERE base = ? AND timestamp >= ? ORDER BY quote, timestamp",
                (base, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
