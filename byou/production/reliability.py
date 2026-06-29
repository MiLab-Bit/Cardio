"""Byou Production — 可靠性守护层。

统一治理:
- Agent 整体超时
- Stage 级超时
- 强制持久化保护
- 脆弱阶段安全包装
- 并发限制 / backpressure
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from byou.production.types import ErrorCategory, ErrorRecord, Severity, StageStatus

logger = logging.getLogger(__name__)


# ── 超时保护 ──────────────────────────────────────────────

async def with_timeout(
    coro,
    timeout_s: float,
    error_message: str = "Operation timed out",
    stage: str = "",
    agent: str = "",
) -> Any:
    """带超时的协程包装。

    超时时返回 ErrorRecord 而不是抛异常 — 不打断 pipeline。
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        return ErrorRecord(
            category=ErrorCategory.TIMEOUT,
            severity=Severity.WARNING,
            message=error_message,
            stage=stage,
            agent=agent,
            retryable=True,
        )


class StageGuard:
    """Stage 级守护。

    每个 pipeline stage 包装:
    - 超时
    - 错误捕获 & 恢复
    - 耗时记录
    """

    def __init__(
        self,
        stage_name: str,
        timeout_s: float = 60.0,
        allow_degraded: bool = True,
        critical: bool = False,
    ):
        self.stage_name = stage_name
        self.timeout_s = timeout_s
        self.allow_degraded = allow_degraded
        self.critical = critical
        self.start_time: float = 0.0

    async def __aenter__(self):
        self.start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        if exc_type:
            if self.critical:
                logger.exception("Critical stage '%s' failed (%.0fms)", self.stage_name, duration_ms)
                return False  # re-raise
            else:
                logger.error("Stage '%s' failed (%.0fms): %s", self.stage_name, duration_ms, exc_val)
                if self.allow_degraded:
                    return True  # suppress
                return False
        return False

    @property
    def elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000


class PersistenceGuard:
    """持久化安全包装。

    防止写盘失败导致数据丢失:
    - 写前备份旧文件
    - 写临时文件，成功后再 rename
    - 带重试
    - 记录 checkpoint
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def safe_write(
        self,
        path: str,
        content: str,
        component: str = "",
    ) -> dict[str, Any]:
        """安全写入文件。

        Returns:
            {"success": bool, "bytes": int, "error": str, "checkpoint_id": str}
        """
        import os
        import uuid
        from pathlib import Path

        target = Path(path)
        tmp = target.with_suffix(target.suffix + ".tmp")
        backup = target.with_suffix(target.suffix + ".bak")

        for attempt in range(self.max_retries):
            try:
                # 写临时文件
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(content, encoding="utf-8")

                # 备份旧文件
                if target.exists():
                    if backup.exists():
                        backup.unlink()
                    target.rename(backup)

                # 原子 rename
                tmp.rename(target)
                return {
                    "success": True,
                    "bytes": len(content.encode("utf-8")),
                    "checkpoint_id": uuid.uuid4().hex[:8],
                    "attempts": attempt + 1,
                }
            except Exception as e:
                logger.warning("Safe write attempt %d/%d failed: %s", attempt + 1, self.max_retries, e)
                if attempt == self.max_retries - 1:
                    return {
                        "success": False,
                        "bytes": 0,
                        "error": str(e),
                        "checkpoint_id": "",
                        "attempts": attempt + 1,
                    }


# ── 并发限制 ──────────────────────────────────────────────

class ConcurrencyLimiter:
    """并发调用限制器。

    Usage:
        limiter = ConcurrencyLimiter(max_concurrent=5)
        async with limiter:
            await do_work()
    """

    def __init__(self, max_concurrent: int):
        self._sem = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self):
        await self._sem.acquire()
        return self

    async def __aexit__(self, *args):
        self._sem.release()

    @property
    def available(self) -> int:
        return self._sem._value


# ── 全局 Reliability Context ──────────────────────────────

class ReliabilityContext:
    """运行时可靠性上下文。

    追踪:
    - 活跃 pipeline 数
    - 开放连接数
    - 熔断器状态快照
    - 最近错误
    """

    def __init__(self):
        self.active_pipelines: int = 0
        self.open_tool_connections: int = 0
        self.open_browser_sessions: int = 0
        self.circuit_breaker_opens: int = 0
        self.rate_limited_calls: int = 0
        self.recent_errors: list[ErrorRecord] = []
        self.max_recent_errors = 50

    def record_error(self, err: ErrorRecord):
        self.recent_errors.append(err)
        if len(self.recent_errors) > self.max_recent_errors:
            self.recent_errors = self.recent_errors[-self.max_recent_errors:]

    def snapshot(self) -> dict:
        return {
            "active_pipelines": self.active_pipelines,
            "open_tool_connections": self.open_tool_connections,
            "open_browser_sessions": self.open_browser_sessions,
            "circuit_breaker_opens": self.circuit_breaker_opens,
            "rate_limited_calls": self.rate_limited_calls,
            "recent_error_count": len(self.recent_errors),
            "recent_errors_by_category": self._errors_by_category(),
        }

    def _errors_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.recent_errors[-100:]:
            cat = e.category.value if hasattr(e.category, "value") else str(e.category)
            counts[cat] = counts.get(cat, 0) + 1
        return counts


# ── 全局单例 ──────────────────────────────────────────────

_reliability: ReliabilityContext | None = None


def get_reliability() -> ReliabilityContext:
    global _reliability
    if _reliability is None:
        _reliability = ReliabilityContext()
    return _reliability
