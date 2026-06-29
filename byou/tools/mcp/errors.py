"""MCP Tool Bus — 统一错误映射。

将各种底层异常映射为结构化 MCPToolError。
Agent 不需要 catch 原始异常，只需看 MCPToolError.category。
"""

from __future__ import annotations

import logging
from asyncio import TimeoutError

from byou.tools.mcp.types import ErrorCategory, MCPToolError

logger = logging.getLogger(__name__)

# ── 异常 → ErrorCategory 映射表 ─────────────────

_ERROR_PATTERNS: list[tuple[type[Exception] | str, ErrorCategory, bool]] = [
    # (异常类型 或 子串, 类别, 是否可重试)
    (TimeoutError, ErrorCategory.TIMEOUT, True),
    ("TimedOut", ErrorCategory.TIMEOUT, True),
    ("timeout", ErrorCategory.TIMEOUT, True),
    ("ReadTimeout", ErrorCategory.TIMEOUT, True),
    ("ConnectionError", ErrorCategory.NETWORK, True),
    ("ConnectionRefused", ErrorCategory.NETWORK, True),
    ("Connection", ErrorCategory.NETWORK, True),
    ("DNS", ErrorCategory.NETWORK, True),
    ("TooManyRequests", ErrorCategory.RATE_LIMIT, True),
    ("RateLimit", ErrorCategory.RATE_LIMIT, True),
    ("rate limit", ErrorCategory.RATE_LIMIT, True),
    ("429", ErrorCategory.RATE_LIMIT, True),
    ("Unauthorized", ErrorCategory.AUTH, False),
    ("Forbidden", ErrorCategory.AUTH, False),
    ("401", ErrorCategory.AUTH, False),
    ("403", ErrorCategory.AUTH, False),
    ("InvalidApiKey", ErrorCategory.AUTH, False),
    ("ValidationError", ErrorCategory.VALIDATION, False),
    ("BadRequest", ErrorCategory.VALIDATION, False),
    ("400", ErrorCategory.VALIDATION, False),
    ("NotFound", ErrorCategory.NOT_FOUND, False),
    ("404", ErrorCategory.NOT_FOUND, False),
    ("ServerError", ErrorCategory.SERVER_ERROR, True),
    ("500", ErrorCategory.SERVER_ERROR, True),
    ("502", ErrorCategory.SERVER_ERROR, True),
    ("503", ErrorCategory.SERVER_ERROR, True),
    ("CircuitBreaker", ErrorCategory.CIRCUIT_OPEN, True),
]


def map_error(
    tool_name: str,
    exc: Exception | str,
    default_category: ErrorCategory = ErrorCategory.UNKNOWN,
) -> MCPToolError:
    """将任意异常映射为结构化 MCPToolError。

    Args:
        tool_name: 发生错误的工具名
        exc: 异常对象或错误字符串
        default_category: 找不到匹配时的默认类别

    Returns:
        MCPToolError (带分类、是否可重试、建议退避时间)
    """
    err_str = str(exc)

    # 遍历模式表找匹配
    for pattern, category, retryable in _ERROR_PATTERNS:
        if isinstance(pattern, type) and isinstance(exc, pattern):
            return _build_error(tool_name, category, err_str, retryable)
        if isinstance(pattern, str) and pattern.lower() in err_str.lower():
            return _build_error(tool_name, category, err_str, retryable)

    # 未匹配 → 默认
    logger.debug("Unclassified error for tool=%s: %s", tool_name, err_str[:200])
    return _build_error(tool_name, default_category, err_str, retryable=False)


def _build_error(
    tool_name: str,
    category: ErrorCategory,
    message: str,
    retryable: bool,
) -> MCPToolError:
    """构建结构化错误对象"""
    backoff = _suggested_backoff(category)
    return MCPToolError(
        tool_name=tool_name,
        category=category,
        message=message[:500],
        detail=message[:2000],
        retryable=retryable,
        suggested_backoff_ms=backoff,
        raw_error=message[:2000],
    )


def _suggested_backoff(category: ErrorCategory) -> int:
    """根据错误类别建议退避时间"""
    return {
        ErrorCategory.RATE_LIMIT: 5000,
        ErrorCategory.CIRCUIT_OPEN: 30_000,
        ErrorCategory.TIMEOUT: 2000,
        ErrorCategory.NETWORK: 1000,
        ErrorCategory.SERVER_ERROR: 3000,
        ErrorCategory.AUTH: 0,      # 不可重试, 无需等待
        ErrorCategory.VALIDATION: 0,
        ErrorCategory.NOT_FOUND: 0,
        ErrorCategory.UNKNOWN: 1000,
    }.get(category, 1000)
