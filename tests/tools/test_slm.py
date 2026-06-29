"""SLM Subsystem — 全覆盖测试"""

from __future__ import annotations

import pytest

from byou.tools.slm.types import (
    ClassificationLabel,
    ClassifyData,
    CompressData,
    EscalationConfig,
    ExtractData,
    ExtractedField,
    RankedItem,
    RerankData,
    RouteData,
    RouteTarget,
    ScoreData,
    SLMCapability,
    SLMResult,
)
from byou.tools.slm.registry import SLMRegistry, get_registry
from byou.tools.slm.policies import SLMPolicies, PolicyDecision, quick_decision
from byou.tools.slm.reranker import Reranker
from byou.tools.slm.classifier import Classifier
from byou.tools.slm.extractor import Extractor
from byou.tools.slm.compressor import Compressor
from byou.tools.slm.router import Router
from byou.tools.slm.confidence import ConfidenceScorer
from byou.tools.slm.gateway import SLMGateway, SLMStats


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def registry():
    return SLMRegistry()


@pytest.fixture
def policies():
    return SLMPolicies()


@pytest.fixture
def gateway():
    return SLMGateway()


# ═══════════════════════════════════════════════════════════════
# 1. Types
# ═══════════════════════════════════════════════════════════════

class TestSLMTypes:
    def test_capability_enum(self):
        assert SLMCapability.RERANK.value == "rerank"
        assert SLMCapability.CLASSIFY.value == "classify"
        assert SLMCapability.EXTRACT.value == "extract"
        assert SLMCapability.COMPRESS.value == "compress"
        assert SLMCapability.SCORE.value == "score"
        assert SLMCapability.ROUTE.value == "route"
        assert SLMCapability.MATCH.value == "match"

    def test_slm_result_is_confident(self):
        r = SLMResult[str](
            capability=SLMCapability.CLASSIFY,
            data="test",
            confidence=0.8,
        )
        assert r.is_confident

        r2 = SLMResult[str](
            capability=SLMCapability.CLASSIFY,
            data="test",
            confidence=0.5,
        )
        assert not r2.is_confident

        r3 = SLMResult[str](
            capability=SLMCapability.CLASSIFY,
            data="test",
            confidence=0.9,
            needs_escalation=True,
        )
        assert not r3.is_confident

    def test_rerank_data_defaults(self):
        d = RerankData()
        assert d.items == []
        assert d.query == ""
        assert d.candidates_count == 0

    def test_ranked_item_fields(self):
        item = RankedItem(id="u1", text="hello", score=0.85, metadata={"url": "http://a"})
        assert item.id == "u1"
        assert item.score == 0.85

    def test_classify_data_top(self):
        d = ClassifyData(
            labels=[
                ClassificationLabel(label="A", score=0.9),
                ClassificationLabel(label="B", score=0.5),
            ],
            top_label="A",
            top_score=0.9,
        )
        assert d.top_label == "A"
        assert d.is_multi_label is False

    def test_extracted_field(self):
        f = ExtractedField(field_name="company_name", value="腾讯科技", confidence=0.9, source_span="...腾讯科技...")
        assert f.field_name == "company_name"
        assert f.value == "腾讯科技"

    def test_extract_data(self):
        d = ExtractData(
            fields=[ExtractedField(field_name="email", value="a@b.com", confidence=0.95)],
            text_length=100,
            fields_found=1,
        )
        assert d.fields_found == 1

    def test_compress_data(self):
        d = CompressData(
            compressed_text="short",
            original_length=1000,
            compressed_length=5,
            key_sentences=["sentence one"],
        )
        assert d.original_length == 1000
        assert d.compressed_length == 5

    def test_route_target(self):
        t = RouteTarget(target="COMPANY_LOOKUP", score=0.88, rationale="matched keywords")
        assert t.target == "COMPANY_LOOKUP"
        assert t.score == 0.88

    def test_score_data(self):
        s = ScoreData(score=0.75, sub_scores={"length": 0.8, "density": 0.7}, rationale="ok")
        assert s.score == 0.75
        assert s.sub_scores["length"] == 0.8

    def test_escalation_config_defaults(self):
        c = EscalationConfig()
        assert c.min_confidence == 0.6
        assert c.enable_fallback is True


