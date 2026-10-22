"""本地 SQLite 存储 —— 按领域拆分为 conn/users/apikeys/providers/contacts/analyses。

本 __init__ 重导出全部公共 API，调用方（server / routers / temporal）无需改动。
"""
from .analyses import list_analyses, save_analysis
from .apikeys import (
    create_api_key,
    get_api_key_by_hash,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
    touch_api_key,
)
from .conn import DEFAULT_OWNER, check_db
from .contacts import delete_contact, get_contact, list_contacts, save_contact, update_contact
from .providers import (
    create_model_provider,
    delete_model_provider,
    get_active_model_provider,
    get_active_provider,
    get_model_provider,
    list_model_providers,
    preset_for,
    provider_presets,
    touch_model_provider,
)
from .users import (
    create_user,
    delete_verify_token,
    get_user,
    get_user_by_email,
    get_verify_token,
    save_verify_token,
    set_email_verified,
    verify_user,
)

__all__ = [
    "DEFAULT_OWNER",
    "check_db",
    "create_user",
    "verify_user",
    "get_user",
    "get_user_by_email",
    "set_email_verified",
    "save_verify_token",
    "get_verify_token",
    "delete_verify_token",
    "create_api_key",
    "list_api_keys",
    "get_api_key_by_hash",
    "rotate_api_key",
    "revoke_api_key",
    "touch_api_key",
    "provider_presets",
    "preset_for",
    "create_model_provider",
    "list_model_providers",
    "get_model_provider",
    "get_active_provider",
    "get_active_model_provider",
    "delete_model_provider",
    "touch_model_provider",
    "save_contact",
    "update_contact",
    "delete_contact",
    "get_contact",
    "list_contacts",
    "save_analysis",
    "list_analyses",
]
