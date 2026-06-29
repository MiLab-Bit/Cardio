"""MCP Security — Onboarding 审计引擎。

新 MCP Server 接入前的安全审计流程:
1. 收集 server metadata → McpServerProfile
2. 安全扫描 (依赖/secret/配置) → McpSecurityFinding
3. capability 风险评估 → CapabilityRiskProfile
4. trust score 计算 → 0-100
5. 最终决策: allow / conditional / quarantine / deny

参考:
  - mcpserver-audit: server 接入前审计
  - mcpscan: semgrep + npm/pip audit 组合扫描
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from .types import (
    ApprovalRequirement,
    AuditStatus,
    CapabilityRiskProfile,
    McpSecurityFinding,
    McpServerAudit,
    McpServerProfile,
    RiskLevel,
    ServerTrustRecord,
    TrustLevel,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 默认 risk profile 映射
# ─────────────────────────────────────────────────────────────

DEFAULT_RISK_MAP: dict[str, CapabilityRiskProfile] = CapabilityRiskProfile.default_risk_map()


class ServerAuditor:
    """MCP Server onboarding 审计器。

    Usage:
        auditor = ServerAuditor()
        profile = auditor.build_profile(
            server_name="tianyancha",
            repo_url="https://...",
            entrypoint_url="https://open.tianyancha.com",
        )
        audit = await auditor.audit(profile)
        if audit.is_approved:
            reg.register_server(profile)  # 注册到 Tool Bus
    """

    def __init__(self, *, risk_map: dict[str, CapabilityRiskProfile] | None = None):
        self.risk_map = risk_map or DEFAULT_RISK_MAP

    # ── Server Profile 构建 ──────────────────────

    def build_profile(
        self,
        *,
        server_name: str,
        display_name: str = "",
        description: str = "",
        repo_url: str = "",
        entrypoint_url: str = "",
        maintainer: str = "",
        version: str = "",
        network_scope: list[str] | None = None,
        data_scope: list[str] | None = None,
        capabilities: list[str] | None = None,
        readonly: bool = False,
    ) -> McpServerProfile:
        """从参数构建 server 安全档案。

        实际接入时这些信息可以从 MCP server 的 metadata endpoint 获取，
        或由管理员手动填写。
        """
        cap_list = list(set(capabilities or []))
        # 派生风险等级 (取所有 cap 中最高)
        risk_level = self._derive_risk_level(cap_list)

        return McpServerProfile(
            server_name=server_name,
            display_name=display_name or server_name,
            description=description,
            repo_url=repo_url,
            entrypoint_url=entrypoint_url,
            maintainer=maintainer,
            version=version or "0.0.0",
            network_scope=network_scope or [],
            data_scope=data_scope or [],
            readonly=readonly,
            trust_level=TrustLevel.UNTRUSTED,
            risk_level=risk_level,
            allowed_capabilities=cap_list,
        )

    # ── 审计主流程 ───────────────────────────────

    async def audit(self, profile: McpServerProfile) -> McpServerAudit:
        """执行完整的 onboarding 审计。

        审计流程:
        1. Metadata 校验
        2. Dependency 安全扫描 (如果提供 repo)
        3. Secret leak 检测
        4. Capability 风险分级
        5. Trust score 计算
        6. 最终决策
        """
        audit = McpServerAudit(
            server_name=profile.server_name,
            server_profile=profile,
            started_at=datetime.now(),
        )

        # Phase 1: Metadata 校验
        findings = []
        findings += self._validate_metadata(profile)

        # Phase 2: Dependency 扫描 (模拟)
        if profile.repo_url:
            findings += await self._scan_dependencies(profile)

        # Phase 3: Secret leak 检测
        findings += self._scan_secrets(profile)

        # Phase 4: Capability 风险分级
        cap_risks = self._assess_capability_risks(profile)
        audit.capability_risks = cap_risks

        # Phase 5: Trust score
        trust_score = self._calculate_trust_score(findings, profile)
        audit.trust_score = trust_score

        # Phase 6: 最终决策
        decision, reason, restrictions = self._make_decision(findings, trust_score, profile)
        audit.decision = decision
        audit.decision_reason = reason
        audit.recommended_restrictions = restrictions

        # 统计
        audit.findings = findings
        audit.high_count = sum(1 for f in findings if f.severity in (RiskLevel.CRITICAL, RiskLevel.HIGH))
        audit.medium_count = sum(1 for f in findings if f.severity == RiskLevel.MEDIUM)
        audit.low_count = sum(1 for f in findings if f.severity == RiskLevel.LOW)

        audit.completed_at = datetime.now()

        logger.info(
            "Audit complete: server=%s decision=%s score=%d findings=%d (H:%d M:%d L:%d)",
            profile.server_name, audit.decision, audit.trust_score,
            len(findings), audit.high_count, audit.medium_count, audit.low_count,
        )
        return audit

    # ── Phase 1: Metadata ─────────────────────────

    def _validate_metadata(self, profile: McpServerProfile) -> list[McpSecurityFinding]:
        findings: list[McpSecurityFinding] = []
        fid = f"{profile.server_name}-meta-"

        if not profile.maintainer:
            findings.append(McpSecurityFinding(
                finding_id=fid + "001",
                server_name=profile.server_name,
                scanner="metadata",
                title="缺少维护者信息",
                description="Server 未声明显式维护者，无法追溯责任",
                severity=RiskLevel.MEDIUM,
                category="metadata",
                recommendation="在 server 配置中填写 maintainer 字段",
            ))

        if not profile.repo_url and not profile.entrypoint_url.startswith(("embed", "internal")):
            findings.append(McpSecurityFinding(
                finding_id=fid + "002",
                server_name=profile.server_name,
                scanner="metadata",
                title="缺少代码仓库链接",
                description="无法审计 server 源代码安全",
                severity=RiskLevel.MEDIUM,
                category="metadata",
                recommendation="填入 repo_url 或标记为 internal",
            ))

        if profile.risk_level >= RiskLevel.HIGH and not profile.readonly:
            findings.append(McpSecurityFinding(
                finding_id=fid + "003",
                server_name=profile.server_name,
                scanner="metadata",
                title="高风险 Server 具有写权限",
                severity=RiskLevel.HIGH,
                category="capability",
                recommendation=f"限制 {profile.server_name} 为只读模式, 或要求严格审批",
            ))

        # Network scope 检查
        if profile.risk_level >= RiskLevel.HIGH and not profile.network_scope:
            findings.append(McpSecurityFinding(
                finding_id=fid + "004",
                server_name=profile.server_name,
                scanner="metadata",
                title="高风险 Server 无网络范围限制",
                severity=RiskLevel.HIGH,
                category="network",
                recommendation=f"为 {profile.server_name} 设置 network_scope 限制允许访问的域名/IP",
            ))

        return findings

    # ── Phase 2: Dependency ───────────────────────

    async def _scan_dependencies(self, profile: McpServerProfile) -> list[McpSecurityFinding]:
        """Dependency 安全扫描。

        生产环境应集成:
         - pip-audit / pip list --outdated
         - semgrep rules
         - OWASP Dependency Check

        当前为骨架实现: 检查组件的版本标识。
        """
        findings: list[McpSecurityFinding] = []
        fid = f"{profile.server_name}-dep-"

        # 骨架: 只有 repo_url 时记录，实际扫描需要 CI runner
        findings.append(McpSecurityFinding(
            finding_id=fid + "001",
            server_name=profile.server_name,
            scanner="dependency_check",
            title="依赖扫描待执行",
            description=f"Server {profile.server_name} 的代码仓库已登记, 建议在 CI 中运行 pip-audit / semgrep",
            severity=RiskLevel.LOW,
            category="dependency",
            recommendation="在 CI pipeline 中添加 pip-audit 扫描步骤",
        ))

        return findings

    # ── Phase 3: Secret Leak ──────────────────────

    def _scan_secrets(self, profile: McpServerProfile) -> list[McpSecurityFinding]:
        """Secret 泄露检测。

        检测 server 配置中是否存在硬编码的 token/API Key。
        """
        findings: list[McpSecurityFinding] = []
        fid = f"{profile.server_name}-secret-"

        # Check: entrypoint URL has token embedded
        url = profile.entrypoint_url
        if url:
            secrets = re.findall(r'[?&](token|api_key|api-key|key|secret|password)=([^&\s]+)', url, re.IGNORECASE)
            if secrets:
                for param, value in secrets:
                    findings.append(McpSecurityFinding(
                        finding_id=fid + "001",
                        server_name=profile.server_name,
                        scanner="secret_scan",
                        title=f"URL 中嵌入了疑似密钥: {param}",
                        description=f"entrypoint_url 查询参数中包含 {param}",
                        severity=RiskLevel.CRITICAL,
                        category="secret_leak",
                        evidence=f"...{param}={value[:6]}...",
                        recommendation=f"将 {param} 移至环境变量或 secret manager",
                    ))

        return findings

    # ── Phase 4: Capability 风险分级 ──────────────

    def _assess_capability_risks(
        self,
        profile: McpServerProfile,
    ) -> dict[str, CapabilityRiskProfile]:
        """为 server 的每个 capability 分配风险档案。"""
        result: dict[str, CapabilityRiskProfile] = {}
        for cap in profile.allowed_capabilities:
            # 查映射表, 未在表中 → 默认 MEDIUM
            existing = self.risk_map.get(cap)
            if existing:
                result[cap] = existing
            else:
                result[cap] = CapabilityRiskProfile(
                    capability=cap,
                    risk_level=RiskLevel.MEDIUM,
                    default_approval=ApprovalRequirement.LOG_ONLY,
                )
        return result

    # ── Phase 5: Trust Score ──────────────────────

    def _calculate_trust_score(
        self,
        findings: list[McpSecurityFinding],
        profile: McpServerProfile,
    ) -> int:
        """计算信任评分 (0-100)。

        扣分规则:
          - CRITICAL finding: -30
          - HIGH finding: -15
          - MEDIUM finding: -5
          - LOW finding: -2
          - 无 maintainer: -10
          - 无 repo: -10
        """
        score = 80  # 基准分

        # 扣除 findings
        for f in findings:
            if f.severity == RiskLevel.CRITICAL:
                score -= 30
            elif f.severity == RiskLevel.HIGH:
                score -= 15
            elif f.severity == RiskLevel.MEDIUM:
                score -= 5
            elif f.severity == RiskLevel.LOW:
                score -= 2

        # metadata 加分/扣分
        if profile.maintainer:
            score += 5
        if profile.repo_url:
            score += 5
        if profile.readonly:
            score += 5
        if profile.network_scope:
            score += 5

        return max(0, min(100, score))

    # ── Phase 6: Decision ─────────────────────────

    def _make_decision(
        self,
        findings: list[McpSecurityFinding],
        trust_score: int,
        profile: McpServerProfile,
    ) -> tuple[AuditStatus, str, list[str]]:
        """根据 findings + trust_score 做出接入决策。

        Rules:
        - CRITICAL finding → FAILED
        - trust_score >= 80 → PASSED
        - trust_score >= 50 → CONDITIONAL (有限制接入)
        - trust_score < 50 → FAILED
        """
        restrictions: list[str] = []
        has_critical = any(f.severity == RiskLevel.CRITICAL for f in findings)

        if has_critical:
            return (
                AuditStatus.FAILED,
                "存在 CRITICAL 级别安全发现",
                ["修复所有 CRITICAL findings 后重新审计"],
            )

        if trust_score >= 80:
            return AuditStatus.PASSED, f"审计通过 (trust={trust_score})", []

        if trust_score >= 50:
            restrictions = ["仅允许只读 capability", "限制调用频率 50%", "不在 untrusted context 中执行"]
            if profile.risk_level >= RiskLevel.HIGH:
                restrictions.append("高风险工具需人工审批")
            return (
                AuditStatus.CONDITIONAL,
                f"有条件通过 (trust={trust_score})",
                restrictions,
            )

        return AuditStatus.FAILED, f"审计不通过 (trust={trust_score})", ["修复 findings 后重新审计"]

    # ── Utils ─────────────────────────────────────

    def _derive_risk_level(self, capabilities: list[str]) -> RiskLevel:
        """从 capability 列表派生 server 风险等级 (取最高)。"""
        levels = {
            RiskLevel.CRITICAL: 4,
            RiskLevel.HIGH: 3,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 1,
        }
        max_level = RiskLevel.LOW
        max_score = 1
        for cap in capabilities:
            cp = self.risk_map.get(cap)
            if cp and levels.get(cp.risk_level, 1) > max_score:
                max_score = levels[cp.risk_level]
                max_level = cp.risk_level
        return max_level


def create_trust_record(server_name: str) -> ServerTrustRecord:
    """创建初始 trust record。"""
    return ServerTrustRecord(
        server_name=server_name,
        trust_level=TrustLevel.UNTRUSTED,
        trust_score=0,
    )
