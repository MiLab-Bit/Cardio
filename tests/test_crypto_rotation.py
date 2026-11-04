"""Synthetic BYOK rotation and key-file handling, never using real credentials."""
from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from cardio import crypto
from scripts.rotate_provider_encryption import migrate


def make_db(path: Path, tokens: list[str]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE model_providers (id TEXT PRIMARY KEY, api_key_enc TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO model_providers(id,api_key_enc) VALUES(?,?)",
            [(str(i), token) for i, token in enumerate(tokens)],
        )


def tokens_at(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT api_key_enc FROM model_providers ORDER BY id"
        )]


def test_rotation_dry_run_and_apply_atomic(tmp_path):
    db = tmp_path / "providers.sqlite"
    old, new = Fernet.generate_key(), Fernet.generate_key()
    original = [Fernet(old).encrypt(s.encode()).decode() for s in ("test-a", "test-b")]
    make_db(db, original)

    assert migrate(db, old, new, apply=False) == 2
    assert tokens_at(db) == original
    assert migrate(db, old, new, apply=True) == 2
    rotated = tokens_at(db)
    assert [Fernet(new).decrypt(x.encode()).decode() for x in rotated] == ["test-a", "test-b"]
    for encrypted in rotated:
        with pytest.raises(InvalidToken):
            Fernet(old).decrypt(encrypted.encode())


def test_rotation_wrong_old_key_does_not_partially_modify_db(tmp_path):
    db = tmp_path / "providers.sqlite"
    old, newer, unrelated = Fernet.generate_key(), Fernet.generate_key(), Fernet.generate_key()
    values = [
        Fernet(old).encrypt(b"good").decode(),
        Fernet(unrelated).encrypt(b"mismatched").decode(),
    ]
    make_db(db, values)
    with pytest.raises(RuntimeError, match="cannot be decrypted"):
        migrate(db, old, newer, apply=True)
    assert tokens_at(db) == values


def test_new_dev_key_is_private_and_production_env_can_fail_closed(tmp_path, monkeypatch):
    key_path = tmp_path / ".enc_key"
    monkeypatch.setattr(crypto, "_KEY_PATH", key_path)
    monkeypatch.delenv("CARDIO_ENC_KEY", raising=False)
    monkeypatch.delenv("CARDIO_REQUIRE_ENC_KEY", raising=False)
    key = crypto._load_key()
    assert len(key) == 44
    if os.name == "posix":
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert crypto._load_key() == key

    key_path.unlink()
    monkeypatch.setenv("CARDIO_REQUIRE_ENC_KEY", "1")
    with pytest.raises(RuntimeError, match="CARDIO_ENC_KEY is required"):
        crypto._load_key()


def test_public_repo_does_not_track_runtime_secret():
    repo = Path(__file__).resolve().parents[1]
    out = subprocess.check_output(
        ["git", "ls-files", "--", "data/.enc_key"],
        cwd=repo, text=True,
    )
    assert out.strip() == "", "runtime Fernet key must never be tracked"
