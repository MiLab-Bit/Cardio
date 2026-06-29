"""Byou L3 HITL — 审批存储。

双模: in-memory (fast) / sqlite (durable)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .types import (
    ApprovalDecision,
    ApprovalEvent,
    ApprovalRequest,
    ApprovalStatus,
    EscalationPolicy,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'action',
    mode TEXT NOT NULL DEFAULT 'demand',
    status TEXT NOT NULL DEFAULT 'pending',
    context_json TEXT NOT NULL,
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT,
    timeout_s INTEGER NOT NULL DEFAULT 300,
    escalation TEXT NOT NULL DEFAULT 'auto_reject',
    max_approvals INTEGER NOT NULL DEFAULT 1,
    approvals_received INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS approval_events (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    before_status TEXT,
    after_status TEXT NOT NULL,
    decision_json TEXT,
    timestamp TEXT NOT NULL,
    pipeline_id TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_requests_pipeline ON approval_requests(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_events_request ON approval_events(request_id);
"""


class ApprovalStore:
    """双模审批队列存储 (in-memory + 可选 sqlite)"""

    def __init__(
        self,
        db_path: str | None = None,
    ):
        self._memory: dict[str, ApprovalRequest] = {}
        self._events: list[ApprovalEvent] = []
        self._lock = threading.Lock()

        self._db: sqlite3.Connection | None = None
        if db_path:
            p = Path(db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(p), check_same_thread=False)
            self._db.executescript(_SCHEMA)
            self._db.commit()
            logger.info("ApprovalStore sqlite ready: %s", p)

    # ── CRUD ────────────────────────────────────────────────────

    def create(self, request: ApprovalRequest) -> None:
        with self._lock:
            self._memory[request.id] = request
            self._record_event(ApprovalEvent(
                request_id=request.id,
                event_type="created",
                after_status=request.status,
                pipeline_id=request.pipeline_id,
            ))
        if self._db:
            self._db.execute(
                """INSERT OR REPLACE INTO approval_requests
                (id, pipeline_id, scope, mode, status, context_json,
                 message, created_at, expires_at, timeout_s, escalation,
                 max_approvals, approvals_received)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    request.id, request.pipeline_id, request.scope.value,
                    request.mode.value, request.status.value,
                    request.context.model_dump_json(),
                    request.message,
                    request.created_at.isoformat(),
                    request.expires_at.isoformat() if request.expires_at else None,
                    request.timeout_s, request.escalation.value,
                    request.max_approvals, request.approvals_received,
                ),
            )
            self._db.commit()

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._lock:
            return self._memory.get(request_id)

    def list_by_pipeline(self, pipeline_id: str) -> list[ApprovalRequest]:
        with self._lock:
            return [r for r in self._memory.values() if r.pipeline_id == pipeline_id]

    def list_pending(self) -> list[ApprovalRequest]:
        with self._lock:
            return [r for r in self._memory.values() if r.status == ApprovalStatus.PENDING]

    def list_all(self) -> list[ApprovalRequest]:
        with self._lock:
            return list(self._memory.values())

    def resolve(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> ApprovalRequest | None:
        """处理审批决策 (批准或拒绝)"""
        with self._lock:
            req = self._memory.get(request_id)
            if req is None:
                logger.warning("ApprovalStore.resolve: unknown request %s", request_id)
                return None
            if req.status != ApprovalStatus.PENDING and req.status != ApprovalStatus.ESCALATED:
                logger.warning("ApprovalStore.resolve: request %s already resolved (%s)", request_id, req.status.value)
                return None

            old_status = req.status
            req.approvals_received += 1
            if req.approvals_received >= req.max_approvals:
                new_status = ApprovalStatus.APPROVED if decision.approved else ApprovalStatus.REJECTED
            else:
                new_status = old_status  # still pending more approvals
            req.status = new_status

            self._record_event(ApprovalEvent(
                request_id=request_id,
                event_type="approved" if decision.approved else "rejected",
                before_status=old_status,
                after_status=new_status,
                decision=decision,
                pipeline_id=req.pipeline_id,
                metadata={"decided_by": decision.decided_by, "modifications": decision.modifications},
            ))

            if self._db:
                self._db.execute(
                    "UPDATE approval_requests SET status=?, approvals_received=? WHERE id=?",
                    (new_status.value, req.approvals_received, request_id),
                )
                self._db.commit()

            return req

    def expire(self, request_id: str) -> ApprovalRequest | None:
        """标记审批请求已过期 (超时未处理)"""
        with self._lock:
            req = self._memory.get(request_id)
            if req is None:
                return None
            if req.status != ApprovalStatus.PENDING:
                return None

            old_status = req.status
            # 按升级策略处理
            if req.escalation == EscalationPolicy.AUTO_APPROVE:
                new_status = ApprovalStatus.AUTO_APPROVED
            elif req.escalation == EscalationPolicy.ESCALATE:
                new_status = ApprovalStatus.ESCALATED
            else:
                new_status = ApprovalStatus.EXPIRED  # auto_reject / keep_pending 都算过期
            req.status = new_status

            self._record_event(ApprovalEvent(
                request_id=request_id,
                event_type="expired",
                before_status=old_status,
                after_status=new_status,
                pipeline_id=req.pipeline_id,
                metadata={"escalation": req.escalation.value},
            ))

            if self._db:
                self._db.execute(
                    "UPDATE approval_requests SET status=? WHERE id=?",
                    (new_status.value, request_id),
                )
                self._db.commit()

            return req

    def revoke(self, request_id: str, reason: str = "") -> ApprovalRequest | None:
        """撤销审批请求 (pipeline 中止时)"""
        with self._lock:
            req = self._memory.get(request_id)
            if req is None:
                return None
            old_status = req.status
            req.status = ApprovalStatus.REVOKED
            self._record_event(ApprovalEvent(
                request_id=request_id,
                event_type="revoked",
                before_status=old_status,
                after_status=ApprovalStatus.REVOKED,
                pipeline_id=req.pipeline_id,
                metadata={"reason": reason},
            ))
            if self._db:
                self._db.execute(
                    "UPDATE approval_requests SET status=? WHERE id=?",
                    (ApprovalStatus.REVOKED.value, request_id),
                )
                self._db.commit()
            return req

    # ── 事件审计 ────────────────────────────────────────────────

    def get_events(self, request_id: str) -> list[ApprovalEvent]:
        with self._lock:
            return [e for e in self._events if e.request_id == request_id]

    def get_all_events(self) -> list[ApprovalEvent]:
        with self._lock:
            return list(self._events)

    def _record_event(self, event: ApprovalEvent) -> None:
        self._events.append(event)
        if self._db:
            self._db.execute(
                """INSERT INTO approval_events
                (id, request_id, event_type, before_status, after_status,
                 decision_json, timestamp, pipeline_id, metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    event.id, event.request_id, event.event_type,
                    event.before_status.value if event.before_status else None,
                    event.after_status.value,
                    event.decision.model_dump_json() if event.decision else None,
                    event.timestamp.isoformat(),
                    event.pipeline_id,
                    json.dumps(event.metadata),
                ),
            )
            self._db.commit()

    # ── 超时检查 ────────────────────────────────────────────────

    async def expire_overdue(self) -> int:
        """检查所有 pending 请求, 标记已过期的。返回过期数量。"""
        expired_count = 0
        with self._lock:
            pending_ids = [
                rid for rid, req in self._memory.items()
                if req.status == ApprovalStatus.PENDING and req.is_expired()
            ]
        for rid in pending_ids:
            result = self.expire(rid)
            if result:
                expired_count += 1
                logger.info("ApprovalStore: expired request %s (pipeline %s)", rid, result.pipeline_id)
        return expired_count

    def cleanup_old_events(self, max_age_hours: int = 72) -> int:
        """清理旧事件。返回清理数量。"""
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
        with self._lock:
            before = len(self._events)
            self._events = [
                e for e in self._events
                if e.timestamp.timestamp() > cutoff
            ]
            return before - len(self._events)
