"""Byou Production — 全类型定义。

横切治理层的所有 Pydantic 数据类型:
- 不引入松散 dict
- 统一 trace_id / run_id / correlation_id
- 覆盖 pipeline / stage / agent / tool 四级粒度
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# 标识
# ═══════════════════════════════════════════════════════════════

class RunIdentity(BaseModel):
    """单次运行的全局身份"""
    trace_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    run_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    parent_trace_id: str | None = None
    correlation_id: str | None = None


# ═══════════════════════════════════════════════════════════════
# 阶段 / 粒度枚举
# ═══════════════════════════════════════════════════════════════

class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    DEGRADED = "degraded"


class HealthLevel(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class Severity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    TIMEOUT = "timeout"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    VALIDATION = "validation"
    DEPENDENCY = "dependency"
    INTERNAL = "internal"
    DEGRADED = "degraded"


# ═══════════════════════════════════════════════════════════════
# 管道运行记录
# ═══════════════════════════════════════════════════════════════

class PipelineRunRecord(BaseModel):
    run_id: str
    trace_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    status: StageStatus = StageStatus.PENDING
    total_duration_ms: float = 0.0
    stages: list[StageRunRecord] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)
    retries: list[RetryRecord] = Field(default_factory=list)
    cost: CostBreakdown = Field(default_factory=lambda: CostBreakdown())
    latency: LatencyBreakdown = Field(default_factory=lambda: LatencyBreakdown())
    quality_score: float | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class StageRunRecord(BaseModel):
    stage_name: str
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    agent_run: AgentRunRecord | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)
    input_summary: str = ""
    output_summary: str = ""


class AgentRunRecord(BaseModel):
    agent_name: str
    status: StageStatus = StageStatus.PENDING
    duration_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    errors: list[ErrorRecord] = Field(default_factory=list)


class ToolCallRecord(BaseModel):
    tool_name: str
    capability: str = ""
    status: StageStatus = StageStatus.PENDING
    duration_ms: float = 0.0
    retry_count: int = 0
    fallback_used: bool = False
    cached: bool = False
    errors: list[ErrorRecord] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 错误 / 重试
# ═══════════════════════════════════════════════════════════════

class ErrorRecord(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: ErrorCategory
    severity: Severity = Severity.ERROR
    message: str
    exception_type: str = ""
    stage: str = ""
    agent: str = ""
    tool: str = ""
    retryable: bool = False
    stack_trace: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


class RetryRecord(BaseModel):
    tool_name: str
    attempt: int
    max_attempts: int
    delay_ms: int
    succeeded: bool
    error_message: str = ""


# ═══════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════

class ComponentHealth(BaseModel):
    component: str
    level: HealthLevel
    message: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthStatus(BaseModel):
    overall: HealthLevel
    components: list[ComponentHealth] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uptime_seconds: float = 0.0
    pipeline_count: int = 0


# ═══════════════════════════════════════════════════════════════
# 成本 / 延迟
# ═══════════════════════════════════════════════════════════════

class CostBreakdown(BaseModel):
    llm_cost_usd: float = 0.0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    api_cost_yuan: float = 0.0
    api_call_count: int = 0
    browser_cost_estimate_usd: float = 0.0
    total_cost_usd: float = 0.0


class LatencyBreakdown(BaseModel):
    total_ms: float = 0.0
    extraction_ms: float = 0.0
    research_ms: float = 0.0
    synthesis_ms: float = 0.0
    strategy_ms: float = 0.0
    critique_ms: float = 0.0
    llm_ms: float = 0.0
    tool_ms: float = 0.0
    browser_ms: float = 0.0
    overhead_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════
# 指标采样
# ═══════════════════════════════════════════════════════════════

class MetricSample(BaseModel):
    name: str
    value: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    labels: dict[str, str] = Field(default_factory=dict)
    unit: str = ""


class MetricsSnapshot(BaseModel):
    samples: list[MetricSample] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
# 评估 / 合约
# ═══════════════════════════════════════════════════════════════

class EvaluationCase(BaseModel):
    case_id: str
    name: str
    description: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    assertions: list[str] = Field(default_factory=list)  # field paths that must match
    tolerance: dict[str, float] = Field(default_factory=dict)  # field→tolerance for numeric compares
    tags: list[str] = Field(default_factory=list)


class AssertionResult(BaseModel):
    assertion: str
    passed: bool
    expected: Any = None
    actual: Any = None
    message: str = ""


class EvaluationResult(BaseModel):
    case: EvaluationCase
    passed: bool
    score: float = 0.0
    assertions: list[AssertionResult] = Field(default_factory=list)
    run_id: str = ""
    duration_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)


class ContractViolation(BaseModel):
    contract_name: str
    severity: Severity
    message: str
    field: str = ""
    expected: Any = None
    actual: Any = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
# 依赖 / 配置
# ═══════════════════════════════════════════════════════════════

class DependencyCheckResult(BaseModel):
    dependency: str
    available: bool
    version: str = ""
    required_version: str = ""
    message: str = ""
    optional: bool = True


class ConfigValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
# 关闭 / 持久化
# ═══════════════════════════════════════════════════════════════

class ShutdownStep(BaseModel):
    step: str
    status: StageStatus
    duration_ms: float = 0.0
    message: str = ""


class ShutdownReport(BaseModel):
    steps: list[ShutdownStep] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    clean: bool = True
    errors: list[str] = Field(default_factory=list)


class PersistenceCheckpoint(BaseModel):
    checkpoint_id: str = Field(default_factory=lambda: uuid4().hex[:8])
    component: str  # "learning_loop", "memory"
    saved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    record_count: int = 0
    bytes_written: int = 0
    success: bool = True
    error: str = ""


# ═══════════════════════════════════════════════════════════════
# 诊断
# ═══════════════════════════════════════════════════════════════

class RuntimeDiagnosticReport(BaseModel):
    report_id: str = Field(default_factory=lambda: uuid4().hex[:8])
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uptime_seconds: float = 0.0
    memory_mb: float = 0.0
    active_pipelines: int = 0
    completed_pipelines: int = 0
    failed_pipelines: int = 0
    open_tool_connections: int = 0
    open_browser_sessions: int = 0
    circuit_breaker_opens: int = 0
    rate_limited_calls: int = 0
    heap_summary: str = ""
    slowest_stages: list[dict[str, Any]] = Field(default_factory=list)
    config_issues: list[str] = Field(default_factory=list)
    dependency_checks: list[DependencyCheckResult] = Field(default_factory=list)
