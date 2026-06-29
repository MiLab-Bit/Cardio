"""Baseline — 保存 / 加载 / 比较 EvalRun 基线。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .types import (
    EvalRun,
    RegressionReport,
    PipelineScore,
    RunVerdict,
    TraceReplayDiff,
)

logger = logging.getLogger(__name__)

DEFAULT_BASELINE_DIR = Path(__file__).resolve().parent / "baselines"


class BaselineManager:
    """Manage evaluation baselines: save, load, compare.

    Each baseline is a EvalRun saved as JSON under baselines/{name}.json.

    Naming convention: <date>_<model>_<prompt_version>.json
    e.g. ``20260627_qwen3-coder-plus_v2.json``
    """

    def __init__(self, store_dir: Path | None = None):
        self._dir = store_dir or DEFAULT_BASELINE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Save / Load ───────────────────────────────────

    def save(self, run: EvalRun, name: str | None = None) -> Path:
        """Persist EvalRun as baseline."""
        filename = name or self._default_name(run)
        if not filename.endswith(".json"):
            filename += ".json"
        path = self._dir / filename
        run.is_baseline = True
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Baseline saved: %s (%d cases, pass_rate=%.3f)", path, run.cases_total, run.overall_pass_rate)
        return path

    def load(self, name: str) -> EvalRun | None:
        """Load a saved baseline."""
        if not name.endswith(".json"):
            name += ".json"
        path = self._dir / name
        if not path.exists():
            logger.warning("Baseline not found: %s", path)
            return None
        return EvalRun.model_validate_json(path.read_text(encoding="utf-8"))

    def list_baselines(self) -> list[str]:
        """List available baseline names (without .json extension)."""
        return sorted(
            p.stem for p in self._dir.glob("*.json")
        )

    def latest(self) -> EvalRun | None:
        """Load the most recent baseline (by filename sort)."""
        names = self.list_baselines()
        if not names:
            return None
        return self.load(names[-1])

    # ── Compare ────────────────────────────────────────

    def compare(
        self,
        baseline: EvalRun,
        candidate: EvalRun,
        diffs: list[TraceReplayDiff] | None = None,
    ) -> RegressionReport:
        """Produce a RegressionReport comparing baseline vs candidate."""
        score_delta = candidate.avg_score - baseline.avg_score
        pass_rate_delta = candidate.overall_pass_rate - baseline.overall_pass_rate
        cost_delta = candidate.total_cost - baseline.total_cost

        is_regression = score_delta < -0.03 or pass_rate_delta < -0.05

        # per-case diffs
        diffs = diffs or []
        regression_cases = [d.case_id for d in diffs if d.is_regression]
        improved_cases = [d.case_id for d in diffs if d.score_delta > 0.03 and not d.is_regression]

        # CI gate: block if pass rate drops > 5% or score drops > 5%
        ci_should_block = (
            pass_rate_delta < -0.05
            or score_delta < -0.05
            or len(regression_cases) > max(1, baseline.cases_total * 0.1)
        )

        ci_parts: list[str] = []
        if score_delta < 0:
            ci_parts.append(f"Score {score_delta:+.3f}")
        if pass_rate_delta < 0:
            ci_parts.append(f"Pass-rate {pass_rate_delta:+.1%}")
        if cost_delta > 0:
            ci_parts.append(f"Cost +${cost_delta:.4f}")
        ci_summary = "; ".join(ci_parts) if ci_parts else "All metrics stable or improved"

        return RegressionReport(
            baseline_run=baseline,
            candidate_run=candidate,
            score_delta=round(score_delta, 4),
            pass_rate_delta=round(pass_rate_delta, 4),
            cost_delta=round(cost_delta, 6),
            diffs=diffs,
            is_regression=is_regression,
            regression_cases=regression_cases,
            improved_cases=improved_cases,
            ci_should_block=ci_should_block,
            ci_summary=ci_summary,
        )

    # ── Internal ───────────────────────────────────────

    @staticmethod
    def _default_name(run: EvalRun) -> str:
        ts = run.timestamp[:10] if run.timestamp else "unknown"
        model = run.model.replace("/", "_").replace(":", "_") if run.model else "default"
        prompt = run.prompt_version or "v1"
        return f"{ts}_{model}_{prompt}"


def get_baseline_manager() -> BaselineManager:
    return BaselineManager()
