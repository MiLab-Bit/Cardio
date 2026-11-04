# Cardio runtime architecture — 2026-11-05

This note describes **current source code**, not a desired architecture.

## Process and data paths

1. React frontend -> FastAPI `cardio.server`.
2. Human JWT / machine token authentication -> owner scope.
3. `POST /api/chat` -> streaming `llm.chat` via `cardio.gateway`.
4. `POST /api/analyze` -> `run_pipeline` (in the API process) ->
   extraction / research / synthesis / strategy / critique. Progress is emitted
   as SSE and completed analysis can be saved to SQLite.
5. `cardio.gateway` -> either platform OpenAI-compatible endpoint
   (per-owner UTC daily quota) or user BYOK provider (not charged to platform).
   The cache is keyed by owner, provider-key fingerprint, model and request
   parameters; no raw API key is stored in a cache key.
6. An *independent optional* `cardio.temporal.worker` implements an alternate
   five-activity workflow. **The HTTP API does not currently dispatch to it.**

## Explicitly unfinished / separate decisions

- **Durability:** API SSE and direct pipeline are **not** durable Temporal jobs.
  Worker restart, a disconnected client and API-process failure require separate
  acceptance tests. A future durable API needs workflow IDs, idempotent submission,
  result queries, and protected ownership.
- **Credentials:** Passing BYOK api_key as a Temporal workflow argument would
  persist the secret in workflow history. Do **not** connect the API to Temporal
  until provider credentials can be resolved by server-side reference within the
  Activity, without persisting plaintext in workflow input/history.
- **Critical assessment:** Critique is a stage, not a measured performance claim.
  A five-task controlled pilot with/without Critique is still required.
- **External verification:** Research currently produces labeled model inference;
  no real web evidence source or provenance pipeline is integrated.
- **Security:** The existing repository tracked encryption key requires a
  controlled operator rotation and historical cleanup; the independent security
  Draft PR documents the blocked rollout.

## Regressions fixed in the candidate branch

| Boundary | Failure mechanism | Verification |
|---|---|---|
| Shared runtime | `openclaw_core` imports absent in clean installations | local gateway + native Temporal SDK + import tests |
| API routing | `include_router` executed before `@api` route definitions | OpenAPI exact routes and unauthorized 401 checks |
| Analysis parsing | `llm.extract_json` absent after refactor | fenced/inline/raw JSON unit tests |
| Quota | missing shared quotas could silently allow unlimited calls | fail-closed SQLite accounting + 12-way concurrency test |
| Cache isolation | identical platform prompts could cross owner contexts | owner/provider/model keyed cache tests |
| BYOK model | platform default model overrode chosen provider model | text+vision model propagation tests |
| Frontend | npm lockfile stale; pnpm lock is canonical | Node 22 / pnpm 9 / frozen lock build |
| Test gate | previous preflight did not run pytest | single fail-closed 4-part preflight |

## Verifying this snapshot

```bash
pip install -r requirements-dev.txt
bash scripts/preflight.sh
```

This checks offline contracts and service imports, not real model/provider
availability or Temporal server behavior. Deployments and encryption key
migration are separate operator-authorized actions.
