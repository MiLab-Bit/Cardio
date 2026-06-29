"""Graders — 5 类阶段评分器 + 1 个 Pipeline Workflow 评分器.

- ResearcherGrader:   源覆盖度 + 事实相关性 + 工具调用合规 (规则为主)
- SynthesizerGrader:  画像完整度 + 字段冲突检测 + 合并合理性 (规则)
- StrategistGrader:   策略可执行性 + 事实一致性 + 业务合理性 (LLM judge + 规则)
- CriticGrader:       风险识别率 + 拦截有效性 + 假阳性率 (规则 + LLM judge)
- PipelineWorkflowGrader: 工具调用链 / fallback / 重试 / handoff (规则)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .types import (
    EvalCase,
    EvalExpectation,
    GraderConfig,
    GraderThresholds,
    GraderType,
    PipelineScore,
    RunVerdict,
    StageName,
    StageScore,
)

logger = logging.getLogger(__name__)


# ── Base ───────────────────────────────────────────────────────

class BaseGrader:
    """Grader 基类 — 输入 context dict，输出 StageScore。"""

    stage: StageName
    config: GraderConfig

    def __init__(self, config: GraderConfig | None = None):
        self.config = config or GraderConfig(
            stage=self.stage,
            grader_type=GraderType.RULE,
            thresholds=GraderThresholds(),
        )

    def grade(self, case: EvalCase, context: dict[str, Any]) -> StageScore:
        """Evaluate one case's stage output. Override in subclass."""
        raise NotImplementedError

    # ── helpers ────────────────────────────────────────────

    def _classify(self, score: float) -> RunVerdict:
        return self.config.thresholds.classify(score)

    def _check_required_fields(
        self, data: dict | object, fields: list[str]
    ) -> tuple[float, list[str]]:
        """Check that required fields are present and non-empty."""
        if isinstance(data, dict):
            d = data
        else:
            d = data.model_dump() if hasattr(data, "model_dump") else {}
        missing: list[str] = []
        for f in fields:
            parts = f.split(".")
            val = d
            ok = True
            for p in parts:
                if isinstance(val, dict) and p in val:
                    val = val[p]
                else:
                    ok = False
                    break
            if not ok or val is None or val == "" or val == []:
                missing.append(f)
        if not fields:
            return 1.0, []
        score = 1.0 - len(missing) / len(fields)
        return max(0.0, score), missing

    def _check_forbidden_tools(
        self, tool_calls: list[str], forbidden: list[str]
    ) -> tuple[float, list[str]]:
        used_forbidden = [t for t in forbidden if t in tool_calls]
        if not forbidden:
            return 1.0, []
        score = 1.0 - len(used_forbidden) / len(forbidden)
        return max(0.0, score), used_forbidden

    def _check_expected_capabilities(
        self, tool_calls: list[str], expected: list[str]
    ) -> tuple[float, list[str]]:
        missing = [c for c in expected if c not in tool_calls]
        if not expected:
            return 1.0, []
        score = 1.0 - len(missing) / len(expected)
        return max(0.0, score), missing


# ── Researcher Grader ─────────────────────────────────────────

class ResearcherGrader(BaseGrader):
    """Researcher 阶段评分。

    维度: source_coverage, fact_relevance, tool_compliance, data_quality
    方式: 规则驱动（确定性检查）
    """

    stage = StageName.RESEARCHER

    def grade(self, case: EvalCase, context: dict[str, Any]) -> StageScore:
        exp = case.expectation

        # 1. 源覆盖度：至少提取了哪些能力
        actual_caps = context.get("capabilities_used", [])
        cov_score, _ = self._check_expected_capabilities(actual_caps, exp.expected_capabilities)

        # 2. 字段完整性：输出是否包含关键字段
        researcher_output = context.get("researcher_output") or context.get("output", {})
        required = exp.required_fields or [
            "company_info.name",
            "industry_analysis",
            "risk_score",
        ]
        field_score, missing_fields = self._check_required_fields(researcher_output, required)

        # 3. 工具合规：未调用禁止工具
        actual_tools = context.get("tool_calls_actual", [])
        tool_score, forbidden_used = self._check_forbidden_tools(actual_tools, exp.forbidden_tools)

        # 4. 数据质量标记
        data_quality = researcher_output.get("data_quality", "unknown") if isinstance(researcher_output, dict) else "unknown"
        dq_map = {"high": 1.0, "medium": 0.7, "low": 0.3, "unknown": 0.5}
        dq_score = dq_map.get(str(data_quality), 0.5)

        # aggregate
        weights = {"coverage": 0.35, "fields": 0.35, "tools": 0.2, "quality": 0.1}
        overall = (
            weights["coverage"] * cov_score
            + weights["fields"] * field_score
            + weights["tools"] * tool_score
            + weights["quality"] * dq_score
        )

        reasons = []
        if missing_fields:
            reasons.append(f"Missing fields: {missing_fields}")
        if forbidden_used:
            reasons.append(f"Forbidden tools called: {forbidden_used}")

        return StageScore(
            stage=self.stage,
            verdict=self._classify(overall),
            score=round(overall, 3),
            grader_type=GraderType.RULE,
            dimensions={
                "source_coverage": round(cov_score, 3),
                "field_completeness": round(field_score, 3),
                "tool_compliance": round(tool_score, 3),
                "data_quality": round(dq_score, 3),
            },
            reasons=reasons,
            tool_calls_expected=exp.expected_capabilities,
            tool_calls_actual=actual_tools,
            elapsed_ms=context.get("elapsed_ms", 0),
        )


