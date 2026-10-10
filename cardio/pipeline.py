"""Cardio 五段式商务分析流水线 — 全部基于 Qwen-flash。

改进（2026-10-05）：
  - 每个 SYSTEM prompt 加优先级标注（准确 > 完整 > 文采）
  - research 段强制标注 [推断]/[待核实]
  - critique 段给审核 checklist
  - temperature 分段控制
  - 每段加"不确定时怎么办"的明确指引
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from . import llm

ProgressFn = Callable[[str, dict], None]

STAGE_ORDER = ["extraction", "research", "synthesis", "strategy", "critique"]

STAGE_META = {
    "extraction": {"label": "信息提取", "agent": "提取官", "icon": "\U0001faaa"},
    "research":   {"label": "背景调研", "agent": "调研员", "icon": "\U0001f52d"},
    "synthesis":  {"label": "画像合成", "agent": "画像师", "icon": "\U0001f9ed"},
    "strategy":   {"label": "BD 策略", "agent": "谋士",   "icon": "\u265f\ufe0f"},
    "critique":   {"label": "风险审核", "agent": "审官",   "icon": "\U0001f6e1\ufe0f"},
}

# 每段 temperature：事实段低（准确）、策略段中（务实）、审核段极低（稳定）
STAGE_TEMPERATURES = {
    "extraction": 0.1,
    "research":   0.2,
    "synthesis":  0.3,
    "strategy":   0.5,
    "critique":   0.1,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SYSTEM_EXTRACTION = """你是 Cardio 数字商册的「提取官」。

【最高优先级】准确 > 完整 > 简洁。宁可留空也不猜。

规则：
1. 只从用户文本中提取明确出现的信息，绝不推断或补全。
2. 缺失字段填空字符串或空数组。
3. 如果文本里写的是"可能""好像是"，对应字段也要标注不确定。

输出 JSON（不要 markdown，不要解释）：
{"name":str,"title":str,"company":str,"phone":str,"email":str,"industry":str,"needs":[str],"tags":[str],"summary":str,"confidence":float}

confidence 含义：你有多大把握提取是准确的（0.0-1.0）。信息越少越低。"""

SYSTEM_RESEARCH = """你是 Cardio 的「调研员」。

【最高优先级】区分事实与推断，绝不在没有依据时做确定性断言。

规则：
1. 你无法实时联网。所有"行业趋势""痛点"都是你的常识推断，必须标注。
2. 每条 industry_trends / pain_points / opportunities 前面加标签：
   - [常识] = 行业通用知识（如"SaaS 公司注重续费率"）
   - [推断] = 基于该客户特征的推测（如"从其规模看可能有审批流程长的问题"）
   - [待核实] = 你不确定但值得验证的假设
3. 禁止编造具体数字（市场规模、公司营收等），除非用户输入里有。
4. suggested_sources 给出"去哪里验证"的建议（如"查其官网新闻页""看天眼查司法风险"）。

输出 JSON（不要 markdown，不要解释）：
{"company_profile":str,"industry_trends":[str],"pain_points":[str],"opportunities":[str],"suggested_sources":[str],"summary":str,"confidence":float}"""

SYSTEM_SYNTHESIS = """你是 Cardio 的「画像师」。

【最高优先级】画像必须可追溯——每个结论对应前面的哪段输入。

规则：
1. intent_score（0-1）：基于线索的明确程度打分。明确采购意向=0.8+，初步接触=0.3-0.5。
2. customer_level 取其一：战略/重要/普通/潜在。判定标准：
   - 战略 = 知名大企业或高客单价
   - 重要 = 有明确需求和预算
   - 普通 = 有接触但需求模糊
   - 潜在 = 刚开始了解
3. relationship_hint 给出一句具体建议（如"通过 XX 活动建立初次联系"），不要空话。

输出 JSON（不要 markdown，不要解释）：
{"enriched_profile":{},"intent_score":float,"customer_level":str,"relationship_hint":str,"summary":str,"confidence":float}"""

SYSTEM_STRATEGY = """你是 Cardio 的「谋士」。

【最高优先级】策略必须具体可执行，不要正确的废话。

规则：
1. next_steps：每条必须是"谁在什么时候做什么"的完整动作（如"本周五前给王总发行业报告 PDF"）。
2. talking_points：给出 3 条以内，每条针对一个具体痛点或机会。
3. channels：优先推荐 2-3 个，说明为什么选这个渠道。
4. follow_up_timing：给出具体时间窗口（如"初次接触后 3-5 个工作日"）。
5. 如果客户信息太少无法给策略，直接在 summary 里说"信息不足，建议先做 XX"，不要硬编。

