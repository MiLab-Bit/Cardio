"""Enrichment Subsystem — Policies: quota, cost, priority, fallback."""

from __future__ import annotations

from byou.tools.enrichment.types import SourceType, SourcePriority

# ── Source priority ranking ──────────────────────
# 按可信度排序: primary > secondary > fallback > unverified

SOURCE_PRIORITY_ORDER: list[SourcePriority] = [
    SourcePriority.PRIMARY,
    SourcePriority.SECONDARY,
    SourcePriority.FALLBACK,
    SourcePriority.UNVERIFIED,
]

# ── Source → priority mapping ────────────────────

SOURCE_PRIORITY_MAP: dict[SourceType, SourcePriority] = {
    SourceType.TIANYANCHA: SourcePriority.PRIMARY,
    SourceType.CRM_SALESFORCE: SourcePriority.PRIMARY,
    SourceType.CRM_HUBSPOT: SourcePriority.PRIMARY,
    SourceType.OPEN_SALES_STACK: SourcePriority.SECONDARY,
    SourceType.BROWSER_RESEARCH: SourcePriority.FALLBACK,
    SourceType.EXTRACTED_CARD: SourcePriority.PRIMARY,      # 名片=一手数据
    SourceType.AGENT_INFERRED: SourcePriority.FALLBACK,
}

# ── Source → cost per call (点) ──────────────────

SOURCE_COST_MAP: dict[SourceType, int] = {
    SourceType.TIANYANCHA: 1,            # 25 点 ≈ 基础工商
    SourceType.CRM_SALESFORCE: 0,         # CRM 查询通常免费
    SourceType.CRM_HUBSPOT: 0,
    SourceType.OPEN_SALES_STACK: 0,       # 开源工具, 无 API 费用
    SourceType.BROWSER_RESEARCH: 2,       # 浏览器执行成本较高 (token+时间)
    SourceType.EXTRACTED_CARD: 0,
    SourceType.AGENT_INFERRED: 1,
}

# ── Source → capability ──────────────────────────

SOURCE_CAPABILITY_MAP: dict[SourceType, list[str]] = {
    SourceType.TIANYANCHA: [
        "company_profile", "company_risk", "equity_analysis",
    ],
    SourceType.CRM_SALESFORCE: [
        "crm_lookup", "crm_account_info",
    ],
    SourceType.CRM_HUBSPOT: [
        "crm_lookup", "crm_account_info",
    ],
    SourceType.OPEN_SALES_STACK: [
        "tech_stack", "hiring_signals", "ad_signals",
    ],
    SourceType.BROWSER_RESEARCH: [
        "web_research", "contact_discovery",
    ],
    SourceType.EXTRACTED_CARD: [
        "contact_info", "identity_verification",
    ],
    SourceType.AGENT_INFERRED: [
        "industry_analysis", "market_position",
    ],
}

# ── Fallback chain ───────────────────────────────
# 当 primary source 不可用时, 按此顺序降级

FALLBACK_CHAIN: dict[SourceType, list[SourceType]] = {
    SourceType.TIANYANCHA: [
        SourceType.BROWSER_RESEARCH,
        SourceType.AGENT_INFERRED,
    ],
    SourceType.CRM_SALESFORCE: [
        SourceType.CRM_HUBSPOT,
        SourceType.BROWSER_RESEARCH,
    ],
    SourceType.OPEN_SALES_STACK: [
        SourceType.BROWSER_RESEARCH,
    ],
}

# ── Field merge policy ───────────────────────────
# 字段冲突时的合并规则

class MergePolicy:
    """决定多源冲突如何解决"""

    # 字段 → 优先级 (哪个源最可信)
    FIELD_AUTHORITY: dict[str, list[SourceType]] = {
        # 工商类 → 天眼查最权威
        "registered_capital": [SourceType.TIANYANCHA, SourceType.CRM_SALESFORCE],
        "legal_person": [SourceType.TIANYANCHA],
        "unified_social_credit_code": [SourceType.TIANYANCHA],
        "established_date": [SourceType.TIANYANCHA],
        "status": [SourceType.TIANYANCHA],
        "address": [SourceType.TIANYANCHA],

        # 联系类 → CRM 最新
        "website": [SourceType.CRM_SALESFORCE, SourceType.BROWSER_RESEARCH, SourceType.TIANYANCHA],
        "contact_emails": [SourceType.CRM_SALESFORCE, SourceType.EXTRACTED_CARD],
        "contact_phones": [SourceType.CRM_SALESFORCE, SourceType.EXTRACTED_CARD],

        # 描述类 → 最后取最新
        "company_description": [SourceType.BROWSER_RESEARCH, SourceType.CRM_SALESFORCE],
        "industry": [SourceType.TIANYANCHA, SourceType.CRM_SALESFORCE],
    }

    @classmethod
    def resolve(
        cls, field: str, values: dict[SourceType, str]
    ) -> tuple[str, SourceType | None, str]:
        """解析冲突。返回 (selected_value, chosen_source, reason)"""
        if len(values) <= 1:
            k, v = next(iter(values.items())) if values else (None, "")
            return v, k, "single_source"

        # 按权威顺序
        authorities = cls.FIELD_AUTHORITY.get(field, [])
        for src in authorities:
            if src in values and values[src]:
                return values[src], src, "authority_chain"

        # 没有明确权威 → 选 PRIMARY 级别最长的非空值
        primary_vals = {
            k: v for k, v in values.items()
            if SOURCE_PRIORITY_MAP.get(k) == SourcePriority.PRIMARY and v
        }
        if primary_vals:
            best = max(primary_vals, key=lambda k: len(primary_vals[k]))
            return primary_vals[best], best, "primary_wins"

        # 兜底: 取最长值
        best = max(values, key=lambda k: len(values[k]))
        return values[best], best, "longest_value"


# ── Cost / Quota ─────────────────────────────────

class QuotaPolicy:
    """成本控制策略"""
    DEFAULT_MAX_COST = 100              # 单次 enrichment 最大点数
    PER_SOURCE_MAX_COST = 50            # 单个源最大点数

    # 某来源单次查询消耗
    COSTS: dict[str, int] = {
        "tianyancha.baseinfo": 1,
        "tianyancha.equity": 2,
        "tianyancha.courts": 2,
        "tianyancha.abnormal": 1,
        "browser.search": 2,
        "browser.targeted": 3,
        "browser.company_website": 5,
        "salesforce.query": 0,
        "salesforce.update": 1,          # CRM 写入消耗
        "open_sales_stack.tech": 0,
        "open_sales_stack.hiring": 0,
        "open_sales_stack.ads": 0,
    }

    @classmethod
    def estimate_cost(cls, sources: list[SourceType]) -> int:
        """估算一次 enrichment 的总成本"""
        return sum(SOURCE_COST_MAP.get(s, 1) for s in sources)

    @classmethod
    def can_afford(cls, current_cost: int, max_cost: int) -> bool:
        return current_cost < max_cost
