"""MCP Security — Server Trust 管理。

持续追踪每个 MCP Server 的信任度。
Trust 不是一次审计就定性的, 而是动态更新的:
  - 正常运行时间 up → trust up
  - 异常/违规 up → trust down
  - 重新审计 → trust 重置
"""

from __future__ import annotations

import logging
from datetime import datetime

from .types import (
    RiskLevel,
    ServerTrustRecord,
    ToolViolationEvent,
    TrustLevel,
)

logger = logging.getLogger(__name__)


class TrustManager:
    """Server 信任度管理。

    管理所有已接入 MCP Server 的 trust record。
    在以下时机更新:
    - Server 接入时: 创建初始 record (trust = 0, UNTRUSTED)
    - 审计通过后: trust = audit.trust_score
    - 每次违规: 扣分 + 可能降级
    - 正常运行: 缓慢加分
    """

    def __init__(self):
        self._records: dict[str, ServerTrustRecord] = {}

    # ── CRUD ──────────────────────────────────────

    def register(self, server_name: str) -> ServerTrustRecord:
        """为新 server 创建初始 trust record。"""
        record = ServerTrustRecord(
            server_name=server_name,
            trust_level=TrustLevel.UNTRUSTED,
            trust_score=0,
        )
        record.trust_level = self._score_to_level(record.trust_score)
        self._records[server_name] = record
        return record

    def get(self, server_name: str) -> ServerTrustRecord | None:
        return self._records.get(server_name)

    def get_or_create(self, server_name: str) -> ServerTrustRecord:
        if server_name not in self._records:
            return self.register(server_name)
        return self._records[server_name]

    # ── 审计结果同步 ──────────────────────────────

    def apply_audit_result(
        self,
        server_name: str,
        trust_score: int,
        audit_date: datetime,
    ) -> ServerTrustRecord:
        """将审计结果写入 trust record。"""
        record = self.get_or_create(server_name)
        record.trust_score = trust_score
        record.last_audit = audit_date

        # 根据 trust_score 映射 trust_level
        record.trust_level = self._score_to_level(trust_score)

        logger.info(
            "Trust record updated from audit: server=%s score=%d level=%s",
            server_name, trust_score, record.trust_level.value,
        )

        self._records[server_name] = record
        return record

    # ── 违规处理 ──────────────────────────────────

    def record_violation(self, server_name: str, violation: ToolViolationEvent) -> ServerTrustRecord:
        """记录一次违规, 扣减 trust score。"""
        record = self.get_or_create(server_name)

        penalty = self._violation_penalty(violation)
        record.trust_score = max(0, record.trust_score - penalty)
        record.violation_count += 1
        record.days_since_last_incident = 0
        record.trust_level = self._score_to_level(record.trust_score)
        record.updated_at = datetime.now()

        logger.warning(
            "Trust penalty applied: server=%s violation=%s penalty=%d new_score=%d new_level=%s",
            server_name, violation.violation_type.value, penalty,
            record.trust_score, record.trust_level.value,
        )

        if record.trust_level == TrustLevel.BLACKLISTED:
            logger.critical("Server %s BLACKLISTED due to violations", server_name)

        self._records[server_name] = record
        return record

    # ── 正常运行时加分 ────────────────────────────

    def record_success(self, server_name: str) -> None:
        """记录一次成功调用, 轻微加分。

        加分速度: 每 100 次成功调用 +1 (上限 100)。
        确保正常运行可以缓慢恢复 trust。
        """
        record = self.get_or_create(server_name)
        record.total_calls += 1

        if record.total_calls % 100 == 0:
            record.trust_score = min(100, record.trust_score + 1)
            record.updated_at = datetime.now()

        self._records[server_name] = record

    def record_error(self, server_name: str) -> None:
        """记录一次调用错误。"""
        record = self.get_or_create(server_name)
        record.total_calls += 1
        # recalculate error rate
        if record.total_calls > 0:
            record.error_rate = record.total_calls * (record.error_rate + 1 / record.total_calls)
        self._records[server_name] = record

    # ── 黑名单管理 ────────────────────────────────

    def blacklist(self, server_name: str, reason: str = "") -> ServerTrustRecord:
        """将 server 加入黑名单。"""
        record = self.get_or_create(server_name)
        record.trust_level = TrustLevel.BLACKLISTED
        record.trust_score = 0
        record.updated_at = datetime.now()

        logger.critical("Server BLACKLISTED: server=%s reason=%s", server_name, reason)
        self._records[server_name] = record
        return record

    def quarantine(self, server_name: str, reason: str = "") -> ServerTrustRecord:
        """将 server 隔离。"""
        record = self.get_or_create(server_name)
        record.trust_level = TrustLevel.QUARANTINED
        record.trust_score = max(0, record.trust_score - 30)
        # Override: only QUARANTINED if score in range, else use score-based level
        record.trust_level = self._score_to_level(record.trust_score) if record.trust_score < 30 else TrustLevel.QUARANTINED
        record.updated_at = datetime.now()

        logger.warning("Server QUARANTINED: server=%s reason=%s", server_name, reason)
        self._records[server_name] = record
        return record

    def unquarantine(self, server_name: str) -> ServerTrustRecord:
        """解除隔离。"""
        record = self.get_or_create(server_name)
        if record.trust_level == TrustLevel.QUARANTINED:
            record.trust_level = TrustLevel.PARTIAL
            record.trust_score = max(record.trust_score, 50)
            record.updated_at = datetime.now()
            logger.info("Server unquarantined: %s", server_name)
        self._records[server_name] = record
        return record

    # ── Queries ───────────────────────────────────

    def get_level(self, server_name: str) -> TrustLevel:
        """获取 server 当前信任级别。"""
        r = self._records.get(server_name)
        return r.trust_level if r else TrustLevel.UNTRUSTED

    def list_by_level(self, level: TrustLevel) -> list[str]:
        """列出某信任级别的所有 server。"""
        return [n for n, r in self._records.items() if r.trust_level == level]

    def list_all(self) -> list[ServerTrustRecord]:
        return list(self._records.values())

    # ── Internal ──────────────────────────────────

    @staticmethod
    def _score_to_level(score: int) -> TrustLevel:
        if score <= 0:
            return TrustLevel.BLACKLISTED
        if score < 30:
            return TrustLevel.QUARANTINED
        if score < 60:
            return TrustLevel.UNTRUSTED
        if score < 80:
            return TrustLevel.PARTIAL
        return TrustLevel.FULL

    @staticmethod
    def _violation_penalty(violation: ToolViolationEvent) -> int:
        """根据违规严重程度计算扣分"""
        # import 放函数内，因为 types.py 可导入
        if violation.severity == RiskLevel.CRITICAL:
            return 30
        if violation.severity == RiskLevel.HIGH:
            return 15
        if violation.severity == RiskLevel.MEDIUM:
            return 5
        return 2
