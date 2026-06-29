"""Byou Evals — 集成测试。

验证:
1. 类型序列化/反序列化
2. 数据集加载三种 JSONL
3. 过滤器 (tag/severity/priority/skip_ci)
4. 5 类 Grader 评分
5. TraceReplay diff
6. BaselineManager 保存/加载/对比
7. EvalRunner 全链路
8. 报告生成 (文本/JSON)
9. 回归报告
10. CI gate 判定
"""

import sys
import os
sys.path.insert(0, r"Z:\Dev\Byou")

from byou.evals.types import *
from byou.evals.datasets import DatasetLoader
from byou.evals.graders import (
    ResearcherGrader,
    SynthesizerGrader,
    StrategistGrader,
    CriticGrader,
    PipelineWorkflowGrader,
)
from byou.evals.replay import TraceReplayer
from byou.evals.baselines import BaselineManager
from byou.evals.runner import EvalRunner
from byou.evals.reports import (
    text_report,
    regression_text_report,
    json_report,
    json_regression_report,
)

PASS, FAIL = 0, 0


def test_types_roundtrip():
    """EvalCase 序列化往返"""
    global PASS, FAIL
    case = EvalCase(
        case_id="test_001",
        title="测试案例",
        tags=["golden", "high_priority"],
        risk_flags=["data_missing"],
        priority=10,
        severity=EvalSeverity.CRITICAL,
    )
    js = case.model_dump_json()
    back = EvalCase.model_validate_json(js)
    assert back.case_id == "test_001"
    assert back.priority == 10
    assert back.severity == EvalSeverity.CRITICAL
    assert "golden" in back.tags
    assert "data_missing" in back.risk_flags
    PASS += 1; print("[PASS] types roundtrip")


def test_pipeline_score():
    """PipelineScore 聚合"""
    global PASS, FAIL
    ss = StageScore(stage=StageName.RESEARCHER, verdict=RunVerdict.PASS, score=0.9)
    ps = PipelineScore(run_id="r1", case_id="c1", stages={"researcher": ss}, overall_score=0.9)
    d = ps.model_dump()
    assert d["stages"]["researcher"]["score"] == 0.9
    assert len(ps.failed_stages) == 0
    PASS += 1; print("[PASS] pipeline score")


def test_thresholds():
    """GraderThresholds 判定"""
    global PASS, FAIL
    t = GraderThresholds(pass_=0.8, warn=0.6)
    assert t.classify(0.9) == RunVerdict.PASS
    assert t.classify(0.75) == RunVerdict.DEGRADED
    assert t.classify(0.3) == RunVerdict.FAIL
    PASS += 1; print("[PASS] thresholds")


def test_dataset_loader():
    """DatasetLoader 加载三种 JSONL"""
    global PASS, FAIL
    loader = DatasetLoader()
    cases = loader.load(["golden_cases.jsonl", "bad_cases.jsonl", "edge_cases.jsonl"])
    assert len(cases) == 10
    n_golden = sum(1 for c in cases if "golden" in c.tags)
    n_bad = sum(1 for c in cases if "bad" in c.tags)
    n_edge = sum(1 for c in cases if "edge" in c.tags)
    assert n_golden == 3
    assert n_bad == 4
    assert n_edge == 3
    PASS += 1; print("[PASS] dataset loader: 10 cases (3g/4b/3e)")


def test_filter_by_severity():
    """severity 过滤"""
    global PASS, FAIL
    loader = DatasetLoader()
    loader.load()
    critical = loader.filter(severity=EvalSeverity.CRITICAL)
    assert len(critical) == 2
    assert all(c.severity == EvalSeverity.CRITICAL for c in critical)
    PASS += 1; print(f"[PASS] filter severity: {len(critical)} critical")


def test_filter_by_tags():
    """tag 过滤"""
    global PASS, FAIL
    loader = DatasetLoader()
    loader.load()
    risk_cases = loader.filter(tags=["risk"])
    assert len(risk_cases) >= 1
    PASS += 1; print(f"[PASS] filter tags: {len(risk_cases)} risk cases")


def test_filter_by_priority():
    """priority 过滤"""
    global PASS, FAIL
    loader = DatasetLoader()
    loader.load()
    high = loader.filter(min_priority=9)
    assert len(high) == 3
    assert all(c.priority >= 9 for c in high)
    PASS += 1; print(f"[PASS] filter priority: {len(high)} high-priority")


