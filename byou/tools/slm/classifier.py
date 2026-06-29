"""SLM Classifier — 文本分类器。

支持:
- label-conditioned classification (你给标签列表, 它打分)
- open-ended classification (自由发现标签)
- heuristic fallback: 关键词+规则匹配
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .types import (
    ClassificationLabel,
    ClassifyData,
    ClassifyResult,
    SLMCapability,
)

logger = logging.getLogger(__name__)

# ── 内置分类器配置 ────────────────────────────────────────────

_CUSTOMER_LEVEL_LABELS = ["A", "B", "C", "D"]

_RESEARCH_INTENT_LABELS = [
    "company_background",    # 企业背调
    "website_research",      # 官网研究
    "risk_check",            # 风险核查
    "competitor_research",   # 竞品研究
    "industry_trend",        # 行业趋势
    "person_investigation",  # 人物调研
]

_PAGE_TYPE_LABELS = [
    "official_website",      # 官网
    "news_article",          # 新闻
    "recruitment",           # 招聘页
    "spam_or_ad",            # 垃圾/广告
    "login_wall",            # 登录墙
    "aggregator",            # 聚合页
    "social_profile",        # 社交主页
    "investment_report",     # 投资报告
    "unknown",
]

_RISK_SIGNAL_LABELS = [
    "lawsuit",               # 诉讼
    "abnormal_operation",    # 经营异常
    "penalty",               # 行政处罚
    "bankruptcy",            # 破产清算
    "labor_dispute",         # 劳动仲裁
    "debt_default",          # 债务违约
    "ownership_change",      # 股权变更
    "regulatory_risk",       # 政策风险
]

_QUALITY_ISSUE_LABELS = [
    "missing_required_field",
    "hallucinated_company",
    "hallucinated_person",
    "factual_contradiction",
    "impractical_suggestion",
    "missing_followup",
    "low_confidence_output",
]


class Classifier:
    """SLM 分类器 — 启发式 + 可扩展为小模型"""

    def __init__(self):
        self._keyword_rules: dict[str, list[str]] = {}

    # ── Public API ─────────────────────────────────────────────

    async def classify(
        self,
        text: str,
        labels: list[str] | None = None,
        context_tag: str = "default",
        multi_label: bool = False,
    ) -> ClassifyResult:
        """对文本做标签分类。

        Args:
            text: 待分类文本
            labels: 标签列表 (None = 自动选择)
            context_tag: 上下文标签 (用于选择内置标签集)
            multi_label: 是否允许多标签

        Returns:
            ClassifyResult
        """
        t0 = time.perf_counter()

        if not text.strip():
            return ClassifyResult(
                capability=SLMCapability.CLASSIFY,
                model="heuristic_classifier",
                data=ClassifyData(labels=[], top_label="", top_score=0.0),
                confidence=0.0,
                latency_ms=0,
            )

        # 解析标签
        actual_labels = labels or self._get_default_labels(context_tag)
        if not actual_labels:
            return ClassifyResult(
                capability=SLMCapability.CLASSIFY,
                model="heuristic_classifier",
                data=ClassifyData(labels=[], top_label="", top_score=0.0),
                confidence=0.0,
                latency_ms=0,
            )

        # 启发式打分
        scored = self._heuristic_classify(text, actual_labels)

        # 选取 top label(s)
        if multi_label:
            top = [l for l in scored if l.score > 0.2]
        else:
            top = scored[:1]

        latency = (time.perf_counter() - t0) * 1000

        # 置信度: 基于 top label 分数和 text 长度
        confidence = min(0.9, top[0].score * 1.2) if top else 0.1
        if len(text) < 20:
            confidence = min(confidence, 0.5)

        top_label = top[0].label if top else ""
        top_score = top[0].score if top else 0.0

        return ClassifyResult(
            capability=SLMCapability.CLASSIFY,
            model="heuristic_classifier",
            data=ClassifyData(
                labels=scored[:10],
                top_label=top_label,
                top_score=round(top_score, 4),
                is_multi_label=multi_label,
            ),
            confidence=round(confidence, 4),
            latency_ms=latency,
            needs_escalation=(confidence < 0.5),
            escalation_reason="Low classification confidence" if confidence < 0.5 else "",
        )

    # ── 快捷方法 ───────────────────────────────────────────────

    async def classify_research_intent(self, query: str) -> ClassifyResult:
        """研究意图分类"""
        return await self.classify(
            query, labels=_RESEARCH_INTENT_LABELS,
            context_tag="research_intent",
        )

    async def classify_page_type(self, snippet: str) -> ClassifyResult:
        """网页类型分类"""
        return await self.classify(
            snippet, labels=_PAGE_TYPE_LABELS,
            context_tag="page_type",
        )

    async def classify_customer_level(self, profile_text: str) -> ClassifyResult:
        """客户等级分类 (A/B/C/D)"""
        return await self.classify(
            profile_text, labels=_CUSTOMER_LEVEL_LABELS,
            context_tag="customer_level",
        )

    async def classify_risk_signals(self, text: str) -> ClassifyResult:
        """风险信号检测 (多标签)"""
        return await self.classify(
            text, labels=_RISK_SIGNAL_LABELS,
            context_tag="risk_signals", multi_label=True,
        )

    async def classify_quality_issues(self, text: str) -> ClassifyResult:
        """质量审计问题检测 (多标签)"""
        return await self.classify(
            text, labels=_QUALITY_ISSUE_LABELS,
            context_tag="critic_prescreen", multi_label=True,
        )

    # ── 启发式打分 ────────────────────────────────────────────

    def _heuristic_classify(
        self, text: str, labels: list[str],
    ) -> list[ClassificationLabel]:
        """基于关键词 + 模式的启发式分类"""
        text_lower = text.lower()
        results: list[ClassificationLabel] = []

        for label in labels:
            keywords = _get_label_keywords(label)
            matched = 0
            total = len(keywords)
            rationales: list[str] = []

            if keywords:
                for kw in keywords:
                    if kw.lower() in text_lower:
                        matched += 1
                        rationales.append(f"matched '{kw}'")

            # 对于自定义标签(无预定义关键词): 直接用标签名中的词匹配
            if not keywords or total == 0:
                # 拆标签中的词作为关键词
                label_parts = label.lower().replace("_", " ").split()
                total = len(label_parts) or 1
                for part in label_parts:
                    if part and len(part) >= 2 and part in text_lower:
                        matched += 1
                        rationales.append(f"label-part '{part}'")

            score = matched / max(total, 1) if total > 0 else 0.0

            # 奖励短文本精准匹配
            if len(text) < 100 and score > 0.5:
                score = min(1.0, score * 1.2)

            results.append(ClassificationLabel(
                label=label,
                score=round(score, 4),
                rationale="; ".join(rationales) if rationales else "no keywords matched",
            ))

        # 按分数降序
        results.sort(key=lambda x: -x.score)
        return results

    @staticmethod
    def _get_default_labels(context_tag: str) -> list[str] | None:
        """根据 context_tag 返回默认标签集"""
        mapping = {
            "research_intent": _RESEARCH_INTENT_LABELS,
            "page_type": _PAGE_TYPE_LABELS,
            "customer_level": _CUSTOMER_LEVEL_LABELS,
            "risk_signals": _RISK_SIGNAL_LABELS,
            "critic_prescreen": _QUALITY_ISSUE_LABELS,
        }
        return mapping.get(context_tag)


# ── 关键词字典 ─────────────────────────────────────────────────


def _get_label_keywords(label: str) -> list[str]:
    """标签 → 关键词列表"""
    mapping: dict[str, list[str]] = {
        # Customer level
        "A": ["CEO", "VP", "总经理", "董事长", "创始人", "决策权", "预算充足"],
        "B": ["总监", "经理", "director", "manager", "意向明确"],
        "C": ["有兴趣", "需要评估", "观望"],
        "D": ["暂无需求", "已用竞品", "拒绝", "拉黑"],

        # Research intent
        "company_background": ["背景", "工商", "注册", "成立", "法人", "注册资本"],
        "website_research": ["官网", "产品", "服务", "解决方案", "about us"],
        "risk_check": ["风险", "诉讼", "判决", "失信", "经营异常"],
        "competitor_research": ["竞品", "竞争", "替代", "市场份额", "对比"],
        "industry_trend": ["行业", "趋势", "报告", "市场规模", "增长率"],
        "person_investigation": ["履历", "教育", "背景", "经历", "linkedin"],

        # Page type
        "official_website": ["官网", "关于我们", "about us", "contact us", "版权所有"],
        "news_article": ["新闻", "news", "报道", "发布", "记者"],
        "recruitment": ["招聘", "职位", "jobs", "career", "加入我们"],
        "spam_or_ad": ["推广", "广告", "点击", "购买", "限时", "优惠"],
        "login_wall": ["登录", "login", "注册", "sign up", "please enable"],
        "aggregator": ["天眼查", "企查查", "启信宝", "更多结果", "相关企业"],
        "social_profile": ["关注", "粉丝", "动态", "linkedin.com/in"],
        "investment_report": ["融资", "估值", "IPO", "股东", "投资"],

        # Risk signals
        "lawsuit": ["诉讼", "开庭", "判决", "原告", "被告"],
        "abnormal_operation": ["经营异常", "列入异常", "移出异常"],
        "penalty": ["处罚", "罚款", "行政处罚", "责令改正"],
        "bankruptcy": ["破产", "清算", "破产重整", "强制清算"],
        "labor_dispute": ["劳动仲裁", "劳动争议", "欠薪"],
        "debt_default": ["失信", "被执行人", "限制消费", "债务"],
        "ownership_change": ["股权变更", "股份转让", "投资人变更", "法人变更"],
        "regulatory_risk": ["约谈", "监管", "整改", "通报批评", "合规"],

        # Quality issues
        "missing_required_field": ["缺失", "未填写", "None", "空"],
        "hallucinated_company": ["公司不匹配", "不存在"],
        "hallucinated_person": ["人物不匹配"],
        "factual_contradiction": ["矛盾", "冲突", "不一致"],
        "impractical_suggestion": ["不切实际", "不可能", "无法实现"],
        "missing_followup": ["无下一步行动", "缺少跟进"],
        "low_confidence_output": ["不确定", "推测", "可能"],
    }
    return mapping.get(label, [])
