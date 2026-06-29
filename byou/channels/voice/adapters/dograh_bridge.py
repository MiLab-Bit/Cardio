# byou/channels/voice/adapters/dograh_bridge.py
"""Dograh bridge — adapts Dograh voice AI platform as a Byou voice provider.

Dograh handles:
  - Twilio/Telnyx/telephony gateway
  - STT/TTS via Pipecat runtime (dograh-hq/pipecat.git submodule)
  - Call recording storage
  - Workflow orchestration

Byou handles:
  - Pre-call: research, enrichment, strategy
  - In-call: turn-level talking points, objection handling
  - Post-call: qualification signals, memory distillation, follow-up

Bridge responsibilities:
  1. Receive Dograh webhooks (call events + STT transcripts)
  2. Translate → ChannelEvent via VoiceEventTranslator
  3. Feed ChannelEvent → VoiceCallCoordinator
  4. Send AgentTurn → Dograh TTS instruction
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass, field

from byou.channels.voice.adapters.event_translator import VoiceEventTranslator
from byou.channels.voice.models import AgentTurn, ChannelEvent, PreCallPackage
from byou.channels.voice.ports import InboundChannelEventPort

logger = logging.getLogger(__name__)


@dataclass
class DograhBridgeConfig:
    """Dograh-specific configuration.

    All fields are provider-specific and stay inside the adapter.
    """
    api_key: str = ""
    webhook_secret: str = ""
    api_base_url: str = "https://api.dograh.com/v1"
    timeout_seconds: int = 30
    max_retries: int = 3


class DograhBridge(InboundChannelEventPort):
    """Dograh provider adapter — implements InboundChannelEventPort.

    This is the ONLY file allowed to import dograh_sdk or call Dograh APIs.
    """

    def __init__(self, config: DograhBridgeConfig | None = None) -> None:
        self._config = config or DograhBridgeConfig()
        self._translator = VoiceEventTranslator()
        self._pending_calls: dict[str, PreCallPackage] = {}

    # ── InboundChannelEventPort implementation ──────────

    async def handle_webhook(self, raw_payload: dict, headers: dict) -> ChannelEvent:
        """Receive Dograh webhook → verify → translate → ChannelEvent."""
        # Verify signature (placeholder)
        self._verify_webhook(raw_payload, headers)

        # Translate provider payload → canonical event
        event = self._translator.translate_dograh(raw_payload, headers)

        logger.info(
            "Dograh webhook: %s → %s (session=%s)",
            raw_payload.get("event", "?"),
            event.event_type,
            event.session_id,
        )
        return event

    # ── Outbound call initiation ────────────────────────

    async def initiate_call(self, package: PreCallPackage) -> str:
        """Initiate an outbound call via Dograh API.

        Returns: Dograh call_id (stored as CallSession.provider_ref).
        """
        # Placeholder: real implementation calls Dograh API
        call_id = f"dograh_{package.lead.lead_id}"

        self._pending_calls[call_id] = package

        logger.info(
            "Dograh outbound call: %s → %s (%s)",
            call_id,
            package.lead.contact_name,
            package.lead.phone,
        )

        # Store package for when webhook events arrive
        return call_id

    async def send_agent_turn(self, provider_ref: str, turn: AgentTurn) -> dict:
        """Send AgentTurn text to Dograh for TTS playback."""
        instruction = self._translator.to_dograh_message(provider_ref, turn.model_dump())
        # Placeholder: real implementation calls Dograh API
        logger.debug("Dograh speak: %s → %s", provider_ref, turn.text[:50])
        return instruction

    async def send_handoff(self, provider_ref: str, request: dict) -> dict:
        """Send transfer request to Dograh."""
        instruction = self._translator.to_dograh_handoff(request)
        logger.info("Dograh transfer: %s → %s", provider_ref, instruction.get("target"))
        return instruction

    async def end_call(self, provider_ref: str) -> dict:
        """End a call via Dograh API."""
        logger.info("Dograh hangup: %s", provider_ref)
        return {"call_id": provider_ref, "action": "hangup"}

    # ── Webhook verification ────────────────────────────

    def _verify_webhook(self, payload: dict, headers: dict) -> None:
        """Verify Dograh webhook signature (placeholder)."""
        secret = self._config.webhook_secret
        if not secret:
            return  # no verification configured

        signature = headers.get("X-Dograh-Signature", "")
        if not signature:
            logger.warning("Missing Dograh webhook signature")
            return

        # Placeholder: real implementation computes HMAC-SHA256
        expected = hmac.new(
            secret.encode(), str(payload).encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            logger.warning("Dograh webhook signature mismatch")
            # In production, raise HTTPException(401)
