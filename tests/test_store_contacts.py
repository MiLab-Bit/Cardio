"""store 包回归测试 —— 重点守护 _row_to_contact 的 owner 往返。

历史 bug：sqlite3.Row 无 __contains__，"owner" in r 恒为 False，
导致 get_contact 返回的 owner 永远回落 DEFAULT_OWNER，
update_contact 的 owner 守卫因此对所有非 default 用户恒失败（编辑功能静默 404）。
"""
from __future__ import annotations

import pytest

from cardio import store
from cardio.auth import hash_password


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """把 store 指向临时 DB，避免污染生产数据。"""
    monkeypatch.setattr("cardio.config.DB_PATH", str(tmp_path / "test.db"))
    return tmp_path


def test_contact_owner_roundtrip_and_update(db):
    email = "owner_rt@example.com"
    uid = store.create_user(email, hash_password("pw123456"), "回归测试")
    assert uid

    c = store.save_contact(uid, {"name": "张三", "company": "测试公司", "tags": "a，b"})
    # owner 必须真实往返，而不是回落 "default"
    assert c["owner"] == uid

    fetched = store.get_contact(c["id"])
    assert fetched["owner"] == uid

    # update_contact 的 owner 守卫依赖 get_contact 的 owner 正确性
    updated = store.update_contact(uid, c["id"], {"name": "张三丰"})
    assert updated is not None
    assert updated["name"] == "张三丰"

    # 越权更新必须被拒
    other = store.create_user("other@example.com", hash_password("pw123456"), "别人")
    assert store.update_contact(other, c["id"], {"name": "篡改"}) is None

    # list 也带回真实 owner
    rows = store.list_contacts(uid)
    assert any(r["owner"] == uid for r in rows)

    assert store.delete_contact(uid, c["id"]) is True
    assert store.get_contact(c["id"]) is None


def test_provider_crypto_roundtrip_via_store(db):
    email = "crypto_rt@example.com"
    uid = store.create_user(email, hash_password("pw123456"), "加密回归")
    assert uid

    pid = store.create_model_provider(uid, "qwen-test", "qwen", "sk-secret", None, None)
    got = store.get_model_provider(pid, uid)
    assert got is not None
    # 加密静态存储：读回必须解密还原
    assert got["api_key"] == "sk-secret"

    assert store.delete_model_provider(pid, uid) is True
