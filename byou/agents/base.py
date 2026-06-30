"""Agent — single generic agent driven by declarative config.

Every agent shares one call_llm + call_llm_json path, differing only in the
system prompt, prompt builder and optional post-process hook — all defined in
:mod:`byou.agents.configs`.

v2: integrates ModelRouter for three-tier LLM cost optimisation.
"""

from __future__ import annotations

import json  # noqa: E402  (moved from inner function to module level)
import logging
from typing import Any

from byou.core.llm_client import get_client, get_client_for_tier, get_model_for_tier
from byou.core.llm_parser import parse_llm_json
from byou.core.model_router import ModelRouter, ModelTier

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────

_TIER_ORDER = [ModelTier.CHEAP, ModelTier.MEDIUM, ModelTier.DEEP]


def _next_tier(tier: ModelTier) -> ModelTier | None:
    """Return the next higher tier, or None if already at DEEP."""
    idx = _TIER_ORDER.index(tier)
    if idx < len(_TIER_ORDER) - 1:
        return _TIER_ORDER[idx + 1]
    return None


def _quick_confidence(text: str) -> float:
    """Rough confidence estimate for escalation decisions.

    Heuristic (fast, no LLM call):
    - Empty / error → 0.0
    - Valid JSON with non-empty fields → 0.8
    - JSON but mostly empty → 0.4
    - Non-JSON but has substantial text → 0.6
    """
    if not text or not text.strip():
        return 0.0
    stripped = text.strip()

    # Try JSON parse
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            # Count non-empty string values
            non_empty = sum(
                1 for v in obj.values()
                if isinstance(v, str) and len(v) > 5
            )
            total = max(len(obj), 1)
            return min(0.95, 0.4 + 0.5 * (non_empty / total))
        return 0.8  # valid JSON, not dict
    except (json.JSONDecodeError, TypeError):
        pass

    # Not JSON — check text substance
    words = stripped.split()
    if len(words) < 10:
        return 0.3
    if "error" in stripped.lower() or "failed" in stripped.lower():
        return 0.2
    return 0.6


class Agent:
    """Generic LLM-backed agent with three-tier model routing.

    Behaviour is controlled by a config dict (see ``AGENT_CONFIGS`` in
    ``byou.agents.configs``).  The same class serves as Extractor, Researcher,
    Synthesizer, Strategist *and* Critic.

    Model routing:
    - Each agent declares a ``preferred_tier`` (CHEAP / MEDIUM / DEEP)
    - At call time, the router may upscale tier if task looks complex
    - Escalation is automatic on low-confidence responses
    """

    def __init__(self, name: str, config: dict[str, Any] = None):
        self.name = name
        cfg = config or {}
        self.description = cfg.get("description", "")
        self.temperature = cfg.get("temperature", 0.7)
        self.system_prompt = cfg.get("system_prompt", "You are a helpful assistant.")
        self._build_prompt = cfg.get("build_prompt", lambda d: str(d))
        self._postprocess = cfg.get("postprocess", lambda parsed, inp: parsed)
        self._default_result = cfg.get("default_result", {})
        self._model = cfg.get("model", "gpt-4o")
        self._max_retries = cfg.get("max_retries", 3)

        # Model router (v2) — accept string or ModelTier
        _raw_tier = cfg.get("preferred_tier", "medium")
        if isinstance(_raw_tier, ModelTier):
            self._preferred_tier = _raw_tier
        else:
            # Handle both value ("cheap") and name ("CHEAP") forms
            try:
                self._preferred_tier = ModelTier(str(_raw_tier).lower())
            except ValueError:
                # Try lookup by member name (e.g. "CHEAP" → ModelTier.CHEAP)
                self._preferred_tier = ModelTier[str(_raw_tier).upper()]
        self._router = ModelRouter()
        self._escalation_enabled: bool = cfg.get("escalation_enabled", True)

        # Legacy single-client fallback
        self.client = get_client()
        logger.info(
            "Agent [%s] ready (model=%s, preferred_tier=%s)",
            name, self._model, self._preferred_tier.name,
        )

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run the agent: build prompt → call LLM → post-process."""
        try:
            prompt = self._build_prompt(input_data)
            if not prompt:
                return self._default_result
            result = await self.call_llm_json([{"role": "user", "content": prompt}])
            return self._postprocess(result, input_data)
        except Exception:
            logger.exception("Agent [%s] failed", self.name)
            return self._default_result

    async def call_llm(self, messages: list[dict[str, str]]) -> str:
        """Call LLM with retry + three-tier routing, returning raw text.

        Routing logic (v2):
        1. Build prompt text from messages
        2. ``ModelRouter.route()`` picks a tier (accepts str or ComplexityScore)
        3. Call LLM with the tier's client / model
        4. If escalation enabled and confidence is low → retry one tier up
        """
        from byou.core.model_router import ComplexityScore, RoutingDecision, ModelTier

        # ── Build routing prompt from messages ──────────────────────
        full_text = " ".join(m.get("content", "") for m in messages)

        last_error = None
        for attempt in range(1, self._max_retries + 1):
            # ── Route ────────────────────────────────────────────────
            decision: RoutingDecision = await self._router.route(
                full_text,
                tools=[],
                history_turns=len(messages) - 1,
                force_tier=self._preferred_tier if attempt == 1 else None,
            )
            tier = decision.tier
            client = get_client_for_tier(tier)
            model = get_model_for_tier(tier)

            logger.debug(
                "[%s] tier=%s model=%s reason=%s",
                self.name, tier.name, model, "; ".join(decision.reasons),
            )

            # ── Call ─────────────────────────────────────────────────
            full = [{"role": "system", "content": self.system_prompt}, *messages]
            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=full,
                    temperature=self.temperature,
                )
                content = resp.choices[0].message.content or ""

                # ── Escalation check ───────────────────────────────
                if self._escalation_enabled:
                    confidence = _quick_confidence(content)
                    next_t = _next_tier(tier)
                    if confidence < 0.6 and next_t is not None:
                        logger.info(
                            "[%s] low confidence (%.2f), escalating %s→%s",
                            self.name, confidence, tier.name, next_t.name,
                        )
                        self._preferred_tier = next_t
                        continue  # retry with deeper tier

                logger.debug("[%s] LLM OK (attempt %d/%d)", self.name, attempt, self._max_retries)
                return content

            except Exception as e:
                last_error = e
                # On rate-limit or server error, try stepping up one tier
                if self._escalation_enabled:
                    next_t = _next_tier(tier)
                    if next_t is not None:
                        logger.warning("[%s] LLM error (attempt %d/%d): %s → escalate tier", self.name, attempt, self._max_retries, e)
                        self._preferred_tier = next_t
                        continue
                logger.warning("[%s] LLM fail (attempt %d/%d): %s", self.name, attempt, self._max_retries, e)

        raise RuntimeError(
            f"Agent [{self.name}] LLM calls exhausted ({self._max_retries}): {last_error}"
        )

    async def call_llm_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Call LLM and parse the response as JSON."""
        raw = await self.call_llm(messages)
        return parse_llm_json(raw)

    def __repr__(self) -> str:
        return f"<Agent(name={self.name}, model={self._model})>"
