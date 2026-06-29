"""Byou L4 — 幂等性保护。

保护非幂等 side-effect:
- CRM 写入 (重复创建)
- Memory 写入 (重复入库)
- Browser 操作 (重复提交)
- Enrichment API 调用 (重复计费)

策略: idempotency key = f"{action}:{resource}:{identity_hash}"

用法:
    guard = IdempotencyGuard(storage)
    key = guard.make_key(run_id, "crm_write", "company_123:张三")

    # 写之前检查
    if guard.is_duplicate(key):
        return  # skip

    # 执行操作...
    # 写之后记录
    guard.record(key, result_hash="abc123", status="completed")
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from .storage import BaseStorage
from .types import IdempotencyKey, IdempotencyRecord

logger = logging.getLogger(__name__)

# ── 需要幂等保护的操作 ─────────────────────────────────────────

_PROTECTED_ACTIONS: set[str] = {
    "crm_write",
    "crm_update",
    "crm_delete",
    "memory_insert",
    "memory_update",
    "browser_form_submit",
    "browser_click_action",
    "enrichment_api_call",
    "external_webhook_send",
    "email_send",
}


class IdempotencyGuard:
    """幂等性守卫"""

    def __init__(self, storage: BaseStorage):
        self._store = storage

    @staticmethod
    def make_key(run_id: str, action: str, resource: str) -> str:
        """生成幂等键。

        key = "{action}:{hash(resource)}_{run_id_suffix}"
        带 run_id 后缀确保同操作不同 run 可以区分。
        """
        resource_hash = hashlib.sha256(resource.encode()).hexdigest()[:12]
        run_suffix = run_id[-6:] if len(run_id) >= 6 else run_id
        return f"{action}:{resource_hash}_{run_suffix}"

    @staticmethod
    def make_resource_hash(*parts: str) -> str:
        """生成资源标识 hash"""
        return hashlib.sha256(":".join(parts).encode()).hexdigest()[:16]

    def is_duplicate(self, key: str) -> bool:
        """检查操作是否已完成 (幂等检测)"""
        rec = self._store.get_idempotency(key)
        if rec is None:
            return False
        if rec.status == "completed":
            logger.debug("Idempotency hit: key=%s — skipping duplicate", key)
            return True
        return False

    def is_completed(self, key: str) -> bool:
        return self.is_duplicate(key)

    def record(
        self,
        key: str,
        run_id: str,
        status: str = "completed",
        result_hash: str = "",
        error: str | None = None,
    ) -> IdempotencyRecord:
        """记录一次操作的完成"""
        rec = IdempotencyRecord(
            key=key,
            status=status,
            run_id=run_id,
            result_hash=result_hash,
            completed_at=datetime.now(timezone.utc),
            error=error,
        )
        self._store.save_idempotency(rec)
        return rec

    def wrap(
        self,
        key: str,
        run_id: str,
        action: str,
        resource: str,
    ) -> tuple[bool, IdempotencyKey]:
        """轻量包装: 检查 → 生成 idempotency key

        返回 (should_execute, ik)。
        should_execute=False → 跳过 (已执行过)。
        """
        ik = IdempotencyKey(
            key=key, run_id=run_id, stage="", action=action, resource=resource,
        )
        return not self.is_duplicate(key), ik


# ── Side-effect 保护包装器 ─────────────────────────────────────


def is_protected_action(action: str) -> bool:
    """判断是否是需要幂等保护的操作"""
    return action in _PROTECTED_ACTIONS


def generate_replay_safe_key(run_id: str, original_run_id: str, action: str, resource: str) -> str:
    """为 replay 生成安全的幂等键 — 加 replay_run_id 前缀避免与原始 run 冲突"""
    return f"replay_{run_id[:8]}:{action}:{resource}_{original_run_id[:6]}"
