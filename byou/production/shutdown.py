"""Byou Production — 优雅关闭协调器。

特性:
- SIGTERM/SIGINT 捕获
- 多阶段关闭:
  1. 停止接收新 pipeline
  2. 等待当前 pipeline 完成 (带超时)
  3. 强制持久化 LearningLoop + Memory
  4. 关闭 Browser sessions
  5. 关闭 MCP ToolBus 连接
  6. 清理临时文件
  7. 报告关闭状态
- 超时保护: 总关闭时间 ≤ graceful_timeout_seconds
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

from byou.production.types import ShutdownReport, ShutdownStep, StageStatus

logger = logging.getLogger(__name__)

# ── 关闭步骤注册 ──────────────────────────────────────────

class _ShutdownStep:
    def __init__(self, name: str, fn: Callable, critical: bool = False, timeout_s: float = 5.0):
        self.name = name
        self.fn = fn
        self.critical = critical
        self.timeout_s = timeout_s


class GracefulShutdown:
    """优雅关闭协调器。

    使用:
        shutdown = GracefulShutdown(timeout_s=15)
        shutdown.register("learning_loop_persist", lambda: learning_loop.persist())
        shutdown.register("browser_cleanup", lambda: browser.close_all())
        shutdown.register("memory_persist", lambda: memory_manager.persist())
        shutdown.install_signal_handlers()
    """

    def __init__(self, timeout_s: float = 30.0):
        self.timeout_s = timeout_s
        self._steps: list[_ShutdownStep] = []
        self._callbacks: list[Callable] = []  # 关闭后回调
        self._shutting_down = False
        self._shutdown_event = asyncio.Event()
        self._report: ShutdownReport | None = None

    # ── 注册 ──────────────────────────────────────────────

    def register(self, name: str, fn: Callable, critical: bool = False, timeout_s: float = 5.0):
        """注册一个关闭步骤。

        Args:
            name: 步骤描述
            fn: 可同步或异步的关闭函数
            critical: 失败后是否终止后续步骤
            timeout_s: 单步超时
        """
        self._steps.append(_ShutdownStep(name, fn, critical, timeout_s))

    def on_shutdown(self, callback: Callable):
        """关闭后回调 (比如写 report 到日志)"""
        self._callbacks.append(callback)

    # ── 安装信号处理器 ────────────────────────────────────

    def install_signal_handlers(self):
        """安装 SIGTERM / SIGINT 处理器"""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.ensure_future(self._handle_signal(s)))
            except NotImplementedError:
                # Windows 不支持 add_signal_handler → 用 signal.signal
                signal.signal(sig, lambda s, f: asyncio.ensure_future(self._handle_signal(s)))

        # Windows 兼容
        if sys.platform == "win32":
            try:
                signal.signal(signal.SIGBREAK, lambda s, f: asyncio.ensure_future(self._handle_signal(s)))
            except AttributeError:
                pass

        logger.info("Shutdown signal handlers installed (SIGTERM, SIGINT)")

    async def _handle_signal(self, sig):
        logger.info("Received signal %s, starting graceful shutdown", sig)
        await self.shutdown()

    # ── 主关闭流程 ──────────────────────────────────────���─

    async def shutdown(self) -> ShutdownReport:
        if self._shutting_down:
            logger.warning("Shutdown already in progress")
            return self._report or ShutdownReport()

        self._shutting_down = True
        report = ShutdownReport()
        start = time.time()

        logger.info("Graceful shutdown starting (%d steps, timeout=%.0fs)",
                     len(self._steps), self.timeout_s)

        for step in self._steps:
            step_start = time.time()
            step_record = ShutdownStep(step=step.name, status=StageStatus.RUNNING)

            try:
                # 总超时检查
                if time.time() - start > self.timeout_s:
                    step_record.status = StageStatus.TIMED_OUT
                    step_record.message = f"Total shutdown timeout ({self.timeout_s}s) reached"
                    report.steps.append(step_record)
                    report.errors.append(step_record.message)
                    break

                # 执行
                result = step.fn()
                if asyncio.iscoroutine(result):
                    result = await asyncio.wait_for(result, timeout=min(step.timeout_s, self.timeout_s - (time.time() - start)))
                step_record.status = StageStatus.SUCCESS
                step_record.message = "OK"

            except asyncio.TimeoutError:
                step_record.status = StageStatus.TIMED_OUT
                step_record.message = f"Step timeout ({step.timeout_s}s)"
                report.errors.append(f"{step.name}: {step_record.message}")
                if step.critical:
                    break
            except Exception as e:
                step_record.status = StageStatus.FAILED
                step_record.message = str(e)
                report.errors.append(f"{step.name}: {e}")
                if step.critical:
                    break

            step_record.duration_ms = round((time.time() - step_start) * 1000, 2)
            report.steps.append(step_record)

        # 后置回调
        for cb in self._callbacks:
            try:
                result = cb()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning("Shutdown callback failed: %s", e)

        report.total_duration_ms = round((time.time() - start) * 1000, 2)
        report.clean = len(report.errors) == 0

        self._report = report
        self._shutdown_event.set()

        logger.info("Shutdown complete: %d steps, %.0fms, clean=%s",
                     len(report.steps), report.total_duration_ms, report.clean)

        return report

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    @property
    def report(self) -> ShutdownReport | None:
        return self._report

    async def wait_for_shutdown(self, timeout_s: float = 30.0):
        """等待关闭完成"""
        await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout_s)


# ── 全局单例 ──────────────────────────────────────────────

_shutdown: GracefulShutdown | None = None


def get_shutdown() -> GracefulShutdown:
    global _shutdown
    if _shutdown is None:
        _shutdown = GracefulShutdown()
    return _shutdown
