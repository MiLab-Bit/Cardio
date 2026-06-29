"""Byou L3 HITL — 审批类型定义。

所有审批域强类型 Pydantic 模型：
- 请求 / 决策 / 策略 / 通道 / 通知
- 与 Security Gatekeeper 打通 requires_approval
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


# ═══════════════════════════════════════════════════════════════
# 审批模式
# ═══════════════════════════════════════════════════════════════

class ApprovalMode(str, Enum):
    """审批触发模式 — 影响 Pipeline 行为"""
    AUTO = "auto"               # 自动通过, 仅记录 audit log
    DEFER = "defer"             # 继续执行, 事后审查 (异步)
    DEMAND = "demand"           # 暂停 pipeline, 等待审批
    HUMAN_REQUIRED = "human_required"  # 必须人工批准, 超时=拒绝


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ESCALATED = "escalated"     # 超时未处理, 升级到高一级审批者
    AUTO_APPROVED = "auto_approved"
    REVOKED = "revoked"         # 已撤销 (pipeline 中止)


class ApprovalChannel(str, Enum):
    WEBCHAT = "webchat"         # 当前会话内推送
    API = "api"                 # 外部API轮询
    WEBHOOK = "webhook"         # 推送到外部端点
    EMAIL = "email"             # 邮件通知
    WEB_SOCKET = "web_socket"   # WebSocket 实时推送


class ApprovalScope(str, Enum):
    """审批粒度: 单次操作 / Stage / Pipeline"""
    ACTION = "action"           # 单个 MCP 工具调用
    STAGE = "stage"             # 整个 Pipeline Stage
    PIPELINE = "pipeline"       # 整条 Pipeline


class EscalationPolicy(str, Enum):
    """超时未处理时的升级策略"""
    AUTO_APPROVE = "auto_approve"       # 超时自动批准
    AUTO_REJECT = "auto_reject"         # 超时自动拒绝
    ESCALATE = "escalate"               # 升级到上级审批
    KEEP_PENDING = "keep_pending"       # 保持 pend 不处理 (极少用)


# ═══════════════════════════════════════════════════════════════
# 审批请求
# ═══════════════════════════════════════════════════════════════

class ApprovalContext(BaseModel):
    """被审批操作的完整上下文, 供审批人决策"""
    pipeline_id: str
    stage: str
    agent: str = ""
    tool_name: str = ""
    capability: str = ""
    action: str            # e.g. "WRITE_CRM", "generate_bd_strategy"
    input_summary: str = ""  # 输入摘要, 最多 500 字
    risk_level: str = "medium"
    server_name: str = ""
    trace_id: str = ""

    # 追加上下文
    customer_name: str = ""
    company: str = ""
    previous_stages: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    pipeline_id: str
    scope: ApprovalScope = ApprovalScope.ACTION
    mode: ApprovalMode = ApprovalMode.DEMAND
    status: ApprovalStatus = ApprovalStatus.PENDING
    context: ApprovalContext
    message: str = ""                           # 展示给审批人的消息
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None          # None = 不过期
    timeout_s: int = 300                         # 默认 5 分钟超时
    escalation: EscalationPolicy = EscalationPolicy.AUTO_REJECT
    max_approvals: int = 1                       # 需要几个审批人
    approvals_received: int = 0

    @model_validator(mode="after")
    def _set_expires(self) -> "ApprovalRequest":
        if self.expires_at is None and self.timeout_s > 0:
            self.expires_at = self.created_at.timestamp() + self.timeout_s
            self.expires_at = datetime.fromtimestamp(self.expires_at, tz=timezone.utc)
        return self

    def is_expired(self) -> bool:
        if self.timeout_s <= 0:
            return True
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""
    modifications: dict[str, Any] = Field(default_factory=dict)  # e.g. {"max_budget": 5000}
    decided_by: str = ""                                          # 审批人标识
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
# 审批策略
# ═══════════════════════════════════════════════════════════════

class ApprovalPolicyRule(BaseModel):
    """描述"什么样的操作需要什么审批"的规则"""
    name: str
    action_pattern: str = "*"    # glob 匹配 action
    capability_pattern: str = "*"
    stage_pattern: str = "*"     # extraction / research / synthesis / strategy / critique
    tool_pattern: str = "*"

    approval_mode: ApprovalMode = ApprovalMode.DEFER
    timeout_s: int = 300
    channel: ApprovalChannel = ApprovalChannel.WEBCHAT
    escalation: EscalationPolicy = EscalationPolicy.AUTO_REJECT
    max_approvals: int = 1
    priority: int = 0        # 更高 priority 的规则优先匹配

    # 安全联动
    min_risk_level: str = "low"    # risk >= 这个等级才触发
    requires_security_audit: bool = False

    # 审批人约束
    required_roles: list[str] = Field(default_factory=list)
    blocked_roles: list[str] = Field(default_factory=list)     # 不能自己批自己
    cooldown_s: int = 0          # 相同 action 审批间隔


class ApprovalPolicyStore(BaseModel):
    """完整策略表"""
    rules: list[ApprovalPolicyRule] = Field(default_factory=list)
    default_mode: ApprovalMode = ApprovalMode.DEMAND
    default_timeout_s: int = 300


# ═══════════════════════════════════════════════════════════════
# 通知
# ═══════════════════════════════════════════════════════════════

class ApprovalNotification(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    request_id: str                          # 对应的 ApprovalRequest ID
    channel: ApprovalChannel
    title: str
    body: str
    recipient: str = ""                      # 接收者 (email/chat_id/...)
    actions: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"                  # pending / sent / failed


# ═══════════════════════════════════════════════════════════════
# 审批事件 (审计日志用)
# ═══════════════════════════════════════════════════════════════

class ApprovalEvent(BaseModel):
    """审计事件 — 每次审批状态变更都记录"""
    id: str = Field(default_factory=lambda: uuid4().hex[:16])
    request_id: str
    event_type: str                          # created / auto_approved / approved / rejected / expired / escalated / revoked
    before_status: ApprovalStatus | None = None
    after_status: ApprovalStatus
    decision: ApprovalDecision | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pipeline_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
