"""Synthesizer Agent — fuse extraction + research into customer profile & scoring."""

from __future__ import annotations

import json
import logging
from typing import Any

from byou.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "customer_level": "C",
    "intent_score": 0.5,
    "customer_value_score": 0.5,
    "key_needs": [],
    "buying_signals": [],
    "summary": "",
}


class SynthesizerAgent(BaseAgent):
    """Merge extraction results and research into a scored customer profile."""

    def __init__(self, **kwargs):
        super().__init__(
            name="synthesizer",
            description="Synthesize customer profile, intent scoring, needs analysis",
            temperature=0.5,
            **kwargs,
        )

    def _default_prompt(self) -> str:
        return """You are a customer profile analyst.

Synthesize extraction + research into a complete customer picture in JSON:
{
  "enriched_profile": { /* supplement missing fields from original profile */ },
  "customer_level": "A|B|C|D",
  "intent_score": 0.0,
  "customer_value_score": 0.0,
  "key_needs": [],
  "buying_signals": [],
  "decision_makers": [],
  "budget_indication": "",
  "timeline": "",
  "competitor_relationship": "",
  "recommended_approach": "",
  "risk_factors": [],
  "summary": ""
}

Grading:
- A: high intent + high value, follow up within 1 week
- B: medium intent/value, follow up within 2 weeks
- C: low intent or value, quarterly
- D: no near-term opportunity, monitor"""

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        profile: dict = input_data.get("profile", {})
        research: dict = input_data.get("research", {})
        raw_text: str = input_data.get("raw_text", "")

        try:
            prompt = (
                "## Customer Information\n"
                f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
                "## Background Research\n"
                f"{json.dumps(research, ensure_ascii=False, indent=2)}\n\n"
                "## Raw Interaction\n"
                f"{raw_text[:2000]}\n\n"
                "Synthesize a complete customer profile with scoring."
            )
            result = await self.call_llm_json([{"role": "user", "content": prompt}])
            _apply_defaults(result, _DEFAULTS)
            return result
        except Exception:
            logger.exception("Synthesizer failed")
            return {**_DEFAULTS, "enriched_profile": profile, "error": "Synthesizer failed"}


def _apply_defaults(result: dict, defaults: dict) -> None:
    for key, default in defaults.items():
        if key not in result:
            result[key] = default
