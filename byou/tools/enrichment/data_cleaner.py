"""Company Data Cleaner — normalise raw API responses to typed models.

No Pandas needed — Pydantic + regex only.  Lightweight, fast, deterministic.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Status mappings ───────────────────────────────────────────

STATUS_MAP: dict[str, str] = {
    "存续": "active",
    "在业": "active",
    "开业": "active",
    "注销": "cancelled",
    "吊销": "revoked",
    "吊销未注销": "revoked",
    "迁出": "moved",
    "停业": "suspended",
    "清算": "liquidating",
    "撤销": "revoked",
}

# 注册资本提取: "1000万人民币" → 1000.0
_CAPITAL_RE = re.compile(r"([\d,]+\.?\d*)\s*(万)?")


def parse_reg_capital(raw: str) -> float:
    """Parse registration capital string into CNY 万元."""
    if not raw or raw == "-":
        return 0.0
    m = _CAPITAL_RE.search(str(raw).replace(",", ""))
    if not m:
        return 0.0
    value = float(m.group(1))
    if m.group(2):  # already in 万元
        return value
    # Original is in 元, convert to 万元
    return value / 10000.0


def parse_date(raw: str | int) -> str | None:
    """Parse date from various formats into ISO string."""
    if not raw:
        return None
    # 2020-05-15 or 2020/05/15
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(raw)[:10], fmt).date().isoformat()
        except (ValueError, IndexError):
            continue
    # Unix timestamp (ms)
    try:
        ts = int(raw)
        return datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts).date().isoformat()
    except (ValueError, OSError):
        pass
    return None


def map_status(raw: str) -> str:
    """Map Chinese registration status to English enum."""
    for cn, en in STATUS_MAP.items():
        if cn in str(raw):
            return en
    return "unknown"


def normalize_tyc_response(raw: dict) -> dict[str, Any]:
    """Normalize a TianYanCha basic-info response into clean dict.

    Args:
        raw: Raw JSON from tianyancha ``baseinfo`` endpoint.

    Returns:
        Clean dict ready for ``CompanyIntelligence`` model creation.
    """
    result: dict[str, Any] = {}

    # Basic fields
    result["name"] = str(raw.get("name", "") or raw.get("companyName", ""))
    result["reg_number"] = str(raw.get("regNumber", "") or raw.get("creditCode", ""))
    result["legal_person"] = str(raw.get("legalPersonName", "") or raw.get("legalPerson", ""))

    # Capital: normalise to 万元 float
    cap_raw = str(raw.get("regCapital", "") or raw.get("registeredCapital", ""))
    result["reg_capital_wan"] = parse_reg_capital(cap_raw)

    # Date
    result["establish_date"] = parse_date(
        raw.get("estiblishTime") or raw.get("establishTime") or raw.get("fromTime", "")
    )

    # Status
    result["status"] = map_status(raw.get("registStatus", "") or raw.get("regStatus", ""))

    # Address
    result["address"] = str(raw.get("address", "") or raw.get("regLocation", ""))

    # Scope
    result["business_scope"] = str(raw.get("businessScope", "") or raw.get("scope", ""))

    # Industry
    result["industry"] = str(raw.get("industry", "") or raw.get("industryName", ""))

    # Registered capital currency
    result["reg_capital_currency"] = str(raw.get("regCapitalCurrency", "") or "CNY")

    # Raw (for debugging)
    result["_raw"] = raw

    return result
