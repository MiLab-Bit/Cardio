"""
BD 策略数据模型

定义 BD Strategist Agent 输出的策略结构。
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class TalkingPoint(BaseModel):
    """谈话要点"""
    angle: str = Field(default="", description="切入角度")
    script: str = Field(default="", description="参考话术")
    key_message: str = Field(default="", description="核心信息")


class FollowUpPlan(BaseModel):
    """跟进计划"""
    timing: str = Field(default="", description="建议联系时间")
    channel: str = Field(default="phone", description="建议联系渠道: phone/email/wechat")
    approach: str = Field(default="", description="跟进策略")
    priority: str = Field(default="medium", description="优先级: high/medium/low")


class BDRisk(BaseModel):
    """BD 风险项"""
    type: str = Field(default="", description="风险类型")
    description: str = Field(default="", description="风险描述")
    severity: str = Field(default="low", description="严重程度: high/medium/low")
    mitigation: str = Field(default="", description="缓解措施")


class BDStrategy(BaseModel):
    """BD 策略 — Strategist Agent 的完整输出"""

    # 客户分析
    customer_analysis: str = Field(default="", description="客户需求分析")
    pain_points: list[str] = Field(default_factory=list, description="客户痛点")
    opportunities: list[str] = Field(default_factory=list, description="商业机会")

    # 沟通策略
    talking_points: list[TalkingPoint] = Field(default_factory=list, description="谈话要点")
    objection_handling: dict[str, str] = Field(
        default_factory=dict, description="异议处理: {异议→回应}"
    )

    # 跟进计划
    follow_up_plan: Optional[FollowUpPlan] = Field(default=None, description="跟进计划")

    # 风险评估
    risks: list[BDRisk] = Field(default_factory=list, description="风险评估")
    competition_analysis: str = Field(default="", description="竞争分析")

    # 推荐行动
    recommended_actions: list[str] = Field(default_factory=list, description="推荐下一步行动")
    confidence_level: float = Field(default=0.7, ge=0.0, le=1.0, description="策略置信度")

    # 元数据
    generated_at: datetime = Field(default_factory=datetime.now)
    version: str = "1.0"
