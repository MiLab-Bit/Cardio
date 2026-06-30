"""CRM Tool — data models for bidirectional sync."""

from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enums ───────────────────────────────────────────────────────

class CRMProvider(str, Enum):
    GENERIC = "generic"
    SALESFORCE = "salesforce"
    HUBSPOT = "hubspot"


class SyncDirection(str, Enum):
    PUSH = "push"   # Byou → CRM
    PULL = "pull"   # CRM → Byou


class SyncStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CONFLICT = "conflict"
    SKIPPED = "skipped"


class ConflictStrategy(str, Enum):
    BYOU_WINS = "byou_wins"       # Byou 覆盖 CRM
    CRM_WINS = "crm_wins"         # CRM 覆盖 Byou
    NEWEST_WINS = "newest_wins"   # 时间戳更新者胜出
    MANUAL = "manual"             # 标记冲突，等待人工处理


# ── Field Mapping ──────────────────────────────────────────────

class FieldMapping(BaseModel):
    """Map between Byou field names and CRM field names."""
    byou_field: str
    crm_field: str
    # For nested CRM fields like "properties.email"
    crm_field_path: Optional[str] = None


# ── CRM Contact (unified representation) ──────────────────────

class CRMContact(BaseModel):
    """Unified contact representation for sync."""
    # Byou internal ID (PipelineContext.id or generated)
    byou_id: Optional[str] = None

    # CRM external ID
    crm_id: Optional[str] = None

    # Standard fields
    name: str = ""
    title: str = ""
    company: str = ""
    phone: str = ""
    email: str = ""
    wechat: str = ""
    address: str = ""
    industry: str = ""
    company_size: str = ""
    company_description: str = ""
    source: str = ""

    # BD-specific fields (Byou extensions)
    customer_level: Optional[str] = None
    intent_score: Optional[float] = None
    trust_score: Optional[float] = None
    last_strategy: Optional[str] = None
    risk_alerts: list[str] = Field(default_factory=list)

    # Sync metadata
    byou_updated_at: Optional[datetime] = None
    crm_updated_at: Optional[datetime] = None

    # Raw CRM data (for debugging / re-sync)
    raw_crm_data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


# ── Sync Status (persisted to SQLite) ─────────────────────────

class CRMSyncRecord(BaseModel):
    """One sync operation record."""
    id: Optional[int] = None
    byou_id: str
    crm_id: Optional[str] = None
    direction: SyncDirection
    status: SyncStatus = SyncStatus.PENDING
    provider: CRMProvider = CRMProvider.GENERIC

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Results
    error_message: Optional[str] = None
    conflict_fields: list[str] = Field(default_factory=list)

    # Snapshot of data at sync time
    byou_data_snapshot: dict[str, Any] = Field(default_factory=dict)
    crm_data_snapshot: dict[str, Any] = Field(default_factory=dict)

    # Retry
    retry_count: int = 0
    max_retries: int = 3


# ── CRM Configuration ──────────────────────────────────────────

class CRMConfig(BaseModel):
    """Runtime CRM configuration."""
    provider: CRMProvider = CRMProvider.GENERIC
    api_url: str = ""
    api_key: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)

    # OAuth (for Salesforce/HubSpot)
    oauth_token: Optional[str] = None
    oauth_refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None

    # Field mapping
    field_mappings: list[FieldMapping] = Field(default_factory=list)

    # Sync behavior
    auto_push: bool = True           # Auto-push after pipeline completes
    auto_pull: bool = False          # Auto-pull (requires webhook or polling)
    conflict_strategy: ConflictStrategy = ConflictStrategy.NEWEST_WINS
    pull_interval_seconds: int = 3600  # For polling mode

    # Endpoints (override defaults)
    contact_create_endpoint: str = ""
    contact_update_endpoint: str = ""
    contact_query_endpoint: str = ""
    contact_get_endpoint: str = ""

    @classmethod
    def default_field_mappings(cls) -> list[FieldMapping]:
        """Default field mappings for generic CRM."""
        return [
            FieldMapping(byou_field="name", crm_field="name"),
            FieldMapping(byou_field="email", crm_field="email"),
            FieldMapping(byou_field="phone", crm_field="phone"),
            FieldMapping(byou_field="company", crm_field="company"),
            FieldMapping(byou_field="title", crm_field="title"),
        ]

    @classmethod
    def salesforce_field_mappings(cls) -> list[FieldMapping]:
        return [
            FieldMapping(byou_field="name", crm_field="Name"),
            FieldMapping(byou_field="email", crm_field="Email"),
            FieldMapping(byou_field="phone", crm_field="Phone"),
            FieldMapping(byou_field="company", crm_field="Account.Name"),
            FieldMapping(byou_field="title", crm_field="Title"),
            FieldMapping(byou_field="industry", crm_field="Industry"),
        ]

    @classmethod
    def hubspot_field_mappings(cls) -> list[FieldMapping]:
        return [
            FieldMapping(byou_field="name", crm_field="properties.full_name"),
            FieldMapping(byou_field="email", crm_field="properties.email"),
            FieldMapping(byou_field="phone", crm_field="properties.phone"),
            FieldMapping(byou_field="company", crm_field="properties.company"),
            FieldMapping(byou_field="title", crm_field="properties.jobtitle"),
        ]