输出 JSON（不要 markdown，不要解释）：
{"next_steps":[str],"talking_points":[str],"channels":[str],"follow_up_timing":str,"proposal_idea":str,"summary":str,"confidence":float}"""

SYSTEM_CRITIQUE = """你是 Cardio 的「审官」。

【最高优先级】独立审核，不迎合前面的结论，敢于说"有问题"。

审核 checklist（逐条检查）：
1. 数字一致性：前面的数字（如意向分、信任分）是否和数据匹配？
2. 逻辑自洽：策略和画像是否对应？战略级客户配的是不是战略级动作？
3. 来源可追溯：每个结论是否有前面的输入支撑？有没有凭空冒出来的？
4. 完整性：有没有关键信息缺失（如没填联系方式但策略里有打电话）？

发现问题时：
- risk_alerts：列出具体问题（不要笼统说"有一定风险"）
- passed = false 时必须在 advice 里给出"怎么修"

输出 JSON（不要 markdown，不要解释）：
{"risk_alerts":[str],"trust_score":float,"passed":bool,"missing_info":[str],"advice":str,"summary":str}"""

_SYSTEMS = {
    "extraction": SYSTEM_EXTRACTION,
    "research": SYSTEM_RESEARCH,
    "synthesis": SYSTEM_SYNTHESIS,
    "strategy": SYSTEM_STRATEGY,
    "critique": SYSTEM_CRITIQUE,
}


async def _stage(stage: str, user_prompt: str, provider: dict | None = None) -> dict[str, Any]:
    """执行单段调用，使用该段专属的 temperature。"""
    text = await llm.chat(
        [{"role": "system", "content": _SYSTEMS[stage]},
         {"role": "user", "content": user_prompt}],
        model=llm.config.LLM_MODEL,
        temperature=STAGE_TEMPERATURES.get(stage, 0.3),
        provider=provider,
    )
    return llm.extract_json(text)


async def run_pipeline(
    text: str,
    on_progress: ProgressFn | None = None,
    provider: dict | None = None,
) -> dict[str, Any]:
    """执行五段式流水线，按阶段回调进度。返回完整结果。"""
    async def emit(stage: str, data: dict) -> None:
        if on_progress is None:
            return
        import asyncio
        if asyncio.iscoroutinefunction(on_progress):
            await on_progress(stage, data)
        else:
            on_progress(stage, data)

    await emit("pipeline_start", {})

    reports: dict[str, Any] = {}

    for stage in STAGE_ORDER:
        meta = STAGE_META[stage]
        await emit("stage_start", {"stage": stage, "label": meta["label"], "agent": meta["agent"]})

        if stage == "extraction":
            user_prompt = f"商务信息如下：\n{text}"
        elif stage == "research":
            user_prompt = "客户档案：\n" + json.dumps(reports.get("extraction", {}), ensure_ascii=False)
        elif stage == "synthesis":
            user_prompt = (
                "客户档案：\n" + json.dumps(reports.get("extraction", {}), ensure_ascii=False) + "\n"
                "调研结果：\n" + json.dumps(reports.get("research", {}), ensure_ascii=False)
            )
        elif stage == "strategy":
            user_prompt = (
                "客户画像：\n" + json.dumps(reports.get("synthesis", {}), ensure_ascii=False) + "\n"
                "原始信息：\n" + text
            )
        else:  # critique
            user_prompt = (
                "客户档案：" + json.dumps(reports.get("extraction", {}), ensure_ascii=False) + "\n"
                "画像：" + json.dumps(reports.get("synthesis", {}), ensure_ascii=False) + "\n"
                "策略：" + json.dumps(reports.get("strategy", {}), ensure_ascii=False)
            )

        result = await _stage(stage, user_prompt, provider=provider)
        result = {
            "agent_name": stage,
            "label": meta["label"],
            "summary": result.get("summary", f"{meta['label']}完成"),
            "details": result,
            "confidence": result.get("confidence", 0.0),
            "generated_at": _now(),
        }
        reports[stage] = result
        await emit("stage_done", {"stage": stage, "report": result})

    ext = reports.get("extraction", {}).get("details", {})
    profile = {
        "name": ext.get("name", ""),
        "title": ext.get("title", ""),
        "company": ext.get("company", ""),
        "phone": ext.get("phone", ""),
        "email": ext.get("email", ""),
        "industry": ext.get("industry", ""),
        "needs": ext.get("needs", []),
        "tags": ext.get("tags", []),
    }

    final = {
        "input_text": text,
        "profile": profile,
        "agent_reports": reports,
        "completed_at": _now(),
    }
    await emit("complete", {"result": final})
    return final
