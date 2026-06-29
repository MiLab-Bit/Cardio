"""MCP Security Governance — 强类型安全模型。

在现有 `byou.tools.mcp.types` 基础上增量增强，
不改动已有类型，而是新增安全专属类型。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────
# 风险等级
# ─────────────────────────────────────────────────────────────


class RiskLevel(str, Enum):
    """Capability / Server 风险等级。

    与 existing ToolCapability 正交:
      同一个 COMPANY_LOOKUP capability 在不同 server 上可以有不同风险等级。
    """
    LOW = "low"            # 纯读取公开信息, 无副作用
    MEDIUM = "medium"      # 读取内部数据, 可能有网络请求
    HIGH = "high"          # 写操作, 修改外部系统
    CRITICAL = "critical"  # 批量外发, 删除, 跨租户

    @property
    def level_value(self) -> int:
        """数值等级, 用于比较。LOW=0, MEDIUM=1, HIGH=2, CRITICAL=3"""
        _map = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
        return _map.get(self, 1)

    def __ge__(self, other: "RiskLevel") -> bool:
        return self.level_value >= other.level_value

    def __le__(self, other: "RiskLevel") -> bool:
        return self.level_value <= other.level_value

    def __gt__(self, other: "RiskLevel") -> bool:
        return self.level_value > other.level_value

    def __lt__(self, other: "RiskLevel") -> bool:
        return self.level_value < other.level_value


class TrustLevel(str, Enum):
    """Server 信任级别"""
    FULL = "full"                  # 官方/内部维护, 完整审计通过
    PARTIAL = "partial"            # 部分审计通过, 有限信任
    UNTRUSTED = "untrusted"        # 默认状态, 未经审计
    QUARANTINED = "quarantined"    # 检测到风险, 不允许接入
    BLACKLISTED = "blacklisted"    # 已知恶意, 永久封禁


class AuditStatus(str, Enum):
    """Onboarding 审计状态"""
    PENDING = "pending"        # 待审计
    IN_PROGRESS = "in_progress"
    PASSED = "passed"          # 通过, 可接入
    CONDITIONAL = "conditional"  # 有条件通过 (e.g. 仅 readonly, 低风险 env)
    FAILED = "failed"          # 不通过


class ApprovalRequirement(str, Enum):
    """审批要求"""
    NONE = "none"              # 无需审批
    LOG_ONLY = "log_only"      # 仅记录, 不阻止
    AUTO_APPROVE = "auto_approve"  # 自动批准 (低风险)
    HUMAN_REQUIRED = "human_required"  # 需要人工审批
    BLOCK = "block"            # 默认拒绝


class ViolationCategory(str, Enum):
    """安全违规类别"""
    OVER_PRIVILEGED = "over_privileged"        # 越权调用
    PROMPT_INJECTION = "prompt_injection"      # 检测到注入
    TOOL_POISONING = "tool_poisoning"           # 工具输出含恶意指令
    UNTRUSTED_SERVER = "untrusted_server"       # 使用未审计服务
    RATE_LIMIT_BYPASS = "rate_limit_bypass"     # 试图绕过限流
    DATA_EXFILTRATION = "data_exfiltration"     # 疑似数据外泄
    AUTH_FAILURE = "auth_failure"               # 鉴权失败
    CAPABILITY_ESCALATION = "capability_escalation"  # 能力升级
    SANDBOX_ESCAPE = "sandbox_escape"           # 沙箱逃逸


# ─────────────────────────────────────────────────────────────
# Server 安全档案
# ─────────────────────────────────────────────────────────────


class McpServerProfile(BaseModel):
    """MCP Server 安全档案。

    Server 注册到 Tool Bus 前必须建立此档案。
    包含: 身份信息、网络范围、数据范围、维护者。
    """
    # 标识
    server_name: str
    display_name: str = ""
    description: str = ""

    # 来源信息
    repo_url: str = ""                  # GitHub repo
    image_ref: str = ""                 # Docker image
    entrypoint_url: str = ""            # 实际 HTTP endpoint
    maintainer: str = ""
    license_: str = Field(default="", alias="license")
    version: str = "0.0.0"

    # 范围声明
    network_scope: list[str] = Field(default_factory=list)   # 允许访问的域名/IP
    data_scope: list[str] = Field(default_factory=list)      # 允许访问的数据类型
    tenant_scope: str = "single"                              # single | multi
    readonly: bool = True

    # 安全属性 (由 audit 流程自动填充)
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    risk_level: RiskLevel = RiskLevel.MEDIUM
    audit_status: AuditStatus = AuditStatus.PENDING
    audit_date: datetime | None = None
    audit_findings_count: int = 0
    high_severity_findings: int = 0

    # 限制
    allowed_capabilities: list[str] = Field(default_factory=list)  # 白名单
    denied_capabilities: list[str] = Field(default_factory=list)   # 黑名单
    max_connections: int = 5
    rate_limit_per_minute: int = 60


class CapabilityRiskProfile(BaseModel):
    """单个 Capability 的风险档案。

    定义: 某个 capability 在不同环境下的风险等级 + 审批要求。
    """
    capability: str                     # ToolCapability 的值
    risk_level: RiskLevel = RiskLevel.LOW
    default_approval: ApprovalRequirement = ApprovalRequirement.NONE
    requires_sandbox: bool = False
    requires_audit: bool = False
    allowed_environments: list[str] = Field(default_factory=lambda: ["production"])
    denied_environments: list[str] = Field(default_factory=list)
    max_calls_per_minute: int = 100
    max_output_size_kb: int = 1024      # 最大工具输出大小
    allow_in_untrusted_context: bool = False  # 是否允许在 untrusted 上下文中调用
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def default_risk_map(cls) -> dict[str, "CapabilityRiskProfile"]:
        """Byou 默认 risk profile 映射表 (low/medium/high/critical)。"""
        return {
            "company_lookup":     cls(capability="company_lookup", risk_level=RiskLevel.LOW),
            "equity_analysis":    cls(capability="equity_analysis", risk_level=RiskLevel.LOW),
            "risk_assessment":    cls(capability="risk_assessment", risk_level=RiskLevel.LOW),
            "web_search":         cls(capability="web_search", risk_level=RiskLevel.MEDIUM),
            "people_search":      cls(capability="people_search", risk_level=RiskLevel.MEDIUM),
            "document_ocr":       cls(capability="document_ocr", risk_level=RiskLevel.MEDIUM),
            "vector_search":      cls(capability="vector_search", risk_level=RiskLevel.LOW),
            "data_enrich":        cls(capability="data_enrich", risk_level=RiskLevel.LOW),
            "browser_automate":   cls(capability="browser_automate", risk_level=RiskLevel.HIGH, requires_sandbox=True),
            "crm_read":           cls(capability="crm_read", risk_level=RiskLevel.MEDIUM),
            "crm_write":          cls(capability="crm_write", risk_level=RiskLevel.HIGH, default_approval=ApprovalRequirement.HUMAN_REQUIRED, requires_audit=True),
            "email_read":         cls(capability="email_read", risk_level=RiskLevel.HIGH),
            "email_send":         cls(capability="email_send", risk_level=RiskLevel.CRITICAL, default_approval=ApprovalRequirement.HUMAN_REQUIRED, requires_audit=True, allow_in_untrusted_context=False),
        }


# ─────────────────────────────────────────────────────────────
# 执行决策 & 审批
# ─────────────────────────────────────────────────────────────


class ToolExecutionDecision(BaseModel):
    """一次工具调用的安全决策结果。

    在 invocation 之前由 PolicyEngine 生成。
    """
    tool_name: str
    capability: str
    caller: str                         # agent name
    trace_id: str
    timestamp: datetime = Field(default_factory=datetime.now)

    # 决策
    allowed: bool
    reason: str = ""

    # 审批
    requires_approval: bool = False
    approval_status: ApprovalRequirement = ApprovalRequirement.NONE
    approval_record_id: str = ""

    # 风险信息
    risk_level: RiskLevel = RiskLevel.LOW
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    is_untrusted_context: bool = False

    # 决策链 (调试用)
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    """高风险操作审批请求"""
    request_id: str
    tool_name: str
    capability: str
    caller: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    reason: str
    created_at: datetime = Field(default_factory=datetime.now)
    ttl_seconds: int = 300             # 审批请求有效期
    auto_reject: bool = False           # 超时自动拒绝


class ApprovalResult(BaseModel):
    """审批结果"""
    request_id: str
    approved: bool
    approved_by: str = ""               # "auto" | "human:admin" | "policy:deny"
    reason: str = ""
    approved_at: datetime = Field(default_factory=datetime.now)
    restrictions: list[str] = Field(default_factory=list)  # "timeout_halved", "output_redacted"


# ─────────────────────────────────────────────────────────────
# 安全事件 & 审计
# ─────────────────────────────────────────────────────────────


class ToolViolationEvent(BaseModel):
    """工具安全违规事件 — 用于 audit trail。

    与 existing AuditEntry (byou.tools.mcp.types) 互补:
      AuditEntry = 正常调用日志
      ToolViolationEvent = 安全违规事件
    """
    event_id: str
    violation_type: ViolationCategory
    tool_name: str
    capability: str = ""
    caller: str = ""
    trace_id: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)

    # 详细信息
    description: str = ""
    evidence: str = ""                  # 证据 (e.g. 匹配到的 injection pattern)
    argument_snapshot: dict[str, Any] = Field(default_factory=dict)
    output_snapshot: str = ""           # 被拦截输出的摘要
    server_name: str = ""

    # 响应
    action_taken: str = ""              # "blocked" | "logged_only" | "quarantined"
    policy_rule: str = ""               # 命中的策略规则
    severity: RiskLevel = RiskLevel.MEDIUM


class McpSecurityFinding(BaseModel):
    """Onboarding 安全扫描发现。

    类似 SAST/DAST finding 的结构。
    """
    finding_id: str
    server_name: str
    scanner: str = ""                   # "mcpscan" | "sast" | "dependency" | "manual"
    title: str
    description: str = ""
    severity: RiskLevel = RiskLevel.MEDIUM
    category: str = ""                  # "dependency" | "secret_leak" | "path_traversal" | ...
    file_path: str = ""                 # 受影响文件/模块
    line_number: int = 0
    evidence: str = ""
    recommendation: str = ""
    is_false_positive: bool = False
    found_at: datetime = Field(default_factory=datetime.now)


class McpServerAudit(BaseModel):
    """一次完整的 Server onboarding 审计结果。

    审计流程执行的快照, 包含所有发现 + 最终决策。
    """
    server_name: str
    server_profile: McpServerProfile
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None

    # 扫描结果
    findings: list[McpSecurityFinding] = Field(default_factory=list)
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    # Capability 风险映射
    capability_risks: dict[str, CapabilityRiskProfile] = Field(default_factory=dict)

    # 最终决策
    decision: AuditStatus = AuditStatus.PENDING
    decision_reason: str = ""
    recommended_restrictions: list[str] = Field(default_factory=list)

    # 信任分 (0-100)
    trust_score: int = 0

    @property
    def is_approved(self) -> bool:
        return self.decision in (AuditStatus.PASSED, AuditStatus.CONDITIONAL)


class ServerTrustRecord(BaseModel):
    """Server 信任追踪记录 — 持续更新的信任档案。

    审计不是一次性的, trust record 会随着运行时间更新:
      - 正常运行时间 → trust 上升
      - 异常/违规 → trust 下降
    """
    server_name: str
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    trust_score: int = 0                # 0-100
    last_audit: datetime | None = None
    violation_count: int = 0
    total_calls: int = 0
    error_rate: float = 0.0
    days_since_last_incident: int = 0
    updated_at: datetime = Field(default_factory=datetime.now)


# ─────────────────────────────────────────────────────────────
# 注入防护
# ─────────────────────────────────────────────────────────────


class InjectionCheckResult(BaseModel):
    """单次注入检查结果"""
    passed: bool
    patterns_matched: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    content_type: str = ""              # "tool_output" | "tool_description" | "server_name"
    confidence: float = 0.0             # 0-1, 注入置信度
    evidence: str = ""


class UntrustedContentMarker(BaseModel):
    """标记为不可信内容的包装器。

    所有 tool output 都必须经过此标记, 才能传给 Agent / LLM。
    防止外部工具返回的文本直接污染 system instruction。
    """
    original_content: str
    source: str = ""                    # tool_name or server_name
    is_untrusted: bool = True
    flags: list[str] = Field(default_factory=list)  # "prompt_injection_risk" | "suspicious_url" | ...
    timestamp: datetime = Field(default_factory=datetime.now)
    sanitized_content: str = ""         # 清洗后的安全版本
    was_sanitized: bool = False
