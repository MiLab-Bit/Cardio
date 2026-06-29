"""Company Intelligence — structured research result.

Replaces the old ``dict[str, Any]`` in ``PipelineContext.research_result``
with a typed model that can carry multi-source data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EquityHolding(BaseModel):
    """Single equity holding record."""

    holder_name: str = ""
    holding_ratio: float = 0.0
    is_controller: bool = False


class CourtCase(BaseModel):
    """Single court case record."""

    case_no: str = ""
    case_type: str = ""  # 民事/刑事/行政/执行
    plaintiff: str = ""
    defendant: str = ""
    amount_yuan: float = 0.0
    judgment_date: str | None = None
    result: str = ""


class CompanyInfo(BaseModel):
    """Structured company basic info."""

    name: str = ""
    reg_number: str = ""            # 统一社会信用代码 / 工商注册号
    legal_person: str = ""          # 法定代表人
    reg_capital_wan: float = 0.0    # 注册资本（万元）
    reg_capital_currency: str = "CNY"
    establish_date: str | None = None
    status: str = "unknown"         # active/cancelled/revoked/…
    address: str = ""
    business_scope: str = ""
    industry: str = ""


class CompanyIntelligence(BaseModel):
    """Full company intelligence — multi-source research result.

    This replaces the old ``research_result: dict[str, Any]``
    in PipelineContext.
    """

    # ── Basic info ──────────────────────────────────────────
    company_info: CompanyInfo = Field(default_factory=CompanyInfo)
    company_name: str = ""

    # ── Multi-source enrichment ─────────────────────────────
    source: str = "llm"  # llm / tianyancha / qichacha / fallback

    # TianYanCha fields
    equity_holders: list[EquityHolding] = Field(default_factory=list)
    court_cases: list[CourtCase] = Field(default_factory=list)
    abnormal_count: int = 0

    # LLM enrichment
    industry_analysis: str = ""
    person_background: dict[str, Any] = Field(default_factory=dict)
    news_mentions: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    market_position: str = ""

    # Metadata
    researched_at: datetime = Field(default_factory=datetime.now)
    risk_score: float = 0.0  # 0-1, higher = riskier
    data_quality: str = "pending"  # low/medium/high

    model_config = {"extra": "allow"}

    def summary(self) -> str:
        """One-line company summary."""
        parts = [self.company_name or self.company_info.name]
        if self.company_info.reg_capital_wan:
            parts.append(f"注册资本 {self.company_info.reg_capital_wan:.0f}万")
        if self.equity_holders:
            parts.append(f"{len(self.equity_holders)} 位股东")
        if self.court_cases:
            parts.append(f"{len(self.court_cases)} 条司法记录")
        if self.risk_score:
            parts.append(f"风险评分 {self.risk_score:.2f}")
        return " | ".join(parts)

    @property
    def is_high_risk(self) -> bool:
        return self.risk_score >= 0.6 or len(self.court_cases) >= 3
