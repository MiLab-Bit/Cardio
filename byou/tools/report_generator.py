"""HTML 背调报告生成器 — 黑客松演示必备。

输入: CompanyIntelligence (Pydantic model)
输出: 自包含 HTML 文件 (inline CSS, 无需外部依赖)

特性:
- 风险仪表盘 (visual risk meter)
- 公司关键信息卡片
- 诉讼/风险信号高亮
- 新闻摘要时间线
- 打印友好 (@media print)
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from byou.models.company_intelligence import CompanyIntelligence


# ─────────────────────────────────────────────────────────────────────────────
#  Color tokens
# ─────────────────────────────────────────────────────────────────────────────

COLORS = {
    "primary": "#4F46E5",    # indigo-600
    "primary_light": "#818CF8",  # indigo-400
    "risk_high": "#EF4444",    # red-500
    "risk_mid": "#F59E0B",    # amber-500
    "risk_low": "#22C55E",     # green-500
    "bg": "#F8FAFC",          # slate-50
    "card": "#FFFFFF",
    "text": "#1E293B",        # slate-800
    "text_muted": "#64748B",  # slate-500
    "border": "#E2E8F0",     # slate-200
}


def _risk_color(score: float) -> str:
    if score >= 0.6:
        return COLORS["risk_high"]
    if score >= 0.3:
        return COLORS["risk_mid"]
    return COLORS["risk_low"]


def _risk_label(score: float) -> str:
    if score >= 0.7:
        return "高风险"
    if score >= 0.4:
        return "中等风险"
    if score >= 0.2:
        return "低风险"
    return "暂无风险信号"


# ─────────────────────────────────────────────────────────────────────────────
#  HTML Template
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>企业背调报告 — {company_name}</title>
<style>
  {css}
</style>
</head>
<body>
<div class="report">
  {header}
  {risk_dashboard}
  {company_info}
  {court_section}
  {news_section}
  {competitors_section}
  {footer}
</div>
</body>
</html>"""


CSS = """
/* ── Reset & Base ──────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: #F1F5F9;
  color: #1E293B;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
.report {
  max-width: 960px;
  margin: 24px auto;
  padding: 0 16px 48px;
}

/* ── Header ─────────────────────────────────── */
.header {
  background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
  color: white;
  border-radius: 16px;
  padding: 32px 36px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
}
.header::before {
  content: "";
  position: absolute;
  top: -40px; right: -40px;
  width: 200px; height: 200px;
  background: rgba(255,255,255,0.08);
  border-radius: 50%;
}
.header h1 {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 4px;
  position: relative;
}
.header .meta {
  font-size: 13px;
  opacity: 0.8;
  position: relative;
}
.header .badge {
  display: inline-block;
  background: rgba(255,255,255,0.2);
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 12px;
  margin-left: 12px;
  vertical-align: middle;
}

/* ── Card ───────────────────────────────────── */
.card {
  background: white;
  border-radius: 12px;
  padding: 24px 28px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  border: 1px solid #E2E8F0;
}
.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #4F46E5;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-title .icon {
  width: 28px; height: 28px;
  background: #EEF2FF;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
}

/* ── Risk Dashboard ──────────────────────────── */
.risk-dashboard {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 20px;
  align-items: center;
}
.risk-meter {
  text-align: center;
}
.risk-meter .score {
  font-size: 48px;
  font-weight: 800;
  line-height: 1;
}
.risk-meter .label {
  font-size: 13px;
  font-weight: 500;
  margin-top: 4px;
}
.risk-bar-track {
  height: 8px;
  background: #E2E8F0;
  border-radius: 4px;
  overflow: hidden;
  margin: 12px 0 8px;
}
.risk-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.6s ease;
}
.risk-flags {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.risk-flag {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #FEF2F2;
  color: #991B1B;
}
.risk-flag.ok {
  background: #F0FDF4;
  color: #166534;
}
.flag-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* ── Info Grid ────────────────────────────────── */
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.info-item {
  padding: 12px 16px;
  background: #F8FAFC;
  border-radius: 8px;
  border: 1px solid #E2E8F0;
}
.info-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748B;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
}
.info-value {
  font-size: 14px;
  font-weight: 500;
  color: #1E293B;
  word-break: break-all;
}

/* ── Court Table ────────────────────────────── */
.court-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.court-table th {
  text-align: left;
  padding: 10px 12px;
  background: #F8FAFC;
  color: #64748B;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid #E2E8F0;
}
.court-table td {
  padding: 10px 12px;
  border-bottom: 1px solid #F1F5F9;
  vertical-align: top;
}
.court-table tr:last-child td { border-bottom: none; }
.severity-high { color: #EF4444; font-weight: 600; }
.severity-mid { color: #F59E0B; font-weight: 500; }

/* ── News Timeline ───────────────────────────── */
.news-timeline {
  position: relative;
  padding-left: 20px;
}
.news-timeline::before {
  content: "";
  position: absolute;
  left: 5px; top: 0; bottom: 0;
  width: 2px;
  background: #E2E8F0;
}
.news-item {
  position: relative;
  padding: 12px 0 12px 16px;
}
.news-item::before {
  content: "";
  position: absolute;
  left: -20px; top: 18px;
  width: 10px; height: 10px;
  background: #4F46E5;
  border: 2px solid white;
  border-radius: 50%;
  box-shadow: 0 0 0 2px #4F46E5;
}
.news-title {
  font-size: 14px;
  font-weight: 500;
  color: #1E293B;
  margin-bottom: 4px;
}
.news-snippet {
  font-size: 13px;
  color: #64748B;
  line-height: 1.5;
}
.news-source {
  font-size: 11px;
  color: #94A3B8;
  margin-top: 4px;
}

/* ── Tags ────────────────────────────────────── */
.tag {
  display: inline-block;
  padding: 3px 10px;
  background: #EEF2FF;
  color: #4F46E5;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  margin: 3px 3px 3px 0;
}

/* ── Footer ──────────────────────────────────── */
.footer {
  text-align: center;
  font-size: 12px;
  color: #94A3B8;
  padding: 24px 0 0;
  border-top: 1px solid #E2E8F0;
  margin-top: 8px;
}

/* ── Print ───────────────────────────────────── */
@media print {
  body { background: white; }
  .report { margin: 0; padding: 0; }
  .header { border-radius: 0; }
}
"""

