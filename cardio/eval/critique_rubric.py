"""critique 段"敢说问题"打分器 —— 把研判质量从黑盒变白盒。

用法（无需真实 LLM）：
    from cardio.eval.critique_rubric import score_critique
    verdict = score_critique(critique_dict)   # critique_dict = 五段 critique 段返回
    verdict["dare_to_flag"]  # True 表示审官确实指出了问题

后续可接入真实 LLM 输出做自动巡检（见 product-optimization-audit.md §10.3）。
"""
from __future__ import annotations

# 风险/质疑导向的语义信号词：命中越多，说明审官越"敢说问题"。
RISK_LEXEMES = [
    "风险", "警惕", "不确定", "可能错", "缺乏", "缺失", "存疑", "建议核实",
    "未提供", "矛盾", "夸大", "过度", "不足", "薄弱", "隐患", "谨慎",
    "未验证", "无依据", "没有", "不对", "不符", "硬编",
]

# 阈值：评分 >= 此值视为"审官确实指出了问题"
DARE_THRESHOLD = 0.34


def score_critique(critique: dict) -> dict:
    """对一段 critique 输出打分。

    返回：score(0-1)、signals(命中的信号词)、has_alerts、passed、dare_to_flag。
    """
    if not isinstance(critique, dict):
        raise TypeError("critique 必须是 critique 段返回的 dict")

    summary = critique.get("summary") or ""
    alerts = critique.get("risk_alerts") or []
    advice = critique.get("advice") or ""
    passed = critique.get("passed", True)

    text = " ".join([summary, " ".join(alerts), advice])
    signals = [w for w in RISK_LEXEMES if w in text]

    # 评分构成：信号词(上限 4 分) + 有具体 alert(2 分) + 判不通过(1 分)
    raw = min(len(signals), 4) + (2 if alerts else 0) + (0 if passed else 1)
    score = max(0.0, min(1.0, raw / 6.0))

    return {
        "score": score,
        "signals": signals,
        "has_alerts": bool(alerts),
        "passed": passed,
        "dare_to_flag": score >= DARE_THRESHOLD,
    }
