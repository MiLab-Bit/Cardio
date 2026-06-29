"""
数据模型测试
"""

import pytest
from datetime import datetime

from byou.models import CustomerProfile, PipelineContext, ResearchResult
from byou.models import BDStrategy, TalkingPoint, FollowUpPlan, BDRisk


class TestCustomerProfile:
    """CustomerProfile 测试"""

    def test_default_profile(self):
        """测试默认客户画像"""
        profile = CustomerProfile()
        assert profile.name == ""
        assert profile.company == ""
        assert profile.confidence == 0.0

    def test_create_profile(self):
        """测试创建客户画像"""
        profile = CustomerProfile(
            name="张三",
            company="华为技术有限公司",
            title="技术总监",
            phone="13800138000",
            email="zhangsan@huawei.com",
            confidence=0.9,
        )
        assert profile.name == "张三"
        assert profile.company == "华为技术有限公司"
        assert profile.confidence == 0.9

    def test_extra_fields(self):
        """测试额外字段"""
        profile = CustomerProfile(
            name="李四",
            custom_field="自定义值",
            another_field=42,
        )
        assert profile.custom_field == "自定义值"
        assert profile.another_field == 42

    def test_profile_serialization(self):
        """测试序列化"""
        profile = CustomerProfile(name="王五", company="腾讯")
        data = profile.model_dump()
        assert data["name"] == "王五"
        assert data["company"] == "腾讯"


class TestPipelineContext:
    """PipelineContext 测试"""

    def test_default_context(self):
        """测试默认上下文"""
        ctx = PipelineContext()
        assert ctx.profile is None
        assert ctx.started_at is not None

    def test_get_summary(self):
        """测试摘要"""
        ctx = PipelineContext(
            profile=CustomerProfile(name="赵六", company="阿里"),
            customer_level="A",
            intent_score=0.85,
            trust_score=0.9,
        )
        summary = ctx.get_summary()
        assert summary["name"] == "赵六"
        assert summary["company"] == "阿里"
        assert summary["customer_level"] == "A"

    def test_errors_accumulation(self):
        """测试错误累积"""
        ctx = PipelineContext()
        ctx.errors.append("错误1")
        ctx.errors.append("错误2")
        assert len(ctx.errors) == 2


class TestBDStrategy:
    """BDStrategy 测试"""

    def test_default_strategy(self):
        """测试默认策略"""
        strategy = BDStrategy()
        assert strategy.confidence_level == 0.7
        assert strategy.version == "1.0"

    def test_create_strategy(self):
        """测试创建策略"""
        strategy = BDStrategy(
            customer_analysis="客户有数字化转型需求",
            pain_points=["系统老旧", "运维成本高"],
            opportunities=["SaaS 订阅", "定制开发"],
            talking_points=[
                TalkingPoint(
                    angle="降本增效",
                    script="您目前的运维成本是...",
                    key_message="我们的方案可降低30%运维成本",
                ),
            ],
            follow_up_plan=FollowUpPlan(
                timing="周二上午",
                channel="phone",
                priority="high",
            ),
            risks=[
                BDRisk(
                    type="竞争风险",
                    description="竞品X已接触客户",
                    severity="high",
                    mitigation="强调差异化优势",
                ),
            ],
            recommended_actions=["周一前发送方案", "预约周二电话"],
        )
        assert len(strategy.talking_points) == 1
        assert len(strategy.risks) == 1
        assert strategy.follow_up_plan.priority == "high"


class TestResearchResult:
    """ResearchResult 测试"""

    def test_default(self):
        result = ResearchResult()
        assert result.company_info == {}
        assert result.industry_analysis == ""
        assert len(result.competitors) == 0
