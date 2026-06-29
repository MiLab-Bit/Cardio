"""BD Strategist Agent — generate personalised BD follow-up strategy."""

from __future__ import annotations

import json
import logging
from typing import Any

from byou.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_PRIORITY_MAP: dict[str, str] = {"A": "high", "B": "medium", "C": "low", "D": "low"}


class StrategistAgent(BaseAgent):
    """Produce actionable BD strategies from customer profiles."""

    def __init__(self, **kwargs):
        super().__init__(
            name="strategist",
            description="Generate BD strategy: talking points, follow-up plan, risk assessment",
            temperature=0.8,
            **kwargs,
        )

    def _default_prompt(self) -> str:
        return """You are a senior BD strategist.

Generate a personalised BD strategy in JSON:
{
  "customer_analysis": "",
  "pain_points": [],
  "opportunities": [],
  "talking_points": [{"angle": "", "script": "", "key_message": ""}],
  "objection_handling": {},
  "follow_up_plan": {"timing": "", "channel": "phone", "approach": "", "priority": "medium"},
  "risks": [{"type": "", "description": "", "severity": "medium", "mitigation": ""}],
  "competition_analysis": "",
  "recommended_actions": [],
  "confidence_level": 0.7
}

Principles: scripts must be actionable; risks must be honest; lead with customer pain points, not product features."""

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        profile: dict = input_data.get("profile", {})
        synthesis: dict = input_data.get("synthesis", {})
        customer_level: str = input_data.get("customer_level", "C")

        try:
            prompt = (
                "## Customer Profile\n"
                f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
                "## Analysis\n"
                f"{json.dumps(synthesis, ensure_ascii=False, indent=2)}\n\n"
                f"Customer level: {customer_level}\n"
                "Produce a concrete, actionable BD strategy."
            )
            result = await self.call_llm_json([{"role": "user", "content": prompt}])
            _apply_strategy_defaults(result, customer_level)
            return {"strategy": result}
        except Exception:
            logger.exception("Strategist failed")
            return {
                "strategy": {
                    "customer_analysis": "",
                    "pain_points": [],
                    "recommended_actions": [],
                    "confidence_level": 0.0,
                },
                "error": "Strategist failed",
            }


def _apply_strategy_defaults(result: dict, customer_level: str) -> None:
    default_priority = _PRIORITY_MAP.get(customer_level, "medium")
    if not result.get("follow_up_plan"):
        result["follow_up_plan"] = {
            "timing": "this week",
            "channel": "phone",
            "approach": "initial outreach, establish relationship",
            "priority": default_priority,
        }
    result.setdefault("talking_points", [])
    result.setdefault("recommended_actions", [])
