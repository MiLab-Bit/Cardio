"""
Learning Loop 测试
"""

import pytest
import json
from pathlib import Path
from datetime import datetime

from byou.core.learning_loop import LearningLoop, ExecutionTrace
from byou.models.customer import PipelineContext, CustomerProfile


class TestLearningLoop:
    """Learning Loop 测试套件"""

    def test_initialization(self, tmp_path):
        """测试初始化"""
        loop = LearningLoop(data_dir=str(tmp_path / "data"))
        assert loop.strategy_weights["extractor"] == 1.0
        assert loop.strategy_weights["critic"] == 1.0
        assert len(loop.performance_history) == 0

    def test_record_execution(self):
        """测试执行记录"""
        loop = LearningLoop()
        ctx = PipelineContext(
            trust_score=0.8,
            intent_score=0.7,
            quality_passed=True,
        )
        trace = loop.record_execution(ctx)
        assert trace is not None
        assert trace.metrics["trust_score"] == 0.8
        assert trace.metrics["intent_score"] == 0.7
        assert trace.metrics["quality_passed"] == 1.0
        assert len(loop.performance_history) == 1

    def test_record_multiple_executions(self):
        """测试多次执行记录"""
        loop = LearningLoop()

        for i in range(5):
            ctx = PipelineContext(
                trust_score=0.5 + i * 0.1,
                intent_score=0.6,
                quality_passed=i % 2 == 0,
            )
            loop.record_execution(ctx)

        assert len(loop.performance_history) == 5

    def test_get_insights_no_data(self):
        """测试无数据时的洞察"""
        loop = LearningLoop()
        insights = loop.get_insights()
        assert insights["status"] == "no_data"

    def test_get_insights_with_data(self):
        """测试有数据时的洞察"""
        loop = LearningLoop()

        ctx = PipelineContext(
            trust_score=0.9,
            intent_score=0.8,
            quality_passed=True,
        )
        loop.record_execution(ctx)

        insights = loop.get_insights()
        assert insights["status"] == "ok"
        assert insights["total_executions"] == 1
        assert insights["recent_avg_trust_score"] == 0.9
        assert insights["recent_quality_pass_rate"] == 1.0

    def test_persist_and_load(self, tmp_path):
        """测试持久化和加载"""
        loop = LearningLoop(data_dir=str(tmp_path))

        ctx = PipelineContext(
            trust_score=0.85,
            intent_score=0.75,
        )
        loop.record_execution(ctx)
        loop.persist()

        # 验证文件存在
        state_file = Path(tmp_path) / "learning_state.json"
        assert state_file.exists()

        # 重新加载
        loop2 = LearningLoop(data_dir=str(tmp_path))
        assert len(loop2.performance_history) == 1
        assert loop2.strategy_weights == loop.strategy_weights

    def test_weight_adjustment(self):
        """测试权重调整"""
        loop = LearningLoop()

        # 低质量通过 → Critic 权重应上调
        ctx = PipelineContext(quality_passed=False)
        initial_critic_weight = loop.strategy_weights["critic"]
        loop.record_execution(ctx)
        assert loop.strategy_weights["critic"] > initial_critic_weight

    def test_sliding_window(self):
        """测试滑动窗口"""
        loop = LearningLoop()

        for i in range(150):
            ctx = PipelineContext(trust_score=0.5)
            loop.record_execution(ctx)

        # 应只保留最近 100 条
        assert len(loop.performance_history) == 100
