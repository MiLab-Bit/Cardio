"""SLM Router — 意图路由。

意图分类 + 工具/Agent 路由:
- 输入: 用户查询/研究问题
- 输出: 应该走哪个 capability / tool / agent

优化策略:
1. 优先使用 SLM 分类器（如果真实模型可用）
2. 关键词匹配作为 fallback
3. 置信度阈值决定是否升级到 LLM
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .types import (
    RouteData,
    RouteResult,
    RouteTarget,
    SLMCapability,
)

logger = logging.getLogger(__name__)

# ── 路由目标 ──────────────────────────────────────────────────

# 研究意图 → tool capability 映射
_INTENT_TO_CAPABILITY: dict[str, list[str]] = {
    "company_background":    ["COMPANY_LOOKUP", "BROWSER_AUTOMATE"],
    "website_research":      ["BROWSER_AUTOMATE", "COMPANY_LOOKUP"],
    "risk_check":            ["RISK_ASSESSMENT", "COMPANY_LOOKUP"],
    "competitor_research":   ["BROWSER_AUTOMATE", "SEARCH_ENGINE"],
    "industry_trend":        ["SEARCH_ENGINE", "BROWSER_AUTOMATE"],
    "person_investigation":  ["COMPANY_LOOKUP", "SOCIAL_MEDIA_SEARCH"],
}

# Agent 名称
_AGENT_NAMES = ["extractor", "researcher", "synthesizer", "strategist", "critic"]

# Capability 名称
_CAPABILITY_NAMES = [
    "COMPANY_LOOKUP", "RISK_ASSESSMENT", "EQUITY_ANALYSIS",
    "BROWSER_AUTOMATE", "SEARCH_ENGINE", "SOCIAL_MEDIA_SEARCH",
    "WRITE_CRM", "MASS_EXPORT", "MEMORY_INSERT",
]

# Agent 路由标签（用于 SLM 分类）
_AGENT_LABELS = [
    "extractor", "researcher", "synthesizer", "strategist", "critic", "general"
]

# Capability 路由标签（用于 SLM 分类）
_CAPABILITY_LABELS = [
    "COMPANY_LOOKUP", "RISK_ASSESSMENT", "EQUITY_ANALYSIS",
    "BROWSER_AUTOMATE", "SEARCH_ENGINE", "SOCIAL_MEDIA_SEARCH",
    "WRITE_CRM", "MASS_EXPORT", "MEMORY_INSERT", "GENERAL",
]


class Router:
    """SLM 意图路由器（优先使用 SLM，关键词作为 fallback）"""

    def __init__(self):
        self._classifier = None  # lazy import
        self._use_slm = True  # 是否优先使用 SLM

    async def _get_classifier(self):
        """懒加载分类器"""
        if self._classifier is None:
            from .classifier import Classifier
            self._classifier = Classifier()
        return self._classifier

    async def _route_with_slm(self, query: str, labels: list[str], route_type: str) -> RouteResult | None:
        """尝试用 SLM 做路由（如果真实模型可用）"""
        try:
            from .real_engines import model_available
            if not model_available():
                return None  # 真实模型不可用，fallback 到关键词

            from .real_engines import RealClassifier
            classifier = RealClassifier()

            t0 = time.perf_counter()

            # 用 SLM 分类
            result = await classifier.classify(query, labels=labels, context_tag=route_type)

            if result.confidence < 0.5:
                return None  # 置信度太低，fallback

            # 构建路由结果
            top_label = result.data.top_label if result.data else labels[0]
            targets = [
                RouteTarget(
                    target=top_label,
                    score=result.data.top_score if result.data else 0.5,
                    rationale=f"SLM classification: {top_label}"
                )
            ]

            # 如果有多个标签，也加入结果
            if result.data and result.data.labels:
                for label in result.data.labels[1:3]:  # 最多加 2 个备选
                    if label.label != top_label:
                        targets.append(RouteTarget(
                            target=label.label,
                            score=label.score,
                            rationale=label.rationale
                        ))

            latency = (time.perf_counter() - t0) * 1000

            return RouteResult(
                capability=SLMCapability.ROUTE,
                model="qwen2.5-0.5b",
                data=RouteData(
                    targets=targets,
                    intent=route_type,
                    top_target=top_label,
                ),
                confidence=result.confidence,
                latency_ms=round(latency, 2),
                needs_escalation=result.confidence < 0.7,
                escalation_reason="Low SLM confidence" if result.confidence < 0.7 else "",
            )

        except Exception as exc:
            logger.warning("SLM routing failed, fallback to heuristic: %s", exc)
            return None

    # ── Public API ─────────────────────────────────────────────

    async def route_intent_to_capability(self, query: str) -> RouteResult:
        """根据研究问题路由到正确的 tool capability"""
        t0 = time.perf_counter()

        if not query.strip():
            return RouteResult(
                capability=SLMCapability.ROUTE,
                model="heuristic_router",
                data=RouteData(targets=[], intent="", top_target=""),
                confidence=0.0,
                latency_ms=0,
            )

        # 尝试用 SLM
        if self._use_slm:
            intent_labels = list(_INTENT_TO_CAPABILITY.keys()) + ["other"]
            slm_result = await self._route_with_slm(query, intent_labels, "research_intent")
            if slm_result:
                # 根据意图映射到 capability
                intent = slm_result.data.top_target if slm_result.data else "other"
                capabilities = _INTENT_TO_CAPABILITY.get(intent, ["COMPANY_LOOKUP"])

                targets = [
                    RouteTarget(
                        target=cap,
                        score=0.85,
                        rationale=f"Intent={intent}"
                    )
                    for cap in capabilities
                ]

                return RouteResult(
                    capability=SLMCapability.ROUTE,
                    model=slm_result.model,
                    data=RouteData(
                        targets=targets,
                        intent=intent,
                        top_target=capabilities[0] if capabilities else "",
                    ),
                    confidence=slm_result.confidence,
                    latency_ms=slm_result.latency_ms,
                    needs_escalation=slm_result.needs_escalation,
                    escalation_reason=slm_result.escalation_reason,
                )

        # Fallback: 用 heuristic classifier
        from .classifier import Classifier
        classifier = await self._get_classifier()
        intent_result = await classifier.classify_research_intent(query)

        intent = intent_result.data.top_label if intent_result.data else ""
        capabilities = _INTENT_TO_CAPABILITY.get(intent, ["COMPANY_LOOKUP"])

        targets = [
            RouteTarget(target=cap, score=intent_result.data.top_score if intent_result.data else 0.5,
                       rationale=f"Intent={intent}")
            for cap in capabilities
        ]

        latency = (time.perf_counter() - t0) * 1000
        top_target = targets[0].target if targets else ""

        return RouteResult(
            capability=SLMCapability.ROUTE,
            model="heuristic_router",
            data=RouteData(
                targets=targets,
                intent=intent,
                top_target=top_target,
            ),
            confidence=round(intent_result.confidence if intent_result.data else 0.5, 4),
            latency_ms=latency,
            needs_escalation=(not intent or intent_result.confidence < 0.5),
            escalation_reason="Unclear intent, escalate to LLM" if not intent else "",
        )

    async def route_to_agent(self, task_description: str) -> RouteResult:
        """路由到 Agent（优先使用 SLM）"""
        t0 = time.perf_counter()

        # 尝试用 SLM
        if self._use_slm:
            slm_result = await self._route_with_slm(task_description, _AGENT_LABELS, "agent_routing")
            if slm_result:
                return slm_result

        # Fallback: 关键词匹配
        text_lower = task_description.lower()

        targets: list[RouteTarget] = []
        agent_keywords = {
            "extractor": ["名片", "ocr", "提取", "抽出", "卡"],
            "researcher": ["研究", "调研", "企业", "公司", "背调", "信息"],
            "synthesizer": ["综合", "融合", "画像", "分析", "评分"],
            "strategist": ["策略", "BD", "跟进", "方案", "商机"],
            "critic": ["审计", "审核", "检查", "质量", "校准"],
        }

        for agent, kws in agent_keywords.items():
            score = sum(1 for kw in kws if kw in text_lower) / max(len(kws), 1)
            if score > 0:
                targets.append(RouteTarget(target=agent, score=round(score, 4),
                                          rationale=f"Keyword match: {score:.0%}"))

        if not targets:
            # 默认路由到 researcher
            targets.append(RouteTarget(target="researcher", score=0.5, rationale="Default fallback"))

        targets.sort(key=lambda x: -x.score)

        latency = (time.perf_counter() - t0) * 1000

        return RouteResult(
            capability=SLMCapability.ROUTE,
            model="heuristic_router",
            data=RouteData(
                targets=targets,
                intent="task_routing",
                top_target=targets[0].target if targets else "researcher",
            ),
            confidence=min(0.85, targets[0].score * 1.5) if targets else 0.3,
            latency_ms=latency,
        )

    async def route_tool_capability(self, query: str) -> RouteResult:
        """路由到具体的 tool capability（优先使用 SLM）"""
        t0 = time.perf_counter()

        # 尝试用 SLM
        if self._use_slm:
            slm_result = await self._route_with_slm(query, _CAPABILITY_LABELS, "capability_routing")
            if slm_result:
                return slm_result

        # Fallback: 关键词匹配
        text_lower = query.lower()

        cap_keywords = {
            "COMPANY_LOOKUP": ["企业", "公司", "工商", "注册", "法人", "天眼查"],
            "RISK_ASSESSMENT": ["风险", "诉讼", "失信", "异常", "处罚"],
            "EQUITY_ANALYSIS": ["股权", "股东", "持股", "穿透"],
            "BROWSER_AUTOMATE": ["网页", "官网", "网站", "浏览", "搜索"],
            "SEARCH_ENGINE": ["搜索", "查询", "找", "查找"],
            "WRITE_CRM": ["写入", "更新", "创建记录", "保存"],
            "MASS_EXPORT": ["导出", "批量", "下载"],
            "MEMORY_INSERT": ["记忆", "记住", "学习", "记录"],
        }

        targets = []
        for cap, kws in cap_keywords.items():
            score = sum(1 for kw in kws if kw in text_lower) / max(len(kws), 1)
            if score > 0:
                targets.append(RouteTarget(target=cap, score=round(score, 4),
                                          rationale=f"Keyword match: {score:.0%}"))

        if not targets:
            # 默认路由到 COMPANY_LOOKUP
            targets.append(RouteTarget(target="COMPANY_LOOKUP", score=0.5, rationale="Default fallback"))

        targets.sort(key=lambda x: -x.score)

        latency = (time.perf_counter() - t0) * 1000

        return RouteResult(
            capability=SLMCapability.ROUTE,
            model="heuristic_router",
            data=RouteData(
                targets=targets,
                intent="capability_routing",
                top_target=targets[0].target if targets else "COMPANY_LOOKUP",
            ),
            confidence=min(0.85, targets[0].score * 1.5) if targets else 0.3,
            latency_ms=latency,
        )
