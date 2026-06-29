# byou/channels/voice/application/policy.py
"""VoicePolicyEvaluator — pre-call / in-call / post-call compliance and safety checks.

Does NOT implement actual DNC lookup or content moderation.
Provides the interface and placeholder implementations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from byou.channels.voice.models import (
    CallSession,
    CallTurn,
    HandoffRequest,
    PreCallAudit,
    PreCallPackage,
)
from byou.channels.voice.ports import ApprovalGateway

logger = logging.getLogger(__name__)


class VoicePolicyEvaluator:
    """Evaluates voice call policies at each phase.

    Pre-call:  DNC check, time window, risk assessment
    In-call:   sensitive topic detection, compliance check
    Post-call: quality score, violation flagging
    """

    def __init__(
        self,
        *,
        approval: ApprovalGateway | None = None,
        blocked_hours_start: int = 21,
        blocked_hours_end: int = 8,
        max_call_duration_seconds: int = 1800,
    ) -> None:
        self._approval = approval
        self._blocked_start = blocked_hours_start
        self._blocked_end = blocked_hours_end
        self._max_duration = max_call_duration_seconds

    # ── Pre-call ────────────────────────────────────────

    def audit_pre_call(self, package: PreCallPackage) -> PreCallAudit:
        """Run pre-call policy checks. Returns PreCallAudit."""
        flags: list[str] = []

        if not self._is_calling_window():
            flags.append("outside_calling_hours")

        if package.lead.phone == "":
            flags.append("missing_phone")

        risk_level = "low"
        if flags:
            risk_level = "medium"

        # Check if lead has prior high-risk flags
        if package.risk_level == "high":
            risk_level = "high"

        return PreCallAudit(
            risk_level=risk_level,
            flags=flags,
            recommendations=(
                ["Schedule for business hours"] if "outside_calling_hours" in flags else []
            ),
        )

    async def check_dnc(self, phone: str) -> bool:
        """Placeholder: check Do-Not-Call list.

        Real implementation calls MCP Tool or external DNC API.
        """
        _ = phone
        return True  # allowed by default

    # ── In-call ─────────────────────────────────────────

    async def evaluate_turn(
        self, session: CallSession, turn: CallTurn
    ) -> dict:
        """Evaluate a single turn for compliance issues.

        Returns {"blocked": bool, "flags": list[str], "requires_approval": bool}
        """
        flags: list[str] = []
        blocked = False
        requires_approval = False

        # Check call duration
        if session.answered_at:
            elapsed = (datetime.now(timezone.utc) - session.answered_at).total_seconds()
            if elapsed > self._max_duration:
                flags.append("max_duration_exceeded")
                blocked = True

        return {
            "blocked": blocked,
            "flags": flags,
            "requires_approval": requires_approval,
        }

    async def evaluate_handoff(self, request: HandoffRequest) -> HandoffRequest:
        """Check if handoff is warranted."""
        # Default: approve explicit user requests
        if request.reason == "user_request":
            request.approved = True
            request.target_queue = request.target_queue or "sales"
        # Approval required for escalation
        elif request.reason == "escalation":
            if self._approval:
                decision = await self._approval.request_approval(
                    scope="action",
                    context={"handoff": request.model_dump()},
                    mode="demand",
                )
                request.approved = decision.get("approved", False)
                request.handoff_notes = decision.get("notes", "")
        return request

    # ── Post-call ───────────────────────────────────────

    def post_call_score(self, session: CallSession, turns: list[CallTurn]) -> dict:
        """Compute post-call quality score (placeholder)."""
        flags: list[str] = []
        score = 1.0

        if session.duration_seconds < 10:
            flags.append("too_short")
            score = 0.3
        elif session.duration_seconds > self._max_duration:
            flags.append("too_long")
            score = 0.5

        return {"score": score, "flags": flags}

    # ── Internal ────────────────────────────────────────

    def _is_calling_window(self) -> bool:
        now = datetime.now().hour
        if self._blocked_start > self._blocked_end:
            return not (self._blocked_start <= now or now < self._blocked_end)
        return self._blocked_end <= now < self._blocked_start
