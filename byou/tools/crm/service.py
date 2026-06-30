"""CRM Tool — high-level CRM service.

Ties together:
- CRM config (from settings or runtime)
- Sync engine
- SQLite persistence for sync status
- Auto-push after pipeline completion
- OAuth token management (Salesforce/HubSpot)
"""

from __future__ import annotations

import logging
from typing import Any

from byou.config import get_settings
from byou.core.sqlite_store import SQLiteStore
from byou.models.customer import PipelineContext
from byou.tools.crm.client import CRMConfig, CRMProvider, create_crm_provider, SalesforceProvider
from byou.tools.crm.models import CRMSyncRecord, SyncStatus, SyncDirection
from byou.tools.crm.sync import CRMSyncEngine

logger = logging.getLogger(__name__)


class CRMService:
    """High-level CRM service with config, sync, and persistence."""

    def __init__(self, sqlite_store: SQLiteStore | None = None):
        self.settings = get_settings()
        self.sqlite_store = sqlite_store
        self._engine: CRMSyncEngine | None = None
        self._config: CRMConfig | None = None

        # Auto-create SQLite store if not provided
        if self.sqlite_store is None:
            try:
                from byou.core.sqlite_store import SQLiteStore
                db_path = self.settings.data_dir / "byou.db"
                self.sqlite_store = SQLiteStore(db_path)
            except Exception as e:
                logger.warning("CRMService: could not init SQLiteStore: %s", e)

    @property
    def config(self) -> CRMConfig:
        if self._config is None:
            self._config = self._load_config()
        return self._config

    @config.setter
    def config(self, value: CRMConfig) -> None:
        self._config = value
        self._engine = None  # reset engine when config changes

    @property
    def engine(self) -> CRMSyncEngine:
        if self._engine is None:
            self._engine = CRMSyncEngine(self.config)
        return self._engine

    def _load_config(self) -> CRMConfig:
        """Load CRM config from settings."""
        settings = self.settings
        provider_str = getattr(settings, "crm_provider", "generic") or "generic"
        try:
            provider = CRMProvider(provider_str)
        except ValueError:
            provider = CRMProvider.GENERIC

        config = CRMConfig(
            provider=provider,
            api_url=getattr(settings, "crm_api_url", "") or "",
            api_key=getattr(settings, "crm_api_key", "") or "",
            auto_push=getattr(settings, "crm_auto_push", True),
            auto_pull=getattr(settings, "crm_auto_pull", False),
            oauth_refresh_token=getattr(settings, "crm_oauth_refresh_token", "") or "",
            oauth_client_id=getattr(settings, "crm_oauth_client_id", "") or "",
            oauth_client_secret=getattr(settings, "crm_oauth_client_secret", "") or "",
        )

        # Load default field mappings for the provider
        if provider == CRMProvider.SALESFORCE:
            config.field_mappings = CRMConfig.salesforce_field_mappings()
        elif provider == CRMProvider.HUBSPOT:
            config.field_mappings = CRMConfig.hubspot_field_mappings()
        else:
            config.field_mappings = CRMConfig.default_field_mappings()

        return config

    # ── Push after pipeline ────────────────────────────────────

    async def push_pipeline(self, ctx: PipelineContext) -> dict:
        """Push pipeline result to CRM and persist sync status.

        Returns:
            Sync status dict (includes status, crm_id, error if any)
        """
        if not self.config.api_url:
            logger.warning("CRM not configured — skipping push")
            return {"status": "skipped", "reason": "CRM not configured"}

        record = await self.engine.push_pipeline_result(ctx)

        # Persist to SQLite
        if self.sqlite_store:
            self._persist_sync_record(record)

        result = {
            "status": record.status.value,
            "byou_id": record.byou_id,
            "crm_id": record.crm_id,
            "direction": record.direction.value,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        }
        if record.error_message:
            result["error"] = record.error_message
        if record.conflict_fields:
            result["conflict_fields"] = record.conflict_fields

        return result

    # ── Pull from CRM ──────────────────────────────────────────

    async def pull_contact(self, crm_id: str) -> dict:
        """Pull a contact from CRM."""
        status, contact, record = await self.engine.pull_contact(crm_id)
        if self.sqlite_store:
            self._persist_sync_record(record)
        if contact:
            return {
                "status": "success",
                "contact": contact.model_dump(),
            }
        return {"status": "failed", "error": record.error_message}

    async def pull_by_email(self, email: str) -> dict:
        """Pull contact by email."""
        status, contact = await self.engine.pull_by_email(email)
        if contact:
            return {"status": "success", "contact": contact.model_dump()}
        return {"status": "not_found"}

    # ── Batch operations ────────────────────────────────────────

    async def batch_push(self, contexts: list[PipelineContext]) -> list[dict]:
        """Push multiple pipeline results."""
        records = await self.engine.batch_push(contexts)
        results = []
        for record in records:
            if self.sqlite_store:
                self._persist_sync_record(record)
            results.append({
                "status": record.status.value,
                "byou_id": record.byou_id,
                "crm_id": record.crm_id,
            })
        return results

    # ── Sync status ────────────────────────────────────────────

    def get_sync_history(self, limit: int = 50) -> list[dict]:
        """Get recent CRM sync history."""
        if not self.sqlite_store:
            return []
        return self.sqlite_store.get_recent_crm_sync(limit)

    def get_sync_by_byou_id(self, byou_id: str) -> list[dict]:
        """Get sync records for a specific customer."""
        if not self.sqlite_store:
            return []
        return self.sqlite_store.get_crm_sync_by_byou_id(byou_id)

    # ── Config management ──────────────────────────────────────

    def update_config(self, **kwargs: Any) -> CRMConfig:
        """Update CRM config at runtime."""
        for k, v in kwargs.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)
        self._engine = None  # reset engine
        logger.info("CRM config updated: %s", kwargs)
        return self.config

    # ── OAuth management ──────────────────────────────────────

    async def oauth_refresh(self) -> dict:
        """Manually trigger OAuth token refresh (for Salesforce/HubSpot)."""
        provider = self.config.provider
        if provider == CRMProvider.SALESFORCE:
            client = create_crm_provider(self.config)
            if isinstance(client, SalesforceProvider):
                await client._refresh_token()
                return {
                    "status": "refreshed",
                    "expires_at": self.config.token_expires_at.isoformat() if self.config.token_expires_at else None,
                }
        return {"status": "unsupported_provider", "provider": provider.value}

    async def oauth_get_auth_url(self, redirect_uri: str) -> dict:
        """Generate OAuth authorization URL (for frontend to redirect user)."""
        provider = self.config.provider
        if provider == CRMProvider.SALESFORCE:
            client_id = self.config.oauth_client_id or ""
            if not client_id:
                return {"status": "error", "error": "oauth_client_id not configured"}
            url = SalesforceProvider.generate_auth_url(client_id, redirect_uri)
            return {"status": "ok", "auth_url": url}
        return {"status": "unsupported_provider", "provider": provider.value}

    async def oauth_exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange OAuth authorization code for tokens."""
        provider = self.config.provider
        if provider == CRMProvider.SALESFORCE:
            client = create_crm_provider(self.config)
            if isinstance(client, SalesforceProvider):
                token_data = await client.exchange_code_for_token(
                    code,
                    self.config.oauth_client_id or "",
                    self.config.oauth_client_secret or "",
                    redirect_uri,
                )
                return {"status": "ok", "token_data": token_data}
        return {"status": "unsupported_provider", "provider": provider.value}

    # ── Private ────────────────────────────────────────────────

    def _persist_sync_record(self, record: CRMSyncRecord) -> None:
        """Save sync record to SQLite."""
        try:
            data = {
                "byou_id": record.byou_id,
                "crm_id": record.crm_id,
                "direction": record.direction.value,
                "provider": record.provider.value,
                "status": record.status.value,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "completed_at": record.completed_at.isoformat() if record.completed_at else None,
                "error_message": record.error_message,
                "conflict_fields": record.conflict_fields,
                "byou_snapshot": record.byou_data_snapshot,
                "crm_snapshot": record.crm_data_snapshot,
                "retry_count": record.retry_count,
                "max_retries": record.max_retries,
            }
            self.sqlite_store.save_crm_sync(data)
        except Exception as e:
            logger.error("Failed to persist CRM sync record: %s", e)

    async def close(self) -> None:
        if self._engine:
            await self._engine.close()
