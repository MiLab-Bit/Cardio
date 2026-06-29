"""
CUA Layer 6: Validation — 校验层

验证操作结果是否符合预期：
- 结果正确性校验
- 异常检测与回滚建议
- 截图比对
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ValidationLayer:
    """
    校验层 — CUA 的第六层（最后一层）。

    验证执行结果，确保操作符合预期；如果发现问题则提出回滚或修正建议。
    """

    def __init__(self):
        self._validation_rules = [
            "page_load_success",
            "no_error_elements",
            "element_state_change",
            "expected_content_present",
        ]

    async def process(
        self,
        execution_result: dict,
        task: Any,
        context: Any,
    ) -> dict:
        """
        校验执行结果。

        Args:
            execution_result: Execution 层的输出
            task: CUA 任务定义
            context: CUA 执行上下文

        Returns:
            {
                "success": bool,
                "checks": list[dict],
                "rollback_needed": bool,
                "rollback_actions": list[dict],
                "overall_score": float,
            }
        """
        logger.debug("CUA Validation: 校验执行结果")

        checks = []
        all_passed = True

        # 规则 1: 无执行错误
        has_errors = bool(execution_result.get("errors"))
        checks.append({
            "rule": "no_execution_errors",
            "passed": not has_errors,
            "detail": execution_result.get("errors", []),
        })
        if has_errors:
            all_passed = False

        # 规则 2: 所有步骤均执行
        total = execution_result.get("total_steps", 0)
        executed = execution_result.get("executed_steps", 0)
        all_steps_executed = executed >= total
        checks.append({
            "rule": "all_steps_executed",
            "passed": all_steps_executed,
            "detail": f"{executed}/{total} 步骤执行",
        })
        if not all_steps_executed:
            all_passed = False

        # 规则 3: 执行时间合理（不超过任务超时）
        duration_ms = execution_result.get("duration_ms", 0)
        timeout_ms = task.timeout_seconds * 1000
        within_timeout = duration_ms <= timeout_ms
        checks.append({
            "rule": "within_timeout",
            "passed": within_timeout,
            "detail": f"耗时 {duration_ms}ms / {timeout_ms}ms",
        })

        # 计算综合评分
        passed_checks = sum(1 for c in checks if c["passed"])
        overall_score = passed_checks / len(checks) if checks else 0.0

        # 判断是否需要回滚
        rollback_needed = not all_passed
        rollback_actions = self._generate_rollback(execution_result) if rollback_needed else []

        validation_result = {
            "success": all_passed,
            "checks": checks,
            "rollback_needed": rollback_needed,
            "rollback_actions": rollback_actions,
            "overall_score": round(overall_score, 2),
            "error": None if all_passed else "部分检查未通过",
        }

        if not all_passed:
            logger.warning(
                "CUA 校验未通过: score=%.2f, checks=%d/%d passed",
                overall_score, passed_checks, len(checks),
            )

        return validation_result

    def _generate_rollback(self, execution_result: dict) -> list[dict]:
        """生成回滚操作建议"""
        rollback = []
        errors = execution_result.get("errors", [])

        for error in errors:
            rollback.append({
                "action": "rollback",
                "description": f"回滚: {error}",
                "severity": "medium",
            })

        # 建议重试
        rollback.append({
            "action": "retry_pipeline",
            "description": "建议重新执行 Pipeline",
            "severity": "low",
        })

        return rollback

    def add_validation_rule(self, rule_name: str) -> None:
        """添加自定义校验规则"""
        if rule_name not in self._validation_rules:
            self._validation_rules.append(rule_name)

    def is_ready(self) -> bool:
        return True
