"""SQLite ledger — the stable ``runs`` table (origin R16).

``predicted_lo``/``predicted_hi`` are nullable until the V2 preflight populates
them, so V2 adds meaning, not a migration. ``consumed`` is recorded for
economics and honesty only, never used to order or select tasks (R20/R26).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .models import RunRow

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    task_id           TEXT    NOT NULL,
    source            TEXT    NOT NULL,
    backend           TEXT    NOT NULL,
    predicted_lo      REAL,
    predicted_hi      REAL,
    consumed          REAL    NOT NULL DEFAULT 0,
    validation_result TEXT    NOT NULL,
    passed            INTEGER NOT NULL,
    escalated         INTEGER NOT NULL,
    branch            TEXT,
    ts                TEXT    NOT NULL,
    park_reason       TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts);
"""


class Ledger:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_DDL)
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- writes ---

    def record(self, row: RunRow) -> None:
        self._conn.execute(
            """INSERT INTO runs (task_id, source, backend, predicted_lo, predicted_hi,
                   consumed, validation_result, passed, escalated, branch, ts, park_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row.task_id, row.source, row.backend, row.predicted_lo, row.predicted_hi,
                row.consumed, row.validation_result, int(row.passed), int(row.escalated),
                row.branch, row.ts, row.park_reason,
            ),
        )
        self._conn.commit()

    # --- reads ---

    def has_run(self, task_id: str) -> bool:
        """True if any prior row exists for this task id (dedupe by ledger, not branch)."""
        cur = self._conn.execute("SELECT 1 FROM runs WHERE task_id=? LIMIT 1", (task_id,))
        return cur.fetchone() is not None

    def runs_since(self, ts: str) -> list:
        cur = self._conn.execute("SELECT * FROM runs WHERE ts >= ? ORDER BY ts", (ts,))
        return [dict(r) for r in cur.fetchall()]

    def spend_since(self, backend: str, ts: str) -> float:
        """Total $ consumed by ``backend`` since ``ts`` — feeds budget-fallback."""
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(consumed),0) AS s FROM runs WHERE backend=? AND ts >= ?",
            (backend, ts),
        )
        return float(cur.fetchone()["s"])

    def lane_summary(self, ts: str) -> dict:
        """Per-backend {consumed, passes, attempts} since ``ts`` — feeds the report."""
        cur = self._conn.execute(
            """SELECT backend,
                      COALESCE(SUM(consumed),0) AS consumed,
                      SUM(passed) AS passes,
                      COUNT(*) AS attempts
               FROM runs WHERE ts >= ? GROUP BY backend""",
            (ts,),
        )
        return {
            r["backend"]: {
                "consumed": float(r["consumed"]),
                "passes": int(r["passes"] or 0),
                "attempts": int(r["attempts"]),
            }
            for r in cur.fetchall()
        }
