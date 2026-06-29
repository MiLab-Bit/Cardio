"""MCP Security — Prompt Injection / Tool Poisoning 防护。

MCP 安全最大的 AI-native 风险:
1. Tool output → 污染 LLM context (prompt injection)
2. Tool description → 劫持 agent 行为 (context poisoning)
3. External 网页/文档 → 含恶意指令

策略:
- 所有外部 tool output 标记为 untrusted
- 禁止工具结果直接拼接为 system instruction
- 正则检测已知 injection 模式
- 高风险 capability + untrusted context → 默认拒绝
"""

from __future__ import annotations

import logging
import re

from .types import (
    InjectionCheckResult,
    RiskLevel,
    UntrustedContentMarker,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Injection 检测模式
# ─────────────────────────────────────────────────────────────

INJECTION_PATTERNS: list[tuple[str, RiskLevel, str]] = [
    # Prompt injection 经典模式
    (r"ignore\s+(all\s+)?(previous|prior|above|before)\s+(instructions?|directions?|guidelines?)",
     RiskLevel.CRITICAL, "Ignore instruction override"),
    (r"(you\s+must|you\s+shall|you\s+are\s+required\s+to|you\s+now\s+work\s+for)\s",
     RiskLevel.HIGH, "Direct instruction injection"),
    (r"reveal\s+(your\s+)?(system\s+(prompt|message|instruction)|secrets?|api\s+key)",
     RiskLevel.CRITICAL, "Secret extraction attempt"),
    (r"call\s+(the\s+)?(this|following)\s+tool",
     RiskLevel.HIGH, "Tool call injection"),
    (r"<\|im_start\|>|<\|im_end\|>|</?system>|</?instruction>",
     RiskLevel.HIGH, "Format boundary injection"),

    # Tool poisoning
    (r"disregard\s+(all\s+)?\b(rules?|constraints?|policies?|safeguards?)",
     RiskLevel.CRITICAL, "Policy bypass attempt"),
    (r"\bprint\s*\(\s*['\"](.+?)['\"]\s*\)\s*#\s*[\w]+",
     RiskLevel.MEDIUM, "Code execution hint in text"),

    # URL / domain 可疑模式
    (r"https?://\S*\.(xyz|top|tk|ml|ga|cf)\b",
     RiskLevel.MEDIUM, "Suspicious TLD"),

    # 数据外泄
    (r"send\s+(this|the\s+above|all|the\s+data)\s+to\s+",
     RiskLevel.HIGH, "Data exfiltration pattern"),
    (r"upload\s+(this|all|the\s+(result|output))\s+to\s+",
     RiskLevel.HIGH, "Upload exfiltration"),

    # 角色扮演逃逸
    (r"you\s+are\s+now\s+(a\s+|an\s+)?\w+\s*(that|who|and)",
     RiskLevel.MEDIUM, "Role transformation attempt"),
    (r"pretend\s+(to\s+be|you\s+are)\s+(a\s+|an\s+)?",
     RiskLevel.MEDIUM, "Pretend instruction"),
]


class InjectionGuard:
    """Prompt injection / tool poisoning 检测引擎。

    三层防护:
    1. Pattern match → 正则检测已知攻击模式
    2. Content marking → 所有 tool output 标记 untrusted
    3. Context gate → 高风险 cap + untrusted 上下文 → 默认拒绝
    """

    def __init__(self):
        self._compiled_patterns: list[tuple[re.Pattern, RiskLevel, str]] = [
            (re.compile(p, re.IGNORECASE), risk, desc)
            for p, risk, desc in INJECTION_PATTERNS
        ]

    # ── 核心检测 ────────────────────────────────

    def check(self, content: str, *, content_type: str = "tool_output") -> InjectionCheckResult:
        """检查内容是否包含注入模式。

        Args:
            content: 待检查的文本
            content_type: 内容类型 (tool_output / tool_description / server_name)

        Returns:
            InjectionCheckResult: passed=True 表示通过检查
        """
        if not content:
            return InjectionCheckResult(passed=True, content_type=content_type)

        matched: list[str] = []
        max_risk = RiskLevel.LOW
        evidence_parts: list[str] = []

        for pattern, risk, desc in self._compiled_patterns:
            match = pattern.search(content)
            if match:
                matched.append(desc)
                evidence_parts.append(f"{desc}: ...{match.group()[:80]}...")
                if risk == RiskLevel.CRITICAL:
                    max_risk = risk
                elif risk == RiskLevel.HIGH and max_risk != RiskLevel.CRITICAL:
                    max_risk = risk
                elif risk == RiskLevel.MEDIUM and max_risk not in (RiskLevel.CRITICAL, RiskLevel.HIGH):
                    max_risk = risk

        confidence = min(0.95, len(matched) * 0.15)

        passed = not matched

        if not passed:
            logger.warning(
                "Injection check FAILED for content_type=%s: %d patterns matched (max_risk=%s, confidence=%.2f)",
                content_type, len(matched), max_risk, confidence,
            )

        return InjectionCheckResult(
            passed=passed,
            patterns_matched=matched,
            risk_level=max_risk,
            content_type=content_type,
            confidence=confidence,
            evidence="; ".join(evidence_parts) if evidence_parts else "",
        )

    # ── 工具输出标记 ─────────────────────────────

    def mark_untrusted(self, content: str, *, source: str = "") -> UntrustedContentMarker:
        """标记工具输出为不可信。

        所有来自外部工具的文本输出都应该经过此标记。
        这防止工具结果直接污染 system instruction / agent context。

        Args:
            content: 工具返回的原始文本
            source: 来源 (tool_name)

        Returns:
            UntrustedContentMarker: 带安全标签的包装器
        """
        check = self.check(content, content_type="tool_output")

        marker = UntrustedContentMarker(
            original_content=content,
            source=source,
            is_untrusted=True,
            flags=check.patterns_matched if not check.passed else [],
            sanitized_content=content,  # 默认不改变, 调用方决定
            was_sanitized=False,
        )
        return marker

    # ── 清洗 ────────────────────────────────────

    def sanitize(self, content: str) -> tuple[str, bool]:
        """清洗内容中的注入模式。

        Args:
            content: 待清洗文本

        Returns:
            (清洗后文本, 是否被修改)
        """
        if not content:
            return content, False

        sanitized = content
        modified = False

        for pattern, _, _ in self._compiled_patterns:
            if pattern.search(sanitized):
                sanitized = pattern.sub("[REDACTED]", sanitized)
                modified = True

        return sanitized, modified

    # ── Context gate ──────────────────────────────

    def should_allow_in_untrusted_context(
        self,
        capability: str,
        risk_profile: "CapabilityRiskProfile",
    ) -> tuple[bool, str]:
        """高风险 capability + untrusted context → 是否应允许。

        Returns:
            (允许?, 原因)
        """
        # 策略: CRITICAL cap 在 untrusted 上下文默认拒绝
        if risk_profile.risk_level in (RiskLevel.CRITICAL,):
            return False, f"Capability {capability} is CRITICAL and blocked in untrusted context"

        # 策略: HIGH cap → 需要显式 allow_in_untrusted_context
        if risk_profile.risk_level == RiskLevel.HIGH and not risk_profile.allow_in_untrusted_context:
            return False, f"Capability {capability} is HIGH risk, not allowed in untrusted context"

        return True, "OK"

    # ── 批量检查 ─────────────────────────────────

    def check_batch(self, items: list[tuple[str, str]]) -> list[InjectionCheckResult]:
        """批量检查多条内容 (concurrent-friendly)。"""
        return [
            self.check(content, content_type=ct)
            for content, ct in items
        ]
