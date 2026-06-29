"""Byou Evals — 评测与轨迹观测子系统.

目录结构:
    byou/production/evals/
    ├── __init__.py      ← 本文件
    ├── types.py         强类型 Pydantic 模型
    ├── datasets.py      JSONL 数据集加载/筛选
    ├── graders.py       5 类阶段评分器 + PipelineWorkflowGrader
    ├── replay.py         轨迹重放与 diff
    ├── baselines.py     Baseline 保存/加载/对比
    ├── reports.py       文本/JSON 报告生成
    ├── runner.py        完整评测运行引擎
    └── fixtures/        固定案例数据
        ├── golden_cases.jsonl
        ├── bad_cases.jsonl
        └── edge_cases.jsonl

使用方式:
    from byou.evals import (
        DatasetLoader, EvalRunner, BaselineManager,
        ResearcherGrader, SynthesizerGrader, StrategistGrader,
        CriticGrader, PipelineWorkflowGrader,
        EvalCase, EvalRun, RegressionReport,
        text_report, regression_text_report,
    )

    # 加载数据集
    loader = DatasetLoader()
    cases = loader.load(["golden_cases.jsonl"])

    # 运行评测 (dry-run mode, 无真实 Orchestrator)
    runner = EvalRunner()
    result = runner.run_sync(cases)

    # 打印报告
    print(text_report(result))

    # 保存 baseline
    bm = BaselineManager()
    bm.save(result, "baseline_v1")

    # 改 prompt 后再跑一次
    result2 = runner.run_sync(cases, prompt_version="v2")
    baseline = bm.load("baseline_v1")
    report = bm.compare(baseline, result2)
    print(regression_text_report(report))
"""

from .types import (
    # Enums
    EvalSeverity,
    StageName,
    GraderType,
    RunVerdict,
    # Data models
    EvalCase,
    EvalExpectation,
    StageScore,
    PipelineScore,
    EvalRun,
    TraceReplayDiff,
    RegressionReport,
    GraderThresholds,
    GraderConfig,
    DiffEntry,
)
from .datasets import DatasetLoader, load_golden_cases, load_bad_cases, load_edge_cases
from .graders import (
    ResearcherGrader,
    SynthesizerGrader,
    StrategistGrader,
    CriticGrader,
    PipelineWorkflowGrader,
)
from .replay import TraceReplayer
from .baselines import BaselineManager, get_baseline_manager
from .reports import text_report, regression_text_report, json_report, json_regression_report
from .runner import EvalRunner

__all__ = [
    # Enums
    "EvalSeverity",
    "StageName",
    "GraderType",
    "RunVerdict",
    # Models
    "EvalCase",
    "EvalExpectation",
    "StageScore",
    "PipelineScore",
    "EvalRun",
    "TraceReplayDiff",
    "RegressionReport",
    "GraderThresholds",
    "GraderConfig",
    "DiffEntry",
    # Data
    "DatasetLoader",
    "load_golden_cases",
    "load_bad_cases",
    "load_edge_cases",
    # Graders
    "ResearcherGrader",
    "SynthesizerGrader",
    "StrategistGrader",
    "CriticGrader",
    "PipelineWorkflowGrader",
    # Replay
    "TraceReplayer",
    # Baseline
    "BaselineManager",
    "get_baseline_manager",
    # Reports
    "text_report",
    "regression_text_report",
    "json_report",
    "json_regression_report",
    # Runner
    "EvalRunner",
]
