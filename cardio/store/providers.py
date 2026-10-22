"""用户自带大模型供应商配置（model_providers 表）。

与机器凭证 api_keys 解耦：此处存用户自己的 LLM 供应商 Key（加密静态存储）。
"""
from __future__ import annotations

import uuid
from typing import Any

from .conn import _connect, _now

# ── 用户自带大模型供应商配置（model_providers）──
# 与机器凭证 api_keys 解耦：此处存的是用户自己的 LLM 供应商 Key（加密静态存储）。
# 预设与 RedTrip/BizAtlas 保持一致：驼峰字段 + 列表结构。
_PROVIDER_PRESETS = [
    {"provider": "openai", "label": "OpenAI", "baseUrl": "https://api.openai.com/v1", "defaultModel": "gpt-4o-mini"},
    {"provider": "anthropic", "label": "Anthropic", "baseUrl": "https://api.anthropic.com/v1", "defaultModel": "claude-3-5-sonnet-latest"},
    {"provider": "deepseek", "label": "DeepSeek", "baseUrl": "https://api.deepseek.com/v1", "defaultModel": "deepseek-chat"},
    {"provider": "moonshot", "label": "Moonshot 月之暗面", "baseUrl": "https://api.moonshot.cn/v1", "defaultModel": "moonshot-v1-8k"},
    {"provider": "qwen", "label": "通义千问", "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1", "defaultModel": "qwen-plus"},
    {"provider": "zhipu", "label": "智谱 GLM", "baseUrl": "https://open.bigmodel.cn/api/paas/v4", "defaultModel": "glm-4-flash"},
    {"provider": "ollama", "label": "Ollama（本地）", "baseUrl": "http://localhost:11434/v1", "defaultModel": "llama3.1"},
    {"provider": "custom", "label": "自定义 / 兼容 OpenAI", "baseUrl": "", "defaultModel": ""},
]

def provider_presets() -> list[dict[str, Any]]:
    return _PROVIDER_PRESETS


def preset_for(provider: str) -> dict[str, Any]:
    """按 provider 名取预设；不存在返回空字典。"""
    return next((p for p in _PROVIDER_PRESETS if p["provider"] == provider), {})


def create_model_provider(
    owner_id: str, name: str, provider: str, api_key: str, base_url: str | None, model: str | None,
    slot: str = "text",
) -> str:
    """创建一条用户自带大模型供应商配置，api_key 加密存储。返回新记录 id。
    slot: 'text'（文本模型）或 'multimodal'（多模态模型），同一用户每槽位各一条。
    """
    from .. import crypto

    pid = uuid.uuid4().hex[:12]
    enc = crypto.encrypt(api_key)
    with _connect() as c:
        c.execute(
            "INSERT INTO model_providers (id,owner_id,slot,name,provider,api_key_enc,base_url,model,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, owner_id, slot, name, provider, enc, base_url, model, "active", _now(), _now()),
        )
    return pid


def list_model_providers(owner_id: str) -> list[dict[str, Any]]:
    """列出某用户的供应商配置（key 仅展示后 4 位，不返回明文），含 slot 字段。"""
    with _connect() as c:
        rows = c.execute(
            "SELECT id,slot,name,provider,base_url,model,status,created_at,updated_at,last_used_at "
            "FROM model_providers WHERE owner_id=? ORDER BY slot, created_at DESC",
            (owner_id,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "slot": r["slot"], "name": r["name"], "provider": r["provider"],
            "base_url": r["base_url"], "model": r["model"], "status": r["status"],
            "created_at": r["created_at"], "updated_at": r["updated_at"], "last_used_at": r["last_used_at"],
        })
    return out


def get_model_provider(id: str, owner_id: str) -> dict[str, Any] | None:
    """取单条配置（含解密后的明文 key，仅供后端调用大模型使用）。"""
    from .. import crypto

    with _connect() as c:
        r = c.execute(
            "SELECT id,owner_id,name,provider,api_key_enc,base_url,model,status FROM model_providers "
            "WHERE id=? AND owner_id=?",
            (id, owner_id),
        ).fetchone()
    if not r:
        return None
    return {
        "id": r["id"], "owner_id": r["owner_id"], "name": r["name"], "provider": r["provider"],
        "api_key": crypto.decrypt(r["api_key_enc"]), "base_url": r["base_url"], "model": r["model"],
        "status": r["status"],
    }


def get_active_provider(owner_id: str, slot: str = "text") -> dict[str, Any] | None:
    """取该用户在指定槽位（'text' 文本 / 'multimodal' 多模态）最近一条 active 配置。
    供对话/分析实际调用大模型时按任务选槽使用。无则返回 None（调用方回退平台默认）。
    """
    with _connect() as c:
        r = c.execute(
            "SELECT id FROM model_providers WHERE owner_id=? AND slot=? AND status='active' "
            "ORDER BY updated_at DESC LIMIT 1",
            (owner_id, slot),
        ).fetchone()
    if not r:
        return None
    return get_model_provider(r["id"], owner_id)


def get_active_model_provider(owner_id: str) -> dict[str, Any] | None:
    """兼容别名：默认取 text 槽位 active 配置（供既有调用方使用，无需改动）。"""
    return get_active_provider(owner_id, "text")


def delete_model_provider(id: str, owner_id: str) -> bool:
    with _connect() as c:
        cur = c.execute("DELETE FROM model_providers WHERE id=? AND owner_id=?", (id, owner_id))
        return cur.rowcount > 0


def touch_model_provider(id: str) -> None:
    with _connect() as c:
        c.execute("UPDATE model_providers SET last_used_at=? WHERE id=?", (_now(), id))