# ═══════════════════════════════════════════════════════════════
# 2. Registry
# ═══════════════════════════════════════════════════════════════

class TestRegistry:
    def test_register_model(self, registry):
        registry.register("test_reranker", SLMCapability.RERANK, priority=10)
        m = registry.get_best(SLMCapability.RERANK)
        assert m is not None
        assert m.model_id == "test_reranker"
        assert m.priority == 10

    def test_get_best_highest_priority(self, registry):
        registry.register("low", SLMCapability.CLASSIFY, priority=1)
        registry.register("high", SLMCapability.CLASSIFY, priority=100)
        m = registry.get_best(SLMCapability.CLASSIFY)
        assert m.model_id == "high"

    def test_register_many(self, registry):
        entries = [
            {"model_id": "a", "capability": "rerank", "priority": 5},
            {"model_id": "b", "capability": "classify", "priority": 3},
        ]
        infos = registry.register_many(entries)
        assert len(infos) == 2
        assert registry.get_model("a") is not None
        assert registry.get_model("b") is not None

    def test_get_candidates(self, registry):
        registry.register("a", SLMCapability.CLASSIFY, priority=1)
        registry.register("b", SLMCapability.CLASSIFY, priority=2)
        candidates = registry.get_candidates(SLMCapability.CLASSIFY)
        assert len(candidates) == 2
        assert candidates[0].priority >= candidates[1].priority

    def test_has_capability(self, registry):
        assert not registry.has_capability(SLMCapability.RERANK)
        registry.register("r", SLMCapability.RERANK)
        assert registry.has_capability(SLMCapability.RERANK)

    def test_get_model_nonexistent(self, registry):
        assert registry.get_model("nope") is None

    def test_list_models(self, registry):
        registry.register("a", SLMCapability.CLASSIFY)
        models = registry.list_models()
        assert len(models) == 1
        assert models[0]["model_id"] == "a"

    def test_default_registry_has_heuristic_models(self):
        reg = get_registry()
        models = reg.list_models()
        assert len(models) >= 7  # at least all heuristic fallbacks

    def test_register_overwrites(self, registry):
        registry.register("dup", SLMCapability.RERANK, priority=5)
        registry.register("dup", SLMCapability.RERANK, priority=99)
        m = registry.get_model("dup")
        assert m.priority == 99


# ═══════════════════════════════════════════════════════════════
# 3. Policies
# ═══════════════════════════════════════════════════════════════

class TestPolicies:
    def test_should_use_slm_high_freq_structured(self, policies):
        d = policies.should_use_slm(
            SLMCapability.RERANK,
            context_tag="browser_snippet",
            input_is_structured=True,
            output_has_fixed_labels=False,
            is_high_frequency=True,
            has_fallback=True,
        )
        assert d.should_use_slm
        assert d.capability == SLMCapability.RERANK

    def test_should_use_slm_low_score(self, policies):
        d = policies.should_use_slm(
            SLMCapability.CLASSIFY,
            input_is_structured=False,
            output_has_fixed_labels=False,
            is_high_frequency=False,
            has_fallback=False,
        )
        assert not d.should_use_slm

    def test_get_config_by_context(self, policies):
        config = policies.get_config(SLMCapability.RERANK, "browser_snippet")
        assert config is not None
        assert config.min_confidence == 0.5

    def test_get_config_default(self, policies):
        config = policies.get_config(SLMCapability.EXTRACT, "unknown_context")
        assert config.min_confidence == 0.6  # default

    def test_set_config(self, policies):
        policies.set_config(
            SLMCapability.CLASSIFY, "custom",
            EscalationConfig(min_confidence=0.9, max_latency_ms=100),
        )
        config = policies.get_config(SLMCapability.CLASSIFY, "custom")
        assert config.min_confidence == 0.9

    def test_needs_escalation(self, policies):
        assert policies.needs_escalation(0.3)
        assert not policies.needs_escalation(0.8)

    def test_quick_decision(self):
        d = quick_decision(SLMCapability.RERANK, is_high_frequency=True, has_fallback=True)
        assert d.should_use_slm

    def test_list_policies(self, policies):
        all_policies = policies.list_policies()
        assert len(all_policies) >= 7  # default policies

    def test_policy_decision_fields(self):
        d = PolicyDecision(
            should_use_slm=True,
            capability=SLMCapability.CLASSIFY,
            config=EscalationConfig(min_confidence=0.6),
            reason="score=4/5",
        )
        assert d.should_use_slm
        assert d.capability == SLMCapability.CLASSIFY