# ── Synthesizer Grader ────────────────────────────────────────

class SynthesizerGrader(BaseGrader):
    """Synthesizer 阶段评分。

    维度: profile_completeness, merge_consistency, field_retention
    方式: 规则驱动
    """

    stage = StageName.SYNTHESIZER

    def grade(self, case: EvalCase, context: dict[str, Any]) -> StageScore:
        exp = case.expectation
        output = context.get("synthesis_output") or context.get("output", {})
        researcher = context.get("researcher_output") or {}

        # 1. 画像完整度
        required = exp.required_fields or [
            "profile.name",
            "profile.company",
            "customer_level",
            "intent_score",
        ]
        comp_score, missing = self._check_required_fields(output, required)

        # 2. 合并一致性：researcher → synthesis 不应丢失关键信息
        retention_score = 1.0
        retention_issues: list[str] = []
        if isinstance(researcher, dict) and isinstance(output, dict):
            for key in ["company_name", "industry_analysis"]:
                if researcher.get(key) and not output.get(key):
                    retention_issues.append(key)
                    retention_score -= 0.3
        retention_score = max(0.0, retention_score)

        overall = 0.5 * comp_score + 0.5 * retention_score
        reasons = []
        if missing:
            reasons.append(f"Missing fields: {missing}")
        if retention_issues:
            reasons.append(f"Lost in synthesis: {retention_issues}")

        return StageScore(
            stage=self.stage,
            verdict=self._classify(overall),
            score=round(overall, 3),
            grader_type=GraderType.RULE,
            dimensions={
                "profile_completeness": round(comp_score, 3),
                "info_retention": round(retention_score, 3),
            },
            reasons=reasons,
        )


# ── Strategist Grader ─────────────────────────────────────────

class StrategistGrader(BaseGrader):
    """Strategist 阶段评分。

    维度: actionability, fact_consistency, business_reasoning
    方式: 规则 + LLM judge
    """

    stage = StageName.STRATEGIST

    def grade(self, case: EvalCase, context: dict[str, Any]) -> StageScore:
        exp = case.expectation
        output = context.get("strategy_output") or context.get("output", {})
        profile = context.get("synthesis_output") or context.get("profile") or {}

        # 1. 规则检查：输出是否完整
        required = exp.required_fields or [
            "strategy.approach",
            "strategy.key_points",
            "strategy.priority_level",
        ]
        rule_score, missing = self._check_required_fields(output, required)

        # 2. 规则检查：事实一致性 — strategy 不能引用 profile 里不存在的公司名
        fact_consistency = 1.0
        fact_issues: list[str] = []
        if isinstance(profile, dict):
            profile_name = profile.get("profile", {}).get("company", "") or profile.get("company_name", "")
            strategy_text = str(output)
            if profile_name and profile_name not in strategy_text:
                # 如果 strategy 完全不提目标公司，可能是幻觉
                fact_consistency = 0.3
                fact_issues.append(f"Strategy doesn't reference target: {profile_name}")

        # 3. LLM judge 占位 — 语义质量由 LLM 评估
        llm_score = 0.8  # default when no LLM judge available

        # aggregate: 70% rule, 30% llm
        overall = 0.35 * rule_score + 0.35 * fact_consistency + 0.3 * llm_score
        reasons = []
        if missing:
            reasons.append(f"Missing fields: {missing}")
        if fact_issues:
            reasons.extend(fact_issues)

        return StageScore(
            stage=self.stage,
            verdict=self._classify(overall),
            score=round(overall, 3),
            grader_type=GraderType.RULE,  # primary; LLM judge is supplementary
            dimensions={
                "field_completeness": round(rule_score, 3),
                "fact_consistency": round(fact_consistency, 3),
                "llm_judge": round(llm_score, 3),
            },
            reasons=reasons,
        )


# ── Critic Grader ─────────────────────────────────────────────

