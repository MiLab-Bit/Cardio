"""
CUA (Computer-Use Agent) Runtime — 让 AI 像人一样操作电脑

6 层架构实现自动化信息收集和操作：
├── Perception Layer      感知层：UI 元素识别、文本提取
├── Semantic Align Layer  语义对齐层：元素语义理解
├── State Modeling Layer  状态建模层：操作状态追踪
├── Planning Layer        规划层：任务分解与路径规划
├── Execution Layer       执行层：操作执行（点击/输入/滚动）
└── Validation Layer      校验层：结果验证与回滚

集成 Playwright 浏览器自动化（系统 Edge 通道）。
"""

import asyncio
import logging
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from byou.core.message_bus import MessageBus
from byou.tools.browser.session import BrowserSessionManager
from byou.infrastructure import BrowserManager
from byou.tools.cua.perception import PerceptionLayer
from byou.tools.cua.semantic_align import SemanticAlignLayer
from byou.tools.cua.state_modeling import StateModelingLayer
from byou.tools.cua.planning import PlanningLayer
from byou.tools.cua.execution import ExecutionLayer
from byou.tools.cua.validation import ValidationLayer

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class CuaTask:
    """CUA 任务定义"""

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
    """CUA 执行上下文"""

    current_state: dict[str, Any] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    screenshots: list[str] = field(default_factory=list)


class CuaRuntime:
    """Computer-Use Agent 运行时引擎。

    集成 Playwright 浏览器自动化，通过 6 层架构
    实现从感知到执行的完整闭环。
    """

    def __init__(
        self,
        message_bus: Optional[MessageBus] = None,
        browser_manager: Optional[BrowserManager] = None,
        use_browser: bool = True,
    ):
        self.message_bus = message_bus
        self.browser_manager = browser_manager
        self.use_browser = use_browser

        # 初始化 6 层架构
        self.perception = PerceptionLayer(self.browser_manager)
        self.semantic_align = SemanticAlignLayer()
        self.state_modeling = StateModelingLayer()
        self.planning = PlanningLayer()
        self.execution = ExecutionLayer(self.browser_manager)
        self.validation = ValidationLayer()

        self._active_tasks: dict[str, CuaTask] = {}
        self._context = CuaContext()

        logger.info(
            "CUA Runtime 初始化完成 (6 层架构, browser=%s)",
            "enabled" if (use_browser and browser_manager) else "disabled",
        )

    async def start_browser(self) -> None:
        """启动浏览器（如未注入则自动创建）。"""
        if self.browser_manager is None and self.use_browser:
            self.browser_manager = BrowserManager()
            self.perception.set_browser(self.browser_manager)
            self.execution.set_browser(self.browser_manager)

        if self.browser_manager and not self.browser_manager._started:
            await self.browser_manager.start()
            logger.info("CUA Runtime 浏览器已启动")

    async def execute_task(self, task: CuaTask) -> CuaTask:
        """执行一个 CUA 任务。

        6 层流水线：
        1. Perception → 感知当前界面状态
        2. Semantic Align → 理解界面元素语义
        3. State Modeling → 构建操作状态模型
        4. Planning → 规划操作路径
        5. Execution → 执行具体操作
        6. Validation → 验证结果
        """
        self._active_tasks[task.id] = task
        task.status = ExecutionStatus.RUNNING

        try:
            # Layer 1: Perception
            perception_result = await self.perception.process(
                task, self._context
            )
            self._context.current_state["perception"] = perception_result

            # Layer 2: Semantic Alignment
            semantic_result = await self.semantic_align.process(
                perception_result, self._context
            )
            self._context.current_state["semantic"] = semantic_result

            # Layer 3: State Modeling
            state_model = await self.state_modeling.process(
                semantic_result, self._context
            )
            self._context.current_state["model"] = state_model

            # Layer 4: Planning
            action_plan = await self.planning.process(
                state_model, task, self._context
            )
            self._context.current_state["plan"] = action_plan

            # 注入 task_id 到每一步
            for step in action_plan.get("steps", []):
                step.setdefault("task_id", task.id)

            # Layer 5: Execution
            execution_result = await self.execution.process(
                action_plan, self._context
            )
            self._context.current_state["execution"] = execution_result
            self._context.history.append(execution_result)

            # Layer 6: Validation
            validation_result = await self.validation.process(
                execution_result, task, self._context
            )

            if validation_result.get("success"):
                task.status = ExecutionStatus.SUCCESS
            else:
                task.status = ExecutionStatus.FAILED
                task.errors.append(
                    validation_result.get("error", "Unknown error")
                )

            task.result = {
                "perception": perception_result,
                "semantic": semantic_result,
                "state_model": state_model,
                "plan": action_plan,
                "execution": execution_result,
                "validation": validation_result,
            }

        except Exception as e:
            logger.exception("CUA 任务执行异常: %s", task.id)
            task.status = ExecutionStatus.FAILED
            task.errors.append(str(e))

        return task

    async def retry_task(self, task_id: str) -> Optional[CuaTask]:
        """重试失败的 CUA 任务。"""
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

        logger.info(
            "重试 CUA 任务 %s (剩余重试: %d)",
            task_id, task.max_retries,
        )
        return await self.execute_task(task)

    def get_task_status(self, task_id: str) -> Optional[ExecutionStatus]:
        """查询任务状态。"""
        task = self._active_tasks.get(task_id)
        return task.status if task else None

    async def shutdown(self) -> None:
        """关闭 CUA Runtime（含浏览器）。"""
        self._active_tasks.clear()

        if self.browser_manager:
            await self.browser_manager.stop()

        logger.info("CUA Runtime 已关闭")
