# byou/channels/voice/webhooks.py
"""HTTP webhook handler — entrypoint for provider callbacks.

This is intentionally minimal. Production deployment would wire this
to FastAPI/Starlette route or a serverless function handler.
"""

from __future__ import annotations

import logging
from typing import Protocol

from byou.channels.voice.models import ChannelEvent
from byou.channels.voice.ports import InboundChannelEventPort

logger = logging.getLogger(__name__)


class WebhookHandler(Protocol):
    """Protocol for processing incoming ChannelEvents.

    In production, this connects to the VoiceCallCoordinator.
    """

    async def __call__(self, event: ChannelEvent) -> None: ...


async def process_dograh_webhook(
    raw_payload: dict,
    headers: dict,
    bridge: InboundChannelEventPort,
    handler: WebhookHandler | None = None,
) -> ChannelEvent:
    """Standard webhook processing pipeline.

    1. Bridge translates provider payload → ChannelEvent
    2. Handler processes the event (→ VoiceCallCoordinator)
    Returns the translated event for logging/auditing.
    """
    event = await bridge.handle_webhook(raw_payload, headers)

    if handler:
        try:
            await handler(event)
        except Exception:
            logger.exception("Webhook handler failed for event %s", event.event_type)

    return event
