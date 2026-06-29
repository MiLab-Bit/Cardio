# byou/channels/voice/adapters/event_translator.py
"""VoiceEventTranslator — provider-specific payload → canonical ChannelEvent.

This is the ONLY module that touches provider-specific field names.
Everything downstream operates on ChannelEvent / CallTurn / CallSession.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from byou.channels.voice.models import (
    CallDirection,
    CallSession,
    CallState,
    CallTurn,
    ChannelEvent,
    ChannelKind,
    Speaker,
)

logger = logging.getLogger(__name__)


class VoiceEventTranslator:
    """Translates raw provider webhook payloads into ChannelEvent.

    Each provider gets its own translate_<provider>() method.
    All produce the exact same ChannelEvent type.
    """

    # ── Event type mapping (Dograh → canonical) ──
    DOGRAH_EVENT_MAP: dict[str, str] = {
        "call.initiated":       "call_started",
        "call.ringing":         "call_ringing",
        "call.answered":        "call_answered",
        "call.hangup":          "call_ended",
        "call.error":           "call_failed",
        "user.speech.start":    "user_speech_start",
        "user.speech.end":      "user_turn",
        "agent.speech.start":   "agent_speech_start",
        "agent.speech.end":     "agent_turn",
        "call.transfer.request": "transfer_requested",
        "call.transfer.complete": "transfer_completed",
    }

    # ── Dograh translator ──────────────────────────────

    def translate_dograh(
        self, raw: dict, headers: dict | None = None
    ) -> ChannelEvent:
        """Dograh webhook payload → ChannelEvent."""
        dograh_event = raw.get("event", "")
        canonical_type = self.DOGRAH_EVENT_MAP.get(dograh_event, "unknown")

        session_id = raw.get("session_id") or raw.get("call_id", "")
        direction = raw.get("direction", "outbound")

        event = ChannelEvent(
            session_id=session_id,
            event_type=canonical_type,
            channel=ChannelKind.VOICE,
            direction=CallDirection(direction),
            provider_ref=raw.get("call_id") or raw.get("id", ""),
            raw_meta=_sanitize_meta(raw),
        )

        # Attach turn if speech data present
        if canonical_type == "user_turn":
            event.turn = self._dograh_to_turn(session_id, raw)

        # Attach session snapshot for lifecycle events
        if canonical_type in ("call_started", "call_answered", "call_ended", "call_failed"):
            event.session = self._dograh_to_session_snapshot(session_id, raw, canonical_type)

        return event

    def _dograh_to_turn(self, session_id: str, raw: dict) -> CallTurn:
        return CallTurn(
            turn_id=raw.get("turn_id", ""),
            session_id=session_id,
            sequence=raw.get("turn_sequence", 0),
            speaker=Speaker.USER,
            text=raw.get("transcript", ""),
            audio_chunk_ref=raw.get("audio_url"),
            duration_ms=raw.get("duration_ms", 0),
        )

    def _dograh_to_session_snapshot(
        self, session_id: str, raw: dict, event_type: str
    ) -> CallSession:
        state = {
            "call_started": CallState.RINGING,
            "call_answered": CallState.ACTIVE,
            "call_ended": CallState.ENDED,
            "call_failed": CallState.FAILED,
        }.get(event_type, CallState.PENDING)

        return CallSession(
            session_id=session_id,
            lead_id=raw.get("lead_id", ""),
            channel=ChannelKind.VOICE,
            direction=CallDirection(raw.get("direction", "outbound")),
            state=state,
            provider_ref=raw.get("call_id", ""),
        )

    # ── Generic / future provider translators ───────────

    def translate_generic(self, raw: dict, provider: str) -> ChannelEvent:
        """Fallback translator for unknown providers.

        Requires at minimum: event_type, session_id.
        """
        return ChannelEvent(
            session_id=raw.get("session_id", raw.get("call_id", "")),
            event_type=raw.get("event_type", raw.get("event", "unknown")),
            channel=ChannelKind.VOICE,
            raw_meta={"_provider": provider, **{k: v for k, v in raw.items() if k != "event"}},
        )

    # ── Reverse: AgentTurn → provider instruction ──────

    def to_dograh_message(self, session_id: str, agent_turn: dict) -> dict:
        """AgentTurn → Dograh speak instruction."""
        return {
            "call_id": session_id,
            "action": "speak",
            "text": agent_turn.get("text", ""),
            "emotion": agent_turn.get("emotion", "neutral"),
            "metadata": agent_turn.get("metadata", {}),
        }

    def to_dograh_handoff(self, request: dict) -> dict:
        """Handoff request → Dograh transfer instruction."""
        return {
            "call_id": request.get("session_id", ""),
            "action": "transfer",
            "target": request.get("transfer_target", "sales"),
            "context": request.get("handoff_notes", ""),
        }


# ── Helpers ─────────────────────────────────────────────

def _sanitize_meta(raw: dict, max_values: int = 20) -> dict:
    """Strip large binary fields from raw meta before storing."""
    skip_keys = {"audio_data", "audio_chunk", "recording", "raw_audio", "audio_base64"}
    return {k: v for k, v in list(raw.items())[:max_values] if k not in skip_keys}
