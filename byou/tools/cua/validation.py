"""
CUA Layer 6: Validation — 校验层（完整实现）

验证操作结果是否符合预期：
- 截图前后对比（感知差异）
- 元素存在性检查
- 页面 URL / 标题校验
- 执行错误检测
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """单次校验结果。"""

    rule: str
    passed: bool
    detail: str = ""
    severity: str = "medium"  # low | medium | high


@dataclass
class ValidationReport:
    """完整校验报告。"""

    success: bool
    checks: list[ValidationResult] = field(default_factory=list)
    rollback_needed: bool = False
    rollback_actions: list[dict] = field(default_factory=list)
    overall_score: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "checks": [c.__dict__ for c in self.checks],
            "rollback_needed": self.rollback_needed,
            "rollback_actions": self.rollback_actions,
            "overall_score": round(self.overall_score, 2),
            "error": self.error,
        }


class ValidationLayer:
    """
    校验层 — CUA 的第六层（最后一层）。

    验证执行结果，确保操作符合预期；
    如果发现问题则提出回滚或修正建议。
    """

    def __init__(self, browser_manager: Any = None):
        self.browser = browser_manager
        self._rules: list[str] = [
            "no_execution_errors",
            "all_steps_executed",
            "within_timeout",
            "expected_url",
            "expected_title",
            "element_present",
            "screenshot_no_crash",
        ]

    def set_browser(self, browser_manager: Any) -> None:
        self.browser = browser_manager

    async def validate(
        self,
        execution_result: dict,
        action_plan: dict,
        context: Any,
    ) -> ValidationReport:
        """
        执行完整校验。

        Args:
            execution_result: Execution 层输出
            action_plan: 原始动作计划（含 expected_state）
            context: CUA 执行上下文（含 page 引用）

        Returns:
            ValidationReport
        """
        checks: list[ValidationResult] = []
        task = action_plan.get("task", {})
        expected = action_plan.get("expected_state", {})
        page = context.page if context else None

        # ── 规则 1: 无执行错误 ──────────────────────────────────
        errors = execution_result.get("errors", [])
        checks.append(ValidationResult(
            rule="no_execution_errors",
            passed=len(errors) == 0,
            detail=f"{len(errors)} 个错误" if errors else "无执行错误",
            severity="high" if errors else "low",
        ))

        # ── 规则 2: 所有步骤均执行 ─────────────────────────────
        total = execution_result.get("total_steps", 0)
        executed = execution_result.get("executed_steps", 0)
        checks.append(ValidationResult(
            rule="all_steps_executed",
            passed=executed >= total,
            detail=f"{executed}/{total} 步骤执行",
            severity="medium",
        ))

        # ── 规则 3: 执行时间合理 ───────────────────────────────
        duration_ms = execution_result.get("duration_ms", 0)
        timeout_ms = (task.get("timeout_seconds") or 60) * 1000
        within = duration_ms <= timeout_ms
        checks.append(ValidationResult(
            rule="within_timeout",
            passed=within,
            detail=f"耗时 {duration_ms}ms / {timeout_ms}ms",
            severity="low",
        ))

        # ── 规则 4: 预期 URL 匹配 ──────────────────────────────
        if expected.get("url"):
            url_ok = False
            detail = "无法检查：无浏览器页面"
            if page:
                try:
                    actual_url = await page.url()
                    url_ok = expected["url"] in actual_url
                    detail = f"预期含 '{expected['url']}'，实际: {actual_url[:80]}"
                except Exception as e:
                    detail = f"URL 检查失败: {e}"
            checks.append(ValidationResult(
                rule="expected_url",
                passed=url_ok,
                detail=detail,
                severity="medium",
            ))

        # ── 规则 5: 预期标题匹配 ──────────────────────────────
        if expected.get("title"):
            title_ok = False
            detail = "无法检查：无浏览器页面"
            if page:
                try:
                    actual_title = await page.title()
                    title_ok = expected["title"] in actual_title
                    detail = f"预期含 '{expected['title']}'，实际: {actual_title[:60]}"
                except Exception as e:
                    detail = f"标题检查失败: {e}"
            checks.append(ValidationResult(
                rule="expected_title",
                passed=title_ok,
                detail=detail,
                severity="low",
            ))

        # ── 规则 6: 关键元素存在 ──────────────────────────────
        for selector in expected.get("required_elements", []):
            present = False
            detail = f"元素 {selector} 未找到"
            if page:
                try:
                    elem = await page.query_selector(selector)
                    present = elem is not None
                    detail = f"元素 {selector} {'存在' if present else '不存在'}"
                except Exception as e:
                    detail = f"元素检查失败: {e}"
            checks.append(ValidationResult(
                rule=f"element_present:{selector}",
                passed=present,
                detail=detail,
                severity="medium",
            ))

        # ── 规则 7: 截图无崩溃迹象 ────────────────────────────
        if self.browser and page:
            try:
                shot = await self.browser.screenshot()
                # 简单启发：截图成功且非空即视为无崩溃
                valid = shot is not None and len(shot) > 100
                checks.append(ValidationResult(
                    rule="screenshot_no_crash",
                    passed=valid,
                    detail="截图正常" if valid else "截图异常或空白",
                    severity="high",
                ))
            except Exception as e:
                checks.append(ValidationResult(
                    rule="screenshot_no_crash",
                    passed=False,
                    detail=f"截图失败: {e}",
                    severity="high",
                ))

        # ── 综合评分 ──────────────────────────────────────────
        passed = sum(1 for c in checks if c.passed)
        total_c = len(checks)
        score = passed / total_c if total_c else 0.0
        all_passed = all(c.passed for c in checks)

        # ── 回滚建议 ──────────────────────────────────────────
        rollback_actions: list[dict] = []
        if not all_passed:
            for c in checks:
                if not c.passed and c.severity in ("high", "medium"):
                    rollback_actions.append({
                        "action": "retry_step",
                        "rule": c.rule,
                        "description": f"重试失败规则: {c.rule} — {c.detail}",
                        "severity": c.severity,
                    })
            rollback_actions.append({
                "action": "refresh_and_retry",
                "description": "刷新页面后重试",
                "severity": "low",
            })

        report = ValidationReport(
            success=all_passed,
            checks=checks,
            rollback_needed=not all_passed,
            rollback_actions=rollback_actions,
            overall_score=score,
            error=None if all_passed else "部分检查未通过",
        )

        if not all_passed:
            logger.warning(
                "CUA 校验未通过: score=%.2f, %d/%d passed",
                score, passed, total_c,
            )

        return report

    # ── 截图对比（可选扩展）───────────────────────────────────

    async def compare_screenshots(
        self,
        before_b64: str,
        after_b64: str,
    ) -> dict:
        """
        对比操作前后的截图，检测页面是否发生预期变化。
        使用像素差异哈希（pHash）做简单对比。
        """
        try:
            from PIL import Image
            import io

            def _decode(b64_str: str) -> Image.Image:
                return Image.open(io.BytesIO(base64.b64decode(b64_str)))

            before_img = _decode(before_b64).convert("L").resize((32, 32))
            after_img = _decode(after_b64).convert("L").resize((32, 32))

            before_pixels = list(before_img.getdata())
            after_pixels = list(after_img.getdata())
            diff = sum(
                abs(a - b) > 30 for a, b in zip(before_pixels, after_pixels)
            ) / len(before_pixels)

            return {
                "similarity": 1.0 - diff,
                "changed": diff > 0.05,
                "diff_ratio": round(diff, 4),
            }
        except ImportError:
            logger.warning("PIL not installed, skipping screenshot comparison")
            return {"similarity": 1.0, "changed": False, "diff_ratio": 0.0}
        except Exception as e:
            logger.warning("Screenshot comparison failed: %s", e)
            return {"similarity": 1.0, "changed": False, "diff_ratio": 0.0}

    def add_rule(self, rule_name: str) -> None:
        if rule_name not in self._rules:
            self._rules.append(rule_name)

    def is_ready(self) -> bool:
        return True
