"""CUA Planning — 规划 + 状态追踪 (v2: StateModel-integrated).

v1: prompt-based step generation.
v2: uses StateModel + StateClusterer + ActionAvailabilityDetector
    for proper state-aware planning.
"""

from __future__ import annotations

import logging
from typing import Any

from byou.cua.state_model import (
    ActionAvailabilityDetector,
    StateBuilder,
    StateClusterer,
    StateModel,
    state_similarity,
)

logger = logging.getLogger(__name__)


class PlanningLayer:
    """规划层 — state-aware step generation + state tracking.

    v2 changes:
      - Converts perception result → StateModel
      - Checks StateClusterer for seen states (re-use plan)
      - Uses ActionAvailabilityDetector for available actions
      - Maintains StateGraph for transition learning
    """

    def __init__(self, similarity_threshold: float = 0.85):
        self._state_clusterer = StateClusterer(similarity_threshold=similarity_threshold)
        self._action_detector = ActionAvailabilityDetector()
        self._state_history: list[StateModel] = []
        self._current_state: StateModel | None = None
        self._expected_state: StateModel | None = None

    async def process(self, perception_result: dict, task: Any, context: Any) -> dict:
        """Main planning entry point (StateModel-aware)."""

        # 1. Build StateModel from perception
        state = StateBuilder.from_perception(perception_result)
        self._state_history.append(state)
        self._current_state = state

        # 2. Check if we've seen a similar state before
        cached_cid, is_new = self._state_clusterer.get_or_add(state)
        reuse_plan = (not is_new) and self._has_cached_plan(cached_cid)

        if reuse_plan:
            logger.info("Reusing cached plan for state cluster %s", cached_cid)
            steps = self._get_cached_steps(cached_cid)
        else:
            # 3. Detect available actions from state
            available = self._action_detector.detect(state)

            # 4. Generate steps from available actions + task description
            anomalies = self._detect_anomalies(state)
            steps = self._generate_steps(
                state, available, task, anomalies,
            )

            # Cache the plan for this cluster
            self._cache_plan(cached_cid, steps)

        plan = {
            "plan_id": f"plan_{task.id}",
            "state_id": state.state_id,
            "cluster_id": cached_cid,
            "steps": steps,
            "fallback_plan": self._fallback(),
            "estimated_steps": len(steps),
            "page_state": state.title or state.url,
            "anomalies": self._detect_anomalies(state),
            "confidence": 0.85 if not self._detect_anomalies(state) else 0.5,
            "reused_plan": reuse_plan,
        }
        return plan

    # ── Step generation (StateModel-aware) ──────────────────────

    def _generate_steps(
        self,
        state: StateModel,
        available: list,
        task: Any,
        anomalies: list[str],
    ) -> list[dict]:
        """Generate steps using StateModel + available actions."""
        steps: list[dict] = []
        step_n = 0

        # Navigate if URL mismatch
        if task.target_url and state.url != task.target_url:
            step_n += 1
            steps.append({
                "step": step_n,
                "action": "navigate",
                "target": task.target_url,
                "description": f"导航到 {task.target_url}",
                "expected_result": "页面加载完成",
                "timeout_ms": 30000,
            })

        # Handle anomalies
        for anomaly in anomalies:
            if "卡住" in anomaly or "stale" in anomaly:
                step_n += 1
                steps.append({
                    "step": step_n,
                    "action": "refresh",
                    "target": "",
                    "description": "刷新页面解决卡住",
                    "timeout_ms": 15000,
                })

        # If task has explicit actions, convert them
        if task.actions:
            for i, action in enumerate(task.actions, step_n + 1):
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
        else:
            # Suggest actions from available actions (top 3)
            for i, action in enumerate(available[:3], step_n + 1):
                steps.append({
                    "step": i,
                    "action": action.action_type,
                    "target": action.target,
                    "description": action.description,
                    "expected_result": f"{action.action_type} 成功",
                    "timeout_ms": 5000,
                })

        # Always add a wait step at the end
        if not steps or steps[-1]["action"] != "wait":
            step_n = len(steps)
            steps.append({
                "step": step_n + 1,
                "action": "wait",
                "target": "",
                "value": "2000",
                "description": "等待页面稳定",
                "timeout_ms": 10000,
            })

        return steps

    def _fallback(self) -> list[dict]:
        return [
            {"step": 1, "action": "retry_last", "description": "重试上一步", "timeout_ms": 15000},
            {"step": 2, "action": "notify", "description": "通知用户人工介入"},
        ]

    # ── Anomaly detection (StateModel-aware) ──────────────────────

    def _detect_anomalies(self, state: StateModel) -> list[str]:
        anomalies: list[str] = []

        # Check expected state (if set)
        if self._expected_state:
            expected_elems = self._expected_state.elements
            current_elems = {_elem_sig(e) for e in state.elements}
            expected_sigs = {_elem_sig(e) for e in expected_elems}
            missing = expected_sigs - current_elems
            if missing:
                anomalies.append(f"预期元素未出现: {missing}")

        # Check stale state (3 consecutive identical states)
        if len(self._state_history) >= 3:
            recent = self._state_history[-3:]
            if all(s.state_id == recent[0].state_id for s in recent):
                anomalies.append("页面连续3步无变化，可能卡住")

        return anomalies

    # ── State cluster cache ──────────────────────────────────────

    def _has_cached_plan(self, cluster_id: str) -> bool:
        return hasattr(self, "_plan_cache") and cluster_id in self._plan_cache

    def _get_cached_steps(self, cluster_id: str) -> list[dict]:
        return self._plan_cache.get(cluster_id, [])

    def _cache_plan(self, cluster_id: str, steps: list[dict]) -> None:
        if not hasattr(self, "_plan_cache"):
            self._plan_cache: dict[str, list[dict]] = {}
        self._plan_cache[cluster_id] = steps

    # ── Public API ──────────────────────────────────────────────

    def set_expected_state(self, expected: StateModel) -> None:
        self._expected_state = expected

    def get_recent_plans(self, limit: int = 5) -> list[list[dict]]:
        return [p for p in getattr(self, "_plan_cache", {}).values()][-limit:]

    def is_ready(self) -> bool:
        return True

    def get_state_summary(self) -> dict[str, Any]:
        """Return summary of current state (for observability)."""
        if not self._current_state:
            return {"status": "no_state"}
        return self._current_state.summarize()


def _elem_sig(e: dict[str, Any]) -> str:
    """Element signature for comparison."""
    return f"{e.get('type','?')}:{e.get('text','')}"
