# Cardio BYOK key rotation — operator-only release gate

**Status: draft security change. Do not deploy or merge blindly.**

## What is affected

- Cardio stores provider credentials in SQLite table model_providers, field api_key_enc.
- cardio.crypto chooses CARDIO_ENC_KEY first and otherwise loads/creates data/.enc_key.
- A Fernet-shaped key file was committed to this public repository. The corresponding
  encryption key must be treated as **compromised** until rotation is completed.
- Removing the file from the current branch does **not** remove it from Git history
  or copies of the repository. It also must not invalidate existing stored ciphertext.

## Operator procedure (requires service access and authorization)

1. **Pause BYOK writes and take an encrypted, access-controlled backup** of the
   Cardio database and the current working decryption key. Do not put the backup
   or old/new keys in Issues, CI logs, PR attachments or code.
2. Identify which key the deployed API actually uses. Verify that the existing
   production model_providers ciphertext decrypts under that key, without logging
   plaintext credentials.
3. Generate a fresh independent Fernet key via a trusted operator host or secret
   manager. Keep it out of source control and CI artifacts.
4. First validate the old key against a **restored offline database copy**.
   The repository provides an operator-only tool; set the two key variables
   securely in the operator environment (never paste values into a shell
   transcript/CI command). The default run only verifies decryptability:

   ```bash
   python scripts/rotate_provider_encryption.py --db /secure/isolated-copy.sqlite
   ```

   After verifying backups, follow the authorized maintenance runbook:

   ```bash
   python scripts/rotate_provider_encryption.py --db /secure/isolated-copy.sqlite --apply --confirm-backup
   ```

   This utility re-encrypts `model_providers.api_key_enc` atomically,
   validates new-key round trips, and rolls back if any old record cannot
   be decrypted. **Apply to production only after separate operator approval,
   using a backup and controlled downtime.**
5. In a maintenance/transactional offline process, re-encrypt **each**
   model_providers.api_key_enc value from the old key to the new key. The process
   must verify that every nonempty value can be decrypted and re-encrypted,
   and must roll back atomically on failure.
6. Update the server environment to provide CARDIO_ENC_KEY from a restricted
   secret source and CARDIO_REQUIRE_ENC_KEY=1; ensure API and Worker use the
   **same** key before restarting either. Do not let an empty key silently
   generate a new one.
7. Verify by an authorized end-to-end BYOK call with a non-sensitive test key,
   existing-provider decryption, and negative controls (wrong key must fail).
8. Revoke/rotate upstream provider API keys whose encrypted copies may have been
   exposed with the old database or backups; check access/audit logs.
9. Deploy the code change that untracks the local key, then separately coordinate
   Git history remediation with repository owners (history rewriting and clone
   rotation may disrupt existing branches/tags). Old public clones remain unsafe.
10. Resume normal writes after reconciliation and backup verification.

## Required evidence before this PR can be treated as production-safe

- Confirmation of actual production key source (env vs local file).
- Count of migrated provider rows, not plaintext values.
- Successful verification against a restored backup / test environment.
- Maintenance plan for API/Worker restart and rollback.
- Review from the authorized operator handling server secrets.

No real production keys or customer data are used or modified by this PR.
