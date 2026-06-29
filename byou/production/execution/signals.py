"""Byou L4 — 外部信号恢复。

统一处理 pause/resume 的外部触发:
- 审批决定 (approval_decision)
- Webhook 回调 (webhook_callback)
- CRM 回调 (crm_callback)
- 人工输入 (human_input)
- 定时器过期 (timer_expiry)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .types import (
    ExternalSignal,
    PipelineRunState,
    RunStatus,
    SignalKind,
)

logger = logging.getLogger(__name__)

# ── Signal timeout 默认值 ──────────────────────────────────────

_DEFAULT_TIMEOUTS: dict[SignalKind, int] = {
    SignalKind.APPROVAL_DECISION: 600,     # 10 分钟
    SignalKind.WEBHOOK_CALLBACK: 3600,     # 1 小时
    SignalKind.CRM_CALLBACK: 3600,
    SignalKind.HUMAN_INPUT: 86400,         # 24 小时
    SignalKind.TIMER_EXPIRY: 0,            # 由 timer 自身控制
    SignalKind.EXTERNAL_EVENT: 3600,
}


class SignalManager:
    """外部信号管理器"""

    def __init__(self):
        self._pending: dict[str, ExternalSignal] = {}   # signal_id → ExternalSignal
        self._by_run: dict[str, list[str]] = {}          # run_id → [signal_ids]

    def register_signal(
        self,
        run_id: str,
        kind: SignalKind,
        payload: dict[str, Any] | None = None,
        timeout_s: int | None = None,
    ) -> ExternalSignal:
        """注册一个待处理的外部信号"""
        signal = ExternalSignal(
            run_id=run_id,
            kind=kind,
            payload=payload or {},
            timeout_s=timeout_s if timeout_s is not None else _DEFAULT_TIMEOUTS.get(kind, 300),
        )
        self._pending[signal.signal_id] = signal
        self._by_run.setdefault(run_id, []).append(signal.signal_id)
        logger.info("Signal registered: id=%s run=%s kind=%s timeout=%ds",
                     signal.signal_id, run_id, kind.value, signal.timeout_s)
        return signal

    def resolve_signal(self, signal_id: str) -> ExternalSignal | None:
        """标记信号为已处理"""
        signal = self._pending.pop(signal_id, None)
        if signal:
            signal.processed = True
            logger.info("Signal resolved: id=%s run=%s kind=%s",
                         signal_id, signal.run_id, signal.kind.value)
        return signal

    def resolve_for_run(self, run_id: str, kind: SignalKind | None = None) -> list[ExternalSignal]:
        """解析 run 的所有 pending signals"""
        sig_ids = self._by_run.pop(run_id, [])
        resolved: list[ExternalSignal] = []
        for sid in sig_ids:
            sig = self._pending.pop(sid, None)
            if sig and (kind is None or sig.kind == kind):
                sig.processed = True
                resolved.append(sig)
        return resolved

    def get_pending_for_run(self, run_id: str) -> list[ExternalSignal]:
        return [self._pending[sid] for sid in self._by_run.get(run_id, []) if sid in self._pending]

    def get_expired(self) -> list[ExternalSignal]:
        """获取所有过期的 signals"""
        now = datetime.now(timezone.utc)
        expired: list[ExternalSignal] = []
        for sig in self._pending.values():
            if sig.timeout_s > 0:
                elapsed = (now - sig.received_at).total_seconds()
                if elapsed > sig.timeout_s:
                    expired.append(sig)
        return expired

    def clear_run(self, run_id: str) -> int:
        """清理 run 的所有 signal — 返回清理数"""
        sig_ids = self._by_run.pop(run_id, [])
        count = 0
        for sid in sig_ids:
            if self._pending.pop(sid, None):
                count += 1
        return count

    def __len__(self) -> int:
        return len(self._pending)


# ── Signal-based Resume ────────────────────────────────────────


async def wait_for_external_signal(
    run_id: str,
    signal_manager: SignalManager,
    kind: SignalKind | None = None,
    timeout_s: int = 300,
    poll_interval_s: float = 0.5,
) -> ExternalSignal | None:
    """异步等待外部信号。

    轮询检查 signal 是否已被 resolve。
    超时返回 None。
    """
    elapsed: float = 0.0
    while elapsed < timeout_s:
        resolved = signal_manager.resolve_for_run(run_id, kind=kind)
        if resolved:
            return resolved[0]
        await asyncio.sleep(poll_interval_s)
        elapsed += poll_interval_s

    # 超时
    logger.warning("Signal timeout: run=%s kind=%s timeout=%ds", run_id, kind, timeout_s)
    return None
