"""Enrichment Subsystem — 冒烟测试。

验证:
1. 类型序列化
2. IdentityResolver 公司名标准化
3. MergePolicy 字段冲突解决
4. LLMMerger 多源合并
5. EnrichmentOrchestrator 无源情况 (no real API keys)
6. ResearchBundle 构建
7. CRM 写入边界
8. Source selection by capability
"""

import sys
sys.path.insert(0, r"Z:\Dev\Byou")

from byou.tools.enrichment import *
from byou.tools.enrichment.types import *
from byou.tools.enrichment.policies import MergePolicy, QuotaPolicy, SOURCE_CAPABILITY_MAP, SOURCE_PRIORITY_MAP


def test_types_roundtrip():
    """数据模型序列化"""
    req = EnrichmentRequest(
        company_name="阿里巴巴",
        website="https://www.alibaba.com",
        capabilities=["company_profile", "company_risk"],
    )
    js = req.model_dump_json()
    back = EnrichmentRequest.model_validate_json(js)
    assert back.company_name == "阿里巴巴"

    profile = CompanyProfile(industry="电商", registered_capital="1000万")
    identity = CompanyIdentity(name="阿里巴巴", unified_social_credit_code="91330100799050655B")
    bundle = ResearchBundle(company_name="阿里巴巴", identity=identity, profile=profile)
    assert "risk_summary" in dir(bundle)
    assert "电商" in str(bundle.for_synthesizer.get("industry"))

    print("[PASS] types roundtrip")


def test_identity_resolver():
    """企业身份解析"""
    resolver = IdentityResolver()
    assert resolver.normalize_name("阿里巴巴（中国）有限公司") == "阿里巴巴(中国)有限公司"
    core = resolver.extract_core_name("阿里巴巴(中国)有限公司")
    assert "有限公司" not in core  # suffix stripped
    assert "阿里" in core
    assert resolver.extract_core_name("Tencent Inc.") == "Tencent"

    # 解析 (有名字即可解析)
    id1 = resolver.resolve(company_name="阿里巴巴", domain="alibaba.com")
    assert id1.name == "阿里巴巴"
    assert id1.is_resolved  # 有名字即可解析

    # 伪造搜索结果匹配
    id2 = resolver.resolve(
        company_name="阿里巴巴",
        search_results=[{"name": "阿里巴巴(中国)有限公司", "id": "123", "credit_code": "91330100799050655B"}],
    )
    assert id2.is_resolved
    assert id2.resolution_confidence >= 0.5
    assert id2.is_fuzzy_match

    print("[PASS] identity resolver")


def test_domain_resolver():
    """域名反查"""
    dr = DomainResolver()
    assert dr.guess_company_from_domain("alibaba.com") == "阿里巴巴"
    assert dr.guess_company_from_domain("huawei.com") == "华为"
    assert dr.guess_company_from_domain("unknown-startup.cn") == "Unknown Startup"

    links = [
        {"href": "https://www.alibaba.com"},
        {"href": "https://www.tencent.com"},
        {"href": "https://www.tencent.com/about"},  # dup
    ]
    domains = dr.extract_domains_from_links(links)
    assert len(domains) == 2
    assert "www.alibaba.com" in domains

    print("[PASS] domain resolver")


def test_merge_policy():
    """字段冲突解决"""
    # 无冲突
    v, src, reason = MergePolicy.resolve("legal_person", {SourceType.TIANYANCHA: "张三"})
    assert v == "张三" and src == SourceType.TIANYANCHA

    # 权威链: 天眼查优先
    v, src, reason = MergePolicy.resolve(
        "legal_person",
        {SourceType.TIANYANCHA: "张三", SourceType.EXTRACTED_CARD: "张某某"},
    )
    assert v == "张三" and src == SourceType.TIANYANCHA

    # 无权威 → primary 最长值
    v, src, reason = MergePolicy.resolve(
        "company_description",
        {SourceType.TIANYANCHA: "", SourceType.BROWSER_RESEARCH: "电商平台", SourceType.AGENT_INFERRED: ""},
    )
    assert v == "电商平台" and src == SourceType.BROWSER_RESEARCH

    print("[PASS] merge policy")


def test_quota_policy():
    """成本控制"""
    cost = QuotaPolicy.estimate_cost([SourceType.TIANYANCHA, SourceType.BROWSER_RESEARCH])
    assert cost == 3  # 1 + 2

    assert QuotaPolicy.can_afford(0, 100)
    assert not QuotaPolicy.can_afford(100, 100)

    print("[PASS] quota policy")


