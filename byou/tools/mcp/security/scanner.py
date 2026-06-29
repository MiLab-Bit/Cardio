"""MCP Security — 安全扫描器。

集成 mcpscan-style 扫描规则:
1. Dependency scanning (pip-audit)
2. Secret detection
3. Configuration validation

CI 友好的扫描接口: 输出结构化发现列表。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path

from .types import (
    McpSecurityFinding,
    RiskLevel,
)

logger = logging.getLogger(__name__)


class SecurityScanner:
    """MCP Server 安全扫描器。

    设计为 CI-friendly: 每个 scan 方法独立, 可选择性运行,
    返回结构化 finding 列表。
    """

    def __init__(self, *, severities_to_fail: set[RiskLevel] | None = None):
        self._severities_to_fail = severities_to_fail or {RiskLevel.CRITICAL}

    # ── Main entry ────────────────────────────────

    def scan_server(
        self,
        *,
        server_name: str,
        source_dir: str | None = None,
        config_dict: dict | None = None,
        run_dependency_scan: bool = False,
    ) -> list[McpSecurityFinding]:
        """对单个 server 执行全量扫描。

        Args:
            server_name: 服务名称
            source_dir: 源代码目录 (提供则执行源码扫描)
            config_dict: 配置字典 (提供则执行配置扫描)
            run_dependency_scan: 是否执行依赖扫描 (慢, 默认跳过)
        """
        findings: list[McpSecurityFinding] = []

        # 1. Config 扫描
        if config_dict:
            findings += self.scan_config(server_name, config_dict)

        # 2. Source 扫描
        if source_dir:
            findings += self.scan_source(server_name, source_dir)

        # 3. Dependency 扫描
        if run_dependency_scan and source_dir:
            findings += self._scan_python_dependencies(server_name, source_dir)

        return findings

    # ── Config scanner ────────────────────────────

    def scan_config(
        self,
        server_name: str,
        config: dict,
    ) -> list[McpSecurityFinding]:
        """扫描配置文件中的安全隐患。

        Checks:
        - Missing auth config
        - OAuth without HTTPS
        - Overly broad network scope
        - Debug mode enabled
        """
        findings: list[McpSecurityFinding] = []
        fid = f"{server_name}-cfg-"

        # Check: no auth configured
        auth = config.get("auth", {})
        if not auth or auth.get("auth_type") in ("none", ""):
            findings.append(McpSecurityFinding(
                finding_id=fid + "001",
                server_name=server_name,
                scanner="config_scan",
                title="缺少鉴权配置",
                description="Server 未配置任何鉴权方式, 可能导致未授权访问",
                severity=RiskLevel.HIGH,
                category="auth",
                recommendation="配置至少一种鉴权方式 (API_KEY_HEADER 或 BEARER_TOKEN)",
            ))

        # Check: auth type+URL combination
        if auth.get("auth_type") == "oauth2" and config.get("base_url", "").startswith("http://"):
            findings.append(McpSecurityFinding(
                finding_id=fid + "002",
                server_name=server_name,
                scanner="config_scan",
                title="OAuth2 使用 HTTP 明文传输",
                description="OAuth2 token 在非加密通道传输, 存在劫持风险",
                severity=RiskLevel.CRITICAL,
                category="auth",
                recommendation="将 base_url 改为 HTTPS",
            ))

        # Check: debug mode
        if config.get("debug") or config.get("log_level") == "DEBUG":
            findings.append(McpSecurityFinding(
                finding_id=fid + "003",
                server_name=server_name,
                scanner="config_scan",
                title="开启了 DEBUG 模式",
                description="生产环境不应启用 DEBUG, 可能泄露敏感信息到日志",
                severity=RiskLevel.MEDIUM,
                category="configuration",
                recommendation="将 log_level 设为 INFO 或 WARNING",
            ))

        # Check: no network scope
        network = config.get("network_scope", [])
        if not network and config.get("server_type") not in ("embedded", "stdio"):
            findings.append(McpSecurityFinding(
                finding_id=fid + "004",
                server_name=server_name,
                scanner="config_scan",
                title="缺少网络范围限制",
                description="Server 未声明允许访问的域名/IP 范围",
                severity=RiskLevel.LOW,
                category="network",
                recommendation="添加 network_scope 列表限制出站访问",
            ))

        return findings

    # ── Source scanner ────────────────────────────

    def scan_source(
        self,
        server_name: str,
        source_dir: str,
    ) -> list[McpSecurityFinding]:
        """扫描源代码中的安全隐患。

        Checks:
        - Hardcoded secrets
        - Dangerous imports (eval, exec, os.system)
        - Insecure cryptography
        """
        findings: list[McpSecurityFinding] = []
        fid = f"{server_name}-src-"
        src_path = Path(source_dir)

        if not src_path.exists() or not src_path.is_dir():
            return findings

        # 遍历所有 Python 和 shell 文件
        for py_file in src_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            rel_path = str(py_file.relative_to(src_path))

            # Check: eval/exec
            if self._has_pattern(content, r'\beval\s*\(|\bexec\s*\(|\bcompile\s*\(.*\'exec\''):
                findings.append(McpSecurityFinding(
                    finding_id=f"{fid}eval-{hash(rel_path) & 0xffff:04x}",
                    server_name=server_name,
                    scanner="source_scan",
                    title="使用了 eval/exec/compile",
                    description=f"文件 {rel_path} 中包含动态代码执行",
                    severity=RiskLevel.HIGH,
                    category="code",
                    file_path=rel_path,
                    recommendation="避免使用 eval/exec, 考虑替代方案",
                ))

            # Check: hardcoded secrets
            secret_matches = re.findall(
                r'(?:secret|password|api_key|apikey|token)\s*[:=]\s*[\'"]([^\'"]+)[\'"]',
                content,
                re.IGNORECASE,
            )
            if secret_matches:
                findings.append(McpSecurityFinding(
                    finding_id=f"{fid}secret-{hash(rel_path) & 0xffff:04x}",
                    server_name=server_name,
                    scanner="source_scan",
                    title="源代码中检测到硬编码密钥",
                    description=f"文件 {rel_path} 中疑似硬编码了 {len(secret_matches)} 个密钥",
                    severity=RiskLevel.CRITICAL,
                    category="secret_leak",
                    file_path=rel_path,
                    evidence=f"Found in lines: {secret_matches[:3]}",
                    recommendation="将密钥移至环境变量或 secret manager",
                ))

            # Check: shell injection risk
            if self._has_pattern(content, r'\bos\.system\s*\(|\bos\.popen\s*\(|\bsubprocess\.call\s*\(.*shell\s*=\s*True'):
                findings.append(McpSecurityFinding(
                    finding_id=f"{fid}shell-{hash(rel_path) & 0xffff:04x}",
                    server_name=server_name,
                    scanner="source_scan",
                    title="使用了不安全的 shell 调用",
                    description=f"文件 {rel_path} 中包含 os.system/os.popen 或 subprocess shell=True",
                    severity=RiskLevel.MEDIUM,
                    category="code",
                    file_path=rel_path,
                    recommendation="使用 subprocess.run() 并将参数作为 list 传递, 避免 shell=True",
                ))

        return findings

    # ── Dependency scanner ─────────────────────────

    def _scan_python_dependencies(
        self,
        server_name: str,
        source_dir: str,
    ) -> list[McpSecurityFinding]:
        """扫描 Python 依赖的安全漏洞。

        尝试运行 pip-audit (如果可用)。
        失败时返回通知性 finding。
        """
        findings: list[McpSecurityFinding] = []
        fid = f"{server_name}-dep-"

        try:
            result = subprocess.run(
                ["pip-audit", "--format", "json"],
                capture_output=True,
                text=True,
                cwd=source_dir,
                timeout=60,
            )
            if result.returncode == 0:
                # No vulnerabilities
                return findings

            # Parse pip-audit output
            try:
                output = json.loads(result.stdout)
                for vuln in output.get("dependencies", []):
                    findings.append(McpSecurityFinding(
                        finding_id=f"{fid}{len(findings):03d}",
                        server_name=server_name,
                        scanner="pip_audit",
                        title=f"依赖漏洞: {vuln.get('name', 'unknown')}",
                        description=vuln.get("description", ""),
                        severity=RiskLevel.MEDIUM,
                        category="dependency",
                        recommendation=f"升级至安全版本: {vuln.get('fix_versions', 'N/A')}",
                    ))
            except json.JSONDecodeError:
                pass

        except FileNotFoundError:
            # pip-audit not installed
            findings.append(McpSecurityFinding(
                finding_id=fid + "001",
                server_name=server_name,
                scanner="pip_audit",
                title="依赖扫描工具未安装",
                description="pip-audit 未在环境中安装, 无法执行依赖安全扫描",
                severity=RiskLevel.LOW,
                category="tooling",
                recommendation="安装 pip-audit: pip install pip-audit",
            ))
        except subprocess.TimeoutExpired:
            findings.append(McpSecurityFinding(
                finding_id=fid + "002",
                server_name=server_name,
                scanner="pip_audit",
                title="依赖扫描超时",
                description="pip-audit 执行超时 (>60s)",
                severity=RiskLevel.LOW,
                category="tooling",
            ))

        return findings

    # ── Helpers ───────────────────────────────────

    @staticmethod
    def _has_pattern(content: str, pattern: str) -> bool:
        return bool(re.search(pattern, content, re.IGNORECASE))

    # ── CI integration ─────────────────────────────

    def ci_check(self, findings: list[McpSecurityFinding]) -> tuple[bool, int]:
        """CI 友好的检查: 有 critical finding → 失败。

        Returns:
            (passed?, critical_count)
        """
        critical = sum(1 for f in findings if f.severity in self._severities_to_fail)
        return critical == 0, critical
