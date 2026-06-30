from .client import (
    BaseCRMProvider, GenericCRMProvider,
    SalesforceProvider, HubSpotProvider,
    create_crm_provider, CRMProvider as CRMProviderEnum,
)
from .models import (
    CRMContact, CRMConfig, CRMSyncRecord,
    SyncStatus, SyncDirection, ConflictStrategy, CRMProvider,
)
from .sync import CRMSyncEngine, resolve_conflict
from .service import CRMService

# Backward compatibility
CRMTool = CRMService

__all__ = [
    "BaseCRMProvider", "GenericCRMProvider",
    "SalesforceProvider", "HubSpotProvider",
    "create_crm_provider", "CRMProviderEnum",
    "CRMContact", "CRMConfig", "CRMSyncRecord",
    "SyncStatus", "SyncDirection", "ConflictStrategy", "CRMProvider",
    "CRMSyncEngine", "resolve_conflict",
    "CRMService", "CRMTool",
]
