"""Logging filters — mask sensitive data from log output."""

from __future__ import annotations

import logging
import re

# Matches OpenAI / Anthropic / DashScope API key patterns
_KEY_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{10,})([A-Za-z0-9_\-]*)")
_TOKEN_RE = re.compile(r"(Bearer\s+)([A-Za-z0-9_\-\.]{10,})")

_loggers_patched: set[str] = set()


class ApiKeyMaskFilter(logging.Filter):
    """Mask API keys and tokens in log messages.

    Patterns masked:
    - ``sk-xxxx...`` (OpenAI / DashScope / Anthropic style keys)
    - ``Bearer xxxx...`` (Authorization headers)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.msg)
        msg = _KEY_RE.sub(r"sk-***\g<2>", msg)
        msg = _TOKEN_RE.sub(r"\1***", msg)
        record.msg = msg

        if record.args:
            record.args = tuple(
                _KEY_RE.sub(r"sk-***\g<2>", _TOKEN_RE.sub(r"\1***", str(a)))
                if isinstance(a, str)
                else a
                for a in record.args
            )
        return True


def install(root_logger_name: str = "") -> None:
    """Install the API key mask filter on the root logger (once).

    Call from your app entry point, e.g. api.py or cli.py.
    """
    if root_logger_name in _loggers_patched:
        return
    target = logging.getLogger(root_logger_name or None)
    target.addFilter(ApiKeyMaskFilter())
    _loggers_patched.add(root_logger_name or "_root_")