# ─────────────────────────────────────────────────────────────────────────────
#  Section renderers
# ─────────────────────────────────────────────────────────────────────────────


def _render_header(ci: CompanyIntelligence) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    source_labels = {
        "tianyancha": "天眼查",
        "llm": "AI 推断",
        "enrichment_l4": "多源增强",
        "tavily": "Tavily 搜索",
        "wikipedia": "Wikipedia",
    }
    src = ci.source or "unknown"
    src_label = source_labels.get(src.split("+")[0], src)
    quality_badge = ""
    if ci.data_quality == "high":
        quality_badge = '<span class="badge">✓ 高可信度</span>'
    elif ci.data_quality == "medium":
        quality_badge = '<span class="badge">数据待补充</span>'

    return f"""
  <div class="header">
    <h1>{html.escape(ci.company_name)}</h1>
    <div class="meta">
      背调报告 · 生成时间 {now} · 数据源 {html.escape(src_label)}
      {quality_badge}
    </div>
  </div>"""


def _render_risk_dashboard(ci: CompanyIntelligence) -> str:
    score = ci.risk_score
    color = _risk_color(score)
    label = _risk_label(score)
    pct = int(score * 100)

    # Risk flags
    flags = []
    if ci.court_cases:
        flags.append(
            f'<div class="risk-flag">'
            f'<span class="flag-dot" style="background:{COLORS["risk_high"]}"></span>'
            f'{len(ci.court_cases)} 条诉讼记录'
            f'</div>'
        )
    else:
        flags.append(
            f'<div class="risk-flag ok">'
            f'<span class="flag-dot" style="background:{COLORS["risk_low"]}"></span>'
            f'未发现诉讼记录'
            f'</div>'
        )
    if ci.abnormal_count and ci.abnormal_count > 0:
        flags.append(
            f'<div class="risk-flag">'
            f'<span class="flag-dot" style="background:{COLORS["risk_high"]}"></span>'
            f'{ci.abnormal_count} 条经营异常'
            f'</div>'
        )
    if ci.equity_holders:
        flags.append(
            f'<div class="risk-flag ok">'
            f'<span class="flag-dot" style="background:{COLORS["risk_low"]}"></span>'
            f'股东信息完整 ({len(ci.equity_holders)} 位股东)'
            f'</div>'
        )
    flags_html = "\n        ".join(flags)

    return f"""
  <div class="card">
    <div class="card-title"><span class="icon">⚠</span> 风险评估</div>
    <div class="risk-dashboard">
      <div class="risk-meter">
        <div class="score" style="color:{color}">{pct}</div>
        <div class="label" style="color:{color}">{label}</div>
      </div>
      <div>
        <div class="risk-bar-track">
          <div class="risk-bar-fill" style="width:{pct}%;background:{color}"></div>
        </div>
        <div class="risk-flags">
          {flags_html}
        </div>
      </div>
    </div>
  </div>"""


