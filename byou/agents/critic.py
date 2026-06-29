"""Critic Agent — quality audit of the full pipeline output."""

from __future__ import annotations

import json
import logging
from typing import Any

from byou.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class CriticAgent(BaseAgent):
    """Audit extraction, research, synthesis and strategy for accuracy and consistency."""

    def __init__(self, **kwargs):
        super().__init__(
            name="critic",
            description="Quality audit: accuracy, consistency, feasibility",
            temperature=0.3,
            **kwargs,
        )

    def _default_prompt(self) -> str:
        return """You are a strict quality auditor.

Audit all pipeline outputs and produce JSON:
{
  "passed": true,
  "trust_score": 0.0,
  "extraction_quality": {"score": 0.0, "issues": [], "missing_fields": []},
  "research_reliability": {"score": 0.0, "uncertain_points": [], "bias_concerns": []},
  "profile_consistency": {"score": 0.0, "contradictions": [], "overconfidence_flags": []},
  "strategy_feasibility": {"score": 0.0, "impractical_suggestions": []},
  "risk_alerts": [{"type": "", "description": "", "severity": "medium", "recommendation": ""}],
  "corrections": [],
  "overall_assessment": ""
}

If trust_score < 0.4, passed must be false. Be honest about risks."""

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        profile: dict = input_data.get("profile", {})
        research: dict = input_data.get("research", {})
        synthesis: dict = input_data.get("synthesis", {})
        strategy: dict = input_data.get("strategy", {})

        try:
            prompt = (
                "### Extracted Info\n"
                f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
                "### Research\n"
                f"{json.dumps(research, ensure_ascii=False, indent=2)}\n\n"
                "### Synthesis\n"
                f"{json.dumps(synthesis, ensure_ascii=False, indent=2)}\n\n"
                "### Strategy\n"
                f"{json.dumps(strategy, ensure_ascii=False, indent=2)}\n\n"
                "Perform a comprehensive quality audit."
            )
            result = await self.call_llm_json([{"role": "user", "content": prompt}])

            if "passed" not in result:
                result["passed"] = result.get("trust_score", 0.5) >= 0.4
            result.setdefault("risk_alerts", [])
            result.setdefault("overall_assessment", "")
            return result
        except Exception:
            logger.exception("Critic failed")
            return {
                "passed": False,
                "trust_score": 0.0,
                "risk_alerts": [{"type": "system_error", "description": "Critic failed", "severity": "high", "recommendation": "manual review"}],
                "overall_assessment": "Audit process errored",
            }
