"""Trace Replay — 重放一次 pipeline run，比较 baseline vs candidate 输出 diff。"""

from __future__ import annotations

import copy
import logging
from typing import Any

from .types import (
    DiffEntry,
    PipelineScore,
    TraceReplayDiff,
)

logger = logging.getLogger(__name__)


class TraceReplayer:
    """Replay an evaluation run and diff against baseline."""

    def __init__(self):
        self._snapshots: dict[str, dict[str, Any]] = {}

    # ── Snapshot ──────────────────────────────────────────

    def capture(self, run_id: str, pipeline_score: PipelineScore, context: dict[str, Any]) -> None:
        """Capture a snapshot for later comparison."""
        self._snapshots[run_id] = {
            "pipeline_score": pipeline_score,
            "context": copy.deepcopy(context),
        }
        logger.info("Snapshot captured: %s", run_id)

    # ── Diff ──────────────────────────────────────────────

    def diff(
        self,
        case_id: str,
        baseline_run_id: str,
        candidate_run_id: str,
    ) -> TraceReplayDiff:
        """Compare candidate against baseline, produce diff."""
        baseline = self._snapshots.get(baseline_run_id)
        candidate = self._snapshots.get(candidate_run_id)

        if not baseline:
            raise KeyError(f"Baseline snapshot not found: {baseline_run_id}")
        if not candidate:
            raise KeyError(f"Candidate snapshot not found: {candidate_run_id}")

        b_score: PipelineScore = baseline["pipeline_score"]
        c_score: PipelineScore = candidate["pipeline_score"]

        entries: list[DiffEntry] = []
        is_regression = False

        # 1. Overall score diff
        score_delta = c_score.overall_score - b_score.overall_score
        if score_delta < -0.03:
            is_regression = True
            entries.append(DiffEntry(
                field="overall_score",
                baseline_value=b_score.overall_score,
                candidate_value=c_score.overall_score,
                delta=round(score_delta, 4),
                is_regression=True,
            ))

        # 2. Per-stage score diffs
        all_stages = set(b_score.stages.keys()) | set(c_score.stages.keys())
        for stage in sorted(all_stages):
            bs = b_score.stages.get(stage)
            cs = c_score.stages.get(stage)
            if bs and cs:
                delta = cs.score - bs.score
                if abs(delta) > 0.02:
                    reg = delta < -0.03
                    is_regression = is_regression or reg
                    entries.append(DiffEntry(
                        field=f"stage.{stage}.score",
                        baseline_value=bs.score,
                        candidate_value=cs.score,
                        delta=round(delta, 4),
                        is_regression=reg,
                    ))
                # Tool call diffs
                b_tools = set(bs.tool_calls_actual)
                c_tools = set(cs.tool_calls_actual)
                added = c_tools - b_tools
                removed = b_tools - c_tools
                if added:
                    entries.append(DiffEntry(
                        field=f"stage.{stage}.tools_added",
                        baseline_value=[],
                        candidate_value=sorted(added),
                        is_regression=False,
                    ))
                if removed:
                    entries.append(DiffEntry(
                        field=f"stage.{stage}.tools_removed",
                        baseline_value=sorted(removed),
                        candidate_value=[],
                        is_regression=True,  # losing tools is usually bad
                    ))

            elif bs and not cs:
                entries.append(DiffEntry(
                    field=f"stage.{stage}",
                    baseline_value="present",
                    candidate_value="missing",
                    is_regression=True,
                ))
                is_regression = True
            elif cs and not bs:
                entries.append(DiffEntry(
                    field=f"stage.{stage}",
                    baseline_value="missing",
                    candidate_value="present",
                    is_regression=False,
                ))

        # 3. Cost & latency
        cost_delta = c_score.cost_estimate - b_score.cost_estimate
        lat_delta = c_score.total_elapsed_ms - b_score.total_elapsed_ms
        # Significant cost increase → warn
        if cost_delta > 0 and c_score.cost_estimate > b_score.cost_estimate * 1.3:
            entries.append(DiffEntry(
                field="cost_estimate",
                baseline_value=b_score.cost_estimate,
                candidate_value=c_score.cost_estimate,
                delta=round(cost_delta, 6),
                is_regression=True,
            ))

        return TraceReplayDiff(
            run_id=candidate_run_id,
            case_id=case_id,
            baseline_run_id=baseline_run_id,
            entries=entries,
            score_delta=round(score_delta, 4),
            cost_delta=round(cost_delta, 6),
            latency_delta_ms=lat_delta,
            is_regression=is_regression,
        )

    # ── Helpers ────────────────────────────────────────────

    def clear(self) -> None:
        self._snapshots.clear()
