# Researcher Agent — 客户背调

## 文件

`byou/agents/researcher.py` → `ResearcherAgent`

## 职责

基于 Extractor 提取的公司名和人名，进行多维度背调研究。

## 处理流程

```
公司名 + 人名
  ├→ 多源搜索 (byou/tools/search.py)
  │    ├→ 搜索引擎
  │    ├→ 企查查/天眼查
  │    └→ 新闻源
  ├→ 知识库查询 (byou/tools/knowledge.py)
  │    └→ 历史客户数据检索
  └→ 知识图谱查询 (byou/infrastructure/graph_store.py)
       └→ 人脉关系路径
            ↓
        LLM 聚合分析
            ↓
        ResearchResult
```

## 输入

```python
{
    "company_name": "华为技术有限公司",
    "person_name": "张三",
    "profile": CustomerProfile,  # 可选，Extractor 输出
}
```

## 输出

```python
{
    "company_info": {
        "full_name": str,         # 公司全称
        "industry": str,          # 行业
        "scale": str,             # 规模 (large/medium/small/startup)
        "funding_stage": str,     # 融资阶段
        "recent_news": [str],     # 近期动态
        "reputation": str,        # 口碑 (positive/neutral/negative)
    },
    "person_info": {
        "background": str,        # 个人背景
        "social_links": [str],    # 社交链接
        "previous_company": [str],# 历史任职
    },
    "industry_analysis": str,     # 行业分析摘要
    "competitors": [str],         # 竞品列表
    "connection_path": [str],     # 人脉路径（通过图谱）
    "risk_flags": [str],          # 风险标记
    "confidence": float,          # 可信度
}
```

## 依赖工具

- `byou.tools.search.SearchTool` — 多源搜索
- `byou.tools.knowledge.KnowledgeBase` — 历史数据
- `byou.infrastructure.graph_store.GraphStore` — 人脉图谱

## 搜索策略

| 维度 | 关键词模板 | 优先级 |
|------|-----------|--------|
| 公司概况 | "{company} 公司介绍" | P0 |
| 融资信息 | "{company} 融资 估值" | P1 |
| 近期新闻 | "{company} 最新动态" | P1 |
| 行业地位 | "{company} 行业排名" | P2 |
| 人物背景 | "{person} {company} 背景" | P0 |
| 人脉关系 | "{person} 关系 联系人" | P2 |

## 设计要点

1. **搜索去重**: 相同 URL 不重复搜索
2. **缓存**: 同一公司 24h 内复用缓存结果
3. **风险标记**: 负面新闻、失信记录自动标记
4. **图谱路径**: 通过 `GraphStore` 查找与已有客户的关联路径
