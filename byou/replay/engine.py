"""Replay Engine — minimal replay capability for Phase 3 v3.

Replay previously-run sessions from audit/evidence/seeds/distilled knowledge.
Supports:
  - per-step replay (ActionDecider, FollowUpPlanner, Distillation, Identity, Memory)
  - output divergence detection against original audit entries
  - review fix application before re-running
  - dry-run mode

No UI, no dashboard, no platform.  Just the engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from uuid import uuid4

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════

class ReplaySourceType(str, Enum):
    AUDIT_LOG = "audit_log"
    EVIDENCE = "evidence"
    SEEDS = "seeds"
    DISTILLED_KNOWLEDGE = "distilled_knowledge"


class ReplayStepType(str, Enum):
    ACTION_DECIDER = "action_decider"
    FOLLOW_UP_PLANNER = "follow_up_planner"
    DISTILLATION = "distillation"
    IDENTITY_RESOLUTION = "identity_resolution"
    MEMORY_UPDATE = "memory_update"


class ReplayStepStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DIVERGED = "diverged"


# ══════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════

class ReplaySource(BaseModel):
    """Source data loaded for replay."""
    source_type: ReplaySourceType
    session_id: str

    audit_entries: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    seeds: list[dict[str, Any]] = Field(default_factory=list)
    distilled: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def source_count(self) -> int:
        return len(self.audit_entries) + len(self.seeds) + len(self.distilled)


class ReplayStep(BaseModel):
    """Single replay step result."""
    step_type: ReplayStepType
    status: ReplayStepStatus = ReplayStepStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None

    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""

    # Divergence tracking
    divergence: bool = False
    original_output: dict[str, Any] = Field(default_factory=dict)
    divergence_details: list[str] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    """Request to replay one session.

    If steps is empty, replay all available.
    """
    session_id: str
    sources: list[ReplaySourceType] = Field(
        default_factory=lambda: [ReplaySourceType.AUDIT_LOG],
    )
    steps: list[ReplayStepType] = Field(default_factory=list)

    # Review fix to apply before replay
    review_fix_id: str = ""
    review_fix_action: str = ""

    # Flags
    compare_with_original: bool = True  # detect divergence
    regen_memory: bool = False           # regenerate memory entries
    dry_run: bool = False                # no side effects

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReplayResult(BaseModel):
    """Outcome of a replay run."""
    replay_id: str
    session_id: str
    source: ReplaySourceType

    steps: list[ReplayStep] = Field(default_factory=list)
    start_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    status: str = "completed"  # "completed" | "failed" | "partial"

    fix_applied: bool = False
    fix_result: dict[str, Any] = Field(default_factory=dict)

    def add_step(self, step: ReplayStep) -> None:
        self.steps.append(step)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def successful_steps(self) -> int:
        return sum(1 for s in self.steps if s.status in (
            ReplayStepStatus.SUCCESS, ReplayStepStatus.SKIPPED,
        ))

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == ReplayStepStatus.FAILED)

    @property
    def diverged_steps(self) -> int:
        return sum(1 for s in self.steps if s.divergence)

    @property
    def has_divergence(self) -> bool:
        return self.diverged_steps > 0

    @property
    def is_clean(self) -> bool:
        """No failures, no divergence, all steps ran."""
        return self.failed_steps == 0 and not self.has_divergence

    @property
    def is_regression(self) -> bool:
        return getattr(self, "_is_regression", False)

    def mark_regression(self, reason: str) -> None:
        object.__setattr__(self, "_is_regression", True)
        if not hasattr(self, "_regression_reasons"):
            object.__setattr__(self, "_regression_reasons", [])
        self._regression_reasons.append(reason)

    @property
    def regression_reasons(self) -> list[str]:
        return getattr(self, "_regression_reasons", [])


# ══════════════════════════════════════════════════════════
# Replay Engine
# ══════════════════════════════════════════════════════════

class ReplayEngine:
    """Minimal replay engine — load source, run steps, detect divergence.

    All dependencies injected.  Missing inject → step skipped.

    Usage:
        engine = ReplayEngine()
        engine.inject_action_decider(decider)
        engine.inject_audit_store(audit)
        source = await engine.load_source(request)
        result = await engine.replay(request, source)
    """

    def __init__(self):
        self._action_decider = None
        self._follow_up_planner = None
        self._distillation_runner = None
        self._identity_gateway = None
        self._review_gateway = None
        self._audit_store = None
        self._memory_gateway = None

    # ── Inject ──────────────────────────────────────────

    def inject_action_decider(self, decider) -> None:
        self._action_decider = decider

    def inject_follow_up_planner(self, planner) -> None:
        self._follow_up_planner = planner

    def inject_distillation_runner(self, runner) -> None:
        self._distillation_runner = runner

    def inject_identity_gateway(self, gateway) -> None:
        self._identity_gateway = gateway

    def inject_review_gateway(self, gateway) -> None:
        self._review_gateway = gateway

    def inject_audit_store(self, store) -> None:
        self._audit_store = store

    def inject_memory_gateway(self, gateway) -> None:
        self._memory_gateway = gateway

    # ── Load source ────────────────────────────────────

    async def load_source(self, request: ReplayRequest) -> ReplaySource:
        """Load replay source data from available stores."""
        source = ReplaySource(
            source_type=request.sources[0] if request.sources else ReplaySourceType.AUDIT_LOG,
            session_id=request.session_id,
        )

        for st in request.sources:
            if st == ReplaySourceType.AUDIT_LOG and self._audit_store:
                if hasattr(self._audit_store, "query_by_session"):
                    entries = await self._audit_store.query_by_session(request.session_id)
                    source.audit_entries = entries

            elif st == ReplaySourceType.SEEDS and self._memory_gateway:
                if hasattr(self._memory_gateway, "query_by_session"):
                    seeds = await self._memory_gateway.query_by_session(request.session_id)
                    source.seeds = seeds

            elif st == ReplaySourceType.DISTILLED_KNOWLEDGE and self._memory_gateway:
                if hasattr(self._memory_gateway, "get_distilled_for"):
                    distilled = await self._memory_gateway.get_distilled_for(request.session_id)
                    source.distilled = distilled

        return source

    # ── Apply review fix ───────────────────────────────

    async def _apply_fix(self, request: ReplayRequest, result: ReplayResult) -> None:
        """Apply a review fix before replaying."""
        if not request.review_fix_id or not self._review_gateway:
            return

        review_item = None
        if hasattr(self._review_gateway, "get"):
            review_item = self._review_gateway.get(request.review_fix_id)
        elif hasattr(self._review_gateway, "resolve"):
            review_item = await self._review_gateway.resolve(request.review_fix_id)

        if review_item:
            result.fix_applied = True
            result.fix_result = {
                "item_id": request.review_fix_id,
                "status": getattr(review_item, "status", "resolved"),
            }

    # ── Replay ──────────────────────────────────────────

    async def replay(
        self, request: ReplayRequest, source: ReplaySource,
    ) -> ReplayResult:
        """Execute replay steps."""
        result = ReplayResult(
            replay_id=f"rp_{uuid4().hex[:8]}",
            session_id=request.session_id,
            source=source.source_type,
        )

        # Apply review fix if requested
        await self._apply_fix(request, result)

        # Determine steps to run
        steps_to_run = request.steps or list(ReplayStepType)
        available = self._available_steps(source, steps_to_run)

        for step_type in available:
            step = await self._run_step(step_type, request, source)
            result.add_step(step)

            if step.divergence:
                request.compare_with_original and result.mark_regression(
                    f"{step_type.value}: output diverged from original"
                )

        result.completed_at = datetime.now(timezone.utc)
        return result

    def _available_steps(
        self, source: ReplaySource, requested: list[ReplayStepType],
    ) -> list[ReplayStepType]:
        """Filter requested steps to those with inject AND data."""
        available: list[ReplayStepType] = []

        for step in requested:
            has_inject = self._has_inject_for(step)
            has_data = self._has_data_for(step, source)

            if has_inject and has_data:
                available.append(step)
            else:
                logger.debug(
                    "Step %s filtered: inject=%s data=%s",
                    step.value, has_inject, has_data,
                )

        return available

    def _has_inject_for(self, step: ReplayStepType) -> bool:
        mapping = {
            ReplayStepType.ACTION_DECIDER: self._action_decider,
            ReplayStepType.FOLLOW_UP_PLANNER: self._follow_up_planner,
            ReplayStepType.DISTILLATION: self._distillation_runner,
            ReplayStepType.IDENTITY_RESOLUTION: self._identity_gateway,
            ReplayStepType.MEMORY_UPDATE: self._memory_gateway,
        }
        return bool(mapping.get(step))

    def _has_data_for(self, step: ReplayStepType, source: ReplaySource) -> bool:
        """Check if source has data for this step."""
        if step in (ReplayStepType.ACTION_DECIDER, ReplayStepType.FOLLOW_UP_PLANNER):
            return len(source.audit_entries) > 0 or len(source.seeds) > 0
        elif step == ReplayStepType.DISTILLATION:
            return len(source.seeds) > 0 or len(source.distilled) > 0
        elif step == ReplayStepType.IDENTITY_RESOLUTION:
            return len(source.audit_entries) > 0 or len(source.seeds) > 0
        elif step == ReplayStepType.MEMORY_UPDATE:
            return len(source.seeds) > 0 or len(source.audit_entries) > 0
        return len(source.audit_entries) > 0

    async def _run_step(
        self, step_type: ReplayStepType, request: ReplayRequest, source: ReplaySource,
    ) -> ReplayStep:
        """Run one replay step."""
        step = ReplayStep(step_type=step_type)
        step.started_at = datetime.now(timezone.utc)

        try:
            if step_type == ReplayStepType.ACTION_DECIDER:
                step = await self._replay_action_decider(step, source, request)
            elif step_type == ReplayStepType.FOLLOW_UP_PLANNER:
                step = await self._replay_follow_up_planner(step, source, request)
            elif step_type == ReplayStepType.DISTILLATION:
                step = await self._replay_distillation(step, source, request)
            elif step_type == ReplayStepType.IDENTITY_RESOLUTION:
                step = await self._replay_identity(step, source, request)
            elif step_type == ReplayStepType.MEMORY_UPDATE:
                step = await self._replay_memory(step, source, request)

        except Exception as e:
            step.status = ReplayStepStatus.FAILED
            step.error = str(e)
            logger.exception("Replay step %s failed: %s", step_type.value, e)

        step.completed_at = datetime.now(timezone.utc)
        return step

    # ── Step implementations ────────────────────────────

    async def _replay_action_decider(
        self, step: ReplayStep, source: ReplaySource, request: ReplayRequest,
    ) -> ReplayStep:
        audit_data = self._extract_input_for("action_decider", source)
        step.input_summary = {"audit_entries": len(source.audit_entries)}

        if audit_data and self._action_decider:
            output = await self._action_decider.decide(audit_data)
            step.output_summary = output
            step.status = ReplayStepStatus.SUCCESS

            # Compare with original
            if request.compare_with_original:
                step = self._compare_divergence(step, "action_decider", output, source.audit_entries)
        else:
            step.status = ReplayStepStatus.SKIPPED

        return step

    async def _replay_follow_up_planner(
        self, step: ReplayStep, source: ReplaySource, request: ReplayRequest,
    ) -> ReplayStep:
        audit_data = self._extract_input_for("follow_up_planner", source)
        step.input_summary = {"audit_entries": len(source.audit_entries)}

        if audit_data and self._follow_up_planner:
            output = await self._follow_up_planner.plan(audit_data)
            step.output_summary = output
            step.status = ReplayStepStatus.SUCCESS

            if request.compare_with_original:
                step = self._compare_divergence(step, "follow_up_planner", output, source.audit_entries)
        else:
            step.status = ReplayStepStatus.SKIPPED

        return step

    async def _replay_distillation(
        self, step: ReplayStep, source: ReplaySource, request: ReplayRequest,
    ) -> ReplayStep:
        if source.seeds and self._distillation_runner:
            step.input_summary = {"seed_count": len(source.seeds)}

            try:
                output = await self._distillation_runner.run(
                    seeds=source.seeds,
                    dry_run=request.dry_run,
                )
                step.output_summary = {"type": output.get("type", "unknown")}
                step.status = ReplayStepStatus.SUCCESS
            except Exception as e:
                step.status = ReplayStepStatus.FAILED
                step.error = str(e)
        elif source.distilled and self._distillation_runner:
            step.status = ReplayStepStatus.SKIPPED
            step.error = "Already distilled — no re-run"
        else:
            step.status = ReplayStepStatus.SKIPPED

        return step

    async def _replay_identity(
        self, step: ReplayStep, source: ReplaySource, request: ReplayRequest,
    ) -> ReplayStep:
        if self._identity_gateway and hasattr(self._identity_gateway, "snapshot"):
            snapshot = self._identity_gateway.snapshot()
            step.output_summary = snapshot if not hasattr(snapshot, "model_dump") \
                                  else snapshot.model_dump(mode="json")
            step.status = ReplayStepStatus.SUCCESS
        else:
            step.status = ReplayStepStatus.SKIPPED

        return step

    async def _replay_memory(
        self, step: ReplayStep, source: ReplaySource, request: ReplayRequest,
    ) -> ReplayStep:
        if not request.regen_memory:
            step.status = ReplayStepStatus.SKIPPED
            step.error = "regen_memory not requested"
            return step

        if source.seeds and self._memory_gateway and not request.dry_run:
            step.input_summary = {"seed_count": len(source.seeds)}

            for seed in source.seeds:
                if hasattr(self._memory_gateway, "ingest_signals"):
                    await self._memory_gateway.ingest_signals(seed)

            step.output_summary = {"ingested": len(source.seeds)}
            step.status = ReplayStepStatus.SUCCESS
        else:
            step.status = ReplayStepStatus.SKIPPED

        return step

    # ── Helpers ─────────────────────────────────────────

    def _extract_input_for(
        self, step_name: str, source: ReplaySource,
    ) -> dict[str, Any] | None:
        """Extract relevant input data from source for a step."""
        if source.audit_entries:
            # Build input from audit entries matching this event type
            matching = [e for e in source.audit_entries
                        if e.get("event_type", "").startswith(step_name)]
            if matching:
                return {"audit_entries": matching, "session_id": source.session_id}

            # Fall back to all entries
            return {"audit_entries": source.audit_entries[:5],
                    "session_id": source.session_id}

        if source.seeds:
            return {"seeds": source.seeds, "session_id": source.session_id}

        return None

    def _compare_divergence(
        self,
        step: ReplayStep,
        step_name: str,
        output: dict[str, Any],
        audit_entries: list[dict[str, Any]],
    ) -> ReplayStep:
        """Compare replay output with original audit entries."""
        # Find matching original output
        matching = [e for e in audit_entries
                    if e.get("event_type", "").startswith(step_name)]
        if not matching:
            return step

        original = matching[0].get("payload", {})
        if not original:
            return step

        # Simple key-based divergence (not deep diff)
        diverged = False
        details: list[str] = []

        for key in output:
            if key in original and output[key] != original[key]:
                diverged = True
                details.append(f"{key}: '{original[key]}' → '{output[key]}'")
            elif key not in original:
                details.append(f"+{key}: '{output[key]}' (not in original)")

        if diverged:
            step.divergence = True
            step.original_output = original
            step.divergence_details = details
            step.status = ReplayStepStatus.DIVERGED

        return step


# ══════════════════════════════════════════════════════════
# Replay factory — builder pattern
# ══════════════════════════════════════════════════════════

class ReplayFactory:
    """Builder for ReplayEngine with injected dependencies."""

    def __init__(self):
        self._action_decider = None
        self._follow_up_planner = None
        self._distillation_runner = None
        self._identity_gateway = None
        self._review_gateway = None
        self._audit_store = None
        self._memory_gateway = None

    def with_action_decider(self, decider) -> "ReplayFactory":
        self._action_decider = decider
        return self

    def with_follow_up_planner(self, planner) -> "ReplayFactory":
        self._follow_up_planner = planner
        return self

    def with_distillation_runner(self, runner) -> "ReplayFactory":
        self._distillation_runner = runner
        return self

    def with_identity_gateway(self, gateway) -> "ReplayFactory":
        self._identity_gateway = gateway
        return self

    def with_review_gateway(self, gateway) -> "ReplayFactory":
        self._review_gateway = gateway
        return self

    def with_audit_store(self, store) -> "ReplayFactory":
        self._audit_store = store
        return self

    def with_memory_gateway(self, gateway) -> "ReplayFactory":
        self._memory_gateway = gateway
        return self

    def build(self) -> ReplayEngine:
        engine = ReplayEngine()
        if self._action_decider:
            engine.inject_action_decider(self._action_decider)
        if self._follow_up_planner:
            engine.inject_follow_up_planner(self._follow_up_planner)
        if self._distillation_runner:
            engine.inject_distillation_runner(self._distillation_runner)
        if self._identity_gateway:
            engine.inject_identity_gateway(self._identity_gateway)
        if self._review_gateway:
            engine.inject_review_gateway(self._review_gateway)
        if self._audit_store:
            engine.inject_audit_store(self._audit_store)
        if self._memory_gateway:
            engine.inject_memory_gateway(self._memory_gateway)
        return engine
