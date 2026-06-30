"""Learning Loop — continuous learning and strategy optimisation.

Collects feedback from each pipeline execution, adjusts agent weights and
persists learning state to SQLite (with JSON migration support).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from byou.core.message_bus import MessageBus
from byou.config import get_settings
from byou.models.customer import PipelineContext
from byou.core.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS: dict[str, float] = {
    "extractor": 1.0,
    "researcher": 1.0,
    "synthesizer": 1.0,
    "strategist": 1.0,
    "critic": 1.0,
}


class ExecutionTrace:
    """Single pipeline execution trace."""

    def __init__(self, pipeline_id: str, started_at: datetime, completed_at: datetime | None = None):
        self.pipeline_id = pipeline_id
        self.started_at = started_at
        self.completed_at = completed_at
        self.stages: dict[str, dict] = {}
        self.metrics: dict[str, float] = {}
        self.feedback: dict | None = None

    def add_stage(self, name: str, data: dict) -> None:
        self.stages[name] = {"timestamp": datetime.now().isoformat(), "data": data}

    def set_feedback(self, feedback: dict) -> None:
        self.feedback = feedback
        self.metrics.update(feedback.get("metrics", {}))


class LearningLoop:
    """Continual learning engine.

    Records execution traces, computes performance metrics and adjusts agent
    weights to improve future pipeline runs.
    Persistence backed by SQLite (see `sqlite_store.py`).
    """

    def __init__(
        self,
        message_bus: MessageBus | None = None,
        data_dir: str | None = None,
    ):
        self.message_bus = message_bus
        self._settings = get_settings()
        self.data_dir = Path(data_dir or self._settings.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # SQLite store
        db_path = self.data_dir / "learning.db"
        self._store = SQLiteStore(db_path)

        # In-memory caches (synced from DB on load)
        self.strategy_weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
        self.performance_history: list[dict] = []

        # Migrate legacy JSON if present
        legacy_json = self.data_dir / "learning_state.json"
        if legacy_json.exists():
            try:
                n = self._store.migrate_from_json(legacy_json)
                logger.info("Migrated %d records from legacy JSON", n)
                # Rename legacy file to avoid re-migration
                legacy_json.rename(legacy_json.with_suffix(".json.bak"))
            except Exception as e:
                logger.warning("JSON migration failed: %s", e)

        self._load_state()

    # ── Recording ───────────────────────────────────────────────

    def record_execution(self, ctx: PipelineContext) -> ExecutionTrace:
        """Record a completed pipeline execution trace."""
        trace = ExecutionTrace(
            pipeline_id=ctx.id or str(datetime.now().timestamp()),
            started_at=ctx.started_at,
            completed_at=ctx.completed_at,
        )

        if ctx.trust_score is not None:
            trace.metrics["trust_score"] = ctx.trust_score
        if ctx.intent_score is not None:
            trace.metrics["intent_score"] = ctx.intent_score
        if ctx.quality_passed is not None:
            trace.metrics["quality_passed"] = 1.0 if ctx.quality_passed else 0.0

        # Record stage data
        for stage_name in ["extraction", "research", "synthesis", "strategy", "critique"]:
            result_key = f"{stage_name}_result"
            if hasattr(ctx, result_key) and getattr(ctx, result_key):
                trace.add_stage(stage_name, {"result": getattr(ctx, result_key)})

        self._update_performance(trace)

        # Persist to SQLite
        try:
            self._store.save_trace(trace)
            self._store.save_weights(self.strategy_weights)
        except Exception as e:
            logger.warning("SQLite persist failed: %s", e)

        logger.info(
            "Trace recorded: %s (trust=%.2f intent=%.2f)",
            trace.pipeline_id,
            trace.metrics.get("trust_score", 0.0),
            trace.metrics.get("intent_score", 0.0),
        )
        return trace

    # ── Metrics ─────────────────────────────────────────────────

    def get_insights(self) -> dict:
        """Return learning insights.

        Queries SQLite for recent performance data.
        """
        try:
            recent = self._store.load_recent_traces(limit=20)
        except Exception:
            recent = self.performance_history[-20:] if self.performance_history else []

        if not recent:
            return {"status": "no_data", "message": "Not enough execution data yet"}

        n = len(recent)
        avg_trust = sum(r.get("metrics", {}).get("trust_score", 0) for r in recent) / n
        avg_intent = sum(r.get("metrics", {}).get("intent_score", 0) for r in recent) / n
        pass_rate = sum(r.get("metrics", {}).get("quality_passed", 0) for r in recent) / n

        # Save snapshot to SQLite
        try:
            self._store.save_snapshot(avg_trust, avg_intent, pass_rate, n, {
                "avg_trust": avg_trust,
                "avg_intent": avg_intent,
                "pass_rate": pass_rate,
            })
        except Exception:
            pass

        return {
            "status": "ok",
            "total_executions": len(self.performance_history),
            "recent_avg_trust_score": round(avg_trust, 3),
            "recent_avg_intent_score": round(avg_intent, 3),
            "recent_quality_pass_rate": round(pass_rate, 3),
            "strategy_weights": dict(self.strategy_weights),
            "trend": "improving" if pass_rate > 0.7 else "needs_attention",
        }

    # ── Persistence (legacy compatibility) ──────────────────────

    def persist(self) -> None:
        """Persist learning state (SQLite-backed; this method kept for compatibility)."""
        try:
            self._store.save_weights(self.strategy_weights)
            logger.info("Learning state persisted to SQLite")
        except Exception as e:
            logger.warning("Persist failed: %s", e)

    # ── Internal ────────────────────────────────────────────────

    def _update_performance(self, trace: ExecutionTrace) -> None:
        self.performance_history.append({
            "timestamp": datetime.now().isoformat(),
            "metrics": trace.metrics,
            "stages": list(trace.stages.keys()),
        })
        # Sliding window
        max_hist = self._settings.learning_max_history
        if len(self.performance_history) > max_hist:
            self.performance_history = self.performance_history[-max_hist:]
        self._adjust_weights(trace)

    def _adjust_weights(self, trace: ExecutionTrace) -> None:
        step = self._settings.learning_weight_step
        quality = trace.metrics.get("quality_passed", 1.0)
        trust = trace.metrics.get("trust_score", 0.7)

        # Low quality → increase critic weight
        if quality < 0.5:
            self.strategy_weights["critic"] = min(2.0, self.strategy_weights["critic"] + step)
            logger.debug("Critic weight → %.2f", self.strategy_weights["critic"])
        # Low trust → increase researcher weight
        if trust < 0.5:
            self.strategy_weights["researcher"] = min(2.0, self.strategy_weights["researcher"] + step)
            logger.debug("Researcher weight → %.2f", self.strategy_weights["researcher"])

    def _load_state(self) -> None:
        try:
            self.strategy_weights = self._store.load_weights()
            self.performance_history = self._store.load_recent_traces(limit=100)
            logger.info("Loaded learning state from SQLite: %d trace records", len(self.performance_history))
        except Exception as e:
            logger.warning("Failed to load from SQLite: %s — using defaults", e)
            self.strategy_weights = dict(DEFAULT_WEIGHTS)
            self.performance_history = []