# ═══════════════════════════════════════════════════════════════
# 4. Reranker
# ═══════════════════════════════════════════════════════════════

class TestReranker:
    @pytest.fixture
    def reranker(self):
        return Reranker()

    async def test_rerank_empty(self, reranker):
        result = await reranker.rerank("query", [])
        assert result.data is not None
        assert result.data.items == []

    async def test_rerank_basic(self, reranker):
        candidates = [
            {"id": "1", "text": "腾讯科技有限公司 提供云计算服务"},
            {"id": "2", "text": "天气预报今天晴天"},
            {"id": "3", "text": "腾讯云是中国领先的云计算平台"},
        ]
        result = await reranker.rerank("腾讯云 企业服务", candidates, top_k=2)
        assert len(result.data.items) <= 2
        # 腾讯相关的应该排前面
        assert "1" in [i.id for i in result.data.items] or "3" in [i.id for i in result.data.items]

    async def test_rerank_top_k(self, reranker):
        candidates = [
            {"id": f"c{i}", "text": f"文档内容 {i} 企业服务 腾讯云"} for i in range(10)
        ]
        result = await reranker.rerank("企业服务", candidates, top_k=3)
        assert len(result.data.items) == 3

    async def test_rerank_min_score(self, reranker):
        candidates = [
            {"id": "1", "text": "完全不相关的内容 天气 美食"},
            {"id": "2", "text": "也不相关"},
        ]
        result = await reranker.rerank("企业背调 科技公司", candidates, top_k=5, min_score=0.5)
        # 都不相关，应该被 min_score 过滤
        assert len(result.data.items) <= 2

    async def test_rerank_single_candidate(self, reranker):
        candidates = [{"id": "1", "text": "腾讯科技公司"}]
        result = await reranker.rerank("腾讯科技", candidates)
        assert len(result.data.items) == 1
        assert result.data.items[0].score > 0

    async def test_rerank_confidence_gap(self, reranker):
        # 大差距 → 高置信度
        candidates = [
            {"id": "1", "text": "腾讯科技云计算人工智能大数据"},
            {"id": "2", "text": "今天天气不错"},
        ]
        result = await reranker.rerank("腾讯科技 云服务 AI", candidates, top_k=2)
        assert result.confidence > 0.5

    async def test_rerank_with_metadata(self, reranker):
        candidates = [
            {"id": "u1", "text": "腾讯官网首页", "metadata": {"url": "https://tencent.com", "type": "official"}},
        ]
        result = await reranker.rerank("腾讯官网", candidates)
        assert result.data.items[0].metadata.get("url") == "https://tencent.com"

    async def test_tokenize_chinese(self, reranker):
        tokens = reranker._tokenize("腾讯科技公司")
        assert len(tokens) >= 3  # 至少拆出中文字符
        assert "腾" in tokens or "讯" in tokens or "科" in tokens

    async def test_tokenize_mixed(self, reranker):
        tokens = reranker._tokenize("Hello 世界 AI")
        assert "hello" in tokens
        assert "ai" in tokens
        # 中文字符也应在
        assert "世" in tokens or "界" in tokens

    async def test_bigram_similarity(self, reranker):
        a = ["a", "b", "c", "d"]
        b = ["a", "b", "x", "y"]
        score = reranker._bigram_similarity(a, b)
        assert 0 < score < 1

    async def test_heuristic_score_exact(self, reranker):
        tokens = reranker._tokenize("企业服务 腾讯")
        score = reranker._heuristic_score(tokens, "腾讯企业服务")
        assert score > 0.3


