# byou/channels/stubs.py
"""Phase 3 v2 stubs — interfaces that are wired but not fully implemented.

These are Protocol interfaces and minimal in-memory stubs for:
  - ReviewQueueGateway: human review queue integration (v2)
  - MetricsEmitter: call-level metric publishing (v2)
  - DistillationJobTrigger: periodic batch distillation trigger (v2)
  - ChannelRegistry: multi-channel adapter registry (v2)

v1 范围只做接口定义 + no-op stub，让调用方可以编译/测试。
v2 替换为真实实现。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from byou.models.channel_contract import (
    ChannelCapability,
    ChannelKind,
    QAResult,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# ReviewQueueGateway (v2)
# ══════════════════════════════════════════════════════════

class ReviewQueueGateway(Protocol):
    """Human review queue interface.

    v1: no-op stub.  v2: real queue backed by ReviewQueue (byou/intake/review/).
    """

    async def enqueue(self, item_type: str, item_id: str, payload: dict) -> str:
        """Enqueue a review item. Returns review job ID."""
        ...

    async def dequeue(self) -> dict | None:
        """Dequeue next pending item. Returns None if empty."""
        ...

    async def resolve(self, job_id: str, decision: str, notes: str = "") -> None:
        """Resolve a review item."""
        ...

    async def get_queue_stats(self) -> dict:
        """Return queue stats: pending, in_review, resolved."""
        ...


class StubReviewQueueGateway:
    """No-op stub.  v2: replace with real ReviewQueue."""

    async def enqueue(self, item_type: str, item_id: str, payload: dict) -> str:
        logger.debug("ReviewQueue stub: enqueue %s:%s", item_type, item_id)
        return f"stub_review_{item_id}"

    async def dequeue(self) -> dict | None:
        return None

    async def resolve(self, job_id: str, decision: str, notes: str = "") -> None:
        pass

    async def get_queue_stats(self) -> dict:
        return {"pending": 0, "in_review": 0, "resolved": 0}


# ══════════════════════════════════════════════════════════
# MetricsEmitter (v2)
# ══════════════════════════════════════════════════════════

class MetricsEmitter(Protocol):
    """Call-level metric publishing interface.

    v1: no-op stub.  v2: real emitter backed by byou.production.metrics.
    """

    async def emit_call_completed(
        self,
        session_id: str,
        lead_id: str,
        duration_seconds: int,
        business_outcome: str,
        quality_score: float,
        signal_count: int,
        labels: dict[str, str] | None = None,
    ) -> None: ...

    async def emit_review_required(
        self, session_id: str, reason: str, qa_score: float,
    ) -> None: ...

    async def emit_objection_detected(
        self, session_id: str, topic: str, outcome: str,
    ) -> None: ...


class StubMetricsEmitter:
    """No-op stub.  v2: replace with real Production metrics."""

    async def emit_call_completed(self, **kwargs) -> None:
        logger.debug("Metrics stub: call_completed session=%s", kwargs.get("session_id"))

    async def emit_review_required(self, **kwargs) -> None:
        logger.debug("Metrics stub: review_required session=%s", kwargs.get("session_id"))

    async def emit_objection_detected(self, **kwargs) -> None:
        pass


# ══════════════════════════════════════════════════════════
# DistillationJobTrigger (v2)
# ══════════════════════════════════════════════════════════

class DistillationJobTrigger(Protocol):
    """Periodic batch distillation trigger interface.

    v1: interface only.  v2: triggers distillation_job.py to process
    accumulated LearningSignals + ObjectionPatterns into Memory
    (ObjectionPlaybooks, ConversionPatterns, etc.).
    """

    async def schedule(self, interval_hours: int = 24) -> str:
        """Schedule periodic distillation. Returns job ID."""
        ...

    async def run_now(self) -> dict:
        """Force immediate distillation run."""
        ...

    async def last_run_status(self) -> dict | None:
        """Get last run status."""
        ...


class StubDistillationJobTrigger:
    """No-op stub.  v2: real cron-based trigger."""

    async def schedule(self, interval_hours: int = 24) -> str:
        return "stub_distill_job"

    async def run_now(self) -> dict:
        return {"status": "skipped", "reason": "stub"}

    async def last_run_status(self) -> dict | None:
        return None


# ══════════════════════════════════════════════════════════
# ChannelRegistry (v2)
# ══════════════════════════════════════════════════════════

class ChannelRegistry(Protocol):
    """Multi-channel adapter registry.

    v1: interface only.  v2: dynamic channel discovery + routing.
    """

    async def register(self, channel: ChannelKind, capability: ChannelCapability) -> None:
        ...

    async def list_channels(self) -> list[ChannelCapability]:
        ...

    async def get_channel(self, channel: ChannelKind) -> ChannelCapability | None:
        ...

    async def route_action(self, action_type: str, lead_id: str) -> ChannelKind | None:
        """Route an action to the best available channel."""
        ...


class StubChannelRegistry:
    """No-op stub.  v2: real channel registry."""

    async def register(self, channel: ChannelKind, capability: ChannelCapability) -> None:
        logger.debug("ChannelRegistry stub: register %s", channel)

    async def list_channels(self) -> list[ChannelCapability]:
        return []

    async def get_channel(self, channel: ChannelKind) -> ChannelCapability | None:
        return None

    async def route_action(self, action_type: str, lead_id: str) -> ChannelKind | None:
        return ChannelKind.VOICE
