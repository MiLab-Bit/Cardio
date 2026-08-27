"""本地 Mock LLM（OpenAI 兼容）——仅用于离线验证 Cardio 后端逻辑。"""
import json
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


def _stage_from(messages):
    sys_text = ""
    for m in messages:
        if m.get("role") == "system":
            sys_text += m.get("content", "")
    if "提取官" in sys_text:
        return "extraction"
    if "调研员" in sys_text:
        return "research"
    if "画像师" in sys_text:
        return "synthesis"
    if "谋士" in sys_text:
        return "strategy"
    if "审官" in sys_text:
        return "critique"
    return "chat"


def _fake(stage):
    if stage == "extraction":
        return json.dumps({
            "name": "王明", "title": "CEO", "company": "环球科技",
            "phone": "13800000000", "email": "wang@global-tech.com",
            "industry": "外贸/供应链", "needs": ["供应链方案", "降本"],
            "tags": ["外贸", "决策人"], "summary": "环球科技 CEO，关注供应链优化。",
            "confidence": 0.92,
        }, ensure_ascii=False)
    if stage == "research":
        return json.dumps({
            "company_profile": "环球科技是一家跨境供应链服务商。",
            "industry_trends": ["近岸采购", "数字化供应链"],
            "pain_points": ["交货周期长", "成本波动"],
            "opportunities": ["东南亚产能", "海外仓"],
            "suggested_sources": ["官网", "行业报告"],
            "summary": "具备成长性的供应链服务商。", "confidence": 0.8,
        }, ensure_ascii=False)
    if stage == "synthesis":
        return json.dumps({
            "enriched_profile": {"规模": "中型", "定位": "跨境供应链"},
            "intent_score": 0.85, "customer_level": "重要",
            "relationship_hint": "可通过行业活动触达", "summary": "高意向重要客户。",
            "confidence": 0.88,
        }, ensure_ascii=False)
    if stage == "strategy":
        return json.dumps({
            "next_steps": ["安排demo", "发送方案"],
            "talking_points": ["交付时效", "成本结构"],
            "channels": ["邮件", "微信"], "follow_up_timing": "3天内",
            "proposal_idea": "提供免费供应链诊断", "summary": "3天内邮件跟进并约demo。",
            "confidence": 0.9,
        }, ensure_ascii=False)
    if stage == "critique":
        return json.dumps({
            "risk_alerts": ["预算未确认"], "trust_score": 0.82, "passed": True,
            "missing_info": ["预算区间"], "advice": "先确认预算再推进。",
            "summary": "整体可信，建议确认预算。",
        }, ensure_ascii=False)
    return "我是商枢，已记录这位客户，可用「数字商册分析」做深度研判。"


@app.post("/v1/chat/completions")
async def completions(req: Request):
    body = await req.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    stage = _stage_from(messages)
    content = _fake(stage)
    if not stream:
        return {
            "id": "mock-" + uuid.uuid4().hex[:8],
            "object": "chat.completion",
            "model": body.get("model", "Qwen-flash"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        }
    # SSE
    async def gen():
        for ch in list(content):
            yield "data: " + json.dumps({
                "choices": [{"delta": {"content": ch}}]
            }, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
