"""MCP Tool Bus — 鉴权层。

负责:
- 从环境变量/密钥管理器注入 token
- 为每个 server 生成 HTTP headers
- 支持 API Key / Bearer / Basic Auth
- 绝不记录明文密钥
"""

from __future__ import annotations

import logging
import os

from byou.tools.mcp.types import MCPAuthConfig, MCPAuthType

logger = logging.getLogger(__name__)


class AuthProvider:
    """统一鉴权提供者。

    注入链: env var → secret file → oauth refresh → header dict
    """

    def __init__(self):
        self._token_cache: dict[str, str] = {}

    def get_headers(self, auth: MCPAuthConfig) -> dict[str, str]:
        """生成 HTTP 鉴权 header 字典。"""
        if auth.auth_type == MCPAuthType.NONE:
            return {}

        token = self._resolve_token(auth)

        if auth.auth_type == MCPAuthType.API_KEY_HEADER:
            if not auth.header_name and not token:
                logger.warning("API_KEY_HEADER configured without header_name or token")
            return {auth.header_name or "X-API-Key": token}

        if auth.auth_type == MCPAuthType.API_KEY_QUERY:
            return {}  # 交给调用方拼 query string

        if auth.auth_type == MCPAuthType.BEARER_TOKEN:
            return {"Authorization": f"Bearer {token}"}

        if auth.auth_type == MCPAuthType.BASIC_AUTH:
            import base64
            user = auth.oauth_config.get("username", "")
            pwd = self._resolve_token(auth, key="password")
            encoded = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            return {"Authorization": f"Basic {encoded}"}

        return {}

    def get_query_params(self, auth: MCPAuthConfig) -> dict[str, str]:
        """生成 query string 鉴权参数 (用于 API_KEY_QUERY 模式)。"""
        if auth.auth_type == MCPAuthType.API_KEY_QUERY:
            param_name = auth.header_name or "api_key"
            return {param_name: self._resolve_token(auth)}
        return {}

    def _resolve_token(self, auth: MCPAuthConfig, key: str = "token") -> str:
        """解析 token: env → cached → file → config 明文(不推荐)"""

        # 1. 环境变量
        if auth.token_env_var:
            val = os.getenv(auth.token_env_var, "")
            if val:
                return val

        # 2. 缓存
        cache_key = f"{auth.token_env_var or auth.token_file or id(auth)}:{key}"
        if cache_key in self._token_cache:
            return self._token_cache[cache_key]

        # 3. 文件
        if auth.token_file and os.path.isfile(auth.token_file):
            try:
                val = open(auth.token_file).read().strip()
                if val:
                    self._token_cache[cache_key] = val
                    return val
            except Exception:
                pass

        # 4. 配置明文 (仅开发环境)
        token = getattr(auth, key, "") or auth.token
        if token:
            self._token_cache[cache_key] = token

        return token

    def is_authenticated(self, auth: MCPAuthConfig) -> bool:
        """检查是否有有效的 token。"""
        return bool(self._resolve_token(auth))
