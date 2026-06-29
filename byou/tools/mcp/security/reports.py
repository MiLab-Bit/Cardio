"""MCP Security — 审计报告生成器。

生成人类可读的审计报告，支持文本和 JSON 两种格式。
"""

from __future__ import annotations

import json
from datetime import datetime

from .types import (
    McpSecurityFinding,
    McpServerAudit,
    McpServerProfile,
    RiskLevel,
    ServerTrustRecord,
    ToolViolationEvent,
)


class AuditReporter:
    """审计报告生成器"""

    @staticmethod
    def text_report(audit: McpServerAudit) -> str:
        """生成文本格式审计报告"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"  MCP Server Onboarding Audit Report")
        lines.append(f"  Server: {audit.server_name}")
        lines.append(f"  Date: {audit.completed_at or datetime.now()}")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"  Decision: {audit.decision.value.upper()}")
        lines.append(f"  Trust Score: {audit.trust_score}/100")
        lines.append(f"  Reason: {audit.decision_reason}")
        lines.append("")

        # Findings summary
        lines.append(f"  Findings: {len(audit.findings)} total")
        lines.append(f"    HIGH/CRITICAL: {audit.high_count}")
        lines.append(f"    MEDIUM: {audit.medium_count}")
        lines.append(f"    LOW: {audit.low_count}")
        lines.append("")

        if audit.findings:
            lines.append("-" * 60)
            lines.append("  Detailed Findings:")
            lines.append("-" * 60)
            for i, f in enumerate(audit.findings, 1):
                lines.append(f"\n  [{i}] [{f.severity.value.upper()}] {f.title}")
                if f.description:
                    lines.append(f"      {f.description}")
                if f.recommendation:
                    lines.append(f"      Fix: {f.recommendation}")
                if f.file_path:
                    lines.append(f"      File: {f.file_path}")

        # Capability risks
        if audit.capability_risks:
            lines.append("")
            lines.append("-" * 60)
            lines.append("  Capability Risk Profiles:")
            lines.append("-" * 60)
            for cap, profile in audit.capability_risks.items():
                lines.append(f"  [{profile.risk_level.value.upper()}] {cap} "
                           f"(approval={profile.default_approval.value})")

        # Restrictions
        if audit.recommended_restrictions:
            lines.append("")
            lines.append("-" * 60)
            lines.append("  Recommended Restrictions:")
            lines.append("-" * 60)
            for r in audit.recommended_restrictions:
                lines.append(f"  - {r}")

        return "\n".join(lines)

    @staticmethod
    def json_report(audit: McpServerAudit) -> str:
        """生成 JSON 格式审计报告"""
        report = {
            "server_name": audit.server_name,
            "completed_at": (audit.completed_at.isoformat() if audit.completed_at else None),
            "decision": audit.decision.value,
            "trust_score": audit.trust_score,
            "decision_reason": audit.decision_reason,
            "findings_summary": {
                "total": len(audit.findings),
                "critical": sum(1 for f in audit.findings if f.severity == RiskLevel.CRITICAL),
                "high": sum(1 for f in audit.findings if f.severity == RiskLevel.HIGH),
                "medium": audit.medium_count,
                "low": audit.low_count,
            },
            "findings": [
                {
                    "id": f.finding_id,
                    "severity": f.severity.value,
                    "title": f.title,
                    "description": f.description,
                    "recommendation": f.recommendation,
                    "file_path": f.file_path,
                }
                for f in audit.findings
            ],
            "capability_risks": {
                cap: profile.model_dump()
                for cap, profile in audit.capability_risks.items()
            },
            "recommended_restrictions": audit.recommended_restrictions,
        }
        return json.dumps(report, ensure_ascii=False, indent=2)

    @staticmethod
    def violation_report(violations: list[ToolViolationEvent], limit: int = 50) -> str:
        """生成违规事件报告"""
        recent = violations[-limit:]

        by_type: dict[str, int] = {}
        by_server: dict[str, int] = {}
        for v in recent:
            vt = v.violation_type.value
            by_type[vt] = by_type.get(vt, 0) + 1
            sn = v.server_name or "unknown"
            by_server[sn] = by_server.get(sn, 0) + 1

        lines = []
        lines.append("=" * 60)
        lines.append(f"  MCP Security Violation Report")
        lines.append(f"  Total violations: {len(violations)}")
        lines.append("=" * 60)
        lines.append("")
        lines.append("  By Type:")
        for vt, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"    {vt}: {count}")
        lines.append("")
        lines.append("  By Server:")
        for sn, count in sorted(by_server.items(), key=lambda x: -x[1]):
            lines.append(f"    {sn}: {count}")
        lines.append("")

        # Top 10 近期违规
        lines.append("-" * 60)
        lines.append("  Recent Violations (top 10):")
        lines.append("-" * 60)
        for v in recent[-10:]:
            lines.append(f"  [{v.timestamp:%H:%M:%S}] [{v.severity.value}] "
                        f"{v.tool_name}: {v.description[:80]}")

        return "\n".join(lines)
