"""Agent configs — declarative definition of all Byou agents.

Each agent is a plain dict with name, description, temperature, system prompt,
and a prompt-builder function.  The shared :class:`Agent` class in `base.py`
wires everything together — no more per-agent subclass boilerplate.
"""

from __future__ import annotations

import json
from typing import Any, Callable

# ── Shared defaults helpers ────────────────────────────────────

def _apply_defaults(result: dict, defaults: dict) -> None:
    for key, default in defaults.items():
        if key not in result:
            result[key] = default


# ── Prompt builders (the only per-agent customisation) ─────────

def _prompt_extractor(input_data: dict) -> str:
    card_text = input_data.get("_card_text", "")
    audio_text = input_data.get("_audio_text", "")
    raw_text = input_data.get("raw_text", "")
    combined = "\n\n".join(t for t in [card_text, audio_text, raw_text] if t)
    return f"Extract structured customer info from:\n\n{combined}"


def _prompt_researcher(input_data: dict) -> str:
    profile: dict = input_data.get("profile", {})
    company = input_data.get("company_name", "") or profile.get("company", "")
    person = input_data.get("person_name", "") or profile.get("name", "")
    queries = _build_queries(company, person, profile)
    return (
        f"Research this target:\n\n"
        f"Company: {company or 'unknown'}\n"
        f"Person: {person or 'unknown'}\n"
        f"Known info: {json.dumps(profile, ensure_ascii=False)}\n\n"
        f"Key questions:\n" + "\n".join(f"- {q}" for q in queries)
    )


def _build_queries(company: str, person: str, profile: dict) -> list[str]:
    q: list[str] = []
    if company:
        q += [f"{company} — scale, funding, business model",
              f"{company} — market position & competitors",
              f"{company} — recent news / developments"]
    if person:
        q += [f"{person} — career & expertise",
              f"{person} — industry influence"]
    return q or ["Infer profile from available info"]


def _prompt_synthesizer(input_data: dict) -> str:
    profile = input_data.get("profile", {})
    research = input_data.get("research", {})
    raw_text = input_data.get("raw_text", "")
    return (
        "## Customer Information\n"
        f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
        "## Background Research\n"
        f"{json.dumps(research, ensure_ascii=False, indent=2)}\n\n"
        "## Raw Interaction\n"
        f"{raw_text[:2000]}\n\n"
        "Synthesize a complete customer profile with scoring."
    )


def _prompt_strategist(input_data: dict) -> str:
    profile = input_data.get("profile", {})
    synthesis = input_data.get("synthesis", {})
    customer_level = input_data.get("customer_level", "C")
    return (
        "## Customer Profile\n"
        f"{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
        "## Analysis\n"
        f"{json.dumps(synthesis, ensure_ascii=False, indent=2)}\n\n"
        f"Customer level: {customer_level}\n"
        "Produce a concrete, actionable BD strategy."
    )


def _safe_json_dumps(obj):
    """JSON serialize with datetime support."""
    def default(o):
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        raise TypeError(f'Object of type {type(o).__name__} is not JSON serializable')
    return json.dumps(obj, ensure_ascii=False, indent=2, default=default)


def _prompt_critic(input_data: dict) -> str:
    profile = input_data.get("profile", {})
    research = input_data.get("research", {})
    synthesis = input_data.get("synthesis", {})
    strategy = input_data.get("strategy", {})
    return (
        "### Extracted Info\n"
        f"{_safe_json_dumps(profile)}\n\n"
        "### Research\n"
        f"{_safe_json_dumps(research)}\n\n"
        "### Synthesis\n"
        f"{_safe_json_dumps(synthesis)}\n\n"
        "### Strategy\n"
        f"{_safe_json_dumps(strategy)}\n\n"
        "Perform a comprehensive quality audit."
    )


# ── Post-processing hooks (optional per-agent transformations) ─

def _postprocess_extractor(parsed: dict, _input: dict) -> dict:
    card_text = _input.get("_card_text", "")
    audio_text = _input.get("_audio_text", "")
    raw_text = _input.get("raw_text", "")
    parsed["raw_text"] = "\n\n".join(t for t in [card_text, audio_text, raw_text] if t)
    return parsed


def _postprocess_researcher(parsed: dict, input_data: dict) -> dict:
    profile = input_data.get("profile", {})
    company = input_data.get("company_name", "") or profile.get("company", "")
    person = input_data.get("person_name", "") or profile.get("name", "")
    parsed["_queries"] = _build_queries(company, person, profile)
    return parsed


def _postprocess_synthesizer(parsed: dict, _input: dict) -> dict:
    _apply_defaults(parsed, {
        "customer_level": "C", "intent_score": 0.5,
        "customer_value_score": 0.5, "key_needs": [],
        "buying_signals": [], "summary": "",
    })
    return parsed


def _postprocess_strategist(parsed: dict, input_data: dict) -> dict:
    customer_level = input_data.get("customer_level", "C")
    priority_map = {"A": "high", "B": "medium", "C": "low", "D": "low"}
    default_priority = priority_map.get(customer_level, "medium")
    if not parsed.get("follow_up_plan"):
        parsed["follow_up_plan"] = {
            "timing": "this week", "channel": "phone",
            "approach": "initial outreach, establish relationship",
            "priority": default_priority,
        }
    parsed.setdefault("talking_points", [])
    parsed.setdefault("recommended_actions", [])
    return {"strategy": parsed}


def _postprocess_critic(parsed: dict, _input: dict) -> dict:
    if "passed" not in parsed:
        parsed["passed"] = parsed.get("trust_score", 0.5) >= 0.4
    parsed.setdefault("risk_alerts", [])
    parsed.setdefault("overall_assessment", "")
    return parsed


# ── Master config ──────────────────────────────────────────────

