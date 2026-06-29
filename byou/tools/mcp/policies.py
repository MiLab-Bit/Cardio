"""MCP Tool Bus — 调用策略引擎。

管理: 超时、重试、熔断器、缓存决策。
每个工具的调用策略由 MCPInvocationPolicy 定义, 策略引擎负责执行。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from byou.tools.mcp.types import (
    CircuitState,
    MCPInvocationPolicy,
    MCPToolError,
    RetryStrategy,
)

logger = logging.getLogger(__name__)


# ── 熔断器 ─────────────────────────────────

@dataclass
class CircuitBreaker:
    """单工具熔断器 (内存态)"""
    tool_name: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    threshold: int = 5
    recovery_ms: int = 30_000

    def on_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def on_failure(self) -> CircuitState:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.threshold:
            self.state = CircuitState.OPEN
            logger.warning("Circuit OPEN for tool=%s (failures=%d)", self.tool_name, self.failure_count)
        return self.state

    def allow_call(self) -> bool:
        """是否允许调用"""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed * 1000 >= self.recovery_ms:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit HALF_OPEN for tool=%s (elapsed=%.0f ms)", self.tool_name, elapsed * 1000)
                return True
            return False
        # HALF_OPEN: 允许一次探测
        return True


# ── 速率限制 ───────────────────────────────

@dataclass
class RateLimiter:
    """滑动窗口速率限制 (内存态)"""
    max_per_minute: int = 60
    _window: list[float] = field(default_factory=list)

    def allow(self) -> bool:
        now = time.monotonic()
        # 清理过期窗口
        self._window = [t for t in self._window if now - t < 60]
        if len(self._window) >= self.max_per_minute:
            return False
        self._window.append(now)
        return True

    def remaining(self) -> int:
        now = time.monotonic()
        self._window = [t for t in self._window if now - t < 60]
        return max(0, self.max_per_minute - len(self._window))


# ── 策略引擎 ───────────────────────────────

class PolicyEngine:
    """统一策略引擎: 熔断 + 限流 + 重试编排。

    每个工具的调用都在这里决策是否可以执行、如何执行、如何重试。
    """

    def __init__(self):
        self._circuits: dict[str, CircuitBreaker] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self._policies: dict[str, MCPInvocationPolicy] = {}

    def register_policy(self, policy: MCPInvocationPolicy) -> None:
        """注册工具的调用策略"""
        self._policies[policy.tool_name] = policy
        # 初始化熔断器
        self._circuits[policy.tool_name] = CircuitBreaker(
            tool_name=policy.tool_name,
            threshold=policy.circuit_breaker_threshold,
            recovery_ms=policy.circuit_breaker_recovery_ms,
        )
        self._limiters[policy.tool_name] = RateLimiter(
            max_per_minute=policy.rate_limit_per_minute,
        )

    def get_policy(self, tool_name: str) -> MCPInvocationPolicy | None:
        return self._policies.get(tool_name)

    def allow_call(self, tool_name: str) -> tuple[bool, str]:
        """检查是否允许调用工具。

        Returns:
            (允许?, 原因)

        检查顺序: 熔断 → 限流 → OK
        """
        # 熔断检查
        cb = self._circuits.get(tool_name)
        if cb and not cb.allow_call():
            return False, f"CircuitBreaker OPEN for {tool_name}"

        # 限流检查
        rl = self._limiters.get(tool_name)
        if rl and not rl.allow():
            return False, f"Rate limit exceeded for {tool_name}"

        return True, "ok"

    def record_success(self, tool_name: str) -> None:
        """记录成功调用"""
        cb = self._circuits.get(tool_name)
        if cb:
            cb.on_success()

    def record_failure(self, tool_name: str) -> None:
        """记录失败调用"""
        cb = self._circuits.get(tool_name)
        if cb:
            state = cb.on_failure()
            if state == CircuitState.OPEN:
                logger.error("CircuitBreaker OPEN for tool=%s", tool_name)

    def circuit_state(self, tool_name: str) -> CircuitState:
        """获取熔断器状态"""
        cb = self._circuits.get(tool_name)
        return cb.state if cb else CircuitState.CLOSED

    async def execute_with_policy(
        self,
        tool_name: str,
        call_fn,
        *args,
        **kwargs,
    ):
        """在策略保护下执行一次工具调用。

        Args:
            tool_name: 工具名
            call_fn: async callable(*args, **kwargs) → result
            *args, **kwargs: 传给 call_fn

        Returns:
            call_fn 的结果

        Raises:
            MCPToolError: 所有重试耗尽后仍失败
        """
        policy = self._policies.get(tool_name)
        if not policy:
            # 无策略 → 直接执行
            return await call_fn(*args, **kwargs)

        last_error: Exception | None = None

        for attempt in range(policy.max_retries + 1):
            try:
                # 限流+熔断前置检查
                allowed, reason = self.allow_call(tool_name)
                if not allowed:
                    from byou.tools.mcp.errors import map_error
                    raise RuntimeError(reason)

                # 超时控制
                timeout = policy.max_timeout_ms / 1000
                result = await asyncio.wait_for(
                    call_fn(*args, **kwargs),
                    timeout=timeout,
                )
                self.record_success(tool_name)
                return result

            except Exception as e:
                last_error = e
                self.record_failure(tool_name)

                # 最后一次尝试 → 不再重试
                if attempt >= policy.max_retries:
                    break

                # 计算重试延迟
                delay = self._calc_delay(policy, attempt)
                logger.warning(
                    "Tool %s failed (attempt %d/%d), retrying in %d ms: %s",
                    tool_name, attempt + 1, policy.max_retries + 1, delay * 1000, e,
                )
                await asyncio.sleep(delay)

        # 所有重试耗尽 → 抛出结构化错误
        from byou.tools.mcp.errors import map_error
        raise map_error(tool_name, last_error or Exception("unknown"))

    @staticmethod
    def _calc_delay(policy: MCPInvocationPolicy, attempt: int) -> float:
        """计算重试延迟 (秒)"""
        base = policy.retry_base_delay_ms / 1000
        max_d = policy.retry_max_delay_ms / 1000

        if policy.retry_strategy == RetryStrategy.FIXED:
            return base
        if policy.retry_strategy == RetryStrategy.EXPONENTIAL:
            return min(base * (2 ** attempt), max_d)
        if policy.retry_strategy == RetryStrategy.LINEAR:
            return min(base * (attempt + 1), max_d)
        return 0
