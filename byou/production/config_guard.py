"""Byou Production — 配置守护。

功能:
- 启动时验证配置完整性
- 检查必需环境变量
- 检测 API Key 泄露风险
- 依赖可用性检查
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any

from byou.production.types import (
    ConfigValidationResult,
    DependencyCheckResult,
)

logger = logging.getLogger(__name__)

# ── 必需的依赖 ──────────────────────────────────────────

REQUIRED_DEPS = [
    ("pydantic", "2.0"),
    ("pydantic_settings", "2.0"),
    ("httpx", "0.24"),
]

OPTIONAL_DEPS = [
    ("playwright", "1.40", "Browser"),
    ("chromadb", "0.4", "VectorStore persistence"),
    ("networkx", "3.0", "GraphStore"),
    ("paddleocr", "2.0", "OCR local"),
    ("cnocr", "2.0", "OCR cnocr fallback"),
    ("openai", "1.0", "LLM"),
]

# ── 必需的配置项 ────────────────────────────────────────

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DASHSCOPE_API_KEY",
]

WARN_ENV_VARS = [
    "TYC_API_KEY",
]


class ConfigGuard:
    """配置守护器。"""

    def __init__(self):
        self._settings = None

    # ── 环境变量验证 ────────────────────────────────────

    def validate_env(self) -> ConfigValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # 检查有任一 LLM key
        has_key = False
        for var in REQUIRED_ENV_VARS:
            val = os.getenv(var, "")
            if val and val not in ("", "sk-placeholder"):
                has_key = True
                break
        if not has_key:
            errors.append(f"Missing all LLM API keys. Set one of: {REQUIRED_ENV_VARS}")

        if not os.getenv("TYC_API_KEY"):
            warnings.append("TYC_API_KEY not set — TianYanCha tools will be disabled")

        return ConfigValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ── API Key 泄漏检查 ────────────────────────────────

    def check_key_leaks(self, src_dirs: list[str] | None = None) -> list[str]:
        """扫描源码目录，检测 API Key 硬编码。

        Returns: 发现问题的文件路径列表
        """
        issues: list[str] = []
        src_dirs = src_dirs or ["./byou"]
        key_patterns = [os.getenv(v, "") for v in REQUIRED_ENV_VARS if os.getenv(v, "")]

        for d in src_dirs:
            p = Path(d)
            if not p.exists():
                continue
            for py_file in p.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    for key in key_patterns:
                        if key and len(key) > 10 and key in content:
                            issues.append(str(py_file))
                            break
                except Exception:
                    pass

        return issues

    # ── 依赖检查 ────────────────────────────────────────

    # 已知会触发 C 层 crash (torch DLL access violation) 的模块，只用 find_spec
    _DANGEROUS_IMPORTS = {"paddleocr", "cnocr", "cnstd"}

    def check_deps(self) -> list[DependencyCheckResult]:
        results: list[DependencyCheckResult] = []
        all_deps = [(name, ver, False, "") for name, ver in REQUIRED_DEPS]
        all_deps += [(name, ver, True, desc) for name, ver, desc in OPTIONAL_DEPS]

        for name, required_ver, optional, description in all_deps:
            try:
                if name in self._DANGEROUS_IMPORTS:
                    # 用 find_spec 避免实际 import 触发 torch C 层 crash
                    spec = importlib.util.find_spec(name)
                    if spec is not None:
                        available = True
                        version = "?"
                        msg = "installed (version unknown, torch DLL may crash on import)"
                    else:
                        available = False
                        version = ""
                        msg = f"Not installed (optional: {description})"
                else:
                    mod = importlib.import_module(name)
                    version = getattr(mod, "__version__", "unknown")
                    available = True
                    msg = f"v{version}"
            except Exception:
                available = False
                version = ""
                msg = "Not installed" if not optional else f"Not installed (optional: {description})"

            results.append(DependencyCheckResult(
                dependency=name,
                available=available,
                version=version,
                required_version=required_ver,
                message=msg,
                optional=optional,
            ))

        return results


# ── 全局单例 ──────────────────────────────────────────────

_guard: ConfigGuard | None = None


def get_config_guard() -> ConfigGuard:
    global _guard
    if _guard is None:
        _guard = ConfigGuard()
    return _guard
