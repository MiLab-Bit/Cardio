"""研判质量评估样例输入 —— 覆盖不同成熟度，供真实 LLM 跑分（白盒化评估集）。

每条样例代表一类典型 BD 场景：
  - high_intent：信息充分、明确采购意向（应得高 intent_score / 高信任）
  - ambiguous：信息含糊、似是而非（应触发 critique 的缺失/存疑提示）
  - thin：信息极少（策略段应诚实说"信息不足"而非硬编）
"""
from __future__ import annotations

SAMPLE_INPUTS: list[dict] = [
    {
        "id": "high_intent",
        "desc": "信息充分、明确采购意向",
        "raw_text": (
            "王伟，星辰科技 CTO，手机号 13800001111，邮箱 wangwei@startech.com。"
            "公司做工业物联网平台，年营收约 2 亿，近期要采购一套数据中台，"
            "预算 300 万，计划 Q4 启动招标，希望下周安排技术交流。"
        ),
    },
    {
        "id": "ambiguous",
        "desc": "信息含糊、似是而非",
        "raw_text": (
            "有个做新能源的朋友，好像是做储能的，感觉规模不小，"
            "说想找合作，但具体做什么、预算多少都没说清楚。"
        ),
    },
    {
        "id": "thin",
        "desc": "信息极少",
        "raw_text": "李总，做教育的，加个微信详聊。",
    },
]
