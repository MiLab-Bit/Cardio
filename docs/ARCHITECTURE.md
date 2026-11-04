# Cardio runtime architecture — 2026-11-05

This note describes **current source code**, not a desired architecture.

## Process and data paths

1. React frontend -> FastAPI `cardio.server`.
2. Human JWT / machine token authentication -> owner scope.
3. `POST /api/chat` -> streaming `llm.chat` via `cardio.gateway`.
4. `POST /api/analyze` -> Temporal `CardioAnalyzeWorkflow` -> five Activities ->
   idempotent `persist_analysis` Activity. The API queries Workflow progress and
   streams stage updates via SSE; there is no in-process pipeline fallback.
5. `cardio.gateway` -> either platform OpenAI-compatible endpoint
   (per-owner UTC daily quota) or user BYOK provider (not charged to platform).
   The cache is keyed by owner, provider-key fingerprint, model and request
   parameters; no raw API key is stored in a cache key.
6. `cardio.temporal.worker` is required for HTTP Analyze. It registers the five
   model Activities plus `persist_analysis`; deployment must provide Temporal
   Server, namespace and shared protected persistence.

## Temporal durability and credential boundary (candidate branch)

- **Mandatory Temporal:** HTTP Analyze returns `503 TEMPORAL_UNAVAILABLE` when the service cannot connect; there is no in-process LLM analysis fallback. The worker must be deployed separately and use the same protected database and encryption configuration.
- **No plaintext BYOK in history:** `AnalyzeInput` and every Activity payload contain the `provider_id` reference and user `owner` only. `store.resolve_workflow_provider()` checks owner + active + text slot and decrypts locally inside the Activity worker; missing/revoked credentials fail closed. Provider dictionaries and decrypted keys are not returned to Workflow history.
- **Result durability:** `persist_analysis` writes successful results within Temporal, using Workflow ID as idempotent analysis ID; SSE disconnect cannot roll back a submitted Workflow. The result remains in the `analyses` table even if the original API stream disconnects.
- **Image boundary:** Card image OCR still runs in the API before Workflow submission. It uses a multimodal BYOK only in API memory; this pre-processing is not yet durable, even though subsequent text analysis is.
- **Known limitations:** The API's SSE progress feed is query-polling, not an event-history replay endpoint. Callers cannot yet resume a disconnected SSE stream by Workflow ID. Model output quality, real Temporal restart recovery, external provider availability and key rotation require independent integration checks. `Critique` remains advisory and `Research` is not a live web search.
- **Security operations:** The existing repository tracked encryption key requires a controlled operator rotation and historical cleanup; the separate security Draft PR documents the blocked rollout. Temporal payloads (customer materials and results) are sensitive even without provider credentials and need retention/access controls.

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

This checks offline contracts, provider-reference security and service imports,
not real model/provider availability or Temporal server behavior. Deployments and encryption key
migration are separate operator-authorized actions.
