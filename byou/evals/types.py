"""Byou Evals — 评测 & 轨迹观测子系统.

把 Multi-Agent 流水线变成可评测 / 可重放 / 可回归 / 可比较的系统。
兼容现有 production 层的 tracing / metrics / evaluation。

数据模型全部强类型 — EvalCase → StageScore → PipelineScore → EvalRun → RegressionReport.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────

class EvalSeverity(str, Enum):
    CRITICAL = "critical"  # 管线级阻断，必须拦截
    HIGH = "high"          # 输出质量明显不可接受
    MEDIUM = "medium"      # 可接受但不理想
    LOW = "low"            # 微调建议


class StageName(str, Enum):
    EXTRACTOR = "extractor"
    RESEARCHER = "researcher"
    SYNTHESIZER = "synthesizer"
    STRATEGIST = "strategist"
    CRITIC = "critic"
    PIPELINE = "pipeline"  # workflow 级


class GraderType(str, Enum):
    RULE = "rule"          # 确定性逻辑: 字段完整度 / 格式 / 工具调用合规
    LLM_JUDGE = "llm_judge"  # 语义质量: 策略合理性 / 信息相关性


class RunVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"  # 通过但比 baseline 差
    SKIPPED = "skipped"    # 前置条件不满足


# ── EvalCase ───────────────────────────────────────────────────

class EvalExpectation(BaseModel):
    """单条 case 的期望信号 — 不写死"期望答案"，而是期望特征。"""
    required_fields: list[str] = Field(default_factory=list)   # e.g. ["company_info.name","risk_score"]
    forbidden_tools: list[str] = Field(default_factory=list)    # 不应调用的工具
    expected_capabilities: list[str] = Field(default_factory=list)  # 应该被调用的能力
    min_stages: int = Field(default=3, ge=1, le=5)
    max_latency_ms: int | None = None


class EvalCase(BaseModel):
    """金光案例 / 坏案例 / 边界案例 的统一模型。"""
    case_id: str
    title: str = ""
    description: str = ""

    # 输入载荷 — 直接喂给 Orchestrator.process_pipeline()
    input_payload: dict[str, Any] = Field(default_factory=dict)

    # 期望
    expectation: EvalExpectation = Field(default_factory=EvalExpectation)

    # 标签与分级
    tags: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    priority: int = Field(default=1, ge=1, le=10)
    severity: EvalSeverity = EvalSeverity.MEDIUM

    # CI 行为
    approval_required: bool = False   # CI fail 时需人工审批
    skip_in_ci: bool = False          # CI 快速通道跳过

    # 元数据
    created_at: str = ""
    updated_at: str = ""

    def model_post_init(self, __context) -> None:
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


# ── Stage scores ───────────────────────────────────────────────

class StageScore(BaseModel):
    """单阶段评分。"""
    stage: StageName
    verdict: RunVerdict
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    grader_type: GraderType = GraderType.RULE

    # 细粒度维度
    dimensions: dict[str, float] = Field(default_factory=dict)  # e.g. {"completeness":0.9, "accuracy":0.7}

    # 证据
    reasons: list[str] = Field(default_factory=list)
    tool_calls_expected: list[str] = Field(default_factory=list)
    tool_calls_actual: list[str] = Field(default_factory=list)

    # timing
    elapsed_ms: int = 0


class PipelineScore(BaseModel):
    """管线总评分 — 聚合所有 Stage。"""
    run_id: str
    case_id: str
    stages: dict[str, StageScore] = Field(default_factory=dict)  # stage_name → score
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    verdict: RunVerdict = RunVerdict.SKIPPED
    total_elapsed_ms: int = 0
    cost_estimate: float = 0.0         # 估算成本 (USD)

    @property
    def failed_stages(self) -> list[str]:
        return [k for k, v in self.stages.items() if v.verdict == RunVerdict.FAIL]

    @property
    def degraded_stages(self) -> list[str]:
        return [k for k, v in self.stages.items() if v.verdict == RunVerdict.DEGRADED]


# ── Trace Replay diff ──────────────────────────────────────────

class DiffEntry(BaseModel):
    """单条差异。"""
    field: str                        # e.g. "researcher.tool_calls", "strategist.score"
    baseline_value: Any | None = None
    candidate_value: Any | None = None
    delta: float | None = None        # 数值变化
    is_regression: bool = False       # True = 变差了


class TraceReplayDiff(BaseModel):
    """一次重放 vs baseline 的完整差异集。"""
    run_id: str
    case_id: str
    baseline_run_id: str
    entries: list[DiffEntry] = Field(default_factory=list)
    score_delta: float = 0.0          # overall score 变化 (正值=improvement)
    cost_delta: float = 0.0
    latency_delta_ms: int = 0
    is_regression: bool = False       # score 下降了

    @property
    def regression_count(self) -> int:
        return sum(1 for e in self.entries if e.is_regression)


# ── EvalRun & RegressionReport ─────────────────────────────────

class EvalRun(BaseModel):
    """一次评测运行的结果。"""
    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    model: str = ""
    prompt_version: str = ""
    cases_total: int = 0
    cases_pass: int = 0
    cases_fail: int = 0
    cases_degraded: int = 0
    pipeline_scores: list[PipelineScore] = Field(default_factory=list)
    overall_pass_rate: float = 0.0
    avg_score: float = 0.0
    total_cost: float = 0.0
    is_baseline: bool = False


class RegressionReport(BaseModel):
    """baseline vs candidate 回归报告。"""
    baseline_run: EvalRun | None = None
    candidate_run: EvalRun | None = None
    compared_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # aggregate
    score_delta: float = 0.0
    pass_rate_delta: float = 0.0
    cost_delta: float = 0.0

    # per-case diffs
    diffs: list[TraceReplayDiff] = Field(default_factory=list)

    # verdict
    is_regression: bool = False
    regression_cases: list[str] = Field(default_factory=list)
    improved_cases: list[str] = Field(default_factory=list)

    # CI
    ci_should_block: bool = False     # 回归严重到应该阻止合并
    ci_summary: str = ""


# ── Grader config ──────────────────────────────────────────────

class GraderThresholds(BaseModel):
    """评分阈值 — 用于判定 pass/fail/degraded。"""
    pass_: float = Field(default=0.8, alias="pass")
    warn: float = 0.6   # < warn → fail
    # score >= pass → PASS,   warn ≤ score < pass → DEGRADED,   score < warn → FAIL

    model_config = {"populate_by_name": True}

    def classify(self, score: float) -> RunVerdict:
        if score >= self.pass_:
            return RunVerdict.PASS
        if score >= self.warn:
            return RunVerdict.DEGRADED
        return RunVerdict.FAIL


class GraderConfig(BaseModel):
    """单个 grader 的配置。"""
    stage: StageName
    grader_type: GraderType
    thresholds: GraderThresholds = Field(default_factory=GraderThresholds)
    dimensions: list[str] = Field(default_factory=list)  # 评分维度
    enabled: bool = True
    model: str = ""                                      # LLM judge 用
