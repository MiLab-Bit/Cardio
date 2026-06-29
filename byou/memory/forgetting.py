"""Byou Memory — ForgettingPolicy.

智能遗忘与记忆管理 (Phase 3)。

策略:
- PERMANENT 数据永不遗忘
- STABLE 数据仅在新证据出现时更新，不主动遗忘
- VOLATILE 数据按 TTL 过期 (默认 90 天)
- INFERRED 数据按访问频率 + 置信度衰减
- STRATEGY 数据按 success_rate 衰减 (低成功率策略被压缩)

遗忘动作:
- archive: 不删除，标记 is_archived，不再被常规查询命中
- compress: 多条相似记忆合并为一条摘要
- expire: 完全删除

触发:
- 定时任务 (每日凌晨)
- 容量达到阈值
- 手动调用
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from byou.memory.types import MemoryEntry, MemoryTier, DataCategory

logger = logging.getLogger(__name__)


class ForgettingPolicy:
    """智能遗忘策略引擎。

    每种数据类别有自己的衰减曲线。
    """

    def __init__(
        self,
        max_long_term_entries: int = 10000,
        max_strategy_entries: int = 5000,
        volatile_ttl_days: int = 90,
        inferred_ttl_days: int = 180,
        compress_threshold: int = 20,         # 相似记忆超过此数触发压缩
    ):
        self.max_long_term = max_long_term_entries
        self.max_strategy = max_strategy_entries
        self.volatile_ttl = volatile_ttl_days * 86400
        self.inferred_ttl = inferred_ttl_days * 86400
        self.compress_threshold = compress_threshold
        self._last_cleanup = datetime.now(timezone.utc)

    def should_forget(self, entry: MemoryEntry, now: datetime | None = None) -> tuple[bool, str]:
        """判断一条记忆是否应该被遗忘。

        Returns:
            (should_forget, reason)
        """
        now = now or datetime.now(timezone.utc)

        # PERMANENT: never
        if entry.category == DataCategory.PERMANENT:
            return False, ""

        # STABLE: 不主动遗忘
        if entry.category == DataCategory.STABLE:
            return False, ""

        # VOLATILE: TTL
        if entry.category == DataCategory.VOLATILE:
            age = (now - entry.created_at).total_seconds()
            if age > self.volatile_ttl:
                return True, f"VOLATILE expired: age={age / 86400:.0f}d"
            return False, ""

        # INFERRED: 访问频率 + 置信度 衰减
        if entry.category == DataCategory.INFERRED:
            age = (now - entry.created_at).total_seconds()
            if age > self.inferred_ttl:
                return True, f"INFERRED TTL expired: age={age / 86400:.0f}d"

            # 低频访问 + 低置信度 → 提前衰减
            days_since_access = (now - entry.last_accessed_at).total_seconds() / 86400
            if days_since_access > 30 and entry.confidence < 0.5:
                return True, f"INFERRED low confidence + low access"
            return False, ""

        # STRATEGY: success_rate 衰减
        if entry.category == DataCategory.STRATEGY:
            content = entry.content
            success_rate = content.get("success_rate", 0.5)
            total_count = content.get("total_count", 0)
            if success_rate < 0.3 and total_count > 10:
                return True, f"STRATEGY low success rate: {success_rate}"
            return False, ""

        return False, ""

    def compute_decay_factor(self, entry: MemoryEntry, now: datetime | None = None) -> float:
        """计算一条记忆的衰减因子 (0-1)。

        1.0 = 全信, 0.0 = 应遗忘。
        """
        if entry.category == DataCategory.PERMANENT:
            return 1.0

        now = now or datetime.now(timezone.utc)
        age_days = (now - entry.created_at).total_seconds() / 86400

        if entry.category == DataCategory.STABLE:
            # 慢衰减: 每 365 天减 0.1
            return max(0.5, 1.0 - age_days * 0.1 / 365)

        if entry.category == DataCategory.VOLATILE:
            # 快衰减: 指数
            return max(0.0, math.exp(-age_days / self.volatile_ttl * 86400 * 3))

        if entry.category == DataCategory.INFERRED:
            # 中衰减 + 自信度修正
            base = max(0.0, 1.0 - age_days / (self.inferred_ttl / 86400))
            return base * entry.confidence

        if entry.category == DataCategory.STRATEGY:
            total_count = entry.content.get("total_count", 0) if isinstance(entry.content, dict) else 0
            success_rate = entry.content.get("success_rate", 0.5) if isinstance(entry.content, dict) else 0.5
            if total_count == 0:
                return 0.5
            return success_rate

        return 0.5

    def run_cleanup(
        self, entries: list[MemoryEntry],
    ) -> tuple[list[str], list[str], list[str]]:
        """执行一轮清理。

        Returns:
            (archived_ids, compressed_ids, deleted_ids)
        """
        archived: list[str] = []
        compressed: list[str] = []
        deleted: list[str] = []

        now = datetime.now(timezone.utc)

        for entry in entries:
            should_forget, reason = self.should_forget(entry, now)
            if not should_forget:
                continue

            # 决定动作
            if entry.category == DataCategory.VOLATILE:
                # 新闻/舆情 → 直接删除
                deleted.append(entry.id)
            elif entry.category == DataCategory.INFERRED:
                # LLM 推理 → 归档
                archived.append(entry.id)
            elif entry.category == DataCategory.STRATEGY:
                # 低成功率策略 → 压缩
                compressed.append(entry.id)
            else:
                archived.append(entry.id)

        self._last_cleanup = now

        logger.info(
            "Cleanup: archived=%d, compressed=%d, deleted=%d",
            len(archived), len(compressed), len(deleted),
        )
        return archived, compressed, deleted

    def should_compress(self, similar_group: list[MemoryEntry]) -> bool:
        """是否该压缩一组相似记忆"""
        return len(similar_group) >= self.compress_threshold

    def compress_group(self, similar_entries: list[MemoryEntry]) -> MemoryEntry:
        """将一组相似记忆压缩为一条摘要"""
        if not similar_entries:
            raise ValueError("No entries to compress")

        # 合并 content
        merged_content: dict[str, Any] = {}
        all_keys = set()
        for entry in similar_entries:
            if isinstance(entry.content, dict):
                all_keys.update(entry.content.keys())

        for key in all_keys:
            values = [
                e.content.get(key) for e in similar_entries
                if isinstance(e.content, dict) and key in e.content
            ]
            if not values:
                continue
            # 简单策略: 取最新的非空值
            values = [v for v in values if v is not None]
            merged_content[key] = values[-1] if values else None

        merged_content["_compressed_from"] = len(similar_entries)
        merged_content["_compressed_at"] = datetime.now(timezone.utc).isoformat()
        merged_content["_original_ids"] = [e.id for e in similar_entries]

        return MemoryEntry(
            tier=similar_entries[0].tier,
            category=similar_entries[0].category,
            key=f"compressed_{similar_entries[0].key}",
            content=merged_content,
            confidence=sum(e.confidence for e in similar_entries) / len(similar_entries),
            source="compression",
        )