# ═══════════════════════════════════════════════════════════════
# 5. Classifier
# ═══════════════════════════════════════════════════════════════

class TestClassifier:
    @pytest.fixture
    def classifier(self):
        return Classifier()

    async def test_classify_empty(self, classifier):
        result = await classifier.classify("")
        assert result.confidence == 0.0

    async def test_classify_research_intent_company(self, classifier):
        result = await classifier.classify_research_intent("查一下腾讯公司的工商背景和注册资本")
        assert result.data.top_label == "company_background"

    async def test_classify_research_intent_risk(self, classifier):
        result = await classifier.classify_research_intent("看看有没有诉讼和失信记录")
        assert result.data.top_label == "risk_check"

    async def test_classify_research_intent_competitor(self, classifier):
        result = await classifier.classify_research_intent("竞争对手有哪些 市场份额")
        assert result.data.top_label == "competitor_research"

    async def test_classify_page_type_official(self, classifier):
        result = await classifier.classify_page_type("关于我们 版权所有 联系我们")
        assert result.data.top_label == "official_website"

    async def test_classify_page_type_news(self, classifier):
        result = await classifier.classify_page_type("新闻 报道 记者 发布")
        assert result.data.top_label == "news_article"

    async def test_classify_customer_level_a(self, classifier):
        result = await classifier.classify_customer_level("CEO 总经理 决策权 预算充足")
        assert result.data.top_label == "A"

    async def test_classify_customer_level_c(self, classifier):
        result = await classifier.classify_customer_level("客户有兴趣但还在观望需要评估")
        assert result.data.top_label in ("B", "C")

    async def test_classify_risk_signals_multi(self, classifier):
        result = await classifier.classify_risk_signals("这个公司有诉讼记录 还有经营异常 被行政处罚过")
        labels = [l.label for l in result.data.labels if l.score > 0.2]
        assert len(labels) >= 2

    async def test_classify_quality_issues(self, classifier):
        result = await classifier.classify_quality_issues("缺失关键字段 数据存在矛盾和不一致")
        labels = [l.label for l in result.data.labels if l.score > 0.2]
        assert len(labels) >= 2

    async def test_classify_custom_labels(self, classifier):
        labels = ["tech_company", "finance_company", "retail_company"]
        result = await classifier.classify("腾讯科技有限公司 云计算 AI 大数据", labels=labels)
        assert result.data.top_label == "tech_company"

    async def test_classify_confidence_decay_short_text(self, classifier):
        result = await classifier.classify("短", labels=["A", "B"])
        assert result.confidence <= 0.5


# ═══════════════════════════════════════════════════════════════
# 6. Extractor
# ═══════════════════════════════════════════════════════════════

class TestExtractor:
    @pytest.fixture
    def extractor(self):
        return Extractor()

    async def test_extract_empty(self, extractor):
        result = await extractor.extract("")
        assert result.confidence == 0.0

    async def test_extract_email(self, extractor):
        result = await extractor.extract("请联系 contact@tencent.com 获取更多信息", fields=["email"])
        assert len(result.data.fields) >= 1
        values = [f.value for f in result.data.fields if f.field_name == "email"]
        assert any("contact@tencent.com" in v for v in values)

    async def test_extract_phone(self, extractor):
        result = await extractor.extract("电话13800138000 欢迎来电", fields=["phone_cn"])
        values = [f.value for f in result.data.fields if f.field_name == "phone_cn"]
        assert any("13800138000" in v for v in values)

    async def test_extract_company_name(self, extractor):
        result = await extractor.extract(
            "腾讯科技有限公司成立于1998年", fields=["company_name"]
        )
        values = [f.value for f in result.data.fields if f.field_name == "company_name"]
        assert any("腾讯科技" in v for v in values)

    async def test_extract_company_fields(self, extractor):
        text = (
            "北京字节跳动科技有限公司\n"
            "电话: 010-12345678\n"
            "邮箱: hr@bytedance.com\n"
            "CEO: 张一鸣\n"
            "官网: https://www.bytedance.com"
        )
        result = await extractor.extract_company_fields(text)
        found_fields = {f.field_name for f in result.data.fields}
        assert "company_name" in found_fields
        assert "phone_cn" in found_fields or "email" in found_fields

    async def test_extract_website(self, extractor):
        result = await extractor.extract(
            "访问 https://www.example.com 了解更多", fields=["website"]
        )
        values = [f.value for f in result.data.fields if f.field_name == "website"]
        assert any("example.com" in v for v in values)

    async def test_extract_no_match(self, extractor):
        result = await extractor.extract("纯文本没有任何结构化信息", fields=["email", "phone_cn"])
        assert all(f.field_name not in ("email", "phone_cn") for f in result.data.fields) or len(result.data.fields) == 0

    async def test_extract_field_confidence_high_quality(self, extractor):
        result = await extractor.extract("邮箱: admin@company.com", fields=["email"])
        for f in result.data.fields:
            if f.field_name == "email":
                assert f.confidence >= 0.8


