"""Byou Production — Cost & Latency Analyzer.

LLM token 计费 + 天眼查 API 调用计费 + 汇总。
"""

from __future__ import annotations

from byou.production.types import CostBreakdown, LatencyBreakdown

# ── LLM 价格表 (USD per 1K tokens) ─────────────────────────

LLM_PRICES = {
    "gpt-4o":           {"prompt": 0.0025, "completion": 0.010},
    "gpt-4o-mini":      {"prompt": 0.00015, "completion": 0.0006},
    "deepseek-v4-pro":  {"prompt": 0.001, "completion": 0.002},  # 阿里百炼
    "qwen3-coder-plus": {"prompt": 0.001, "completion": 0.002},
    "claude-sonnet-4-20250514": {"prompt": 0.003, "completion": 0.015},
}

# 天眼查 API 价格 (元/次)
TYC_PRICES = {
    "baseinfo":   0.20,
    "equity":     0.50,
    "court":      0.10,
    "risk":       0.10,
}

# Browser 成本估算 (USD/分钟)
BROWSER_COST_PER_MINUTE = 0.02


class CostAnalyzer:
    """成本分析器。

    Usage:
        ca = CostAnalyzer()
        ca.record_llm("gpt-4o", prompt_tokens=500, completion_tokens=200)
        ca.record_tyc("baseinfo")
        summary = ca.summary()
    """

    def __init__(self):
        self._llm_prompt_tokens = 0
        self._llm_completion_tokens = 0
        self._llm_cost_usd = 0.0
        self._llm_model = ""
        self._api_call_count = 0
        self._api_cost_yuan = 0.0
        self._browser_minutes = 0.0

    def record_llm(self, model: str, prompt_tokens: int, completion_tokens: int):
        self._llm_model = model
        self._llm_prompt_tokens += prompt_tokens
        self._llm_completion_tokens += completion_tokens
        price = LLM_PRICES.get(model, {"prompt": 0.001, "completion": 0.002})
        self._llm_cost_usd += (prompt_tokens * price["prompt"] + completion_tokens * price["completion"]) / 1000

    def record_tyc(self, api_type: str):
        self._api_call_count += 1
        self._api_cost_yuan += TYC_PRICES.get(api_type, 0.10)

    def record_browser(self, duration_s: float):
        self._browser_minutes += duration_s / 60.0

    def summary(self, latency: LatencyBreakdown | None = None) -> CostBreakdown:
        return CostBreakdown(
            llm_cost_usd=round(self._llm_cost_usd, 6),
            llm_prompt_tokens=self._llm_prompt_tokens,
            llm_completion_tokens=self._llm_completion_tokens,
            api_cost_yuan=round(self._api_cost_yuan, 4),
            api_call_count=self._api_call_count,
            browser_cost_estimate_usd=round(self._browser_minutes * BROWSER_COST_PER_MINUTE, 6),
            total_cost_usd=round(
                self._llm_cost_usd + self._api_cost_yuan * 0.14 + self._browser_minutes * BROWSER_COST_PER_MINUTE, 6,
            ),
        )

    def reset(self):
        self.__init__()
