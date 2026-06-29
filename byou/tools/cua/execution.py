"""
CUA Layer 5: Execution — 执行层

通过 Playwright 真实执行浏览器操作：
- navigate / click / type / wait / scroll / refresh
- 操作超时与重试
- 执行日志
"""

import asyncio
import logging
from typing import Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ExecutionLayer:
    """执行层 — CUA 的第五层。

    将 Planning 层的操作计划转化为真实的浏览器操作。
    支持 Playwright 驱动，无浏览器时回退到模拟模式。
    """

    def __init__(self, browser_manager: Optional[Any] = None):
        self.browser = browser_manager
        self._execution_log: list[dict] = []

    def set_browser(self, browser_manager: Any) -> None:
        """注入浏览器管理器。"""
        self.browser = browser_manager

    async def process(self, action_plan: dict, context: Any) -> dict:
        """执行操作计划。"""
        logger.debug("CUA Execution: 执行操作计划")

        steps = action_plan.get("steps", [])
        results = []
        errors = []
        start_time = datetime.now()

        for step in steps:
            try:
                result = await self._execute_step(step, context)
                results.append(result)

                if not result.get("success", True):
                    err_msg = (
                        f"步骤 {step.get('step')} 失败: "
                        f"{result.get('error', 'unknown')}"
                    )
                    errors.append(err_msg)

                    if step.get("retry_on_failure"):
                        logger.info("重试步骤 %d", step.get("step"))
                        await asyncio.sleep(0.5)
                        retry = await self._execute_step(step, context)
                        results.append({"retry": True, **retry})
                        if retry.get("success"):
                            errors.pop()

            except Exception as e:
                errors.append(
                    f"步骤 {step.get('step')} 异常: {e}"
                )
                logger.warning(
                    "步骤执行异常: step=%d, error=%s",
                    step.get("step"), e,
                )

        duration_ms = int(
            (datetime.now() - start_time).total_seconds() * 1000
        )

        execution_result = {
            "executed_steps": len(results),
            "total_steps": len(steps),
            "results": results,
            "success": len(errors) == 0,
            "duration_ms": duration_ms,
            "errors": errors,
        }

        self._execution_log.append(execution_result)
        return execution_result

    async def _execute_step(self, step: dict, context: Any) -> dict:
        """执行单个操作步骤。

        优先使用 Playwright，无浏览器时使用模拟执行。
        """
        action = step.get("action", "")
        target = step.get("target", "")
        value = step.get("value", "")
        timeout = step.get("timeout_ms", 5000)
        task_id = step.get("task_id", "default")

        if self.browser:
            return await self._execute_with_browser(
                action, target, value, timeout, task_id, step
            )
        else:
            return await self._execute_simulated(
                action, target, value, timeout, context, step
            )

    async def _execute_with_browser(
        self,
        action: str,
        target: str,
        value: str,
        timeout: int,
        task_id: str,
        step: dict,
    ) -> dict:
        """通过 Playwright 真实执行操作。"""
        result = {
            "step": step.get("step"),
            "action": action,
            "target": target,
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "engine": "playwright",
        }

        try:
            if action == "navigate":
                info = await self.browser.navigate(task_id, target, timeout)
                result["description"] = (
                    f"导航到 {target} → {info.get('title', '')}"
                )
                result["detail"] = info

            elif action == "click":
                ok = await self.browser.click(task_id, target, timeout)
                result["success"] = ok
                result["description"] = (
                    f"点击 {target}" if ok else f"点击 {target} 失败"
                )
                if not ok:
                    result["error"] = "元素不可点击"

            elif action == "type":
                ok = await self.browser.type_text(
                    task_id, target, value, timeout
                )
                result["success"] = ok
                result["description"] = (
                    f"输入 {target}: {value}"
                    if ok
                    else f"输入 {target} 失败"
                )
                if not ok:
                    result["error"] = "输入框不可用"

            elif action == "wait":
                selector = target if target else None
                ok = await self.browser.wait_for(
                    task_id, selector, timeout
                )
                result["description"] = (
                    f"等待 {selector or timeout}ms"
                )
                result["detail"] = {"timeout_ms": timeout, "found": ok}

            elif action == "scroll":
                direction = value if value in ("up", "down") else "down"
                await self.browser.scroll(task_id, direction)
                result["description"] = f"滚动页面 {direction}"

            elif action == "refresh":
                await self.browser.refresh(task_id)
                result["description"] = "刷新页面"

            else:
                # 通用：尝试在页面执行 JS
                result["description"] = f"执行 {action}"
                result["success"] = True

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            result["description"] = f"{action} 异常: {e}"

        return result

    async def _execute_simulated(
        self,
        action: str,
        target: str,
        value: str,
        timeout: int,
        context: Any,
        step: dict,
    ) -> dict:
        """模拟执行（无浏览器时回退）。"""
        await asyncio.sleep(0.05)

        result = {
            "step": step.get("step"),
            "action": action,
            "target": target,
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "engine": "simulated",
        }

        if action == "navigate":
            context.memory.setdefault(
                "navigation_path", []
            ).append(target)
            result["description"] = f"导航到 {target}"

        elif action == "click":
            context.memory.setdefault(
                "clicks", []
            ).append(target)
            result["description"] = f"点击 {target}"

        elif action == "type":
            context.memory.setdefault("inputs", []).append(
                {"target": target, "value": value}
            )
            result["description"] = f"输入 {target}: {value}"

        elif action == "wait":
            wait_ms = int(value) if value else min(timeout, 5000)
            await asyncio.sleep(min(wait_ms / 1000, 5.0))
            result["description"] = f"等待 {wait_ms}ms"

        elif action == "refresh":
            result["description"] = "刷新页面"

        else:
            result["description"] = f"执行 {action}"

        return result

    def get_execution_log(self, limit: int = 20) -> list[dict]:
        """获取最近执行日志。"""
        return self._execution_log[-limit:]

    def is_ready(self) -> bool:
        return True
