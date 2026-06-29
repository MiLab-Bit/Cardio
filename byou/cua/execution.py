"""CUA Execution — 执行 + 校验

执行操作步骤（Playwright 真实操作 或 模拟回退），完成后自动运行校验规则。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class ExecutionLayer:
    """执行层 — 操作执行 + 结果校验。

    合并了原 Validation 层的 3 条核心校验规则。
    """

    def __init__(self, browser_manager: Any = None):
        self.browser = browser_manager
        self._execution_log: list[dict] = []

    def set_browser(self, browser_manager: Any) -> None:
        self.browser = browser_manager

    async def process(self, action_plan: dict, context: Any) -> dict:
        steps = action_plan.get("steps", [])
        results: list[dict] = []
        errors: list[str] = []
        start = datetime.now()

        for step in steps:
            try:
                result = await self._execute_one(step, context)
                results.append(result)
                if not result.get("success", True):
                    err_msg = f"步骤 {step.get('step')} 失败: {result.get('error', 'unknown')}"
                    errors.append(err_msg)
                    if step.get("retry_on_failure"):
                        await asyncio.sleep(0.5)
                        retry = await self._execute_one(step, context)
                        results.append({"retry": True, **retry})
                        if retry.get("success"):
                            errors.pop()
            except Exception as e:
                errors.append(f"步骤 {step.get('step')} 异常: {e}")
                logger.warning("执行异常: step=%d, %s", step.get("step"), e)

        duration_ms = int((datetime.now() - start).total_seconds() * 1000)
        executed = len(results)

        exec_result = {
            "executed_steps": executed, "total_steps": len(steps),
            "results": results, "success": len(errors) == 0,
            "duration_ms": duration_ms, "errors": errors,
        }
        self._execution_log.append(exec_result)

        # ── 内联校验 ──
        return {**exec_result, "validation": self._validate(exec_result, action_plan)}

    # ── 单步执行 ──────────────────────────────────────────────

    async def _execute_one(self, step: dict, context: Any) -> dict:
        action, target, value = step.get("action", ""), step.get("target", ""), step.get("value", "")
        timeout = step.get("timeout_ms", 5000)
        task_id = step.get("task_id", "default")

        if self.browser:
            return await self._browser_exec(action, target, value, timeout, task_id, step)
        return await self._simulated_exec(action, target, value, timeout, context, step)

    async def _browser_exec(self, action: str, target: str, value: str,
                            timeout: int, task_id: str, step: dict) -> dict:
        r = {"step": step.get("step"), "action": action, "target": target,
             "success": True, "timestamp": datetime.now().isoformat(), "engine": "playwright"}
        try:
            if action == "navigate":
                info = await self.browser.navigate(task_id, target, timeout)
                r["description"] = f"导航到 {target} → {info.get('title', '')}"
                r["detail"] = info
            elif action == "click":
                ok = await self.browser.click(task_id, target, timeout)
                r["success"] = ok
                r["description"] = f"点击 {target}" if ok else f"点击 {target} 失败"
                if not ok:
                    r["error"] = "元素不可点击"
            elif action == "type":
                ok = await self.browser.type_text(task_id, target, value, timeout)
                r["success"] = ok
                r["description"] = f"输入 {target}: {value}" if ok else f"输入 {target} 失败"
                if not ok:
                    r["error"] = "输入框不可用"
            elif action == "wait":
                ok = await self.browser.wait_for(task_id, target if target else None, timeout)
                r["description"] = f"等待 {target or timeout}ms"
                r["detail"] = {"timeout_ms": timeout, "found": ok}
            elif action == "scroll":
                await self.browser.scroll(task_id, value if value in ("up", "down") else "down")
                r["description"] = f"滚动页面 {value or 'down'}"
            elif action == "refresh":
                await self.browser.refresh(task_id)
                r["description"] = "刷新页面"
            else:
                r["description"] = f"执行 {action}"
        except Exception as e:
            r["success"] = False
            r["error"] = str(e)
            r["description"] = f"{action} 异常: {e}"
        return r

    async def _simulated_exec(self, action: str, target: str, value: str,
                              timeout: int, context: Any, step: dict) -> dict:
        await asyncio.sleep(0.05)
        r = {"step": step.get("step"), "action": action, "target": target,
             "success": True, "timestamp": datetime.now().isoformat(), "engine": "simulated"}
        if action == "navigate":
            context.memory.setdefault("navigation_path", []).append(target)
            r["description"] = f"导航到 {target}"
        elif action == "click":
            context.memory.setdefault("clicks", []).append(target)
            r["description"] = f"点击 {target}"
        elif action == "type":
            context.memory.setdefault("inputs", []).append({"target": target, "value": value})
            r["description"] = f"输入 {target}: {value}"
        elif action == "wait":
            wait_ms = int(value) if value else min(timeout, 5000)
            await asyncio.sleep(min(wait_ms / 1000, 5.0))
            r["description"] = f"等待 {wait_ms}ms"
        elif action == "refresh":
            r["description"] = "刷新页面"
        else:
            r["description"] = f"执行 {action}"
        return r

    # ── 校验（内联） ──────────────────────────────────────────

    @staticmethod
    def _validate(exec_result: dict, action_plan: dict) -> dict:
        checks: list[dict] = []

        has_errors = bool(exec_result.get("errors"))
        checks.append({"rule": "no_execution_errors", "passed": not has_errors,
                       "detail": exec_result.get("errors", [])})

        total = exec_result.get("total_steps", 0)
        executed = exec_result.get("executed_steps", 0)
        all_steps = executed >= total
        checks.append({"rule": "all_steps_executed", "passed": all_steps,
                       "detail": f"{executed}/{total} 步骤执行"})

        passed = sum(1 for c in checks if c["passed"])
        score = passed / len(checks) if checks else 0.0
        success = passed == len(checks)

        return {
            "success": success, "checks": checks,
            "rollback_needed": not success,
            "rollback_actions": [{"action": "retry_pipeline", "description": "建议重试"}]
            if not success else [],
            "overall_score": round(score, 2),
            "error": None if success else "部分检查未通过",
        }

    def get_execution_log(self, limit: int = 20) -> list[dict]:
        return self._execution_log[-limit:]

    def is_ready(self) -> bool:
        return True
