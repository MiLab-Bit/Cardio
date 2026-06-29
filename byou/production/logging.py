"""Byou Production — 结构化日志层。

特性:
- JSON 结构化输出 (file + stdout 双通道)
- Trace ID / Correlation ID 注入
- API Key / Secret 自动遮罩
- 支持 pipeline/stage/agent/tool 四级上下文
- 关键事件审计
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from byou.production.types import Severity

# ── Key 遮罩 ────────────────────────────────────────────────

_KEY_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9_-]{10,}'),      'sk-***'),
    (re.compile(r'(api[_-]?key[=:]\s*)[^\s,}]+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(token[=:]\s*)[^\s,}]+',       re.IGNORECASE), r'\1***'),
    (re.compile(r'(secret[=:]\s*)[^\s,}]+',      re.IGNORECASE), r'\1***'),
    (re.compile(r'(password[=:]\s*)[^\s,}]+',    re.IGNORECASE), r'\1***'),
]

def mask_secrets(text: str) -> str:
    for pattern, replacement in _KEY_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ── 结构化日志器 ─────────────────────────────────────────────

class StructuredLogger:
    """JSON 结构化日志器。

    trace_id / run_id 通过 contextvars 传播，无需显式传参。
    """

    # contextvars 替代: 线程本地
    _trace_context: dict[str, str] = {}

    def __init__(
        self,
        name: str = "byou",
        level: str = "INFO",
        json_file: str | None = None,
        mask_keys: bool = True,
    ):
        self.name = name
        self.mask_keys = mask_keys

        # 标准 Python logger
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)

        # JSON 文件输出
        self._json_path = json_file

    # ── 上下文管理 ──────────────────────────────────────────

    @classmethod
    def set_trace(cls, trace_id: str = "", run_id: str = ""):
        cls._trace_context["trace_id"] = trace_id
        cls._trace_context["run_id"] = run_id

    @classmethod
    def clear_trace(cls):
        cls._trace_context.clear()

    @classmethod
    def get_trace(cls) -> dict[str, str]:
        return dict(cls._trace_context)

    # ── 日志方法 ────────────────────────────────────────────

    def log(
        self,
        level: Severity | str,
        message: str,
        *,
        pipeline_id: str = "",
        stage: str = "",
        agent: str = "",
        tool: str = "",
        duration_ms: float = 0.0,
        extra: dict[str, Any] | None = None,
    ):
        """统一日志入口"""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level if isinstance(level, str) else level.value,
            "logger": self.name,
            "message": self._sanitize(message),
            **self._trace_context,
        }

        if pipeline_id:
            entry["pipeline_id"] = pipeline_id
        if stage:
            entry["stage"] = stage
        if agent:
            entry["agent"] = agent
        if tool:
            entry["tool"] = tool
        if duration_ms:
            entry["duration_ms"] = round(duration_ms, 2)

        if extra:
            entry["extra"] = self._sanitize_dict(extra)

        # 输出
        line = json.dumps(entry, ensure_ascii=False)
        log_level = getattr(logging, str(level).upper(), 20)
        self._logger.log(log_level, line)

        # JSON 文件追加
        if self._json_path:
            try:
                with open(self._json_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def debug(self, msg: str, **kwargs):
        self.log(Severity.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        self.log(Severity.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self.log(Severity.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self.log(Severity.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs):
        self.log(Severity.CRITICAL, msg, **kwargs)

    # ── 审计事件 ────────────────────────────────────────────

    AUDIT_EVENTS: set[str] = {
        "pipeline_start", "pipeline_complete", "pipeline_error",
        "tool_call", "tool_failure",
        "browser_session_start", "browser_session_end",
        "llm_call", "llm_error",
        "persistence_save", "persistence_fail",
        "shutdown_start", "shutdown_complete",
        "health_check_fail",
    }

    def audit(self, event: str, details: dict[str, Any] | None = None):
        """审计事件（关键操作）"""
        if event not in self.AUDIT_EVENTS:
            self.warning(f"Unknown audit event: {event}")
        self.info(event, extra={"audit_event": event, **(details or {})})

    # ── 脱敏 ────────────────────────────────────────────────

    def _sanitize(self, text: str) -> str:
        return mask_secrets(text) if self.mask_keys else text

    def _sanitize_dict(self, d: dict) -> dict:
        if not self.mask_keys or not d:
            return d
        return json.loads(mask_secrets(json.dumps(d, ensure_ascii=False)))


# ── 全局单例 ──────────────────────────────────────────────

_logger: StructuredLogger | None = None


def get_logger() -> StructuredLogger:
    global _logger
    if _logger is None:
        json_path = os.environ.get("BYOU_LOG_FILE", "")
        _logger = StructuredLogger(
            name="byou",
            level=os.environ.get("BYOU_LOG_LEVEL", "INFO"),
            json_file=json_path or None,
        )
    return _logger