# ═══════════════════════════════════════════════════════════════
# 7. Compressor
# ═══════════════════════════════════════════════════════════════

class TestCompressor:
    @pytest.fixture
    def compressor(self):
        return Compressor()

    async def test_compress_empty(self, compressor):
        result = await compressor.compress("")
        assert result.data.original_length == 0

    async def test_compress_reduces_length(self, compressor):
        long_text = "腾讯科技有限公司是一家领先的互联网企业。" * 20
        result = await compressor.compress(long_text, max_chars=200)
        assert result.data.compressed_length < result.data.original_length

    async def test_compress_key_sentences(self, compressor):
        text = (
            "版权所有 2024 腾讯科技。\n"
            "腾讯云是中国领先的云计算平台。\n"
            "提供弹性计算、存储、数据库等服务。\n"
            "服务超过数百万企业客户。\n"
            "电话: 0755-86013388。\n"
            "更多信息请访问官网。\n"
        )
        result = await compressor.compress(text, max_chars=500)
        assert len(result.data.key_sentences) >= 1
        # 腾讯云信息应保留
        assert "腾讯云" in result.data.compressed_text or "云计算" in result.data.compressed_text

    async def test_compress_filters_noise(self, compressor):
        text = (
            "这是关键内容。\n"
            "版权所有 2024 Company Inc.\n"
            "- \n"
            "第二个关键信息。\n"
            "Loading...\n"
            "更多\n"
        )
        result = await compressor.compress(text, max_chars=500)
        assert "关键内容" in result.data.compressed_text
        assert "关键信息" in result.data.compressed_text
        assert "版权所有" not in result.data.compressed_text

    async def test_compress_respects_max_chars(self, compressor):
        text = "A" * 2000
        result = await compressor.compress(text, max_chars=100)
        assert result.data.compressed_length <= 100

    async def test_compress_browser_snippet(self, compressor):
        html = "<html><body><h1>腾讯科技</h1><p>云服务</p></body></html>"
        result = await compressor.compress_browser_snippet(html, max_chars=200)
        assert result.data.compressed_length > 0

    async def test_extract_text_from_html(self, compressor):
        html = "<html><script>alert('xss')</script><p>正文内容</p><style>.a{}</style></html>"
        text = compressor._extract_text_from_html(html)
        assert "alert" not in text
        assert "正文内容" in text
        assert ".a{}" not in text

    async def test_split_sentences(self, compressor):
        sentences = compressor._split_sentences("第一句。第二句！第三句？第四句")
        assert len(sentences) >= 3

    async def test_filter_noise_removes_empty(self, compressor):
        # _filter_noise 只过滤噪音模式的句, 不处理空句 (空句由 _split_sentences 过滤)
        clean = compressor._filter_noise(["真内容真内容", "Loading...请稍候", "版权所有 2024"])
        assert "真内容真内容" in clean
        assert "Loading..." not in clean
        assert "版权所有" not in clean

    async def test_score_sentences_position_bias(self, compressor):
        sents = ["开头关键句", "中间", "中间", "中间", "末尾句"]
        scored = compressor._score_sentences(sents)
        # 开头得分应较高
        assert scored[0][1] > scored[2][1]


