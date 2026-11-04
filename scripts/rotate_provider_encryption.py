#!/usr/bin/env python3
"""Offline BYOK encryption rotation. Never prints plaintext credentials.

Must be executed by an authorized operator under a maintenance window,
against a verified backup and isolated copy before production.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def migrate(db_path: Path, old_key: bytes, new_key: bytes, *, apply: bool) -> int:
    if not db_path.is_file():
        raise RuntimeError("database path is not an existing regular file")
    if old_key == new_key:
        raise RuntimeError("new encryption key must differ from old key")

    old, new = Fernet(old_key), Fernet(new_key)
    with sqlite3.connect(db_path, timeout=30, isolation_level=None) as conn:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            # Always validate every record before making any changes.
            records = conn.execute(
                "SELECT id, api_key_enc FROM model_providers "
                "WHERE api_key_enc IS NOT NULL AND api_key_enc <> ''"
            ).fetchall()
            updates: list[tuple[str, str]] = []
            for row_id, ciphertext in records:
                try:
                    plain = old.decrypt(ciphertext.encode("utf-8"))
                except InvalidToken as exc:
                    raise RuntimeError(
                        "some provider keys cannot be decrypted by the supplied old key"
                    ) from exc
                rotated = new.encrypt(plain)
                if new.decrypt(rotated) != plain:
                    raise RuntimeError("new-key roundtrip check failed")
                updates.append((rotated.decode("utf-8"), row_id))

            if apply:
                conn.executemany(
                    "UPDATE model_providers SET api_key_enc=? WHERE id=?",
                    updates,
                )
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
            return len(updates)
        except Exception:
            conn.execute("ROLLBACK")
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="mutate DB; requires confirmed backup")
    parser.add_argument("--confirm-backup", action="store_true")
    args = parser.parse_args()

    if args.apply and not args.confirm_backup:
        parser.error("--apply requires --confirm-backup and an actual protected backup")
    old = os.environ.get("CARDIO_OLD_ENC_KEY")
    new = os.environ.get("CARDIO_NEW_ENC_KEY")
    if not old or not new:
        parser.error("CARDIO_OLD_ENC_KEY and CARDIO_NEW_ENC_KEY must be set in operator environment")
    try:
        count = migrate(args.db, old.encode(), new.encode(), apply=args.apply)
    except Exception as exc:
        # Do not echo ciphertext, key values, row IDs, or plaintext.
        print(f"Rotation aborted: {type(exc).__name__}")
        return 1
    print(f"{'Applied' if args.apply else 'Verified dry run'}: {count} provider key rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
