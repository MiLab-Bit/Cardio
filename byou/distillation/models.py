# byou/distillation/models.py
"""Batch Distillation — job & output models.

Reads L2 structured signals → produces L3 distilled knowledge.
NEVER reads raw transcripts (ensured by design — only consumes
ObjectionPattern, LearningSignal, MemorySummary, QAResult).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class DistillationJobType(str, Enum):
    OBJECTION_PLAYBOOK = "objection_playbook"     # ObjectionPattern[] → ObjectionPlaybook
    CONVERSION_PATTERN = "conversion_pattern"    # QualificationSignal[] → ConversionPattern
    TALKING_POINT_EFFECT = "talking_point_effect"# LearningSignal[] → TalkingPointEffect
    STRATEGY_TEMPLATE = "strategy_template"      # PostCallReport[] → StrategyTemplate
    FULL = "full"                                # all of the above


class DistillationJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DistillationJob(BaseModel):
    """A single batch distillation run."""
    job_id: str = Field(default_factory=lambda: f"dist_{uuid4().hex[:8]}")
    job_type: DistillationJobType
    status: DistillationJobStatus = DistillationJobStatus.PENDING
    input_count: int = 0                     # number of signals consumed
    output_count: int = 0                    # number of distilled artifacts
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="e.g. {min_confidence: 0.6, industry: ['fintech'], last_n_days: 30}"
    )
    error: str = ""
    dry_run: bool = False                    # preview mode — no writeback

    def start(self) -> None:
        self.status = DistillationJobStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)

    def complete(self) -> None:
        self.status = DistillationJobStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)

    def fail(self, error: str) -> None:
        self.status = DistillationJobStatus.FAILED
        self.error = error
        self.completed_at = datetime.now(timezone.utc)


class ObjectionPlaybookEntry(BaseModel):
    """One objection → handling strategy entry in a playbook."""
    objection_topic: str                     # "价格", "竞品", etc.
    common_phrases: list[str] = Field(default_factory=list)
    recommended_responses: list[str] = Field(default_factory=list)
    overcome_rate: float = 0.0              # fraction of times successfully handled
    sample_count: int = 0
    industries: list[str] = Field(default_factory=list)
    company_scales: list[str] = Field(default_factory=list)


class ObjectionPlaybook(BaseModel):
    """Distilled objection handling playbook."""
    playbook_id: str = Field(default_factory=lambda: f"pb_{uuid4().hex[:8]}")
    version: int = 1
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    job_id: str = ""
    entries: list[ObjectionPlaybookEntry] = Field(default_factory=list)
    source_signal_count: int = 0


class ConversionPattern(BaseModel):
    """Distilled conversion pattern from clustered qualification signals."""
    pattern_id: str = Field(default_factory=lambda: f"cp_{uuid4().hex[:8]}")
    industry: str = ""
    lead_role: str = ""
    company_scale: str = ""
    key_signals: list[str] = Field(default_factory=list)  # signals that correlate with conversion
    signal_sequence: list[str] = Field(default_factory=list)  # typical order
    conversion_rate: float = 0.0
    sample_count: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    job_id: str = ""


class TalkingPointEffect(BaseModel):
    """Distilled talking point effectiveness data."""
    talking_point: str
    signal_type: str                        # "effective", "ineffective", "neutral"
    effectiveness_score: float = 0.0        # 0-1, higher = more effective
    sample_count: int = 0
    best_used_at: str = ""                  # "opening", "discovery", "objection_handling", "closing"
    industries: list[str] = Field(default_factory=list)


class DistilledKnowledge(BaseModel):
    """Aggregate output of a full distillation run."""
    job_id: str
    job_type: DistillationJobType
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    playbooks: list[ObjectionPlaybook] = Field(default_factory=list)
    conversion_patterns: list[ConversionPattern] = Field(default_factory=list)
    talking_point_effects: list[TalkingPointEffect] = Field(default_factory=list)
