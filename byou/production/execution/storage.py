"""Byou L4 — 状态存储层。

多后端: memory (开发/测试) / sqlite (单机) / jsonl (冷备份)。
提供统一接口给 checkpoints / run_state / lifecycle_events。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from .types import (
    CheckpointRecord,
    IdempotencyRecord,
    PipelineRunState,
    RunLifecycleEvent,
    StageExecStatus,
    StageExecutionState,
)

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data/durable")


class BaseStorage:
    """存储抽象基类"""

    def save_run_state(self, state: PipelineRunState) -> None:  # pragma: no cover
        raise NotImplementedError

    def load_run_state(self, run_id: str) -> PipelineRunState | None:  # pragma: no cover
        raise NotImplementedError

    def save_stage_state(self, s: StageExecutionState) -> None:  # pragma: no cover
        raise NotImplementedError

    def load_stage_state(self, run_id: str, stage: str) -> StageExecutionState | None:  # pragma: no cover
        raise NotImplementedError

    def save_checkpoint(self, cp: CheckpointRecord) -> None:  # pragma: no cover
        raise NotImplementedError

    def load_checkpoint(self, checkpoint_id: str) -> CheckpointRecord | None:  # pragma: no cover
        raise NotImplementedError

    def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]:  # pragma: no cover
        raise NotImplementedError

    def save_event(self, evt: RunLifecycleEvent) -> None:  # pragma: no cover
        raise NotImplementedError

    def list_events(self, run_id: str) -> list[RunLifecycleEvent]:  # pragma: no cover
        raise NotImplementedError

    def save_idempotency(self, rec: IdempotencyRecord) -> None:  # pragma: no cover
        raise NotImplementedError

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:
        pass


# ── Memory (测试用) ────────────────────────────────────────────


class MemoryStorage(BaseStorage):
    """In-memory 存储 — 测试/开发专用"""

    def __init__(self):
        self._runs: dict[str, PipelineRunState] = {}
        self._stages: dict[str, StageExecutionState] = {}
        self._checkpoints: dict[str, CheckpointRecord] = {}
        self._events: dict[str, list[RunLifecycleEvent]] = {}
        self._idempotency: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def _stage_key(self, run_id: str, stage: str) -> str:
        return f"{run_id}:{stage}"

    # Run state
    def save_run_state(self, state: PipelineRunState) -> None:
        with self._lock:
            self._runs[state.run_id] = state.model_copy(deep=True)

    def load_run_state(self, run_id: str) -> PipelineRunState | None:
        with self._lock:
            return self._runs.get(run_id)

    # Stage state
    def save_stage_state(self, s: StageExecutionState) -> None:
        with self._lock:
            self._stages[self._stage_key(s.run_id, s.stage_name)] = s.model_copy(deep=True)

    def load_stage_state(self, run_id: str, stage: str) -> StageExecutionState | None:
        with self._lock:
            return self._stages.get(self._stage_key(run_id, stage))

    # Checkpoints
    def save_checkpoint(self, cp: CheckpointRecord) -> None:
        with self._lock:
            self._checkpoints[cp.checkpoint_id] = cp.model_copy(deep=True)

    def load_checkpoint(self, checkpoint_id: str) -> CheckpointRecord | None:
        with self._lock:
            return self._checkpoints.get(checkpoint_id)

    def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]:
        with self._lock:
            return [c for c in self._checkpoints.values() if c.run_id == run_id]

    # Events
    def save_event(self, evt: RunLifecycleEvent) -> None:
        with self._lock:
            self._events.setdefault(evt.run_id, []).append(evt.model_copy(deep=True))

    def list_events(self, run_id: str) -> list[RunLifecycleEvent]:
        with self._lock:
            return list(self._events.get(run_id, []))

    # Idempotency
    def save_idempotency(self, rec: IdempotencyRecord) -> None:
        with self._lock:
            self._idempotency[rec.key] = rec.model_copy(deep=True)

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        with self._lock:
            return self._idempotency.get(key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)


# ── SQLite ────────────────────────────────────────────────────


class SQLiteStorage(BaseStorage):
    """SQLite 持久存储 — 单机生产"""

    def __init__(self, db_path: str = ""):
        if not db_path:
            db_path = str(DEFAULT_DATA_DIR / "durable.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self._local = threading.local()
        self._init_schema()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    trace_id TEXT,
                    status TEXT,
                    created_at TEXT,
                    started_at TEXT,
                    paused_at TEXT,
                    resumed_at TEXT,
                    completed_at TEXT,
                    last_heartbeat TEXT,
                    current_stage TEXT,
                    current_step TEXT,
                    pause_reason TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    total_duration_ms REAL DEFAULT 0,
                    approval_request_id TEXT,
                    extra_json TEXT DEFAULT '{}',
                    tags_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS stages (
                    run_id TEXT,
                    stage_name TEXT,
                    status TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_ms REAL DEFAULT 0,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    error TEXT,
                    agent_name TEXT DEFAULT '',
                    input_snapshot_ref TEXT DEFAULT '',
                    output_snapshot_ref TEXT DEFAULT '',
                    checkpoint_ids_json TEXT DEFAULT '[]',
                    PRIMARY KEY (run_id, stage_name)
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    trace_id TEXT,
                    stage TEXT,
                    step TEXT,
                    status TEXT,
                    agent_name TEXT DEFAULT '',
                    resumable INTEGER DEFAULT 1,
                    retry_count INTEGER DEFAULT 0,
                    input_json TEXT DEFAULT '{}',
                    output_json TEXT DEFAULT '{}',
                    data_ref TEXT DEFAULT '',
                    extra_json TEXT DEFAULT '{}',
                    checkpoint_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cp_run ON checkpoints(run_id);

                CREATE TABLE IF NOT EXISTS lifecycle_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    event_type TEXT,
                    from_status TEXT,
                    to_status TEXT,
                    stage TEXT,
                    details_json TEXT DEFAULT '{}',
                    timestamp TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_evt_run ON lifecycle_events(run_id);

                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    status TEXT,
                    run_id TEXT,
                    result_hash TEXT DEFAULT '',
                    completed_at TEXT,
                    error TEXT
                );
            """)
            c.commit()

    # ── helpers ──

    @staticmethod
    def _dt(d: datetime | None) -> str | None:
        return d.isoformat() if d else None

    @staticmethod
    def _pd(s: str | None) -> datetime | None:
        return datetime.fromisoformat(s) if s else None

    # Run
    def save_run_state(self, state: PipelineRunState) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO runs
                (run_id, trace_id, status, created_at, started_at, paused_at, resumed_at,
                 completed_at, last_heartbeat, current_stage, current_step, pause_reason,
                 error_message, retry_count, max_retries, total_duration_ms,
                 approval_request_id, extra_json, tags_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                state.run_id, state.trace_id, state.status.value, self._dt(state.created_at),
                self._dt(state.started_at), self._dt(state.paused_at), self._dt(state.resumed_at),
                self._dt(state.completed_at), self._dt(state.last_heartbeat),
                state.current_stage, state.current_step, state.pause_reason,
                state.error_message, state.retry_count, state.max_retries,
                state.total_duration_ms, state.approval_request_id,
                json.dumps(state.extra_context, ensure_ascii=False),
                json.dumps(state.tags, ensure_ascii=False),
            ))
            c.commit()

    def load_run_state(self, run_id: str) -> PipelineRunState | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return None
        return PipelineRunState(
            run_id=row["run_id"], trace_id=row["trace_id"],
            status=RunStatus(row["status"]), created_at=self._pd(row["created_at"]),
            started_at=self._pd(row["started_at"]), paused_at=self._pd(row["paused_at"]),
            resumed_at=self._pd(row["resumed_at"]), completed_at=self._pd(row["completed_at"]),
            last_heartbeat=self._pd(row["last_heartbeat"]),
            current_stage=row["current_stage"], current_step=row["current_step"],
            pause_reason=row["pause_reason"], error_message=row["error_message"],
            retry_count=row["retry_count"], max_retries=row["max_retries"],
            total_duration_ms=row["total_duration_ms"],
            approval_request_id=row["approval_request_id"],
            extra_context=json.loads(row["extra_json"]),
            tags=json.loads(row["tags_json"]),
        )

    # Stage
    def save_stage_state(self, s: StageExecutionState) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO stages
                (run_id, stage_name, status, started_at, completed_at, duration_ms,
                 retry_count, max_retries, error, agent_name, input_snapshot_ref,
                 output_snapshot_ref, checkpoint_ids_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                s.run_id, s.stage_name, s.status.value, self._dt(s.started_at),
                self._dt(s.completed_at), s.duration_ms, s.retry_count, s.max_retries,
                s.error, s.agent_name, s.input_snapshot_ref, s.output_snapshot_ref,
                json.dumps(s.checkpoint_ids),
            ))
            c.commit()

    def load_stage_state(self, run_id: str, stage: str) -> StageExecutionState | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM stages WHERE run_id = ? AND stage_name = ?",
                (run_id, stage),
            ).fetchone()
        if not row:
            return None
        return StageExecutionState(
            run_id=row["run_id"], stage_name=row["stage_name"],
            status=StageExecStatus(row["status"]),
            started_at=self._pd(row["started_at"]),
            completed_at=self._pd(row["completed_at"]),
            duration_ms=row["duration_ms"], retry_count=row["retry_count"],
            max_retries=row["max_retries"], error=row["error"],
            agent_name=row["agent_name"],
            input_snapshot_ref=row["input_snapshot_ref"],
            output_snapshot_ref=row["output_snapshot_ref"],
            checkpoint_ids=json.loads(row["checkpoint_ids_json"]),
        )

    # Checkpoint
    def save_checkpoint(self, cp: CheckpointRecord) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO checkpoints
                (checkpoint_id, run_id, trace_id, stage, step, status, agent_name,
                 resumable, retry_count, input_json, output_json, data_ref, extra_json, checkpoint_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                cp.checkpoint_id, cp.run_id, cp.trace_id, cp.stage, cp.step,
                cp.status.value, cp.agent_name, int(cp.resumable), cp.retry_count,
                json.dumps(cp.input_snapshot, ensure_ascii=False),
                json.dumps(cp.output_snapshot, ensure_ascii=False),
                cp.data_ref,
                json.dumps(cp.extra, ensure_ascii=False),
                self._dt(cp.checkpoint_at),
            ))
            c.commit()

    def load_checkpoint(self, checkpoint_id: str) -> CheckpointRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)).fetchone()
        if not row:
            return None
        return CheckpointRecord(
            checkpoint_id=row["checkpoint_id"], run_id=row["run_id"],
            trace_id=row["trace_id"], stage=row["stage"], step=row["step"],
            status=StageExecStatus(row["status"]), agent_name=row["agent_name"],
            resumable=bool(row["resumable"]), retry_count=row["retry_count"],
            input_snapshot=json.loads(row["input_json"]),
            output_snapshot=json.loads(row["output_json"]),
            data_ref=row["data_ref"], extra=json.loads(row["extra_json"]),
            checkpoint_at=self._pd(row["checkpoint_at"]),
        )

    def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT checkpoint_id FROM checkpoints WHERE run_id = ? ORDER BY checkpoint_at",
                (run_id,),
            ).fetchall()
        return [self.load_checkpoint(r["checkpoint_id"]) for r in rows]  # type: ignore

    # Events
    def save_event(self, evt: RunLifecycleEvent) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO lifecycle_events
                (event_id, run_id, event_type, from_status, to_status, stage, details_json, timestamp)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                evt.event_id, evt.run_id, evt.event_type,
                evt.from_status.value if evt.from_status else None,
                evt.to_status.value if evt.to_status else None,
                evt.stage, json.dumps(evt.details, ensure_ascii=False),
                self._dt(evt.timestamp),
            ))
            c.commit()

    def list_events(self, run_id: str) -> list[RunLifecycleEvent]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM lifecycle_events WHERE run_id = ? ORDER BY timestamp",
                (run_id,),
            ).fetchall()
        result: list[RunLifecycleEvent] = []
        for row in rows:
            from_s = RunStatus(row["from_status"]) if row["from_status"] else None
            to_s = RunStatus(row["to_status"]) if row["to_status"] else None
            result.append(RunLifecycleEvent(
                event_id=row["event_id"], run_id=row["run_id"],
                event_type=row["event_type"], from_status=from_s, to_status=to_s,
                stage=row["stage"], details=json.loads(row["details_json"]),
                timestamp=self._pd(row["timestamp"]),
            ))
        return result

    # Idempotency
    def save_idempotency(self, rec: IdempotencyRecord) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO idempotency (key, status, run_id, result_hash, completed_at, error)
                VALUES (?,?,?,?,?,?)
            """, (rec.key, rec.status, rec.run_id, rec.result_hash, self._dt(rec.completed_at), rec.error))
            c.commit()

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM idempotency WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        return IdempotencyRecord(
            key=row["key"], status=row["status"], run_id=row["run_id"],
            result_hash=row["result_hash"],
            completed_at=self._pd(row["completed_at"]), error=row["error"],
        )

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None


# Late import to avoid circular dependency at module top
from .types import RunStatus  # noqa: E402
