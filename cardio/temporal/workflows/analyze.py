"""AnalyzeWorkflow — Cardio 五段管线（Temporal 底座）。

extraction -> research -> synthesis -> strategy -> critique
"""
from __future__ import annotations
from datetime import timedelta
from typing import Any
from temporalio import workflow
from temporalio.common import RetryPolicy
from cardio.temporal.common import AnalyzeInput

_ACT_TIMEOUT = timedelta(minutes=3)
_ACT_RETRY = RetryPolicy(maximum_attempts=3)


@workflow.defn(name="CardioAnalyzeWorkflow")
class CardioAnalyzeWorkflow:
    def __init__(self) -> None:
        self.progress: list[dict[str, Any]] = []
        self.status: str = "running"
        self.results: dict[str, Any] = {}

    def _emit(self, stage: str, pct: float, msg: str = "") -> None:
        self.progress.append({"stage": stage, "progress": pct, "message": msg})

    @workflow.run
    async def run(self, inp: AnalyzeInput) -> dict[str, Any]:
        self._emit("init", 2.0, "接收客户信息")
        shared = {"raw_text": inp.raw_text, "provider": inp.provider}

        # 1) extraction
        self._emit("extraction", 20.0, "信息提取")
        self.results["extraction"] = await workflow.execute_activity(
            "extraction", shared,
            start_to_close_timeout=_ACT_TIMEOUT, retry_policy=_ACT_RETRY,
        )

        # 2) research
        self._emit("research", 40.0, "背景调研")
        self.results["research"] = await workflow.execute_activity(
            "research", {**shared, "extraction": self.results["extraction"]},
            start_to_close_timeout=_ACT_TIMEOUT, retry_policy=_ACT_RETRY,
        )

        # 3) synthesis
        self._emit("synthesis", 60.0, "画像合成")
        self.results["synthesis"] = await workflow.execute_activity(
            "synthesis", {**shared, "extraction": self.results["extraction"], "research": self.results["research"]},
            start_to_close_timeout=_ACT_TIMEOUT, retry_policy=_ACT_RETRY,
        )

        # 4) strategy
        self._emit("strategy", 80.0, "BD 策略")
        self.results["strategy"] = await workflow.execute_activity(
            "strategy", {**shared, "synthesis": self.results["synthesis"], "extraction": self.results["extraction"]},
            start_to_close_timeout=_ACT_TIMEOUT, retry_policy=_ACT_RETRY,
        )

        # 5) critique
        self._emit("critique", 95.0, "风险审核")
        self.results["critique"] = await workflow.execute_activity(
            "critique", {**self.results, "provider": inp.provider},
            start_to_close_timeout=_ACT_TIMEOUT, retry_policy=_ACT_RETRY,
        )

        self.status = "completed"
        self._emit("done", 100.0, "分析完成")
        return self._snapshot()

    @workflow.query
    def get_progress(self) -> list[dict[str, Any]]:
        return self.progress

    @workflow.query
    def get_status(self) -> str:
        return self.status

    @workflow.query
    def get_snapshot(self) -> dict[str, Any]:
        return self._snapshot()

    def _snapshot(self) -> dict[str, Any]:
        return {"status": self.status, "progress": self.progress, "results": self.results}
