"""AnalyzeWorkflow — Cardio 五段管线（Temporal 底座，单一执行路径）。

extraction -> research -> synthesis -> strategy -> critique
编排 / 进度 emit / 结果包装都在这里；LLM 调用在 activities 中。
strategy 段输入 = 画像 + 原始信息；critique 段输入 = 档案 + 画像 + 策略（不含 research），
与产品设计一致，避免与旧 run_pipeline 逻辑漂移。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from cardio.prompts import ACTIVE_PROMPT_VERSION, STAGE_META
from cardio.temporal.common import AnalyzeInput

_ACT_TIMEOUT = timedelta(minutes=3)
_ACT_RETRY = RetryPolicy(maximum_attempts=3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@workflow.defn(name="CardioAnalyzeWorkflow")
class CardioAnalyzeWorkflow:
    def __init__(self) -> None:
        self.progress: list[dict[str, Any]] = []
        self.status: str = "running"
        self.results: dict[str, Any] = {}

    def _emit(self, event: str, stage: str, **extra: Any) -> None:
        self.progress.append({"event": event, "stage": stage, **extra})

    def _details(self, stage: str) -> dict[str, Any]:
        return (self.results.get(stage) or {}).get("details", {})

    def _build_payload(self, name: str, inp: AnalyzeInput) -> dict[str, Any]:
        base = {"provider": inp.provider, "owner": inp.owner}
        if name == "extraction":
            return {"raw_text": inp.raw_text, **base}
        if name == "research":
            return {"extraction": self._details("extraction"), **base}
        if name == "synthesis":
            return {
                "extraction": self._details("extraction"),
                "research": self._details("research"),
                **base,
            }
        if name == "strategy":
            return {
                "synthesis": self._details("synthesis"),
                "raw_text": inp.raw_text,
                **base,
            }
        if name == "critique":
            return {
                "extraction": self._details("extraction"),
                "synthesis": self._details("synthesis"),
                "strategy": self._details("strategy"),
                **base,
            }
        raise ValueError(f"unknown stage {name}")

    def _wrap(self, name: str, details: dict[str, Any]) -> dict[str, Any]:
        meta = STAGE_META[name]
        return {
            "agent_name": name,
            "label": meta["label"],
            "summary": (details or {}).get("summary", f"{meta['label']}完成"),
            "details": details or {},
            "confidence": (details or {}).get("confidence", 0.0),
            "generated_at": _now(),
        }

    def _final(self, inp: AnalyzeInput) -> dict[str, Any]:
        ext = self._details("extraction")
        profile = {
            "name": ext.get("name", ""),
            "title": ext.get("title", ""),
            "company": ext.get("company", ""),
            "phone": ext.get("phone", ""),
            "email": ext.get("email", ""),
            "industry": ext.get("industry", ""),
            "needs": ext.get("needs", []),
            "tags": ext.get("tags", []),
        }
        return {
            "input_text": inp.raw_text,
            "profile": profile,
            "agent_reports": self.results,
            "completed_at": _now(),
            "prompt_version": ACTIVE_PROMPT_VERSION,
        }

    @workflow.run
    async def run(self, inp: AnalyzeInput) -> dict[str, Any]:
        self._emit("init", "init", progress=2.0, message="接收客户信息")
        # (stage, 完成百分比)
        stages = [
            ("extraction", 20.0),
            ("research", 40.0),
            ("synthesis", 60.0),
            ("strategy", 80.0),
            ("critique", 95.0),
        ]
        for name, pct in stages:
            meta = STAGE_META[name]
            self._emit(
                "stage_start", name, label=meta["label"],
                agent=meta["agent"], progress=max(pct - 15.0, 1.0),
            )
            result = await workflow.execute_activity(
                name,
                self._build_payload(name, inp),
                start_to_close_timeout=_ACT_TIMEOUT,
                retry_policy=_ACT_RETRY,
            )
            report = self._wrap(name, result)
            self.results[name] = report
            self._emit("stage_done", name, report=report, progress=pct)

        self.status = "completed"
        self._emit("done", "done", progress=100.0, message="分析完成")
        return self._final(inp)

    @workflow.query
    def get_progress(self) -> list[dict[str, Any]]:
        return self.progress

    @workflow.query
    def get_status(self) -> str:
        return self.status

    @workflow.query
    def get_snapshot(self) -> dict[str, Any]:
        return {"status": self.status, "progress": self.progress, "results": self.results}
