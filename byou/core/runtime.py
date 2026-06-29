"""CUA (Computer-Use Agent) Runtime — 浏览器自动化执行

3 层架构：
├── Perception Layer     感知层：UI 元素识别 + 语义对齐
├── Planning Layer       规划层：任务分解 + 状态追踪
└── Execution Layer      执行层：真实操作 + 结果校验

集成 Playwright 浏览器自动化（系统 Edge 通道）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from byou.core.message_bus import MessageBus
from byou.infrastructure.browser import BrowserManager
from byou.cua.perception import PerceptionLayer
from byou.cua.planning import PlanningLayer
from byou.cua.execution import ExecutionLayer

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class CuaTask:
    id: str
    description: str
    target_url: Optional[str] = None
    actions: list[dict] = field(default_factory=list)
    max_retries: int = 3
    timeout_seconds: int = 60
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[dict] = None
    errors: list[str] = field(default_factory=list)


@dataclass
class CuaContext:
    current_state: dict[str, Any] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    screenshots: list[str] = field(default_factory=list)


class CuaRuntime:
    """Computer-Use Agent 运行时引擎（3 层架构）。"""

    def __init__(
        self,
        message_bus: Optional[MessageBus] = None,
        browser_manager: Optional[BrowserManager] = None,
        use_browser: bool = True,
    ):
        self.message_bus = message_bus
        self.browser_manager = browser_manager
        self.use_browser = use_browser

        self.perception = PerceptionLayer(self.browser_manager)
        self.planning = PlanningLayer()
        self.execution = ExecutionLayer(self.browser_manager)

        self._active_tasks: dict[str, CuaTask] = {}
        self._context = CuaContext()

        logger.info("CUA Runtime 就绪 (3层, browser=%s)",
                     "enabled" if (use_browser and browser_manager) else "disabled")

    async def start_browser(self) -> None:
        if self.browser_manager is None and self.use_browser:
            self.browser_manager = BrowserManager()
            self.perception.set_browser(self.browser_manager)
            self.execution.set_browser(self.browser_manager)
        if self.browser_manager and not self.browser_manager._started:
            await self.browser_manager.start()
            logger.info("CUA 浏览器已启动")

    async def execute_task(self, task: CuaTask) -> CuaTask:
        """3 层流水线: Perception → Planning → Execution（含校验）。"""
        self._active_tasks[task.id] = task
        task.status = ExecutionStatus.RUNNING

        try:
            # Layer 1: Perception（含语义对齐 + 页面状态检测）
            perception = await self.perception.process(task, self._context)
            self._context.current_state["perception"] = perception

            # Layer 2: Planning（含状态追踪 + 异常检测）
            action_plan = await self.planning.process(perception, task, self._context)
            self._context.current_state["plan"] = action_plan

            for step in action_plan.get("steps", []):
                step.setdefault("task_id", task.id)

            # Layer 3: Execution（含校验）
            exec_result = await self.execution.process(action_plan, self._context)
            self._context.current_state["execution"] = exec_result
            self._context.history.append(exec_result)

            validation = exec_result.get("validation", {})
            if validation.get("success", not exec_result.get("errors")):
                task.status = ExecutionStatus.SUCCESS
            else:
                task.status = ExecutionStatus.FAILED
                task.errors.append(validation.get("error", "校验未通过"))

            task.result = {"perception": perception, "plan": action_plan,
                          "execution": exec_result, "validation": validation}

        except Exception as e:
            logger.exception("CUA 任务异常: %s", task.id)
            task.status = ExecutionStatus.FAILED
            task.errors.append(str(e))

        return task

    async def retry_task(self, task_id: str) -> Optional[CuaTask]:
        task = self._active_tasks.get(task_id)
        if not task:
            logger.warning("任务不存在: %s", task_id)
            return None
        if task.max_retries <= 0:
            logger.warning("任务 %s 已达最大重试次数", task_id)
            return None
        task.max_retries -= 1
        task.status = ExecutionStatus.RETRYING
        task.errors = []
        logger.info("重试 %s (剩余: %d)", task_id, task.max_retries)
        return await self.execute_task(task)

    def get_task_status(self, task_id: str) -> Optional[ExecutionStatus]:
        task = self._active_tasks.get(task_id)
        return task.status if task else None

    async def shutdown(self) -> None:
        self._active_tasks.clear()
        if self.browser_manager:
            await self.browser_manager.stop()
        logger.info("CUA Runtime 已关闭")