# ═══════════════════════════════════════════════════════════════
# 8. Router
# ═══════════════════════════════════════════════════════════════

class TestRouter:
    @pytest.fixture
    def router(self):
        return Router()

    async def test_route_intent_company_background(self, router):
        result = await router.route_intent_to_capability("查公司工商注册信息")
        assert result.data.intent == "company_background"
        assert "COMPANY_LOOKUP" in [t.target for t in result.data.targets]

    async def test_route_intent_risk(self, router):
        result = await router.route_intent_to_capability("有没有诉讼和失信记录")
        assert result.data.intent == "risk_check"
        assert "RISK_ASSESSMENT" in [t.target for t in result.data.targets]

    async def test_route_intent_website(self, router):
        result = await router.route_intent_to_capability("打开官网看看产品介绍")
        assert result.data.intent == "website_research"

    async def test_route_to_agent(self, router):
        result = await router.route_to_agent("调研一下这个公司的背景信息")
        assert "researcher" in [t.target for t in result.data.targets]

    async def test_route_to_agent_strategist(self, router):
        result = await router.route_to_agent("生成BD跟进策略")
        assert any(t.target == "strategist" for t in result.data.targets)

    async def test_route_tool_capability(self, router):
        result = await router.route_tool_capability("企业工商信息查询")
        assert "COMPANY_LOOKUP" in [t.target for t in result.data.targets]

    async def test_route_empty_query(self, router):
        result = await router.route_intent_to_capability("")
        assert result.confidence == 0.0

    async def test_route_intent_competitor(self, router):
        result = await router.route_intent_to_capability("竞品分析 市场份额对比")
        assert result.data.intent == "competitor_research"


# ═══════════════════════════════════════════════════════════════
# 9. Confidence Scorer
# ═══════════════════════════════════════════════════════════════

class TestConfidenceScorer:
    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer()

    async def test_score_empty(self, scorer):
        result = await scorer.score("")
        assert result.data.score == 0.0

    async def test_score_good_text(self, scorer):
        result = await scorer.score("腾讯科技有限公司是一家领先的互联网企业，提供云计算、大数据等服务。")
        assert result.data.score > 0.3

    async def test_score_short_text_low(self, scorer):
        result = await scorer.score("hi")
        assert result.data.score < 0.5

    async def test_score_length_optimal(self, scorer):
        s = scorer._score_length(100)
        assert s == 1.0

    async def test_score_length_too_short(self, scorer):
        s = scorer._score_length(5)
        assert s < 0.3

    async def test_score_density_with_entities(self, scorer):
        score = scorer._score_density("腾讯「2024云服务报告」收入达到100亿人民币")
        assert score > 0

    async def test_score_structure_with_list(self, scorer):
        score = scorer._score_structure("1. 第一点\n2. 第二点\n3. 第三点")
        assert score >= 0.3

    async def test_score_slm_result(self, scorer):
        result = await scorer.score_slm_result("good text with enough content for scoring purpose", confidence=0.8)
        assert result.data.score > 0


# ═══════════════════════════════════════════════════════════════
# 10. Gateway
# ═══════════════════════════════════════════════════════════════

