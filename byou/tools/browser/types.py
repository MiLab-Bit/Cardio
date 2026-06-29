"""Browser Execution Subsystem — 强类型数据模型。

定义了 Byou 浏览器执行层的所有核心数据结构。
基于 Playwright 的 accessibility snapshot + DOM extraction 模式。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum, auto
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════
# Browser Action — 浏览器可执行的原子操作
# ═══════════════════════════════════════════════════════════════════

class BrowserActionType(str, Enum):
    """原子操作类型"""
    NAVIGATE = "navigate"           # go to URL
    CLICK = "click"                 # click element
    TYPE = "type"                   # fill input
    SCROLL = "scroll"               # scroll page
    EXTRACT = "extract"             # extract content
    SCREENSHOT = "screenshot"       # take screenshot
    WAIT = "wait"                   # wait for condition
    PRESS_KEY = "press_key"         # keyboard key
    SELECT = "select"               # select dropdown
    HOVER = "hover"                 # hover element
    GO_BACK = "go_back"             # browser back
    REFRESH = "refresh"             # page refresh
    SWITCH_TAB = "switch_tab"       # switch browser tab
    CLOSE_TAB = "close_tab"         # close tab
    RUN_JS = "run_js"               # execute JavaScript
    SCROLL_INTO_VIEW = "scroll_into_view"


class BrowserSelectorType(str, Enum):
    """元素定位方式"""
    TEXT = "text"                    # text=登录
    CSS = "css"                      # .class #id
    ROLE = "role"                    # button[name=提交]
    ARIA_LABEL = "aria_label"        # aria-label
    PLACEHOLDER = "placeholder"      # placeholder text
    TEST_ID = "test_id"              # data-testid
    XPATH = "xpath"
    AUTO = "auto"                    # auto-detect


class BrowserAction(BaseModel):
    """单个浏览器操作"""
    action_type: BrowserActionType
    description: str = ""            # 人类可读描述

    # 目标定位
    selector: str = ""
    selector_type: BrowserSelectorType = BrowserSelectorType.AUTO

    # 动作参数
    value: str = ""                  # 输入文本 / URL / JS code
    timeout_ms: int = 10_000
    wait_after_ms: int = 500         # 执行后等待
    wait_for_navigation: bool = False
    wait_for_selector: str = ""      # 等待某元素出现

    # 元数据
    step_index: int = 0              # 在序列中的位置
    retry_on_failure: bool = True
    continue_on_failure: bool = False  # 失败是否继续


class BrowserActionResult(BaseModel):
    """单个动作执行结果"""
    action: BrowserAction
    success: bool
    error: str = ""
    error_category: str = ""         # timeout / not_found / blocked 等

    # 结果数据
    extracted_text: str = ""
    extracted_links: list[dict[str, str]] = Field(default_factory=list)
    page_url: str = ""
    page_title: str = ""
    screenshot_base64: str = ""      # 可选截图

    # 性能
    elapsed_ms: float = 0
    retry_count: int = 0


# ═══════════════════════════════════════════════════════════════════
# Browser Task — 一次完整的浏览器研究任务
# ═══════════════════════════════════════════════════════════════════

class ResearchMode(str, Enum):
    """研究模式"""
    COMPANY_WEBSITE = "company_website"       # 公司官网研究
    SEARCH_DRIVEN = "search_driven"           # 搜索引擎驱动
    TARGETED_DOMAIN = "targeted_domain"       # 指定站点定向
    DEEP_DIVE = "deep_dive"                   # 深度多页面研究


class BrowserTask(BaseModel):
    """一次浏览器研究任务"""
    task_id: str = ""
    mode: ResearchMode = ResearchMode.SEARCH_DRIVEN
    description: str = ""            # 人类可读任务描述

    # 目标
    target_url: str = ""
    target_urls: list[str] = Field(default_factory=list)
    search_query: str = ""           # 搜索驱动的 key query

    # 执行计划
    actions: list[BrowserAction] = Field(default_factory=list)
    max_steps: int = 15
    max_depth: int = 2               # 最多深入几层链接
    max_total_time_ms: int = 120_000

    # 提取要求
    extract_links: bool = True
    extract_images: bool = False
    extract_forms: bool = False
    screenshot_each_page: bool = False

    # 安全
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    allow_file_download: bool = False
    max_file_size_mb: int = 10

    # Session
    session_id: str = ""
    reuse_session: bool = True       # 复用已有会话
    headless: bool = True

    # 调用方
    caller: str = ""                 # Agent name
    trace_id: str = ""


# ═══════════════════════════════════════════════════════════════════
# Page Snapshot / Extraction
# ═══════════════════════════════════════════════════════════════════

class PageSnapshot(BaseModel):
    """页面快照"""
    url: str
    title: str
    domain: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)

    # 内容摘要
    text_summary: str = ""           # 前 2000 字符
    headings: list[str] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
    forms_detected: int = 0
    images_detected: int = 0

    # 元数据
    content_length: int = 0
    charset: str = ""
    load_time_ms: float = 0

    # 截图引用
    screenshot_path: str = ""        # 文件路径

    # 反爬/异常标记
    is_blocked: bool = False
    has_captcha: bool = False
    is_login_wall: bool = False
    is_error_page: bool = False
    status_code: int = 200


class ExtractedPageData(BaseModel):
    """从页面提取的结构化数据"""
    url: str
    title: str
    extraction_time: datetime = Field(default_factory=datetime.now)

    # 按类型分组
    key_paragraphs: list[str] = Field(default_factory=list)
    key_links: list[dict[str, str]] = Field(default_factory=list)
    contact_info: dict[str, list[str]] = Field(default_factory=dict)  # {emails: [], phones: []}
    tables: list[dict] = Field(default_factory=list)

    # 语义标注
    sections: dict[str, str] = Field(default_factory=dict)  # {"about":"公司简介内容", "products":"..."}
    main_topic: str = ""
    language: str = "zh"
    readability: Literal["clean", "noisy", "sparse"] = "clean"

    # 原始保留
    full_text: str = ""              # 完整文本 (用于 LLM 解析)
    raw_html_hash: str = ""          # 用于去重


class ResearchFinding(BaseModel):
    """单条研究结论"""
    source_url: str
    source_title: str
    finding_type: str = ""           # company_intro / product / contact / news / competitor ...
    content: str
    confidence: float = 1.0
    extracted_at: datetime = Field(default_factory=datetime.now)
    screenshot_ref: str = ""


class BrowserExecutionReport(BaseModel):
    """一次浏览器研究的完整报告"""
    task: BrowserTask
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None

    # 执行记录
    total_steps: int = 0
    success_steps: int = 0
    failed_steps: int = 0
    total_elapsed_ms: float = 0

    # 结果
    pages_visited: list[PageSnapshot] = Field(default_factory=list)
    extracted_data: list[ExtractedPageData] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)

    # Trace
    action_trace: list[BrowserActionResult] = Field(default_factory=list)

    # 错误
    errors: list[str] = Field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    @property
    def summary(self) -> str:
        return (
            f"任务: {self.task.description[:60]}... | "
            f"步骤: {self.success_steps}/{self.total_steps} | "
            f"页面: {len(self.pages_visited)} | "
            f"发现: {len(self.findings)}"
        )


# ═══════════════════════════════════════════════════════════════════
# Session Management
# ═══════════════════════════════════════════════════════════════════

class BrowserSessionState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    BLOCKED = "blocked"              # 被反爬/验证码
    CLOSING = "closing"
    CLOSED = "closed"


class BrowserSessionInfo(BaseModel):
    """浏览器会话状态"""
    session_id: str
    state: BrowserSessionState = BrowserSessionState.IDLE
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)

    # Tab 管理
    tab_count: int = 0
    active_tab_url: str = ""

    # 统计
    total_tasks: int = 0
    total_pages: int = 0
    total_errors: int = 0

    # Config
    headless: bool = True
    user_agent: str = ""
    proxy: str = ""


# ═══════════════════════════════════════════════════════════════════
# Browser Error & Recovery
# ═══════════════════════════════════════════════════════════════════

class BrowserErrorCategory(str, Enum):
    TIMEOUT = "timeout"
    ELEMENT_NOT_FOUND = "element_not_found"
    NAVIGATION_FAILED = "navigation_failed"
    PAGE_LOAD_FAILED = "page_load_failed"
    ANTI_BOT = "anti_bot"            # 反爬/验证码
    LOGIN_WALL = "login_wall"
    NETWORK = "network"
    BROWSER_CRASH = "browser_crash"
    INVALID_URL = "invalid_url"
    UNEXPECTED_REDIRECT = "unexpected_redirect"
    STALE_ELEMENT = "stale_element"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    RETRY = "retry"                  # 重试当前操作
    RETRY_WITH_FALLBACK = "retry_with_fallback"  # 换策略重试
    SKIP = "skip"                    # 跳过这一步继续
    NAVIGATE_BACK = "navigate_back"  # 回到之前页面
    REFRESH_PAGE = "refresh_page"
    RESTART_SESSION = "restart_session"
    ABORT = "abort"                  # 终止任务


class RecoveryMapping(BaseModel):
    """单个错误→恢复策略映射"""
    error_category: BrowserErrorCategory
    max_retries: int = 1
    recovery_actions: list[RecoveryAction] = Field(default_factory=lambda: [RecoveryAction.RETRY])
    backoff_ms: int = 1000
    escalate_on_limit: RecoveryAction = RecoveryAction.ABORT


# ═══════════════════════════════════════════════════════════════════
# Trace / Audit
# ═══════════════════════════════════════════════════════════════════

class BrowserTrace(BaseModel):
    """浏览器执行跟踪"""
    task_id: str
    session_id: str
    started_at: datetime = Field(default_factory=datetime.now)
    actions: list[BrowserActionResult] = Field(default_factory=list)
    pages_visited: list[str] = Field(default_factory=list)  # URL 序列
    total_time_ms: float = 0
    outcome: Literal["completed", "failed", "aborted"] = "completed"

    @property
    def step_count(self) -> int:
        return len(self.actions)

    @property
    def error_count(self) -> int:
        return sum(1 for a in self.actions if not a.success)


# ═══════════════════════════════════════════════════════════════════
# Safety Guard Config
# ═══════════════════════════════════════════════════════════════════

class SafetyPolicy(BaseModel):
    """浏览器安全策略"""
    # 域名白名单/黑名单
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)

    # 操作限制
    max_consecutive_errors: int = 5
    max_total_steps: int = 30
    max_session_duration_ms: int = 300_000  # 5 分钟

    # 内容安全
    block_file_download: bool = True
    block_form_submit: bool = True         # 默认拦截提交
    block_popups: bool = True

    # 敏感数据
    sanitize_screenshots: bool = False
    redact_patterns: list[str] = Field(default_factory=list)
