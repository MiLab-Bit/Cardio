"""Browser Execution Subsystem — Byou 浏览器执行与网页研究层。

基于 Playwright 原生 API，面向 ResearcherAgent 提供声明式浏览器研究能力。

三种研究模式:
- research_company_website() — 公司官网研究
- search_and_research() — 搜索引擎驱动
- targeted_research() — 指定站点定向

核心组件:
- BrowserTaskExecutor — 浏览器任务执行引擎
- BrowserSessionManager — 会话池管理
- SafetyGuard — 安全护栏
- RecoveryEngine — 错误恢复
- BrowserResearchAdapter — ResearcherAgent 适配器

架构:
    ResearcherAgent → BrowserResearchAdapter → BrowserTaskExecutor
                      ↓                              ↓
                  BrowserTask                   BrowserSession
                      ↓                              ↓
                  (actions[])              Playwright BrowserContext
"""

from byou.tools.browser.types import (
    # 核心任务
    BrowserTask,
    BrowserAction,
    BrowserActionResult,
    ResearchMode,
    # 页面抽取
    PageSnapshot,
    ExtractedPageData,
    ResearchFinding,
    # 报告
    BrowserExecutionReport,
    # Session
    BrowserSessionState,
    BrowserSessionInfo,
    # 安全/恢复
    BrowserErrorCategory,
    RecoveryAction,
    RecoveryMapping,
    SafetyPolicy,
    # Action 类型
    BrowserActionType,
    BrowserSelectorType,
    # Trace
    BrowserTrace,
)

from byou.tools.browser.session import BrowserSession, BrowserSessionManager
from byou.tools.browser.safety import SafetyGuard
from byou.tools.browser.recovery import RecoveryEngine
from byou.tools.browser.executor import BrowserTaskExecutor
from byou.tools.browser.adapter import BrowserResearchAdapter

__all__ = [
    # Types
    "BrowserTask", "BrowserAction", "BrowserActionResult", "ResearchMode",
    "PageSnapshot", "ExtractedPageData", "ResearchFinding",
    "BrowserExecutionReport", "BrowserSessionState", "BrowserSessionInfo",
    "BrowserErrorCategory", "RecoveryAction", "RecoveryMapping", "SafetyPolicy",
    "BrowserActionType", "BrowserSelectorType", "BrowserTrace",
    # Engine
    "BrowserSession", "BrowserSessionManager",
    "SafetyGuard", "RecoveryEngine",
    "BrowserTaskExecutor", "BrowserResearchAdapter",
]
