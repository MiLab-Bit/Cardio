# byou/core/conversation/turn_executor.py
"""TurnExecutor — generates AgentTurn from user speech + session context.

Wires the existing Strategist agent for turn-by-turn talking points.
Implements the TurnExecutorPort Protocol expected by VoiceCallCoordinator.
"""

from __future__ import annotations

import logging
from typing import Any

from byou.channels.voice.models import AgentTurn, CallSession, CallTurn

logger = logging.getLogger(__name__)


class TurnExecutor:
    """Generates agent responses during live voice calls.

    Each user turn triggers:
      1. SLM classification (intent / sentiment — if SLM gateway available)
      2. Strategist.generate_turn_response() with conversation context
      3. AgentTurn → back to VoiceAdapter for TTS playback

    This is the in-call bridge between VoiceChannel and Byou Core.
    """

    def __init__(
        self,
        *,
        orchestrator=None,  # byou.core.orchestrator.Orchestrator
        slm=None,  # SLMGateway Protocol
    ) -> None:
        self._orchestrator = orchestrator
        self._slm = slm

    async def execute(
        self,
        session: CallSession,
        turn: CallTurn,
        history: list[CallTurn],
    ) -> AgentTurn:
        """Generate the agent's response for this user turn.

        Args:
            session: Current call session (has pre_call_package with talking_points)
            turn: The user's latest turn (text + optional audio_features)
            history: All prior turns in this call

        Returns:
            AgentTurn with text to speak and any actions to execute
        """
        # ── Step 1: Classify user intent ──
        intent = "general"
        sentiment = "neutral"
        if self._slm:
            try:
                intent_result = await self._slm.classify_intent(turn.text)
                intent = intent_result.get("intent", "general")
                sentiment_result = await self._slm.analyze_sentiment(turn.text)
                sentiment = sentiment_result.get("sentiment", "neutral")
            except Exception:
                logger.debug("SLM classification failed, using defaults")

        # ── Step 2: Generate response ──
        response_text = await self._generate_response(
            session, turn, history, intent, sentiment
        )

        # ── Step 3: Determine actions ──
        actions = self._determine_actions(intent, sentiment, turn.text)

        return AgentTurn(
            text=response_text,
            actions=actions,
            emotion=self._emotion_for_sentiment(sentiment),
            confidence=0.8,
            metadata={"intent": intent, "sentiment": sentiment},
        )

    # ── Internal ──────────────────────────────────────────

    async def _generate_response(
        self,
        session: CallSession,
        turn: CallTurn,
        history: list[CallTurn],
        intent: str,
        sentiment: str,
    ) -> str:
        """Generate agent response text.

        If orchestrator + strategist available, uses the real pipeline.
        Otherwise, falls back to context-aware templated responses.
        """
        # Try real pipeline
        if self._orchestrator:
            try:
                result = await self._orchestrator.run_pipeline(
                    raw_input={
                        "conversation_context": {
                            "user_text": turn.text,
                            "user_intent": intent,
                            "user_sentiment": sentiment,
                            "lead_context": (
                                session.pre_call_package.lead.model_dump()
                                if session.pre_call_package
                                else {}
                            ),
                            "talking_points": [
                                tp.model_dump()
                                for tp in (session.pre_call_package.talking_points if session.pre_call_package else [])
                            ],
                            "objection_handling": (
                                session.pre_call_package.objection_handling
                                if session.pre_call_package
                                else {}
                            ),
                            "conversation_history": [
                                f"[{h.speaker.value}] {h.text}"
                                for h in history[-10:]  # last 10 turns
                            ],
                        }
                    },
                    pipeline_id=f"turn_{session.session_id}_{turn.sequence}",
                )
                strategy = result.get("strategy", {})
                talking_points = strategy.get("talking_points", [])
                if talking_points:
                    return talking_points[0].get("script", self._fallback_response(intent))
            except Exception:
                logger.exception("Pipeline-based response failed, using fallback")

        return self._fallback_response(intent)

    @staticmethod
    def _fallback_response(intent: str) -> str:
        responses = {
            "greeting": "您好！感谢接听。",
            "inquiry": "这是个很好的问题，让我为您详细说明。",
            "objection": "理解您的顾虑。让我从另一个角度为您分析。",
            "interest": "很高兴您对这个方向感兴趣。",
            "not_interested": "完全理解。方便告诉我目前最关注什么方向吗？",
            "hangup": "感谢您的时间，后续我们会通过邮件发送详细资料。再见！",
            "general": "我明白了。让我接着为您介绍。",
        }
        return responses.get(intent, responses["general"])

    @staticmethod
    def _determine_actions(intent: str, sentiment: str, text: str) -> list[str]:
        """Determine actions to take based on user input."""
        actions = []

        if intent == "hangup":
            actions.append("end_call")

        if sentiment == "angry":
            actions.append("escalation_check")

        if "转人工" in text or "找真人" in text:
            actions.append("request_handoff")

        return actions

    @staticmethod
    def _emotion_for_sentiment(sentiment: str) -> str:
        return {
            "positive": "friendly",
            "negative": "empathetic",
            "angry": "calm",
            "neutral": "professional",
        }.get(sentiment, "professional")
