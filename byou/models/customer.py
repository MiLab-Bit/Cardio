"""Byou data models — all business entities in one place."""

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


# ── Customer ──────────────────────────────────────────────────

class CustomerProfile(BaseModel):
    name: str = Field(default="")
    title: str = Field(default="")
    company: str = Field(default="")
    department: str = Field(default="")
    phone: str = Field(default="")
    email: str = Field(default="")
    wechat: str = Field(default="")
    address: str = Field(default="")
    industry: str = Field(default="")
    company_size: str = Field(default="")
    company_description: str = Field(default="")
    personal_summary: str = Field(default="")
    source: str = Field(default="")
    extracted_at: Optional[datetime] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    model_config = {"extra": "allow"}


class ResearchResult(BaseModel):
    company_info: dict[str, Any] = Field(default_factory=dict)
    industry_analysis: str = Field(default="")
    person_background: dict[str, Any] = Field(default_factory=dict)
    news_mentions: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    market_position: str = Field(default="")
    model_config = {"extra": "allow"}


class PipelineContext(BaseModel):
    id: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    card_image_path: Optional[str] = None
    audio_file_path: Optional[str] = None
    extra_context: dict[str, Any] = Field(default_factory=dict)
    raw_extraction: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""
    profile: Optional[CustomerProfile] = None
    research_result: dict[str, Any] = Field(default_factory=dict)
    synthesis_result: dict[str, Any] = Field(default_factory=dict)
    strategy_result: dict[str, Any] = Field(default_factory=dict)
    critique_result: dict[str, Any] = Field(default_factory=dict)
    intent_score: Optional[float] = None
    customer_level: Optional[str] = None
    trust_score: Optional[float] = None
    quality_passed: Optional[bool] = None
    risk_alerts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    agent_reports: dict[str, Any] = Field(default_factory=dict)
    bd_strategy: Optional["BDStrategy"] = None  # set by _handle_strategy

    def get_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.profile.name if self.profile else "Unknown",
            "company": self.profile.company if self.profile else "Unknown",
            "customer_level": self.customer_level,
            "intent_score": self.intent_score,
            "trust_score": self.trust_score,
            "quality_passed": self.quality_passed,
            "risk_count": len(self.risk_alerts),
            "error_count": len(self.errors),
            "duration": ((self.completed_at - self.started_at).total_seconds()
                         if self.completed_at else None),
        }


# ── Strategy ──────────────────────────────────────────────────

class TalkingPoint(BaseModel):
    angle: str = Field(default="")
    script: str = Field(default="")
    key_message: str = Field(default="")


class FollowUpPlan(BaseModel):
    timing: str = Field(default="")
    channel: str = Field(default="phone")
    approach: str = Field(default="")
    priority: str = Field(default="medium")


class BDRisk(BaseModel):
    type: str = Field(default="")
    description: str = Field(default="")
    severity: str = Field(default="low")
    mitigation: str = Field(default="")


class BDStrategy(BaseModel):
    customer_analysis: str = Field(default="")
    pain_points: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    talking_points: list[TalkingPoint] = Field(default_factory=list)
    objection_handling: dict[str, str] = Field(default_factory=dict)
    follow_up_plan: Optional[FollowUpPlan] = None
    risks: list[BDRisk] = Field(default_factory=list)
    competition_analysis: str = Field(default="")
    recommended_actions: list[str] = Field(default_factory=list)
    confidence_level: float = Field(default=0.7, ge=0.0, le=1.0)
    generated_at: datetime = Field(default_factory=datetime.now)
    version: str = "1.0"