AgentConfig = dict[str, Any]

AGENT_CONFIGS: dict[str, AgentConfig] = {
    "extractor": {
        "description": "Extract structured customer info from cards and audio",
        "temperature": 0.7,
        "preferred_tier": "cheap",  # 结构化提取，轻量任务
        "system_prompt": """You are a professional information extraction agent.

Extract key customer details from business card text or meeting transcripts.

Output valid JSON:
{
  "profile": {
    "name": "", "title": "", "company": "", "department": "",
    "phone": "", "email": "", "wechat": "", "address": "",
    "industry": "", "company_size": "", "company_description": "",
    "personal_summary": ""
  },
  "raw_text": "",
  "key_points": [],
  "confidence": 0.0
}
Rules: extract only what is present; leave missing fields empty; normalise phone/email.""",
        "build_prompt": _prompt_extractor,
        "postprocess": _postprocess_extractor,
        "default_result": {"profile": {}, "raw_text": "", "key_points": [], "confidence": 0.0},
    },
    "researcher": {
        "description": "Deep background research on companies/people/industries",
        "temperature": 0.5,
        "preferred_tier": "medium",  # 需要理解+综合
        "system_prompt": """You are a business research analyst.

Research the given company and person, output valid JSON:
{
  "company_info": {
    "full_name": "", "founded": "", "headquarters": "",
    "employee_count": "", "revenue_range": "", "funding_stage": "",
    "key_products": [], "website": "", "social_media": {}
  },
  "industry_analysis": "",
  "person_background": {
    "education": "", "career_history": [], "expertise": [], "social_presence": ""
  },
  "news_mentions": [],
  "competitors": [],
  "market_position": "",
  "relevance_score": 0.0
}
Mark uncertain info explicitly. relevance_score 0-1 for BD fit.""",
        "build_prompt": _prompt_researcher,
        "postprocess": _postprocess_researcher,
        "default_result": {
            "company_info": {}, "industry_analysis": "",
            "person_background": {}, "news_mentions": [],
            "competitors": [], "market_position": "unknown", "relevance_score": 0.0,
        },
    },
    "synthesizer": {
        "description": "Synthesize customer profile, intent scoring, needs analysis",
        "temperature": 0.5,
        "preferred_tier": "medium",  # 需要分析能力
        "system_prompt": """You are a customer profile analyst.

Synthesize extraction + research into a complete customer picture in JSON:
{
  "enriched_profile": { /* supplement missing fields from original profile */ },
  "customer_level": "A|B|C|D",
  "intent_score": 0.0,
  "customer_value_score": 0.0,
  "key_needs": [],
  "buying_signals": [],
  "decision_makers": [],
  "budget_indication": "",
  "timeline": "",
  "competitor_relationship": "",
  "recommended_approach": "",
  "risk_factors": [],
  "summary": ""
}

Grading:
- A: high intent + high value, follow up within 1 week
- B: medium intent/value, follow up within 2 weeks
- C: low intent or value, quarterly
- D: no near-term opportunity, monitor""",
        "build_prompt": _prompt_synthesizer,
        "postprocess": _postprocess_synthesizer,
        "default_result": {
            "customer_level": "C", "intent_score": 0.5,
            "customer_value_score": 0.5, "key_needs": [],
            "buying_signals": [], "summary": "",
            "enriched_profile": {},
        },
    },
    "strategist": {
        "description": "Generate BD strategy: talking points, follow-up plan, risk assessment",
        "temperature": 0.8,
        "preferred_tier": "deep",  # 复杂商业策略思考
        "system_prompt": """You are a senior BD strategist.

Generate a personalised BD strategy in JSON:
{
  "customer_analysis": "",
  "pain_points": [],
  "opportunities": [],
  "talking_points": [{"angle": "", "script": "", "key_message": ""}],
  "objection_handling": {},
  "follow_up_plan": {"timing": "", "channel": "phone", "approach": "", "priority": "medium"},
  "risks": [{"type": "", "description": "", "severity": "medium", "mitigation": ""}],
  "competition_analysis": "",
  "recommended_actions": [],
  "confidence_level": 0.7
}

Principles: scripts must be actionable; risks must be honest; lead with customer pain points, not product features.""",
        "build_prompt": _prompt_strategist,
        "postprocess": _postprocess_strategist,
        "default_result": {
            "strategy": {
                "customer_analysis": "", "pain_points": [],
                "recommended_actions": [], "confidence_level": 0.0,
            },
            "error": "Strategist failed",
        },
    },
    "critic": {
        "description": "Quality audit: accuracy, consistency, feasibility",
        "temperature": 0.3,
        "preferred_tier": "deep",  # 仔细质量评估
        "system_prompt": """You are a strict quality auditor.

Audit all pipeline outputs and produce JSON:
{
  "passed": true,
  "trust_score": 0.0,
  "extraction_quality": {"score": 0.0, "issues": [], "missing_fields": []},
  "research_reliability": {"score": 0.0, "uncertain_points": [], "bias_concerns": []},
  "profile_consistency": {"score": 0.0, "contradictions": [], "overconfidence_flags": []},
  "strategy_feasibility": {"score": 0.0, "impractical_suggestions": []},
  "risk_alerts": [{"type": "", "description": "", "severity": "medium", "recommendation": ""}],
  "corrections": [],
  "overall_assessment": ""
}

If trust_score < 0.4, passed must be false. Be honest about risks.""",
        "build_prompt": _prompt_critic,
        "postprocess": _postprocess_critic,
        "default_result": {
            "passed": False, "trust_score": 0.0,
            "risk_alerts": [{"type": "system_error", "description": "Critic failed",
                             "severity": "high", "recommendation": "manual review"}],
            "overall_assessment": "Audit process errored",
        },
    },
}