def _render_company_info(ci: CompanyIntelligence) -> str:
    info = ci.company_info
    if not info:
        return ""

    fields: list[tuple[str, str]] = [
        ("公司全称", getattr(info, 'name', '') or ""),
        ("注册号", getattr(info, 'reg_number', '') or ""),
        ("法定代表人", getattr(info, 'legal_person', '') or ""),
        ("成立日期", str(getattr(info, 'establish_date', None) or "")),
        ("经营状态", getattr(info, 'status', '') or ""),
        ("注册资本(万元)", str(getattr(info, 'reg_capital_wan', 0) or "")),
        ("行业", getattr(info, 'industry', '') or ""),
        ("地址", getattr(info, 'address', '') or ""),
    ]
    # Filter out empty
    fields = [(l, v) for l, v in fields if v and str(v).strip()]

    items = "\n        ".join(
        f'<div class="info-item">'
        f'<div class="info-label">{html.escape(l)}</div>'
        f'<div class="info-value">{html.escape(str(v))}</div>'
        f'</div>'
        for l, v in fields
    )

    # Business scope
    scope = ""
    biz = getattr(info, 'business_scope', '') or ''
    if biz:
        scope = (
            f'<div style="margin-top:16px;padding:12px 16px;background:#F8FAFC;'
            f'border-radius:8px;border:1px solid #E2E8F0;">'
            f'<div class="info-label">经营范围</div>'
            f'<div style="font-size:13px;color:#334155;margin-top:4px;">'
            f'{html.escape(info.business_scope[:300])}'
            f'</div></div>'
        )

    return f"""
  <div class="card">
    <div class="card-title"><span class="icon">🏢</span> 公司信息</div>
    <div class="info-grid">
      {items}
    </div>
    {scope}
  </div>"""


def _render_court(ci: CompanyIntelligence) -> str:
    cases = ci.court_cases
    if not cases:
        return ""

    rows = ""
    for c in cases[:10]:
        severity = "severity-high" if (c.amount_yuan or 0) > 100000 else "severity-mid"
        amount = f"¥{c.amount_yuan:,.0f}" if c.amount_yuan else "—"
        rows += (
            f"<tr>"
            f"<td><span class='{severity}'>{html.escape(c.case_no or '—')}</span></td>"
            f"<td>{html.escape(c.case_type or '—')}</td>"
            f"<td>{html.escape(c.plaintiff or '—')}</td>"
            f"<td>{html.escape(c.defendant or '—')}</td>"
            f"<td style='text-align:right;font-weight:600;'>{amount}</td>"
            f"</tr>"
        )

    return f"""
  <div class="card">
    <div class="card-title"><span class="icon">⚖</span> 诉讼记录 ({len(cases)} 条)</div>
    <div style="overflow-x:auto;">
      <table class="court-table">
        <thead>
          <tr>
            <th>案号</th><th>类型</th><th>原告</th><th>被告</th><th style="text-align:right">金额</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>"""


def _render_news(ci: CompanyIntelligence) -> str:
    news = ci.news_mentions
    if not news:
        return ""

    items = ""
    for n in news[:8]:
        title = n.get("title") or n.get("headline") or "相关报道"
        snippet = n.get("snippet") or n.get("content") or ""
        url = n.get("url") or n.get("link") or "#"
        source = n.get("source") or ""
        items += (
            f'<div class="news-item">'
            f'<div class="news-title"><a href="{html.escape(url)}" target="_blank" '
            f'style="color:inherit;text-decoration:none;">{html.escape(title)}</a></div>'
            f'<div class="news-snippet">{html.escape(snippet[:150])}</div>'
            f'<div class="news-source">{html.escape(source)}</div>'
            f'</div>'
        )

    return f"""
  <div class="card">
    <div class="card-title"><span class="icon">📰</span> 相关新闻</div>
    <div class="news-timeline">
      {items}
    </div>
  </div>"""


def _render_competitors(ci: CompanyIntelligence) -> str:
    comps = ci.competitors
    if not comps:
        return ""

    tags = " ".join(
        f'<span class="tag">{html.escape(c if isinstance(c, str) else str(c))}</span>'
        for c in comps
    )

    market = ci.market_position or ""

    return f"""
  <div class="card">
    <div class="card-title"><span class="icon">📊</span> 市场分析</div>
    {"<p style=\"font-size:14px;color:#334155;margin-bottom:12px;\">" + html.escape(market) + "</p>" if market else ""}
    <div>
      <div style="font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">竞品</div>
      {tags}
    </div>
  </div>"""


def _render_footer(ci: CompanyIntelligence) -> str:
    return (
        f'<div class="footer">'
        f'Byou BD Multi-Agent System · {datetime.now().strftime("%Y-%m-%d")}'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_html_report(ci: CompanyIntelligence) -> str:
    """Generate a self-contained HTML report from CompanyIntelligence."""
    return HTML_TEMPLATE.format(
        company_name=html.escape(ci.company_name),
        css=CSS,
        header=_render_header(ci),
        risk_dashboard=_render_risk_dashboard(ci),
        company_info=_render_company_info(ci),
        court_section=_render_court(ci),
        news_section=_render_news(ci),
        competitors_section=_render_competitors(ci),
        footer=_render_footer(ci),
    )


def save_html_report(ci: CompanyIntelligence, output_path: str) -> str:
    """Save HTML report to file, return the path."""
    content = generate_html_report(ci)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def generate_html_report_from_dict(data: dict[str, Any]) -> str:
    """Convenience: accept dict (from agent output), return HTML string."""
    try:
        ci = CompanyIntelligence.model_validate(data)
    except Exception:
        # Partial — build minimal CI
        ci = CompanyIntelligence(
            company_name=data.get("company_name", "未知公司"),
            company_info=data.get("company_info", {}),
            source=data.get("source", "unknown"),
            risk_score=data.get("risk_score", 0.0),
        )
    return generate_html_report(ci)
