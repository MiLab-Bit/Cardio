"""Evals Runner — 完整评测运行引擎。

编排流程:
1. 加载数据集
2. 逐 case 执行 pipeline → 收集 StageScore
3. 按 case 聚合 → PipelineScore
4. 按 run 聚合 → EvalRun
5. 与 baseline 对比 → RegressionReport
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from .types import (
    EvalCase,
    EvalRun,
    PipelineScore,
    RegressionReport,
    RunVerdict,
    StageName,
    StageScore,
    TraceReplayDiff,
)
from .datasets import DatasetLoader
from .graders import (
    ResearcherGrader,
    SynthesizerGrader,
    StrategistGrader,
    CriticGrader,
    PipelineWorkflowGrader,
)
from .replay import TraceReplayer
from .baselines import BaselineManager

logger = logging.getLogger(__name__)


class EvalRunner:
    """Run eval cases and produce scores."""

    def __init__(
        self,
        dataset_loader: DatasetLoader | None = None,
        baseline_mgr: BaselineManager | None = None,
    ):
        self.datasets = dataset_loader or DatasetLoader()
        self.baselines = baseline_mgr or BaselineManager()
        self.replayer = TraceReplayer()

        self._researcher_grader = ResearcherGrader()
        self._synthesizer_grader = SynthesizerGrader()
        self._strategist_grader = StrategistGrader()
        self._critic_grader = CriticGrader()
        self._pipeline_grader = PipelineWorkflowGrader()

    # ── Run ────────────────────────────────────────────

    def run_sync(
        self,
        cases: list[EvalCase],
        *,
        model: str = "",
        prompt_version: str = "",
        run_orchestrator: Any = None,  # Orchestrator or callable
        baseline_name: str | None = None,
    ) -> EvalRun:
        """Synchronous eval run (calls async run)."""
        return asyncio.run(self.run(
            cases,
            model=model,
            prompt_version=prompt_version,
            run_orchestrator=run_orchestrator,
            baseline_name=baseline_name,
        ))

    async def run(
        self,
        cases: list[EvalCase],
        *,
        model: str = "",
        prompt_version: str = "",
        run_orchestrator: Any = None,
        baseline_name: str | None = None,
    ) -> EvalRun:
        """Run full eval against a set of cases.

        Args:
            cases: EvalCase list.
            run_orchestrator: a callable that accepts a PipelineContext-like input
                              and returns PipelineContext. If None, uses dummy scoring.
        Returns:
            EvalRun with aggregated scores.
        """
        run_id = uuid.uuid4().hex[:12]
        run = EvalRun(
            run_id=run_id,
            model=model,
            prompt_version=prompt_version,
            cases_total=len(cases),
        )

        for case in cases:
            try:
                ps = await self._eval_one_case(case, run_id, run_orchestrator)
                run.pipeline_scores.append(ps)
                if ps.verdict == RunVerdict.PASS:
                    run.cases_pass += 1
                elif ps.verdict == RunVerdict.FAIL:
                    run.cases_fail += 1
                elif ps.verdict == RunVerdict.DEGRADED:
                    run.cases_degraded += 1
            except Exception as exc:
                logger.exception("Eval failed for case=%s — %s", case.case_id, exc)
                ps = PipelineScore(
                    run_id=run_id,
                    case_id=case.case_id,
                    overall_score=0.0,
                    verdict=RunVerdict.FAIL,
                )
                run.pipeline_scores.append(ps)
                run.cases_fail += 1

        # Aggregate
        n = run.cases_total or 1
        total_score = sum(ps.overall_score for ps in run.pipeline_scores)
        run.avg_score = round(total_score / n, 4)
        run.overall_pass_rate = round(run.cases_pass / n, 4)
        run.total_cost = round(sum(ps.cost_estimate for ps in run.pipeline_scores), 6)

        # Save as baseline if requested
        if baseline_name:
            self.baselines.save(run, baseline_name)

        return run

    # ── Single case ────────────────────────────────────

    async def _eval_one_case(
        self,
        case: EvalCase,
        run_id: str,
        orchestrator: Any,
    ) -> PipelineScore:
        """Evaluate a single EvalCase through the full pipeline."""
        ps = PipelineScore(run_id=run_id, case_id=case.case_id)

        # Execute pipeline
        context: dict[str, Any] = {}
        if orchestrator is not None:
            try:
                ctx = await orchestrator(case.input_payload)
                context = self._extract_context(ctx)
            except Exception as exc:
                context["error"] = str(exc)
        else:
            # Dry-run mode — use dummy context for grader testing
            context = _dummy_context(case)

        # Grade each stage
        stage_results: dict[str, StageScore] = {}

        for grader, ctx_key in [
            (self._researcher_grader, "researcher_context"),
            (self._synthesizer_grader, "synthesis_context"),
            (self._strategist_grader, "strategy_context"),
            (self._critic_grader, "critic_context"),
        ]:
            stage_ctx = context.get(ctx_key, context)
            try:
                ss = grader.grade(case, stage_ctx)
                stage_results[ss.stage.value] = ss
            except Exception as exc:
                logger.warning("Grader %s failed: %s", grader.stage.value, exc)
                stage_results[grader.stage.value] = StageScore(
                    stage=grader.stage,
                    verdict=RunVerdict.SKIPPED,
                    score=0.0,
                    reasons=[f"Grader error: {exc}"],
                )

        # Pipeline workflow grade
        wf_ss = self._pipeline_grader.grade(case, context, stage_results)
        stage_results[wf_ss.stage.value] = wf_ss

        ps.stages = stage_results

        # Aggregate overall score from stage scores
        weights: dict[str, float] = {
            "researcher": 0.3,
            "synthesizer": 0.15,
            "strategist": 0.2,
            "critic": 0.2,
            "pipeline": 0.15,
        }
        overall = sum(
            weights.get(k, 0) * ss.score
            for k, ss in stage_results.items()
            if ss.verdict != RunVerdict.SKIPPED
        )
        # Normalize
        used = sum(
            weights.get(k, 0)
            for k, ss in stage_results.items()
            if ss.verdict != RunVerdict.SKIPPED
        )
        if used > 0:
            overall = overall / used
        ps.overall_score = round(overall, 3)

        # Verdict
        fails = [k for k, v in stage_results.items() if v.verdict == RunVerdict.FAIL]
        if fails:
            ps.verdict = RunVerdict.FAIL
        elif any(v.verdict == RunVerdict.DEGRADED for v in stage_results.values()):
            ps.verdict = RunVerdict.DEGRADED
        else:
            ps.verdict = RunVerdict.PASS

        # Capture for replay
        self.replayer.capture(run_id, ps, context)

        return ps

    # ── Helpers ────────────────────────────────────────

    def _extract_context(self, ctx: Any) -> dict[str, Any]:
        """Extract grading context from a PipelineContext or dict."""
        if isinstance(ctx, dict):
            return ctx
        result: dict[str, Any] = {}
        if hasattr(ctx, "research_result"):
            result["researcher_output"] = ctx.research_result
            result["researcher_context"] = {
                "output": ctx.research_result or {},
                "capabilities_used": getattr(ctx, "_capabilities_used", []),
                "tool_calls_actual": getattr(ctx, "_tool_calls", []),
            }
        if hasattr(ctx, "synthesis_result"):
            result["synthesis_output"] = ctx.synthesis_result
            result["synthesis_context"] = {
                "output": ctx.synthesis_result or {},
                "researcher_output": result.get("researcher_output", {}),
            }
        if hasattr(ctx, "strategy_result"):
            result["strategy_output"] = ctx.strategy_result
            result["strategy_context"] = {
                "output": ctx.strategy_result or {},
                "profile": ctx.synthesis_result if hasattr(ctx, "synthesis_result") else {},
            }
        if hasattr(ctx, "critique_result"):
            result["critic_output"] = getattr(ctx, "critique_result", {})
            result["critic_context"] = {"output": result["critic_output"]}
        if hasattr(ctx, "errors"):
            errs = ctx.errors if isinstance(ctx.errors, list) else [str(ctx.errors)]
            result["errors"] = errs
            result["traces"] = getattr(ctx, "_tool_traces", [])
        return result


def _dummy_context(case: EvalCase) -> dict[str, Any]:
    """Build a dummy context for dry-run eval (no real orchestrator)."""
    return {
        "researcher_context": {
            "output": {
                "company_info": {"name": "阿里巴巴", "status": "active"},
                "industry_analysis": "电子商务/云计算龙头",
                "risk_score": 0.1,
                "data_quality": "high",
            },
            "capabilities_used": ["company_profile", "company_risk"],
            "tool_calls_actual": ["tianyancha.baseinfo", "tianyancha.risk"],
        },
        "synthesis_context": {
            "output": {
                "profile": {"name": "张明", "company": "阿里巴巴", "title": "CTO"},
                "customer_level": "premium",
                "intent_score": 0.85,
            },
            "researcher_output": {"company_name": "阿里巴巴"},
        },
        "strategy_context": {
            "output": {
                "strategy": {
                    "approach": "技术合作路线",
                    "key_points": ["云计算方案", "AI 平台"],
                    "priority_level": "high",
                },
            },
            "profile": {"company_name": "阿里巴巴"},
        },
        "critic_context": {
            "output": {
                "findings": ["公司公开信息充足，来源权威"],
                "risks": [],
                "suggestions": ["联系CTO部门优先接触"],
            },
        },
        "traces": [],
        "errors": [],
    }
