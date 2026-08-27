"""名片识别 — 调用多模态视觉模型，从名片图片提取结构化信息。

服务于 Cardio「数字商册」：用户拍一张名片照片，模型识别姓名/职位/公司等，
结构化后可直接存入商册，或作为五段式分析的输入。
"""
from __future__ import annotations

from . import config, llm

CARD_FIELDS = [
    "name", "title", "company", "department",
    "phone", "mobile", "email", "website",
    "address", "industry", "tags",
]

_CARD_PROMPT = (
    "你是一名专业的商务名片识别助手，服务于 Cardio 数字商册。"
    "请仔细识别这张名片图片，提取以下字段（识别到的填值，未识别到的填空字符串）：\n"
    "- name：姓名\n"
    "- title：职位/头衔\n"
    "- company：公司/机构\n"
    "- department：部门\n"
    "- phone：电话\n"
    "- mobile：手机\n"
    "- email：邮箱\n"
    "- website：网址\n"
    "- address：地址\n"
    "- industry：行业\n"
    "- tags：关键词标签数组（string[]）\n"
    "只输出一个 JSON 对象，不要输出任何解释性文字。"
)


async def extract_card(image_b64: str, image_format: str = "jpeg", provider: dict | None = None) -> dict:
    """从名片图片提取结构化字段，返回 dict（含可能的 'raw' 退路字段）。
    provider: 可选多模态槽位配置；为 None 时回退平台视觉模型。
    """
    raw = await llm.vision_chat(
        _CARD_PROMPT,
        image_b64,
        image_format=image_format,
        temperature=0.2,
        max_tokens=1500,
        provider=provider,
    )
    data = llm.extract_json(raw)
    # extract_json 退路：整体无法解析时返回 {"raw": text}
    if "raw" in data and len(data) == 1:
        return {"name": "", "company": "", "title": "", "raw_text": data["raw"]}
    # 归一化：确保字段存在、tags 为列表
    card = {k: (data.get(k) or "") for k in CARD_FIELDS if k != "tags"}
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    card["tags"] = tags
    return card


def card_to_text(card: dict) -> str:
    """把结构化名片转为可读文本，作为五段式分析的输入前缀。"""
    lines = []
    for k in ["name", "title", "company", "department", "phone", "mobile", "email", "website", "address", "industry"]:
        v = (card.get(k) or "").strip()
        if v:
            lines.append(f"{k}: {v}")
    tags = card.get("tags") or []
    if tags:
        lines.append("tags: " + ", ".join(tags))
    if card.get("raw_text"):
        lines.append(card["raw_text"])
    if not lines:
        return ""
    return "【名片识别结果】\n" + "\n".join(lines)