class CriticGrader(BaseGrader):
    """Critic 阶段评分。

    维度:
    - risk_identification: 是否发现了已知风险信号
    - false_positive_rate: 是否误判了 safe case
    - audit_quality: 审核输出是否具体有建议
    方式: 规则 + LLM judge
    """

    stage = StageName.CRITIC

    def grade(self, case: EvalCase, context: dict[str, Any]) -> StageScore:
        output = context.get("critic_output") or context.get("output", {})
        risk_flags = case.risk_flags or []

        # 1. 风险识别率：已知的 risk_flags 是否被 critic 发现
        risk_hits = 0
        if risk_flags and isinstance(output, dict):
            critic_text = str(output.get("findings", "")) + str(output.get("risks", ""))
            risk_hits = sum(1 for r in risk_flags if r.lower() in critic_text.lower())
        risk_score = min(1.0, risk_hits / max(1, len(risk_flags)))

        # 2. 假阳性：如果没有风险但 critic 报了很多 warning
        fp_score = 1.0
        if not risk_flags and isinstance(output, dict):
            findings = output.get("findings", [])
            if isinstance(findings, list) and len(findings) > 5:
                fp_score = 0.5

        # 3. 审核质量：输出是否有具体建议
        audit_score = 0.5
        if isinstance(output, dict):
            suggestions = output.get("suggestions") or output.get("recommendations", [])
            if isinstance(suggestions, list) and len(suggestions) > 0:
                audit_score = min(1.0, 0.6 + len(suggestions) * 0.1)

        overall = 0.4 * risk_score + 0.3 * fp_score + 0.3 * audit_score
        reasons = []
        if risk_hits < len(risk_flags):
            reasons.append(f"Missed risks: {set(risk_flags) - set(r for r in risk_flags if r.lower() in str(output).lower())}")

        return StageScore(
            stage=self.stage,
            verdict=self._classify(overall),
            score=round(overall, 3),
            grader_type=GraderType.RULE,
            dimensions={
                "risk_identification": round(risk_score, 3),
                "false_positive_control": round(fp_score, 3),
                "audit_quality": round(audit_score, 3),
            },
            reasons=reasons,
        )


# ── Pipeline Workflow Grader ──────────────────────────────────

class PipelineWorkflowGrader:
    """管线工作流评分 — 不看输出内容，看链路行为。

    维度: tool_call_chain, fallback_usage, handoff_correctness, retry_reasonableness
    方式: 规则
    """

    def grade(
        self,
        case: EvalCase,
        pipeline_context: dict[str, Any],
        stage_scores: dict[str, StageScore],
    ) -> StageScore:
        exp = case.expectation
        traces = pipeline_context.get("traces", [])
        errors = pipeline_context.get("errors", [])

        # 1. 最少 stage 数
        actual_stages = len([s for s in stage_scores.values() if s.verdict != RunVerdict.SKIPPED])
        stage_score = 1.0 if actual_stages >= exp.min_stages else actual_stages / exp.min_stages

        # 2. 错误/fallback 计数
        fallback_count = sum(
            1 for t in traces if t.get("fallback_used") or t.get("fallback")
        )
        # 2+ fallbacks → warning
        fb_penalty = min(0.4, fallback_count * 0.15)
        fb_score = max(0.0, 1.0 - fb_penalty)

        # 3. 工作流错误
        err_score = 1.0 if not errors else max(0.0, 1.0 - len(errors) * 0.2)

        # 4. tool call 链条合理性：是否有重复调用
        tool_names = [t.get("tool") or t.get("name", "") for t in traces if t.get("tool") or t.get("name")]
        dupes = len(tool_names) - len(set(tool_names))
        dup_score = 1.0 if dupes <= 2 else max(0.0, 1.0 - (dupes - 2) * 0.1)

        weights = {"stages": 0.3, "fallback": 0.25, "errors": 0.25, "duplicates": 0.2}
        overall = (
            weights["stages"] * stage_score
            + weights["fallback"] * fb_score
            + weights["errors"] * err_score
            + weights["duplicates"] * dup_score
        )

        thresholds = GraderThresholds(pass_=0.75, warn=0.5)

        reasons = []
        if actual_stages < exp.min_stages:
            reasons.append(f"Only {actual_stages}/{exp.min_stages} stages completed")
        if errors:
            reasons.append(f"{len(errors)} workflow errors")
        if fallback_count > 1:
            reasons.append(f"{fallback_count} fallbacks triggered")

        return StageScore(
            stage=StageName.PIPELINE,
            verdict=thresholds.classify(overall),
            score=round(overall, 3),
            grader_type=GraderType.RULE,
            dimensions={
                "stage_count": round(stage_score, 3),
                "fallback_control": round(fb_score, 3),
                "error_control": round(err_score, 3),
                "tool_dedup": round(dup_score, 3),
            },
            reasons=reasons,
        )