def test_skip_ci():
    """skip_ci 过滤"""
    global PASS, FAIL
    loader = DatasetLoader()
    loader.load()
    all_count = len(list(loader._cases.values()))
    ci_count = len(loader.filter(skip_ci=True))
    # 有 skip_in_ci case 时 ci_count < all_count
    skipped = sum(1 for c in loader._cases.values() if c.skip_in_ci)
    assert ci_count <= all_count
    PASS += 1; print(f"[PASS] skip_ci: {all_count}→{ci_count} ({skipped} skipped)")


def test_researcher_grader():
    """ResearcherGrader 评分"""
    global PASS, FAIL
    g = ResearcherGrader()
    case = EvalCase(case_id="r1", expectation=EvalExpectation(
        required_fields=["company_info.name", "risk_score"],
        expected_capabilities=["company_profile"],
    ))
    ctx = {
        "output": {"company_info": {"name": "阿里"}, "risk_score": 0.1, "data_quality": "high"},
        "capabilities_used": ["company_profile"],
        "tool_calls_actual": ["tianyancha.baseinfo"],
    }
    ss = g.grade(case, ctx)
    assert ss.verdict == RunVerdict.PASS
    assert ss.score >= 0.7
    assert "source_coverage" in ss.dimensions
    PASS += 1; print(f"[PASS] researcher grader: {ss.score:.2f}")


def test_critic_grader_missed_risk():
    """CriticGrader 漏报检测"""
    global PASS, FAIL
    g = CriticGrader()
    case = EvalCase(case_id="c1", risk_flags=["court_cases", "abnormal"], expectation=EvalExpectation())
    ctx = {"output": {"findings": ["公司运营正常"], "risks": [], "suggestions": []}}
    ss = g.grade(case, ctx)
    # Should have low risk_identification because risk_flags not found
    assert ss.dimensions["risk_identification"] < 0.5
    assert "Missed risks" in str(ss.reasons)
    PASS += 1; print(f"[PASS] critic grader missed risks: {ss.dimensions['risk_identification']:.2f}")


def test_pipeline_workflow_grader():
    """PipelineWorkflowGrader 评分"""
    global PASS, FAIL
    g = PipelineWorkflowGrader()
    case = EvalCase(case_id="p1", expectation=EvalExpectation(min_stages=4))
    ctx = {"traces": [], "errors": []}
    stage_scores = {
        "researcher": StageScore(stage=StageName.RESEARCHER, verdict=RunVerdict.PASS, score=0.9),
        "synthesizer": StageScore(stage=StageName.SYNTHESIZER, verdict=RunVerdict.PASS, score=0.85),
        "strategist": StageScore(stage=StageName.STRATEGIST, verdict=RunVerdict.PASS, score=0.8),
        "critic": StageScore(stage=StageName.CRITIC, verdict=RunVerdict.PASS, score=0.85),
    }
    ss = g.grade(case, ctx, stage_scores)
    assert ss.score >= 0.8  # 4/4 stages
    PASS += 1; print(f"[PASS] pipeline workflow: {ss.score:.2f}")


def test_pipeline_workflow_too_few_stages():
    """PipelineWorkflowGrader 阶段不足"""
    global PASS, FAIL
    g = PipelineWorkflowGrader()
    case = EvalCase(case_id="p2", expectation=EvalExpectation(min_stages=4))
    ctx = {"traces": [], "errors": []}
    stage_scores = {
        "researcher": StageScore(stage=StageName.RESEARCHER, verdict=RunVerdict.PASS, score=0.9),
    }
    ss = g.grade(case, ctx, stage_scores)
    assert ss.score < 0.8  # 1/4 stages
    PASS += 1; print(f"[PASS] workflow too few stages: {ss.score:.2f}")


def test_trace_replayer():
    """TraceReplayer diff"""
    global PASS, FAIL
    rp = TraceReplayer()
    # baseline
    ps1 = PipelineScore(run_id="base_1", case_id="c1", overall_score=0.85)
    ps1.stages = {
        "researcher": StageScore(stage=StageName.RESEARCHER, verdict=RunVerdict.PASS, score=0.9, tool_calls_actual=["t1"]),
    }
    rp.capture("base_1", ps1, {"traces": [{"tool": "t1"}]})

    # candidate — worse
    ps2 = PipelineScore(run_id="cand_1", case_id="c1", overall_score=0.72, total_elapsed_ms=5000)
    ps2.stages = {
        "researcher": StageScore(stage=StageName.RESEARCHER, verdict=RunVerdict.DEGRADED, score=0.7, tool_calls_actual=["t2"]),
    }
    rp.capture("cand_1", ps2, {"traces": [{"tool": "t2"}]})

    diff = rp.diff("c1", "base_1", "cand_1")
    assert diff.is_regression
    assert diff.score_delta < 0
    assert len(diff.entries) >= 1
    PASS += 1; print(f"[PASS] trace replay: regression={diff.is_regression}, entries={len(diff.entries)}")


