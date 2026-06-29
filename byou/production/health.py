"""Byou Production — Health Check Manager.

检查范围:
- /health      → 快速检查 (各组件 alive?)
- /health/deep → 深度检查 (LLM ping, Browser, VectorStore, GraphStore, Enrichment)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from byou.production.types import ComponentHealth, HealthLevel, HealthStatus
from byou.production.metrics import get_metrics

# ── 健康检查抽象 ──────────────────────────────────────────

class HealthCheck:
    """单个组件的健康检查"""
    def __init__(self, component: str, required: bool = True):
        self.component = component
        self.required = required

    async def check(self) -> ComponentHealth:
        raise NotImplementedError


class FunctionHealthCheck(HealthCheck):
    """基于回调函数的健康检查"""
    def __init__(self, component: str, fn, required: bool = True):
        super().__init__(component, required)
        self._fn = fn

    async def check(self) -> ComponentHealth:
        start = time.time()
        try:
            result = self._fn()
            if hasattr(result, "__await__"):
                result = await result
            ok = bool(result)
            msg = str(result) if isinstance(result, str) else ("OK" if ok else "FAIL")
            details = result if isinstance(result, dict) else {}
        except Exception as e:
            ok = False
            msg = str(e)
            details = {"error": str(e)}

        latency = (time.time() - start) * 1000
        return ComponentHealth(
            component=self.component,
            level=HealthLevel.OK if ok else (HealthLevel.DEGRADED if not self.required else HealthLevel.UNHEALTHY),
            message=msg,
            latency_ms=round(latency, 2),
            details=details,
        )


# ── Health Check Manager ──────────────────────────────────

class HealthCheckManager:
    """健康检查管理器。

    注册组件检查器，暴露 /health 和 /health/deep。
    """

    def __init__(self):
        self._checks: dict[str, HealthCheck] = {}
        self._deep_checks: dict[str, HealthCheck] = {}
        self._last_result: HealthStatus | None = None

    def register(self, check: HealthCheck, deep: bool = False):
        target = self._deep_checks if deep else self._checks
        target[check.component] = check

    async def quick(self) -> HealthStatus:
        """快速健康检查 — 只跑基本组件"""
        return await self._run(self._checks)

    async def deep(self) -> HealthStatus:
        """深度健康检查 — 跑所有组件"""
        all_checks = {**self._checks, **self._deep_checks}
        return await self._run(all_checks)

    async def _run(self, checks: dict[str, HealthCheck]) -> HealthStatus:
        components: list[ComponentHealth] = []
        has_unhealthy = False
        has_degraded = False

        for comp, check in checks.items():
            try:
                result = await check.check()
                components.append(result)
                if result.level == HealthLevel.UNHEALTHY:
                    has_unhealthy = True
                elif result.level == HealthLevel.DEGRADED:
                    has_degraded = True
            except Exception as e:
                components.append(ComponentHealth(
                    component=comp,
                    level=HealthLevel.UNHEALTHY,
                    message=str(e),
                ))
                has_unhealthy = True

        if has_unhealthy:
            overall = HealthLevel.UNHEALTHY
        elif has_degraded:
            overall = HealthLevel.DEGRADED
        else:
            overall = HealthLevel.OK

        metrics = get_metrics()
        status = HealthStatus(
            overall=overall,
            components=components,
            uptime_seconds=metrics.uptime_seconds,
            pipeline_count=int(metrics.pipelines_total.get({"status": "success"}) or 0),
        )
        self._last_result = status
        return status

    @property
    def last(self) -> HealthStatus | None:
        return self._last_result


# ── 全局单例 ──────────────────────────────────────────────

_manager: HealthCheckManager | None = None


def get_health() -> HealthCheckManager:
    global _manager
    if _manager is None:
        _manager = HealthCheckManager()
    return _manager
