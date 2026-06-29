"""Browser Execution Subsystem — Safety Guard.

确保浏览器执行不会越界:
- 域名白名单/黑名单拦截
- 表单提交拦截
- 文件下载拦截
- 反爬/验证码检测
- 超时保护
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from byou.tools.browser.types import SafetyPolicy

logger = logging.getLogger(__name__)

# 已知反爬/验证码特征
_ANTI_BOT_INDICATORS = [
    "captcha", "验证码", "人机验证", "verify you are human",
    "Attention Required! | Cloudflare",
    "Just a moment...",
    "Checking your browser",
    "DDoS protection",
    "Access Denied",
    "403 Forbidden",
    "blocked",
]


class SafetyGuard:
    """浏览器安全护栏 — 在每个动作执行前/后做安全检查。"""

    def __init__(self, policy: SafetyPolicy | None = None):
        self.policy = policy or SafetyPolicy()

        # 默认拦截的域名后缀
        self._default_blocked_suffixes = {
            ".gov.cn", ".mil.cn",  # 政府军事站点
        }

    # ── 导航前检查 ──────────────────────────────

    def check_url_allowed(self, url: str) -> tuple[bool, str]:
        """检查 URL 是否允许访问。返回 (允许?, 原因)"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            hostname = parsed.hostname or ""
        except Exception:
            return False, f"Invalid URL: {url[:100]}"

        # 空 URL
        if not domain:
            return False, "Empty URL"

        # 黑名单优先
        for blocked in self.policy.blocked_domains:
            if blocked in domain:
                return False, f"Domain blocked: {blocked}"

        # 默认拦截后缀
        for suffix in self._default_blocked_suffixes:
            if hostname.endswith(suffix):
                return False, f"Default blocked suffix: {suffix}"

        # 白名单
        if self.policy.allowed_domains:
            allowed = any(d in domain for d in self.policy.allowed_domains)
            if not allowed:
                return False, f"Domain not in allowlist: {domain}"

        return True, "OK"

    def check_file_download(self, url: str, content_type: str = "", size_bytes: int = 0) -> tuple[bool, str]:
        """检查文件下载是否允许"""
        if self.policy.block_file_download:
            # 检查是否为文件下载 URL
            file_extensions = {".zip", ".exe", ".msi", ".dmg", ".apk", ".tar.gz",
                               ".pdf", ".doc", ".docx", ".xls", ".xlsx"}
            for ext in file_extensions:
                if url.lower().endswith(ext):
                    return False, f"File download blocked: {ext}"

        if size_bytes > self.policy.max_file_size_mb * 1024 * 1024:
            return False, f"File too large: {size_bytes} bytes"

        return True, "OK"

    def check_form_submit(self, form_data: dict) -> tuple[bool, str]:
        """检查表单提交是否允许"""
        if self.policy.block_form_submit:
            return False, "Form submit blocked by safety policy"
        return True, "OK"

    # ── 执行后检查 ──────────────────────────────

    def detect_anti_bot(self, page_title: str, page_text: str, status_code: int) -> tuple[bool, str]:
        """检测反爬/验证码页面"""
        if status_code in (403, 429):
            return True, f"HTTP {status_code}"

        combined = (page_title + " " + page_text[:2000]).lower()
        for indicator in _ANTI_BOT_INDICATORS:
            if indicator.lower() in combined:
                return True, f"Anti-bot indicator: {indicator}"

        return False, "OK"

    def detect_login_wall(self, page_title: str, page_text: str) -> tuple[bool, str]:
        """检测登录墙"""
        login_keywords = ["登录", "sign in", "log in", "请登录", "立即登录"]
        combined = (page_title + " " + page_text[:500]).lower()

        login_count = sum(1 for kw in login_keywords if kw.lower() in combined)
        if login_count >= 2:
            return True, "Login wall detected"
        return False, "OK"

    def detect_error_page(self, page_title: str, status_code: int) -> tuple[bool, str]:
        """检测错误页面"""
        if status_code >= 500:
            return True, f"Server error: {status_code}"
        if status_code == 404:
            return True, "Page not found (404)"
        return False, "OK"

    # ── 超时保护 ────────────────────────────────

    def check_step_limit(self, current_steps: int) -> tuple[bool, str]:
        """检查是否超过步数限制"""
        if current_steps >= self.policy.max_total_steps:
            return False, f"Step limit reached: {current_steps}/{self.policy.max_total_steps}"
        return True, "OK"

    def check_error_limit(self, consecutive_errors: int) -> tuple[bool, str]:
        """检查是否超过连续错误限制"""
        if consecutive_errors >= self.policy.max_consecutive_errors:
            return False, f"Consecutive error limit reached: {consecutive_errors}"
        return True, "OK"

    # ── 弹窗拦截 ────────────────────────────────

    def should_block_popup(self, popup_url: str) -> tuple[bool, str]:
        """检查是否拦截弹窗"""
        if self.policy.block_popups:
            return True, "Popups blocked by safety policy"
        return self.check_url_allowed(popup_url)
