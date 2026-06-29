"""
CUA Layer 4: Planning — 规划层

基于当前状态制定操作计划：
- 任务分解为原子操作
- 操作路径规划
- 应急预案（if-else 分支）
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PlanningLayer:
    """
    规划层 — CUA 的第四层。

    将高层任务分解为一系列可执行的原子操作序列。
    """

    def __init__(self):
        self._plan_history: list[list[dict]] = []

    async def process(self, state_model: dict, task: Any, context: Any) -> dict:
        """
        制定操作计划。

        Args:
            state_model: State Modeling 层的输出
            task: CUA 任务定义
            context: CUA 执行上下文

        Returns:
            {
                "plan_id": str,
                "steps": list[dict],
                "fallback_plan": list[dict],
                "estimated_steps": int,
                "confidence": float,
            }
        """
        logger.debug("CUA Planning: 制定操作计划")

        page_state = state_model.get("page_state", "unknown")
        anomalies = state_model.get("anomalies", [])
        task_actions = task.actions or []

        # 如果任务已定义具体动作，直接使用
        if task_actions:
            steps = self._convert_task_actions(task_actions)
        else:
            steps = self._generate_plan(state_model, task, anomalies)

        # 生成后备计划
        fallback = self._generate_fallback(steps)

        plan = {
            "plan_id": f"plan_{task.id}",
            "steps": steps,
            "fallback_plan": fallback,
            "estimated_steps": len(steps),
            "page_state": page_state,
            "confidence": 0.85 if not anomalies else 0.5,
        }

        self._plan_history.append(steps)
        return plan

    def _convert_task_actions(self, actions: list[dict]) -> list[dict]:
        """将任务定义的动作转换为操作步骤"""
        steps = []
        for i, action in enumerate(actions, 1):
            steps.append({
                "step": i,
                "action": action.get("type", "click"),
                "target": action.get("target", ""),
                "value": action.get("value", ""),
                "description": action.get("description", f"执行 {action.get('type', 'click')}"),
                "expected_result": action.get("expected", ""),
                "timeout_ms": action.get("timeout", 5000),
                "retry_on_failure": action.get("retry", True),
            })
        return steps

    def _generate_plan(
        self,
        state_model: dict,
        task: Any,
        anomalies: list[str],
    ) -> list[dict]:
        """根据任务描述自动生成操作计划"""
        steps = []

        # 如果有目标 URL 且当前不在该页面
        if task.target_url:
            steps.append({
                "step": 1,
                "action": "navigate",
                "target": task.target_url,
                "description": f"导航到 {task.target_url}",
                "expected_result": "页面加载完成",
                "timeout_ms": 30000,
            })

        # 处理异常情况
        for anomaly in anomalies:
            if "卡住" in anomaly:
                steps.append({
                    "step": len(steps) + 1,
                    "action": "refresh",
                    "target": "",
                    "description": "刷新页面解决卡住问题",
                    "expected_result": "页面重新加载",
                    "timeout_ms": 15000,
                })

        # 基于任务描述添加操作
        steps.append({
            "step": len(steps) + 1,
            "action": "wait",
            "target": "",
            "value": "2000",
            "description": f"等待页面稳定: {task.description}",
            "expected_result": "页面元素加载完成",
            "timeout_ms": 10000,
        })

        return steps

    def _generate_fallback(self, primary_steps: list[dict]) -> list[dict]:
        """生成后备计划"""
        return [
            {
                "step": 1,
                "action": "retry_last",
                "description": "重试上一步操作",
                "timeout_ms": 15000,
            },
            {
                "step": 2,
                "action": "notify",
                "description": "通知用户需要人工介入",
            },
        ]

    def get_recent_plans(self, limit: int = 5) -> list[list[dict]]:
        """获取最近的计划"""
        return self._plan_history[-limit:]

    def is_ready(self) -> bool:
        return True