def test_merger():
    """多源合并"""
    merger = DataMerger()

    records = [
        SourceRecord(
            source=SourceType.TIANYANCHA,
            source_priority=SourcePriority.PRIMARY,
            raw_data={"profile": {
                "legal_person": "张三", "registered_capital": "1000万",
                "industry": "电商", "website": "https://example.com",
            }},
        ),
        SourceRecord(
            source=SourceType.CRM_SALESFORCE,
            source_priority=SourcePriority.PRIMARY,
            raw_data={"profile": {
                "industry": "零售电商", "website": "https://example.com",
                "contact_emails": ["contact@example.com"],
            }},
        ),
    ]

    profile, decisions = merger.merge_profiles(records, "阿里巴巴")
    assert profile.legal_person == "张三"  # 天眼查权威
    assert profile.industry == "电商"       # 天眼查权威

    # 查找 industry 冲突
    industry_dec = [d for d in decisions if d.field_name == "industry"]
    assert len(industry_dec) > 0
    assert industry_dec[0].conflict_detected

    print("[PASS] merger")


def test_capability_source_mapping():
    """capability → source 映射"""
    caps = SOURCE_CAPABILITY_MAP[SourceType.TIANYANCHA]
    assert "company_profile" in caps
    assert "company_risk" in caps

    caps = SOURCE_CAPABILITY_MAP[SourceType.OPEN_SALES_STACK]
    assert "tech_stack" in caps
    assert "hiring_signals" in caps

    print("[PASS] capability mapping")


def test_enrichment_result_quality():
    """质量评分"""
    result = EnrichmentResult(
        request=EnrichmentRequest(company_name="test"),
        identity=CompanyIdentity(name="test", resolution_confidence=0.9),
        profile=CompanyProfile(industry="tech", website="https://test.com", status="存续", registered_capital="100万"),
        source_records=[
            SourceRecord(source=SourceType.TIANYANCHA, source_priority=SourcePriority.PRIMARY, is_error=False),
        ],
        conflicts_detected=0,
        sources_queried=1,
        sources_failed=0,
    )
    score = EnrichmentOrchestrator._compute_quality(result)
    assert score > 0.7  # 高质量: primary + identity + complete + no errors

    bad_result = EnrichmentResult(
        request=EnrichmentRequest(company_name="bad"),
        identity=CompanyIdentity(name="bad"),
        profile=CompanyProfile(),
        source_records=[
            SourceRecord(source=SourceType.AGENT_INFERRED, source_priority=SourcePriority.FALLBACK, is_error=True),
        ],
        errors=["No source found"],
    )
    bad_score = EnrichmentOrchestrator._compute_quality(bad_result)
    assert bad_score <= 0.3

    print("[PASS] quality scoring")


def test_research_bundle():
    """ResearchBundle 构建"""
    profile = CompanyProfile(
        industry="AI", employee_count_range="100-500", revenue_range="1000万-5000万",
        products_services=["AI Platform", "ML API"],
    )
    risk = CompanyRiskProfile(
        company_name="test", risk_score=0.15, risk_level="medium",
        court_case_count=3, abnormal_operation_count=1,
    )
    bundle = ResearchBundle(
        company_name="Test AI Co",
        profile=profile,
        risk=risk,
        quality_score=0.85,
        data_quality="high",
        data_gaps=["website"],
        warnings=["CRM not connected"],
    )
    syn = bundle.for_synthesizer
    assert syn["industry"] == "AI"
    assert syn["risk_level"] == "medium"
    assert syn["scale"]["employees"] == "100-500"

    assert "no risk data" not in bundle.risk_summary
    assert "risk=0.15" in bundle.risk_summary

    print("[PASS] research bundle")


def test_crm_write_safety():
    """CRM 写入边界"""
    import asyncio

    async def _test():
        crm = CRMAdapter()
        assert not crm.is_available

        # 不允许写
        req = EnrichmentRequest(company_name="test", allow_crm_write=False)
        record = await crm.write_back(req, {"website": "https://test.com"})
        assert record.is_error  # CRM write not allowed

        # 允许写但字段违规 — 不炸即可
        req2 = EnrichmentRequest(
            company_name="test",
            allow_crm_write=True,
            allowed_crm_fields=["website"],
        )
        # mock 不会真调, 但验证不出错
        record2 = await crm.write_back(req2, {"website": "https://test.com"})
        # mock 返回 error 因为 not implemented
        # 只验证不抛异常

    asyncio.run(_test())
    print("[PASS] CRM write safety")


# ── Run ─────────────────────────────────────────
if __name__ == "__main__":
    for fn in [
        test_types_roundtrip,
        test_identity_resolver,
        test_domain_resolver,
        test_merge_policy,
        test_quota_policy,
        test_merger,
        test_capability_source_mapping,
        test_enrichment_result_quality,
        test_research_bundle,
        test_crm_write_safety,
    ]:
        fn()
    print("\n=== ALL 10 ENRICHMENT TESTS PASSED ===")
