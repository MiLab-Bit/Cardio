# byou/distillation/runner.py
"""Batch Distillation Runner — L2 structured signals → L3 distilled knowledge.

Reads: ObjectionPattern[], LearningSignal[], MemorySummary[], QAResult[]
(when available from Memory / Audit store).

Writes: ObjectionPlaybook, ConversionPattern, TalkingPointEffect → Memory (L3).

NEVER reads raw transcripts.  Idempotent by job_id.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from byou.distillation.models import (
    ConversionPattern,
    DistillationJob,
    DistillationJobStatus,
    DistillationJobType,
    DistilledKnowledge,
    ObjectionPlaybook,
    ObjectionPlaybookEntry,
    TalkingPointEffect,
)

logger = logging.getLogger(__name__)


class DistillationRunner:
    """Batch distillation engine.

    In v2, signal sources are injected (MemoryGateway, etc.).
    In v1 MVP, signals are passed directly for testing/minimal integration.

    Usage:
        runner = DistillationRunner()
        knowledge = await runner.run(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            objection_patterns=[...],
        )
        # Runner writes to Memory via on_complete callback
    """

    def __init__(self) -> None:
        self._on_complete: callable | None = None
        self._jobs: dict[str, DistillationJob] = {}

    def on_complete(self, callback: callable) -> None:
        """Register callback: async fn(DistilledKnowledge) -> None."""
        self._on_complete = callback

    # ── Main entry ────────────────────────────────────

    async def run(
        self,
        *,
        job_type: DistillationJobType = DistillationJobType.FULL,
        objection_patterns: list | None = None,
        learning_signals: list | None = None,
        memory_summaries: list | None = None,
        qa_results: list | None = None,
        filters: dict | None = None,
        dry_run: bool = False,
    ) -> DistilledKnowledge:
        """Run distillation and produce DistilledKnowledge.

        Signal lists come from external sources (Memory read, DB query).
        Runner does NOT own the data access — it only processes.
        """
        job = DistillationJob(
            job_type=job_type,
            filters=filters or {},
            dry_run=dry_run,
        )
        self._jobs[job.job_id] = job
        job.start()

        try:
            knowledge = DistilledKnowledge(
                job_id=job.job_id,
                job_type=job_type,
            )

            # ── Objection playbook distillation ──────
            if job_type in (DistillationJobType.OBJECTION_PLAYBOOK, DistillationJobType.FULL):
                if objection_patterns:
                    knowledge.playbooks.append(
                        self._distill_playbook(objection_patterns, job.job_id)
                    )
                    job.input_count += len(objection_patterns)

            # ── Conversion pattern distillation ──────
            if job_type in (DistillationJobType.CONVERSION_PATTERN, DistillationJobType.FULL):
                if memory_summaries:
                    knowledge.conversion_patterns.extend(
                        self._distill_conversion_patterns(memory_summaries, job.job_id)
                    )
                    job.input_count += len(memory_summaries)

            # ── Talking point effect distillation ────
            if job_type in (DistillationJobType.TALKING_POINT_EFFECT, DistillationJobType.FULL):
                if learning_signals:
                    knowledge.talking_point_effects.extend(
                        self._distill_talking_points(learning_signals)
                    )
                    job.input_count += len(learning_signals)

            job.output_count = (
                len(knowledge.playbooks)
                + len(knowledge.conversion_patterns)
                + len(knowledge.talking_point_effects)
            )
            job.complete()

            # Callback to write to Memory
            if self._on_complete and not dry_run and job.output_count > 0:
                try:
                    await self._on_complete(knowledge)
                except Exception as e:
                    logger.exception("Distillation on_complete callback failed")
                    job.fail(f"writeback failed: {e}")

            return knowledge

        except Exception as e:
            logger.exception("Distillation job %s failed", job.job_id)
            job.fail(str(e))
            raise

    # ── Objection playbook ────────────────────────────

    def _distill_playbook(
        self, patterns: list, job_id: str,
    ) -> ObjectionPlaybook:
        """ObjectionPattern[] → ObjectionPlaybook."""
        by_topic: dict[str, list] = defaultdict(list)
        for p in patterns:
            topic = getattr(p, "objection_topic", getattr(p, "topic", "unknown"))
            by_topic[topic].append(p)

        entries = []
        total = len(patterns)

        for topic, items in by_topic.items():
            overcome = sum(
                1 for p in items
                if getattr(p, "outcome", None) and str(getattr(p, "outcome")) == "overcome"
            )
            entries.append(ObjectionPlaybookEntry(
                objection_topic=topic,
                common_phrases=list(set(
                    getattr(p, "user_phrase", "")[:100] for p in items
                    if getattr(p, "user_phrase", "")
                ))[:10],
                recommended_responses=list(set(
                    getattr(p, "agent_response", "")[:100] for p in items
                    if getattr(p, "agent_response", "")
                ))[:10],
                overcome_rate=round(overcome / len(items), 2) if items else 0.0,
                sample_count=len(items),
                industries=list(set(
                    getattr(p, "industry", "") for p in items
                    if getattr(p, "industry", "")
                )),
                company_scales=list(set(
                    getattr(p, "company_scale", "") for p in items
                    if getattr(p, "company_scale", "")
                )),
            ))

        return ObjectionPlaybook(
            job_id=job_id,
            entries=entries,
            source_signal_count=total,
        )

    # ── Conversion patterns ──────────────────────────

    def _distill_conversion_patterns(
        self, summaries: list, job_id: str,
    ) -> list[ConversionPattern]:
        """MemorySummary[] → ConversionPattern[]."""
        by_industry: dict[str, list] = defaultdict(list)
        for s in summaries:
            ind = getattr(s, "industry", "") or ""
            by_industry[ind].append(s)

        patterns = []
        for industry, items in by_industry.items():
            if len(items) < 2:
                continue

            # Aggregate positive signals
            all_signals: list[str] = []
            for s in items:
                sigs = getattr(s, "best_talking_points", []) or []
                all_signals.extend(sigs)

            signal_counts: dict[str, int] = defaultdict(int)
            for sig in all_signals:
                signal_counts[sig] += 1

            key_signals = [
                sig for sig, count in sorted(
                    signal_counts.items(), key=lambda x: -x[1]
                )[:5]
                if count >= 2
            ]

            patterns.append(ConversionPattern(
                job_id=job_id,
                industry=industry or "unknown",
                key_signals=key_signals,
                sample_count=len(items),
            ))

        return patterns

    # ── Talking point effects ─────────────────────────

    def _distill_talking_points(
        self, signals: list,
    ) -> list[TalkingPointEffect]:
        """LearningSignal[] → TalkingPointEffect[]."""
        by_description: dict[str, list] = defaultdict(list)
        for sig in signals:
            desc = getattr(sig, "description", "") or ""
            sig_type = getattr(sig, "signal_type", None)
            if sig_type:
                type_val = sig_type.value if hasattr(sig_type, "value") else str(sig_type)
                by_description[desc].append(type_val)

        effects = []
        for desc, types in by_description.items():
            effective = types.count("talking_point_effective")
            unresolved = types.count("objection_unresolved")
            total = effective + unresolved

            effectiveness = round(effective / total, 2) if total > 0 else 0.5

            effects.append(TalkingPointEffect(
                talking_point=desc[:150],
                signal_type="effective" if effectiveness >= 0.6 else "ineffective",
                effectiveness_score=effectiveness,
                sample_count=total,
            ))

        return sorted(effects, key=lambda e: -e.effectiveness_score)


# ══════════════════════════════════════════════════════════
# DistillationJobTrigger — idempotent periodic trigger
# ══════════════════════════════════════════════════════════

class DistillationJobTrigger:
    """Schedules and manages periodic distillation runs.

    Idempotency: uses job_id = dist_{job_type}_{date}_{hash} to prevent
    duplicate runs on the same data set.

    v2: in-memory trigger.  v3: cron-based with persistent state.
    """

    def __init__(self) -> None:
        self._completed_job_ids: set[str] = set()
        self._runner = DistillationRunner()

    @property
    def runner(self) -> DistillationRunner:
        return self._runner

    def already_ran(self, idempotency_key: str) -> bool:
        return idempotency_key in self._completed_job_ids

    def mark_completed(self, job_id: str) -> None:
        self._completed_job_ids.add(job_id)

    async def trigger(
        self,
        *,
        job_type: DistillationJobType = DistillationJobType.FULL,
        idempotency_key: str = "",
        dry_run: bool = False,
        **signal_kwargs,
    ) -> DistilledKnowledge | None:
        """Trigger a distillation run if not already completed."""
        job_id = f"dist_{job_type.value}_{idempotency_key}"

        if self.already_ran(job_id):
            logger.info("Distillation job %s already completed, skip", job_id)
            return None

        knowledge = await self._runner.run(
            job_type=job_type,
            dry_run=dry_run,
            **signal_kwargs,
        )
        self.mark_completed(job_id)
        return knowledge