def test_baseline_manager():
    """BaselineManager 保存/加载/对比"""
    global PASS, FAIL
    bm = BaselineManager()
    run = EvalRun(
        run_id="test_bl",
        cases_total=10, cases_pass=8, cases_fail=2,
        overall_pass_rate=0.8, avg_score=0.85,
    )
    path = bm.save(run, "test_baseline_bl")
    assert path.exists()

    loaded = bm.load("test_baseline_bl")
    assert loaded is not None
    assert loaded.cases_total == 10

    # compare
    run2 = EvalRun(
        run_id="test_bl2",
        cases_total=10, cases_pass=6, cases_fail=4,
        overall_pass_rate=0.6, avg_score=0.72,
    )
    report = bm.compare(loaded, run2)
    assert report.is_regression
    assert report.score_delta < 0
    assert report.pass_rate_delta < 0

    # cleanup
    path.unlink()
    PASS += 1; print(f"[PASS] baseline manager: regression={report.is_regression}")


def test_eval_runner():
    """EvalRunner 全链路 (dry-run)"""
    global PASS, FAIL
    loader = DatasetLoader()
    loader.load(["golden_cases.jsonl"])
    runner = EvalRunner(dataset_loader=loader)
    cases = list(loader._cases.values())
    result = runner.run_sync(cases, model="test-model", prompt_version="test")
    assert result.cases_total == 3
    assert result.run_id
    assert len(result.pipeline_scores) == 3
    assert 0 <= result.avg_score <= 1
    PASS += 1; print(f"[PASS] eval runner: {result.cases_total} cases, avg={result.avg_score:.3f}")


def test_reports():
    """报告生成"""
    global PASS, FAIL
    run = EvalRun(
        run_id="test_rpt",
        cases_total=5, cases_pass=3, cases_fail=2,
        overall_pass_rate=0.6, avg_score=0.75,
    )
    # Text
    txt = text_report(run)
    assert "test_rpt" in txt
    assert "Pass:      3" in txt

    # JSON
    js = json_report(run)
    assert '"run_id": "test_rpt"' in js or '"run_id":"test_rpt"' in js

    PASS += 1; print("[PASS] reports")


def test_regression_report():
    """回归报告"""
    global PASS, FAIL
    base = EvalRun(run_id="base", cases_total=10, cases_pass=9, cases_fail=1, overall_pass_rate=0.9, avg_score=0.88)
    cand = EvalRun(run_id="cand", cases_total=10, cases_pass=7, cases_fail=3, overall_pass_rate=0.7, avg_score=0.74)

    bm = BaselineManager()
    report = bm.compare(base, cand)
    assert report.is_regression
    assert report.ci_should_block  # >5% drop
    assert "Score" in report.ci_summary or "Pass-rate" in report.ci_summary

    # Text report
    txt = regression_text_report(report)
    assert "Regression:" in txt
    assert "regression" in txt.lower()

    PASS += 1; print(f"[PASS] regression report: CI block={report.ci_should_block}")


def test_ci_gate_pass():
    """CI gate 不应阻断 — 改进情况"""
    global PASS, FAIL
    base = EvalRun(run_id="base", cases_total=10, cases_pass=8, overall_pass_rate=0.8, avg_score=0.8)
    cand = EvalRun(run_id="cand", cases_total=10, cases_pass=9, overall_pass_rate=0.9, avg_score=0.86)

    bm = BaselineManager()
    report = bm.compare(base, cand)
    assert not report.is_regression
    assert not report.ci_should_block
    PASS += 1; print(f"[PASS] CI gate: improvement not blocked")


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Byou Evals — Integration Tests")
    print("=" * 60)

    tests = [
        test_types_roundtrip,
        test_pipeline_score,
        test_thresholds,
        test_dataset_loader,
        test_filter_by_severity,
        test_filter_by_tags,
        test_filter_by_priority,
        test_skip_ci,
        test_researcher_grader,
        test_critic_grader_missed_risk,
        test_pipeline_workflow_grader,
        test_pipeline_workflow_too_few_stages,
        test_trace_replayer,
        test_baseline_manager,
        test_eval_runner,
        test_reports,
        test_regression_report,
        test_ci_gate_pass,
    ]

    for fn in tests:
        try:
            fn()
        except Exception as e:
            FAIL += 1
            import traceback
            traceback.print_exc()
            print(f"  [FAIL] {fn.__name__}: {e}")

    print()
    print(f"Results: {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
    if FAIL:
        print("XXX FAILURES XXX")
        sys.exit(1)
    else:
        print(">>> ALL EVALS TESTS PASSED <<<")
