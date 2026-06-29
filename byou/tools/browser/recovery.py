"""Browser Execution Subsystem — Recovery Policy.

将浏览器错误映射为恢复动作:
- retry / retry_with_fallback / skip / abort
- 支持指数退避
- 支持 escalation (多次重试后升级)
"""

from __future__ import annotations

import asyncio

from byou.tools.browser.types import (
    BrowserErrorCategory,
    RecoveryAction,
    RecoveryMapping,
)

# ── Default recovery mappings ────────────────────
# (error_category, max_retries, recovery_sequence, escalate_on_limit)

DEFAULT_RECOVERY_MAP: dict[BrowserErrorCategory, RecoveryMapping] = {
    BrowserErrorCategory.TIMEOUT: RecoveryMapping(
        error_category=BrowserErrorCategory.TIMEOUT,
        max_retries=2,
        recovery_actions=[RecoveryAction.RETRY, RecoveryAction.REFRESH_PAGE],
        backoff_ms=2000,
        escalate_on_limit=RecoveryAction.SKIP,
    ),
    BrowserErrorCategory.ELEMENT_NOT_FOUND: RecoveryMapping(
        error_category=BrowserErrorCategory.ELEMENT_NOT_FOUND,
        max_retries=2,
        recovery_actions=[RecoveryAction.RETRY_WITH_FALLBACK, RecoveryAction.REFRESH_PAGE, RecoveryAction.SKIP],
        backoff_ms=1000,
        escalate_on_limit=RecoveryAction.SKIP,
    ),
    BrowserErrorCategory.NAVIGATION_FAILED: RecoveryMapping(
        error_category=BrowserErrorCategory.NAVIGATION_FAILED,
        max_retries=1,
        recovery_actions=[RecoveryAction.RETRY, RecoveryAction.NAVIGATE_BACK],
        backoff_ms=3000,
        escalate_on_limit=RecoveryAction.ABORT,
    ),
    BrowserErrorCategory.PAGE_LOAD_FAILED: RecoveryMapping(
        error_category=BrowserErrorCategory.PAGE_LOAD_FAILED,
        max_retries=2,
        recovery_actions=[RecoveryAction.RETRY, RecoveryAction.REFRESH_PAGE],
        backoff_ms=5000,
        escalate_on_limit=RecoveryAction.SKIP,
    ),
    BrowserErrorCategory.ANTI_BOT: RecoveryMapping(
        error_category=BrowserErrorCategory.ANTI_BOT,
        max_retries=0,
        recovery_actions=[RecoveryAction.ABORT],
        backoff_ms=0,
        escalate_on_limit=RecoveryAction.ABORT,
    ),
    BrowserErrorCategory.LOGIN_WALL: RecoveryMapping(
        error_category=BrowserErrorCategory.LOGIN_WALL,
        max_retries=0,
        recovery_actions=[RecoveryAction.SKIP],
        backoff_ms=0,
        escalate_on_limit=RecoveryAction.SKIP,
    ),
    BrowserErrorCategory.NETWORK: RecoveryMapping(
        error_category=BrowserErrorCategory.NETWORK,
        max_retries=3,
        recovery_actions=[RecoveryAction.RETRY],
        backoff_ms=3000,
        escalate_on_limit=RecoveryAction.ABORT,
    ),
    BrowserErrorCategory.BROWSER_CRASH: RecoveryMapping(
        error_category=BrowserErrorCategory.BROWSER_CRASH,
        max_retries=1,
        recovery_actions=[RecoveryAction.RESTART_SESSION],
        backoff_ms=5000,
        escalate_on_limit=RecoveryAction.ABORT,
    ),
    BrowserErrorCategory.INVALID_URL: RecoveryMapping(
        error_category=BrowserErrorCategory.INVALID_URL,
        max_retries=0,
        recovery_actions=[RecoveryAction.ABORT],
        backoff_ms=0,
        escalate_on_limit=RecoveryAction.ABORT,
    ),
    BrowserErrorCategory.UNEXPECTED_REDIRECT: RecoveryMapping(
        error_category=BrowserErrorCategory.UNEXPECTED_REDIRECT,
        max_retries=1,
        recovery_actions=[RecoveryAction.NAVIGATE_BACK, RecoveryAction.RETRY],
        backoff_ms=2000,
        escalate_on_limit=RecoveryAction.SKIP,
    ),
    BrowserErrorCategory.STALE_ELEMENT: RecoveryMapping(
        error_category=BrowserErrorCategory.STALE_ELEMENT,
        max_retries=1,
        recovery_actions=[RecoveryAction.RETRY, RecoveryAction.SKIP],
        backoff_ms=500,
        escalate_on_limit=RecoveryAction.SKIP,
    ),
    BrowserErrorCategory.UNKNOWN: RecoveryMapping(
        error_category=BrowserErrorCategory.UNKNOWN,
        max_retries=0,
        recovery_actions=[RecoveryAction.ABORT],
        backoff_ms=0,
        escalate_on_limit=RecoveryAction.ABORT,
    ),
}


class RecoveryEngine:
    """浏览器错误恢复引擎"""

    def __init__(self, mappings: dict[BrowserErrorCategory, RecoveryMapping] | None = None):
        self._mappings = dict(DEFAULT_RECOVERY_MAP)
        if mappings:
            self._mappings.update(mappings)
        self._error_counts: dict[BrowserErrorCategory, int] = {}

    def get_recovery(
        self, error_category: BrowserErrorCategory, attempt: int
    ) -> tuple[RecoveryAction, int]:
        """返回 (恢复动作, 延迟毫秒)

        Args:
            error_category: 错误类别
            attempt: 当前是第几次尝试 (0-based)
        """
        mapping = self._mappings.get(error_category)
        if not mapping:
            return RecoveryAction.ABORT, 0

        self._error_counts[error_category] = self._error_counts.get(error_category, 0) + 1

        if attempt < mapping.max_retries:
            idx = min(attempt, len(mapping.recovery_actions) - 1)
            action = mapping.recovery_actions[idx]
            delay = mapping.backoff_ms * (2 ** attempt)  # 指数退避
            return action, delay
        else:
            # 升级
            return mapping.escalate_on_limit, mapping.backoff_ms * 4

    def reset_counts(self) -> None:
        self._error_counts.clear()

    async def apply_recovery(
        self,
        error_category: BrowserErrorCategory,
        attempt: int,
        *,
        retry_fn=None,
        refresh_fn=None,
        navigate_back_fn=None,
        restart_fn=None,
    ) -> bool:
        """应用恢复策略。返回 True 表示恢复成功可继续。

        Args:
            error_category: 错误类别
            attempt: 尝试次数
            retry_fn: 重试函数
            refresh_fn: 刷新页面函数
            navigate_back_fn: 返回上一页函数
            restart_fn: 重启会话函数
        """
        action, delay_ms = self.get_recovery(error_category, attempt)

        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)

        try:
            if action == RecoveryAction.RETRY and retry_fn:
                await retry_fn()
                return True
            elif action == RecoveryAction.RETRY_WITH_FALLBACK and retry_fn:
                await retry_fn()
                return True
            elif action == RecoveryAction.REFRESH_PAGE and refresh_fn:
                await refresh_fn()
                return True
            elif action == RecoveryAction.NAVIGATE_BACK and navigate_back_fn:
                await navigate_back_fn()
                return True
            elif action == RecoveryAction.RESTART_SESSION and restart_fn:
                await restart_fn()
                return True
            elif action == RecoveryAction.SKIP:
                return False  # 跳过，但不终止
            elif action == RecoveryAction.ABORT:
                return False  # 终止
        except Exception:
            pass

        return False
