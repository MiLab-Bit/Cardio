"""MCP Tool Bus — 强类型数据模型。

定义了 Byou 工具总线的所有核心数据结构。
不依赖任何外部 MCP SDK，纯 Pydantic v2。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum, auto
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ═══════════════════════════════════════════════════════════════════
# 工具描述符 — 工具的运行时元数据
# ═══════════════════════════════════════════════════════════════════

class ParameterType(str, Enum):
    """工具参数类型"""
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    FILE = "file"       # 文件路径或二进制


class MCPToolParameter(BaseModel):
    """单个工具参数描述"""
    name: str
    type: ParameterType = ParameterType.STRING
    description: str = ""
    required: bool = False
    default: Any = None
    enum: list[str] | None = None         # 可选值列表
    pattern: str | None = None             # regex 校验
    minimum: float | None = None
    maximum: float | None = None
    items: MCPToolParameter | None = None  # array 的元素类型
    properties: dict[str, MCPToolParameter] | None = None  # object 的子字段


class ToolCategory(str, Enum):
    """工具分类 — 用于过滤和权限控制"""
    BUSINESS_DATA = "business_data"     # 天眼查/企查查
    WEB_SEARCH = "web_search"           # 网页搜索
    CRM = "crm"                         # Salesforce/HubSpot
    KNOWLEDGE = "knowledge"             # 内部知识库
    BROWSER = "browser"                 # 浏览器执行
    COMMUNICATION = "communication"     # 邮件/消息
    FILE_IO = "file_io"                 # 文件读写
    INTERNAL = "internal"               # 系统内部工具
    CUSTOM = "custom"                   # 用户自定义


class ToolCapability(str, Enum):
    """工具能力标签 — Agent 按能力声明依赖，不按具体工具名"""
    COMPANY_LOOKUP = "company_lookup"         # 查公司工商信息
    EQUITY_ANALYSIS = "equity_analysis"       # 股权穿透
    RISK_ASSESSMENT = "risk_assessment"       # 司法/风险
    WEB_SEARCH = "web_search"                 # 通用搜索
    PEOPLE_SEARCH = "people_search"           # 搜索人物
    DOCUMENT_OCR = "document_ocr"            # OCR
    CRM_READ = "crm_read"                     # CRM 读取
    CRM_WRITE = "crm_write"                   # CRM 写入
    EMAIL_SEND = "email_send"                # 发邮件
    EMAIL_READ = "email_read"                # 读邮件
    VECTOR_SEARCH = "vector_search"          # 向量检索
    BROWSER_AUTOMATE = "browser_automate"    # 浏览器自动化
    DATA_ENRICH = "data_enrich"              # 数据增强


class MCPToolDescriptor(BaseModel):
    """完整的工具描述符 — Registry 的核心数据单元。

    一个工具可由多个 descriptor 表示 (同一工具的不同环境/配置)。
    """
    model_config = ConfigDict(frozen=True)  # 不可变，注册后不修改

    # 标识
    name: str                                            # 唯一标识, e.g. "tianyancha.baseinfo"
    display_name: str = ""                               # 人类可读名
    description: str = ""                                # 功能描述
    version: str = "1.0.0"

    # 分类与能力
    category: ToolCategory = ToolCategory.CUSTOM
    capabilities: list[ToolCapability] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # 参数 schema
    parameters: list[MCPToolParameter] = Field(default_factory=list)

    # 来源
    server_name: str = ""                                # 所属 MCP server
    provider: str = ""                                   # 提供方, e.g. "tianyancha", "salesforce"

    # 运行时配置
    is_async: bool = True                                # 是否异步调用
    is_readonly: bool = True                             # 是否只读 (用于安全控制)
    priority: int = 5                                    # 1-10, 优先级 (同类工具选优先级高的)
    max_concurrency: int = 5                             # 最大并发调用数
    timeout_ms: int = 30_000                             # 默认超时 ms
    retry_count: int = 1                                 # 默认重试次数
    rate_limit_per_minute: int = 60                      # 每分钟最大调用次数

    # 环境隔离
    environments: list[str] = Field(default_factory=lambda: ["production"])
    # 标记稳定程度
    stability: Literal["stable", "beta", "experimental"] = "stable"

    # 示例
    example_input: dict[str, Any] = Field(default_factory=dict)
    example_output: dict[str, Any] = Field(default_factory=dict)

    @property
    def key(self) -> str:
        """唯一键: name + version"""
        return f"{self.name}@{self.version}"


# ═══════════════════════════════════════════════════════════════════
# 调用请求 & 结果
# ═══════════════════════════════════════════════════════════════════

class MCPToolCallRequest(BaseModel):
    """工具调用请求"""
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    caller: str = ""                       # 调用方标识 (agent name)
    trace_id: str = ""                     # 链路追踪 ID
    timeout_ms: int | None = None          # 覆盖默认超时
    retry_count: int | None = None         # 覆盖默认重试


class MCPToolCallResult(BaseModel):
    """工具调用成功结果"""
    tool_name: str
    arguments: dict[str, Any]
    data: Any = None                       # 返回数据
    elapsed_ms: float = 0                  # 耗时
    server_name: str = ""
    model_used: str = ""                   # 如果走 LLM, 记录模型名
    fallback_used: bool = False            # 是否走了 fallback
    cached: bool = False                   # 是否命中缓存


# ═══════════════════════════════════════════════════════════════════
# 错误分类
# ═══════════════════════════════════════════════════════════════════

class ErrorCategory(str, Enum):
    """错误大类"""
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    NETWORK = "network"
    VALIDATION = "validation"
    SERVER_ERROR = "server_error"
    NOT_FOUND = "not_found"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


class MCPToolError(Exception):
    """结构化工具错误 — 既是异常又可序列化。

    Usage:
        raise MCPToolError(tool_name="x", category=ErrorCategory.TIMEOUT, message="...")
        try: ... except MCPToolError as e: if e.retryable: retry()
    """

    def __init__(
        self,
        tool_name: str,
        category: ErrorCategory | str,
        message: str,
        *,
        detail: str = "",
        status_code: int | None = None,
        retryable: bool = False,
        suggested_backoff_ms: int = 1000,
        raw_error: str = "",
    ):
        super().__init__(message)
        self.tool_name = tool_name
        self.category = category if isinstance(category, ErrorCategory) else ErrorCategory(category)
        self.message = message
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        self.suggested_backoff_ms = suggested_backoff_ms
        self.raw_error = raw_error

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "category": self.category.value if isinstance(self.category, ErrorCategory) else self.category,
            "message": self.message,
            "detail": self.detail,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "suggested_backoff_ms": self.suggested_backoff_ms,
        }


# ═══════════════════════════════════════════════════════════════════
# 服务器配置
# ═══════════════════════════════════════════════════════════════════

class MCPAuthType(str, Enum):
    """认证方式"""
    API_KEY_HEADER = "api_key_header"        # X-API-Key 头
    API_KEY_QUERY = "api_key_query"          # ?api_key=xxx
    BEARER_TOKEN = "bearer_token"            # Authorization: Bearer
    BASIC_AUTH = "basic_auth"                # Basic Auth
    OAUTH2 = "oauth2"                        # OAuth2
    MCP_STANDARD = "mcp_standard"            # 标准 MCP 协议内置鉴权
    NONE = "none"


class MCPAuthConfig(BaseModel):
    """鉴权配置"""
    auth_type: MCPAuthType = MCPAuthType.API_KEY_HEADER
    header_name: str = "X-API-Key"
    token: str = ""                          # 从 secret manager 注入
    token_env_var: str = ""                  # 环境变量名, e.g. "TYC_API_KEY"
    token_file: str = ""                     # 从文件读取
    oauth_config: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime | None = None


class MCPServerType(str, Enum):
    """MCP 服务器类型"""
    STDIO = "stdio"                          # 标准 MCP 进程
    HTTP = "http"                            # HTTP REST API (py-mcp-min 风格)
    WEBSOCKET = "websocket"                  # WebSocket 长连接
    EMBEDDED = "embedded"                   # 嵌入到 Byou 进程中运行
    SDK_WRAPPER = "sdk_wrapper"             # 非 MCP 协议的 SDK 包装


class MCPServerConfig(BaseModel):
    """单个 MCP 服务器的配置"""
    name: str                                # 唯一标识, e.g. "tianyancha"
    display_name: str = ""
    server_type: MCPServerType = MCPServerType.SDK_WRAPPER
    description: str = ""

    # 连接
    base_url: str = ""
    command: str = ""                        # stdio: e.g. "python -m mcp_server"
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    # 鉴权
    auth: MCPAuthConfig = Field(default_factory=MCPAuthConfig)

    # 运行时
    enabled: bool = True
    max_connections: int = 5
    connect_timeout_ms: int = 10_000
    health_check_interval_s: int = 30

    # 隔离
    environments: list[str] = Field(default_factory=lambda: ["production"])
    allowed_tools: list[str] = Field(default_factory=list)  # 白名单, 空=全部
    denied_tools: list[str] = Field(default_factory=list)   # 黑名单


# ═══════════════════════════════════════════════════════════════════
# 调用策略
# ═══════════════════════════════════════════════════════════════════

class RetryStrategy(str, Enum):
    """重试策略"""
    FIXED = "fixed"              # 固定间隔
    EXPONENTIAL = "exponential"  # 指数退避
    LINEAR = "linear"            # 线性增长
    NONE = "none"                # 不重试


class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"            # 正常
    OPEN = "open"                # 熔断
    HALF_OPEN = "half_open"      # 半开 (尝试恢复)


class MCPInvocationPolicy(BaseModel):
    """单个工具的调用策略"""
    tool_name: str
    max_timeout_ms: int = 30_000
    retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_retries: int = 2
    retry_base_delay_ms: int = 500
    retry_max_delay_ms: int = 10_000
    rate_limit_per_minute: int = 60
    circuit_breaker_threshold: int = 5    # 连续失败 N 次后熔断
    circuit_breaker_recovery_ms: int = 30_000  # 熔断后 N ms 尝试恢复
    enable_cache: bool = False
    cache_ttl_ms: int = 300_000           # 缓存 5 分钟


# ═══════════════════════════════════════════════════════════════════
# 会话管理
# ═══════════════════════════════════════════════════════════════════

class MCPSessionState(str, Enum):
    """会话状态"""
    IDLE = "idle"
    ACTIVE = "active"
    BLOCKED = "blocked"          # 被 rate limit / 熔断
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class MCPSessionInfo(BaseModel):
    """当前会话的快照"""
    server_name: str
    state: MCPSessionState = MCPSessionState.IDLE
    connection_count: int = 0
    active_calls: int = 0
    total_calls: int = 0
    total_errors: int = 0
    last_error: str = ""
    last_activity: datetime | None = None
    circuit_state: CircuitState = CircuitState.CLOSED


# ═══════════════════════════════════════════════════════════════════
# 审计日志
# ═══════════════════════════════════════════════════════════════════

class AuditEventType(str, Enum):
    TOOL_CALL = "tool_call"
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    CIRCUIT_OPEN = "circuit_open"
    SESSION_CREATE = "session_create"
    SESSION_CLOSE = "session_close"
    REGISTRY_UPDATE = "registry_update"


class AuditEntry(BaseModel):
    """单条审计日志"""
    event_type: AuditEventType
    timestamp: datetime = Field(default_factory=datetime.now)
    server_name: str = ""
    tool_name: str = ""
    caller: str = ""
    trace_id: str = ""
    elapsed_ms: float = 0
    result: str = ""         # "success" | "error" | "timeout"
    detail: dict[str, Any] = Field(default_factory=dict)
