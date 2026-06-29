"""Reports — 评测报告生成。

输出人类可读的文本报告或结构化 JSON。
"""

from __future__ import annotations

import json
from datetime import datetime

from .types import (
    EvalRun,
    RegressionReport,
    PipelineScore,
    RunVerdict,
)


def text_report(run: EvalRun) -> str:
    """Generate a human-readable text report for one eval run."""
    lines = [
        "=" * 60,
        f"  Byou Eval Report — {run.run_id}",
        f"  Model: {run.model or 'unknown'} | Prompt: {run.prompt_version or 'unknown'}",
        f"  Timestamp: {run.timestamp}",
        "=" * 60,
        "",
        f"  Cases: {run.cases_total} total",
        f"    Pass:      {run.cases_pass} ({run.cases_pass/max(1,run.cases_total)*100:.0f}%)",
        f"    Fail:      {run.cases_fail} ({run.cases_fail/max(1,run.cases_total)*100:.0f}%)",
        f"    Degraded:  {run.cases_degraded} ({run.cases_degraded/max(1,run.cases_total)*100:.0f}%)",
        "",
        f"  Avg Score: {run.avg_score:.3f}",
        f"  Pass Rate: {run.overall_pass_rate:.1%}",
        f"  Total Cost: ${run.total_cost:.4f}",
        "",
    ]

    # Per-case details
    for ps in run.pipeline_scores:
        if ps.verdict == RunVerdict.PASS:
            continue
        lines.append(f"  [{ps.verdict.value.upper()}] case={ps.case_id} score={ps.overall_score:.3f}")
        for stage_name, ss in ps.stages.items():
            if ss.verdict != RunVerdict.PASS:
                lines.append(f"         {stage_name}: {ss.score:.3f} — {', '.join(ss.reasons) or 'no details'}")
        lines.append("")

    return "\n".join(lines)


def regression_text_report(report: RegressionReport) -> str:
    """Generate a human-readable regression report."""
    lines = [
        "=" * 60,
        "  Byou Regression Report",
        f"  Baseline: {report.baseline_run.run_id if report.baseline_run else '?'}",
        f"  Candidate: {report.candidate_run.run_id if report.candidate_run else '?'}",
        f"  Compared at: {report.compared_at}",
        "=" * 60,
        "",
        f"  Score Delta:   {report.score_delta:+.4f}",
        f"  Pass-Rate Δ:   {report.pass_rate_delta:+.1%}",
        f"  Cost Δ:        ${report.cost_delta:+.6f}",
        "",
        f"  Regression:     {'⚠️  YES' if report.is_regression else '✅  No'}",
        f"  CI Block:       {'🚫 BLOCK' if report.ci_should_block else '✅ Allow'}",
        "",
    ]

    if report.improved_cases:
        lines.append(f"  Improved cases ({len(report.improved_cases)}):")
        for cid in report.improved_cases[:10]:
            lines.append(f"    + {cid}")
        lines.append("")

    if report.regression_cases:
        lines.append(f"  Regression cases ({len(report.regression_cases)}):")
        for cid in report.regression_cases[:10]:
            lines.append(f"    - {cid}")
        lines.append("")

    # Per-case diff details
    for diff in report.diffs:
        if not diff.entries:
            continue
        lines.append(f"  Case: {diff.case_id} (score Δ={diff.score_delta:+.3f}, regression={'YES' if diff.is_regression else 'no'})")
        for entry in diff.entries[:20]:
            arrow = "↓" if entry.is_regression else "→"
            lines.append(f"    {arrow} {entry.field}: {entry.baseline_value} → {entry.candidate_value} (Δ={entry.delta})")
        lines.append("")

    lines.append(f"  CI: {report.ci_summary}")
    return "\n".join(lines)


def json_report(run: EvalRun, pretty: bool = True) -> str:
    """Export EvalRun as JSON."""
    indent = 2 if pretty else None
    return run.model_dump_json(indent=indent)


def json_regression_report(report: RegressionReport, pretty: bool = True) -> str:
    """Export RegressionReport as JSON."""
    indent = 2 if pretty else None
    return report.model_dump_json(indent=indent, exclude_none=True)
