"""SQLite persistence layer for Learning Loop.

Replaces the JSON-file backed store with a proper SQLite database
for efficient querying of execution history and strategy weights.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CRM_SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_sync_status (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    byou_id         TEXT NOT NULL,
    crm_id          TEXT,
    direction       TEXT NOT NULL DEFAULT 'push',
    provider        TEXT NOT NULL DEFAULT 'generic',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    error_message   TEXT,
    conflict_fields TEXT,          -- JSON array
    byou_snapshot   TEXT,          -- JSON blob
    crm_snapshot    TEXT,          -- JSON blob
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3
);
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS execution_traces (
    id          TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    metrics      TEXT,          -- JSON blob
    feedback     TEXT,          -- JSON blob
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stage_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL REFERENCES execution_traces(id) ON DELETE CASCADE,
    stage_name  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    data        TEXT,          -- JSON blob
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS strategy_weights (
    agent_name  TEXT PRIMARY KEY,
    weight      REAL NOT NULL DEFAULT 1.0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    avg_trust   REAL,
    avg_intent  REAL,
    pass_rate   REAL,
    total       INTEGER,
    raw_metrics TEXT          -- JSON blob
);

""" + CRM_SYNC_SCHEMA

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_traces_created ON execution_traces(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stage_trace    ON stage_records(trace_id);
CREATE INDEX IF NOT EXISTS idx_crm_sync_byou  ON crm_sync_status(byou_id);
CREATE INDEX IF NOT EXISTS idx_crm_sync_crm   ON crm_sync_status(crm_id);
CREATE INDEX IF NOT EXISTS idx_crm_sync_time  ON crm_sync_status(created_at DESC);
"""


class SQLiteStore:
    """SQLite-backed store for Learning Loop data."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ── Lifecycle ────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.executescript(INDEX_SQL)
        conn.commit()
        # Seed default weights if empty
        cur = conn.execute("SELECT count(*) FROM strategy_weights")
        if cur.fetchone()[0] == 0:
            defaults = ["extractor", "researcher", "synthesizer", "strategist", "critic"]
            now = datetime.now().isoformat()
            conn.executemany(
                "INSERT INTO strategy_weights (agent_name, weight, updated_at) VALUES (?, 1.0, ?)",
                [(d, now) for d in defaults],
            )
            conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Execution Traces ─────────────────────────────────────────

    def save_trace(self, trace: Any) -> None:
        """Upsert an ExecutionTrace."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO execution_traces (id, started_at, completed_at, metrics, feedback)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 completed_at=excluded.completed_at,
                 metrics=excluded.metrics,
                 feedback=excluded.feedback""",
            (
                trace.pipeline_id,
                trace.started_at.isoformat() if trace.started_at else now,
                trace.completed_at.isoformat() if trace.completed_at else None,
                json.dumps(trace.metrics, ensure_ascii=False),
                json.dumps(trace.feedback, ensure_ascii=False) if trace.feedback else None,
            ),
        )
        # Save stage records
        for name, stage_data in (trace.stages or {}).items():
            conn.execute(
                """INSERT INTO stage_records (trace_id, stage_name, timestamp, data)
                   VALUES (?, ?, ?, ?)""",
                (
                    trace.pipeline_id,
                    name,
                    stage_data.get("timestamp", now),
                    json.dumps(stage_data.get("data"), ensure_ascii=False),
                ),
            )
        conn.commit()

    def load_recent_traces(self, limit: int = 50) -> list[dict]:
        """Load recent execution traces for performance history."""
        conn = self._get_conn()
        cur = conn.execute(
            """SELECT id, started_at, completed_at, metrics
               FROM execution_traces
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r["id"],
                "timestamp": r["started_at"],
                "metrics": json.loads(r["metrics"]) if r["metrics"] else {},
                "stages": self._load_stages(r["id"]),
            }
            for r in rows
        ]

    def _load_stages(self, trace_id: str) -> list[str]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT stage_name FROM stage_records WHERE trace_id=? ORDER BY id",
            (trace_id,),
        )
        return [r["stage_name"] for r in cur.fetchall()]

    # ── Strategy Weights ─────────────────────────────────────────

    def load_weights(self) -> dict[str, float]:
        conn = self._get_conn()
        cur = conn.execute("SELECT agent_name, weight FROM strategy_weights")
        return {r["agent_name"]: r["weight"] for r in cur.fetchall()}

    def save_weights(self, weights: dict[str, float]) -> None:
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.executemany(
            """INSERT INTO strategy_weights (agent_name, weight, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(agent_name) DO UPDATE SET
                 weight=excluded.weight,
                 updated_at=excluded.updated_at""",
            [(k, v, now) for k, v in weights.items()],
        )
        conn.commit()

    # ── Performance Snapshots ────────────────────────────────────

    def save_snapshot(self, avg_trust: float, avg_intent: float,
                     pass_rate: float, total: int, raw: dict) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO performance_snapshots
               (avg_trust, avg_intent, pass_rate, total, raw_metrics)
               VALUES (?, ?, ?, ?, ?)""",
            (avg_trust, avg_intent, pass_rate, total,
             json.dumps(raw, ensure_ascii=False)),
        )
        conn.commit()

    # ── Migration from JSON ─────────────────────────────────────

    def migrate_from_json(self, json_path: Path) -> int:
        """Migrate data from legacy JSON file. Returns number of traces migrated."""
        if not json_path.exists():
            return 0
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read legacy JSON: %s", json_path)
            return 0

        count = 0
        # Migrate weights
        weights = data.get("strategy_weights", {})
        if weights:
            self.save_weights(weights)

        # Migrate performance history as traces
        for record in data.get("recent_performance", []):
            # Reconstruct a minimal trace
            trace_id = record.get("timestamp", str(count))
            conn = self._get_conn()
            conn.execute(
                """INSERT OR IGNORE INTO execution_traces (id, started_at, metrics)
                   VALUES (?, ?, ?)""",
                (trace_id, record.get("timestamp", ""),
                 json.dumps(record.get("metrics", {}), ensure_ascii=False)),
            )
            count += 1
        conn.commit()  # type: ignore[possibly-undefined]
        logger.info("Migrated %d records from %s", count, json_path)
        return count

    # ── CRM Sync Status ─────────────────────────────────────

    def save_crm_sync(self, record: dict) -> int:
        """Save a CRM sync record. Returns row id."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        cursor = conn.execute(
            """INSERT INTO crm_sync_status
               (byou_id, crm_id, direction, provider, status,
                created_at, completed_at, error_message, conflict_fields,
                byou_snapshot, crm_snapshot, retry_count, max_retries)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("byou_id", ""),
                record.get("crm_id"),
                record.get("direction", "push"),
                record.get("provider", "generic"),
                record.get("status", "pending"),
                record.get("created_at", now),
                record.get("completed_at"),
                record.get("error_message"),
                json.dumps(record.get("conflict_fields", []), ensure_ascii=False),
                json.dumps(record.get("byou_snapshot", {}), ensure_ascii=False),
                json.dumps(record.get("crm_snapshot", {}), ensure_ascii=False),
                record.get("retry_count", 0),
                record.get("max_retries", 3),
            ),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[no-any-return]

    def update_crm_sync(self, record_id: int, updates: dict) -> None:
        """Update a CRM sync record by id."""
        conn = self._get_conn()
        sets = []
        vals: list[Any] = []
        for key, val in updates.items():
            sets.append(f"{key}=?")
            if key in ("conflict_fields", "byou_snapshot", "crm_snapshot") and not isinstance(val, str):
                vals.append(json.dumps(val, ensure_ascii=False))
            else:
                vals.append(val)
        vals.append(record_id)
        conn.execute(
            f"UPDATE crm_sync_status SET {', '.join(sets)} WHERE id=?",
            vals,
        )
        conn.commit()

    def get_recent_crm_sync(self, limit: int = 50) -> list[dict]:
        """Get recent CRM sync records."""
        conn = self._get_conn()
        cur = conn.execute(
            """SELECT * FROM crm_sync_status
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_crm_sync_by_byou_id(self, byou_id: str) -> list[dict]:
        """Get all sync records for a byou_id."""
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM crm_sync_status WHERE byou_id=? ORDER BY created_at DESC",
            (byou_id,),
        )
        return [dict(r) for r in cur.fetchall()]