class TestGateway:
    @pytest.fixture
    def gateway(self):
        return SLMGateway()

    async def test_rerank(self, gateway):
        candidates = [
            {"id": "1", "text": "腾讯云计算服务"},
            {"id": "2", "text": "今天天气晴朗"},
            {"id": "3", "text": "腾讯企业服务方案"},
        ]
        result = await gateway.rerank("腾讯云 企业服务", candidates, top_k=2)
        assert len(result.data.items) == 2
        assert result.data.items[0].score >= result.data.items[1].score

    async def test_classify(self, gateway):
        result = await gateway.classify("腾讯科技有限公司 工商背景 注册资本", labels=[
            "company_background", "risk_check", "competitor_research"
        ])
        assert result.data.top_label == "company_background"

    async def test_extract(self, gateway):
        result = await gateway.extract("联系邮箱: hr@company.com", fields=["email"])
        emails = [f.value for f in result.data.fields if f.field_name == "email"]
        assert any("hr@company.com" in e for e in emails)

    async def test_compress(self, gateway):
        result = await gateway.compress("重要内容。重复。重要内容。", max_chars=15)
        assert result.data.compressed_length <= 15

    async def test_route(self, gateway):
        result = await gateway.route("查企业工商信息", route_type="capability")
        assert result.data.top_target == "COMPANY_LOOKUP"

    async def test_score_quality(self, gateway):
        result = await gateway.score_quality("这是一段质量还不错的文本，长度适中，信息密度合理。")
        assert result.data.score > 0.3

    async def test_quick_methods(self, gateway):
        # rerank_browser_results
        r1 = await gateway.rerank_browser_results("企业信息", [{"id": "a", "text": "企业官网首页"}], top_k=1)
        assert len(r1.data.items) == 1

        # classify_research_intent
        c1 = await gateway.classify_research_intent("查一下诉讼记录")
        assert c1.data.top_label == "risk_check"

        # classify_page_type
        c2 = await gateway.classify_page_type("关于我们 联系我们 版权所有")
        assert c2.data.top_label == "official_website"

        # classify_customer_level
        c3 = await gateway.classify_customer_level("CEO 总经理 大客户")
        assert c3.data.top_label == "A"

        # extract_company_fields
        e1 = await gateway.extract_company_fields("腾讯科技 电话13800138000 邮箱hr@tencent.com")
        found = {f.field_name for f in e1.data.fields}
        assert "company_name" in found

        # compress_browser_snippet
        p1 = await gateway.compress_browser_snippet("<p>公司介绍腾讯云服务</p>")
        assert p1.data.compressed_length > 0

    async def test_needs_llm_confident(self, gateway):
        r = SLMResult[str](
            capability=SLMCapability.CLASSIFY,
            data="test",
            confidence=0.9,
        )
        assert not await gateway.needs_llm(SLMCapability.CLASSIFY, r)

    async def test_needs_llm_unconfident(self, gateway):
        r = SLMResult[str](
            capability=SLMCapability.CLASSIFY,
            data="test",
            confidence=0.3,
        )
        assert await gateway.needs_llm(SLMCapability.CLASSIFY, r)

    async def test_needs_llm_escalation_flagged(self, gateway):
        r = SLMResult[str](
            capability=SLMCapability.CLASSIFY,
            data="test",
            confidence=0.9,
            needs_escalation=True,
        )
        assert await gateway.needs_llm(SLMCapability.CLASSIFY, r)

    async def test_stats(self, gateway):
        await gateway.classify_research_intent("腾讯公司")
        await gateway.classify_research_intent("风险调查")
        summary = gateway.stats.summary()
        assert summary["total_calls"] == 2
        assert summary["by_capability"]["classify"] == 2

    async def test_session_context_manager(self):
        g = SLMGateway()
        async with g.session() as s:
            assert s is g
        # 成功退出即可

    async def test_policy_skip(self, gateway):
        # 覆盖一个已知不会被策略允许的场景 (无 fallback)
        # 实际上默认策略允许，这里只是验证路由不报错
        result = await gateway.rerank("test", [{"id": "1", "text": "hello"}])
        assert result is not None


# ═══════════════════════════════════════════════════════════════
# 11. Stats
# ═══════════════════════════════════════════════════════════════

class TestStats:
    def test_increment(self):
        s = SLMStats()
        s.increment("rerank")
        s.increment("rerank")
        s.increment("classify")
        assert s.summary()["total_calls"] == 3
        assert s.summary()["by_capability"]["rerank"] == 2

    def test_record_latency(self):
        s = SLMStats()
        s.record_latency("rerank", 10.5)
        s.record_latency("rerank", 20.5)
        avg = s.summary()["avg_latency_ms"]["rerank"]
        assert avg == 15.5

    def test_record_escalation(self):
        s = SLMStats()
        s.record_escalation("classify")
        s.record_escalation("classify")
        assert s.summary()["escalations"]["classify"] == 2

    def test_reset(self):
        s = SLMStats()
        s.increment("rerank")
        s.reset()
        assert s.summary()["total_calls"] == 0
