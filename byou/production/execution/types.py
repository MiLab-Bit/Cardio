"""Byou L4 — Durable Execution 强类型模型。

Checkpoint / Recovery / Replay / Rerun / Idempotency / Signal — 全部 Pydantic。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field

# ── Run / Stage 状态枚举 ──────────────────────────────────────


class RunStatus(str, Enum):
    """Pipeline run 顶层生命周期状态"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_SIGNAL = "waiting_signal"
    RETRYING = "retrying"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REPLAYING = "replaying"

    @property
    def terminal(self) -> bool:
        return self in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)

    @property
    def resumable(self) -> bool:
        return self in (RunStatus.PAUSED, RunStatus.WAITING_SIGNAL, RunStatus.FAILED)


class StageExecStatus(str, Enum):
    """单个 stage 的执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"         # 等待审批/信号
    SKIPPED = "skipped"       # 被跳过
    RETRYING = "retrying"


class RecoveryAction(str, Enum):
    """恢复动作类型"""
    RETRY_STAGE = "retry_stage"
    RESUME_RUN = "resume_run"
    RERUN_FROM_STAGE = "rerun_from_stage"
    RESTART_RUN = "restart_run"
    REPLAY_RUN = "replay_run"
    CANCEL_RUN = "cancel_run"
    ESCALATE = "escalate"


class SignalKind(str, Enum):
    """外部信号类型"""
    APPROVAL_DECISION = "approval_decision"
    WEBHOOK_CALLBACK = "webhook_callback"
    CRM_CALLBACK = "crm_callback"
    HUMAN_INPUT = "human_input"
    TIMER_EXPIRY = "timer_expiry"
    EXTERNAL_EVENT = "external_event"


# ── Identity ──────────────────────────────────────────────────


class RunIdentity(BaseModel):
    """Run 全局标识"""
    run_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    trace_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    parent_run_id: str | None = None
    correlation_id: str | None = None


# ── Pipeline Run State ────────────────────────────────────────


class PipelineRunState(BaseModel):
    """一次 pipeline 运行的完整持久化状态"""
    run_id: str
    trace_id: str
    status: RunStatus = RunStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    paused_at: datetime | None = None
    resumed_at: datetime | None = None
    completed_at: datetime | None = None
    last_heartbeat: datetime | None = None
    current_stage: str | None = None         # 运行到哪个 stage
    current_step: str | None = None          # stage 内子步骤
    pause_reason: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    total_duration_ms: float = 0.0

    # 输入上下文快照
    card_image_path: str | None = None
    audio_file_path: str | None = None
    extra_context: dict[str, Any] = Field(default_factory=dict)
    skip_stages: list[str] = Field(default_factory=list)

    # 审批
    approval_request_id: str | None = None   # 当前审批请求 ID

    # Tags / metadata
    tags: dict[str, str] = Field(default_factory=dict)


class StageExecutionState(BaseModel):
    """单个 stage 的执行状态"""
    run_id: str
    stage_name: str
    status: StageExecStatus = StageExecStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    retry_count: int = 0
    max_retries: int = 3
    error: str | None = None
    agent_name: str = ""
    input_snapshot_ref: str = ""             # 指向 CheckpointRecord.data_ref
    output_snapshot_ref: str = ""
    checkpoint_ids: list[str] = Field(default_factory=list)


# ── Checkpoint ────────────────────────────────────────────────


class CheckpointRecord(BaseModel):
    """一次持久化快照"""
    checkpoint_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    run_id: str
    trace_id: str
    stage: str                              # extraction / research / ...
    step: str | None = None                 # 子步骤: enrichment / browser / synthesis_inner
    status: StageExecStatus = StageExecStatus.SUCCESS
    agent_name: str = ""
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    output_snapshot: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    resumable: bool = True                  # 是否可作为恢复点
    data_ref: str = ""                      # 大对象外部引用
    extra: dict[str, Any] = Field(default_factory=dict)
    checkpoint_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResumablePayload(BaseModel):
    """可从 checkpoint 恢复时携带的上下文"""
    run_id: str
    from_stage: str
    from_step: str | None = None
    checkpoint_id: str
    stage_results: dict[str, Any] = Field(default_factory=dict)
    # PipelineContext 的可序列化快照
    ctx_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Recovery ──────────────────────────────────────────────────


class RecoveryPlan(BaseModel):
    """恢复计划 — 决定怎么从失败中恢复"""
    run_id: str
    current_status: RunStatus
    failed_stage: str | None = None
    suggested_action: RecoveryAction = RecoveryAction.RETRY_STAGE
    available_checkpoints: list[str] = Field(default_factory=list)
    resume_from_checkpoint: str | None = None
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecoveryDecision(BaseModel):
    """恢复执行结果"""
    run_id: str
    action: RecoveryAction
    success: bool
    resumed_at: datetime | None = None
    new_status: RunStatus | None = None
    message: str = ""
    duration_ms: float = 0.0


# ── Replay ────────────────────────────────────────────────────


class ReplayRequest(BaseModel):
    """回放请求"""
    run_id: str
    from_stage: str | None = None           # None → 从第一个 stage 重放
    compare_with: str | None = None         # 跟哪个 run 比较
    dry_run: bool = True                    # True → 只分析不执行副作用
    max_retries: int = 3


class ReplayResult(BaseModel):
    """回放结果"""
    request: ReplayRequest
    success: bool
    original_run_id: str
    replayed_run_id: str | None = None
    stages_replayed: int = 0
    stages_diverged: int = 0
    stages_passed: int = 0
    stages_failed: int = 0
    divergence_details: list[dict[str, Any]] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)


# ── Rerun ─────────────────────────────────────────────────────


class RerunRequest(BaseModel):
    """从中间 stage 重跑请求"""
    run_id: str
    from_stage: str                         # 从哪个 stage 开始重跑
    reuse_checkpoints: bool = True          # True → 复用前面成功的 stage 结果
    dry_run: bool = False
    max_retries: int = 3
    allow_side_effects: bool = True


class RerunResult(BaseModel):
    """重跑结果"""
    request: RerunRequest
    success: bool
    new_run_id: str
    reused_stages: list[str] = Field(default_factory=list)
    reran_stages: list[str] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)


# ── Idempotency ───────────────────────────────────────────────


class IdempotencyKey(BaseModel):
    """幂等键"""
    key: str                                # 如 "crm_write:company_123:张三"
    run_id: str
    stage: str
    action: str                             # e.g. "crm_write", "memory_insert"
    resource: str                           # 目标资源标识
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IdempotencyRecord(BaseModel):
    """已完成操作的幂等记录"""
    key: str
    status: str                             # "completed" | "in_progress" | "failed"
    run_id: str
    result_hash: str = ""                   # 结果哈希，用于检测重复
    completed_at: datetime | None = None
    error: str | None = None


# ── External Signal ───────────────────────────────────────────


class ExternalSignal(BaseModel):
    """外部信号 — 用于 resume waiting/paused run"""
    signal_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    run_id: str
    kind: SignalKind
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed: bool = False
    timeout_s: int = 0                      # 0 means unlimited


# ── Lifecycle Event ───────────────────────────────────────────


class RunLifecycleEvent(BaseModel):
    """Run 生命周期事件 — 审计追踪"""
    event_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    run_id: str
    event_type: str                         # created / started / checkpointed / paused / resumed / retried / failed / completed / cancelled / replayed
    from_status: RunStatus | None = None
    to_status: RunStatus | None = None
    stage: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Type aliases ──────────────────────────────────────────────

RunId: TypeAlias = str
CheckpointId: TypeAlias = str
StageName: TypeAlias = str
