"""Memory → Enrichment 全链路冒烟测试"""
import sys
sys.path.insert(0, r"Z:\Dev\Byou")

from byou.memory import *

mm = MemoryManager()
mm.start_pipeline("杭州深度求索科技", "梁文锋")

bundle = {
    "company_name": "杭州深度求索人工智能有限公司",
    "profile": {
        "industry": "AI基础模型", "employee_count_range": "100-500",
        "risk_score": 0.1, "legal_person": "梁文锋",
        "address": "浙江省杭州市", "registered_capital": "1000万",
        "key_people": [{"name": "梁文锋", "title": "CEO"}],
        "contact_emails": ["bd@deepseek.com"],
    },
    "risk": {"risk_score": 0.1, "risk_factors": ["快速增长"], "court_cases": []},
    "identity": {"unified_social_credit_code": "91330100XXX"},
    "competitors": ["百度", "字节跳动"],
}

stats = mm.remember(bundle)
print(f"Distilled: +{stats['entities_created']} entities, +{stats['relations_added']} relations")

mm.distill_strategy(
    strategy_json={"approach": "技术创新合作", "key_points": ["API开放"]},
    company_context={"industry": "AI基础模型", "risk_score": 0.1},
    outcome="won",
)
mm.end_pipeline()

# 查询
history = mm.history("深度求索")
print(f"History entries: {len(history)}")

print(f"Graph nodes: {mm.stats['graph']['nodes']}")

competitors = mm.get_competitors("杭州深度求索人工智能有限公司")
print(f"Competitors: {len(competitors)}")

patterns = mm.lookup_patterns(industry="AI基础模型")
print(f"Patterns found: {len(patterns)}")

result = mm.find_similar_cases(CaseQuery(
    company_name="智谱AI",
    company_profile={"industry": "AI基础模型", "employee_count_range": "100-500", "risk_score": 0.15},
    top_k=3,
))
print(f"Similar cases: {len(result.cases)}")

print("Memory full cycle OK")
