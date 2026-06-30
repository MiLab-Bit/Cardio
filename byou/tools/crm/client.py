"""CRM Tool — multi-provider CRM client.

Supports:
- Generic REST CRM (configurable endpoints & field mappings)
- Salesforce (REST API + OAuth 2.0 token refresh)
- HubSpot (REST API)

All providers implement the same interface:
- create_contact()
- update_contact()
- upsert_contact()
- get_contact()
- query_contacts()
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

from byou.tools.crm.models import (
    CRMContact, CRMConfig, CRMProvider,
    SyncStatus, FieldMapping,
)

logger = logging.getLogger(__name__)

# ── Base Provider ───────────────────────────────────────────────

class BaseCRMProvider:
    """Abstract base for all CRM providers."""

    def __init__(self, config: CRMConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            headers.update(self.config.extra_headers)
            self._client = httpx.AsyncClient(
                base_url=self.config.api_url.rstrip("/"),
                headers=headers,
                timeout=30.0,
            )
        return self._client

    def _byou_to_crm_fields(self, contact: CRMContact) -> dict[str, Any]:
        """Convert CRMContact to CRM-specific field dict."""
        if self.config.field_mappings:
            result = {}
            contact_dict = contact.model_dump()
            mapping = {m.byou_field: m.crm_field for m in self.config.field_mappings}
            for byou_field, crm_field in mapping.items():
                if hasattr(contact, byou_field):
                    value = getattr(contact, byou_field)
                    if value:
                        result[crm_field] = value
            return result

        # No mapping — dump all non-empty fields
        return {k: v for k, v in contact.model_dump().items()
                if v and k not in ("byou_id", "crm_id", "raw_crm_data",
                                   "byou_updated_at", "crm_updated_at")}

    async def create_contact(self, contact: CRMContact) -> tuple[SyncStatus, str, dict]:
        """Create contact in CRM. Returns (status, crm_id, response_data)."""
        raise NotImplementedError

    async def update_contact(self, crm_id: str, contact: CRMContact) -> tuple[SyncStatus, dict]:
        """Update existing CRM contact. Returns (status, response_data)."""
        raise NotImplementedError

    async def upsert_contact(self, contact: CRMContact) -> tuple[SyncStatus, str, dict]:
        """Create or update. Returns (status, crm_id, response_data)."""
        # Default: try update, fall back to create
        if contact.crm_id:
            status, resp = await self.update_contact(contact.crm_id, contact)
            if status == SyncStatus.SUCCESS:
                return status, contact.crm_id, resp
        return await self.create_contact(contact)

    async def get_contact(self, crm_id: str) -> tuple[SyncStatus, CRMContact | None]:
        """Fetch contact from CRM by ID."""
        raise NotImplementedError

    async def query_contacts(self, email: str = "", phone: str = "",
                            name: str = "") -> list[CRMContact]:
        """Query CRM for contacts matching criteria."""
        raise NotImplementedError

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# ── Generic REST Provider ───────────────────────────────────────

class GenericCRMProvider(BaseCRMProvider):
    """Configurable REST API CRM provider.

    Expected CRM API:
    - POST /contacts       → create
    - PUT  /contacts/{id}  → update
    - GET  /contacts/{id}  → get
    - GET  /contacts?q=x   → query
    Response format: { "id": "...", ... } or { "data": { "id": "..." } }
    """

    async def create_contact(self, contact: CRMContact) -> tuple[SyncStatus, str, dict]:
        try:
            client = await self._get_client()
            fields = self._byou_to_crm_fields(contact)
            endpoint = self.config.contact_create_endpoint or "/contacts"
            resp = await client.post(endpoint, json=fields)
            resp.raise_for_status()
            data = resp.json()
            crm_id = data.get("id") or data.get("data", {}).get("id") or ""
            if not crm_id:
                return SyncStatus.FAILED, "", {"error": "No ID in response", "response": data}
            logger.info("CRM: created contact id=%s", crm_id)
            return SyncStatus.SUCCESS, str(crm_id), data
        except httpx.HTTPStatusError as e:
            logger.error("CRM create failed: %s %s", e.response.status_code, e.response.text)
            return SyncStatus.FAILED, "", {"error": str(e), "status": e.response.status_code}
        except Exception as e:
            logger.error("CRM create error: %s", e)
            return SyncStatus.FAILED, "", {"error": str(e)}

    async def update_contact(self, crm_id: str, contact: CRMContact) -> tuple[SyncStatus, dict]:
        try:
            client = await self._get_client()
            fields = self._byou_to_crm_fields(contact)
            endpoint = (self.config.contact_update_endpoint or "/contacts/{id}").replace("{id}", crm_id)
            resp = await client.put(endpoint, json=fields)
            resp.raise_for_status()
            data = resp.json()
            logger.info("CRM: updated contact id=%s", crm_id)
            return SyncStatus.SUCCESS, data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Contact deleted in CRM — need to recreate
                return SyncStatus.FAILED, {"error": "not_found", "status": 404}
            logger.error("CRM update failed: %s", e)
            return SyncStatus.FAILED, {"error": str(e)}
        except Exception as e:
            logger.error("CRM update error: %s", e)
            return SyncStatus.FAILED, {"error": str(e)}

    async def get_contact(self, crm_id: str) -> tuple[SyncStatus, CRMContact | None]:
        try:
            client = await self._get_client()
            endpoint = (self.config.contact_get_endpoint or "/contacts/{id}").replace("{id}", crm_id)
            resp = await client.get(endpoint)
            resp.raise_for_status()
            data = resp.json()
            contact = self._crm_data_to_contact(data, crm_id)
            return SyncStatus.SUCCESS, contact
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return SyncStatus.SUCCESS, None
            return SyncStatus.FAILED, None
        except Exception as e:
            logger.error("CRM get error: %s", e)
            return SyncStatus.FAILED, None

    async def query_contacts(self, email: str = "", phone: str = "",
                            name: str = "") -> list[CRMContact]:
        try:
            client = await self._get_client()
            params = {}
            if email:
                params["email"] = email
            if phone:
                params["phone"] = phone
            if name:
                params["q"] = name
            endpoint = self.config.contact_query_endpoint or "/contacts"
            resp = await client.get(endpoint, params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            return [self._crm_data_to_contact(item) for item in items]
        except Exception as e:
            logger.error("CRM query error: %s", e)
            return []

    def _crm_data_to_contact(self, data: dict, crm_id: str = "") -> CRMContact:
        """Convert CRM API response to CRMContact."""
        cid = crm_id or str(data.get("id", ""))
        # Reverse field mapping
        contact_data = {"crm_id": cid, "raw_crm_data": data}
        if self.config.field_mappings:
            for m in self.config.field_mappings:
                value = data
                for key in m.crm_field.split("."):
                    value = value.get(key, {})
                if isinstance(value, str) and value:
                    contact_data[m.byou_field] = value
        else:
            for k, v in data.items():
                if isinstance(v, (str, int, float)) and k in CRMContact.model_fields:
                    contact_data[k] = v
        return CRMContact(**contact_data)


# ── Salesforce Provider ────────────────────────────────────────

class SalesforceProvider(BaseCRMProvider):
    """Salesforce REST API provider with OAuth 2.0 token refresh.

    Uses: /services/data/vXX.X/sobjects/Contact

    OAuth flow:
    - Access token stored in config.api_key
    - Refresh token stored in config.oauth_refresh_token
    - Auto-refreshes when token expires (401 response or token_expires_at)
    - Updates config.token_expires_at after refresh
    """

    def __init__(self, config: CRMConfig):
        super().__init__(config)
        # Salesforce instance URL (e.g., https://your-instance.salesforce.com)
        self.instance_url = config.api_url.rstrip("/") if config.api_url else ""
        # OAuth client credentials (for token refresh)
        self._client_id = getattr(config, "oauth_client_id", "")
        self._client_secret = getattr(config, "oauth_client_secret", "")
        # Token refresh lock (prevent concurrent refreshes)
        self._refresh_lock = asyncio.Lock() if hasattr(asyncio, "Lock") else None

    async def _ensure_token(self) -> None:
        """Ensure access token is valid. Refresh if expired."""
        if not self._needs_token_refresh():
            return
        await self._refresh_token()

    def _needs_token_refresh(self) -> bool:
        """Check if token needs refresh (expired or expires in < 5 minutes)."""
        if not self.config.token_expires_at:
            # No expiry info — assume token is valid (will catch 401 later)
            return False
        # Refresh if expires in less than 5 minutes (buffer)
        buffer = timedelta(minutes=5)
        return datetime.now() + buffer >= self.config.token_expires_at

    async def _refresh_token(self) -> None:
        """Refresh OAuth access token using refresh_token."""
        refresh_token = self.config.oauth_refresh_token
        if not refresh_token:
            logger.warning("Salesforce: no refresh_token available — cannot refresh")
            return

        # Use asyncio.Lock if available (Python 3.7+)
        if hasattr(asyncio, "Lock"):
            async with asyncio.Lock():
                await self._do_token_refresh(refresh_token)
        else:
            await self._do_token_refresh(refresh_token)

    async def _do_token_refresh(self, refresh_token: str) -> None:
        """Actual token refresh request."""
        try:
            # Salesforce token refresh endpoint
            # https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_refresh_token.htm
            token_url = "https://login.salesforce.com/services/oauth2/token"

            # If using sandbox, use test.salesforce.com
            if "sandbox" in self.instance_url.lower() or "--sb" in self.instance_url:
                token_url = "https://test.salesforce.com/services/oauth2/token"

            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id or self.config.extra_headers.get("X-Client-Id", ""),
                "client_secret": self._client_secret or "",
            }

            # Use a fresh client (no auth headers) for token refresh
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(token_url, data=data)
                resp.raise_for_status()
                token_data = resp.json()

            # Update config with new tokens
            new_access_token = token_data["access_token"]
            self.config.api_key = new_access_token

            # Update refresh_token if rotated (some orgs do this)
            if "refresh_token" in token_data:
                self.config.oauth_refresh_token = token_data["refresh_token"]

            # Calculate new expiry
            expires_in = token_data.get("expires_in", 7200)  # default 2 hours
            self.config.token_expires_at = datetime.now() + timedelta(seconds=expires_in)

            # Update instance URL if provided
            if "instance_url" in token_data:
                self.instance_url = token_data["instance_url"].rstrip("/")

            # Reset HTTP client (new auth header)
            if self._client:
                await self._client.aclose()
                self._client = None

            logger.info(
                "Salesforce: token refreshed, expires at %s",
                self.config.token_expires_at.isoformat(),
            )

        except Exception as e:
            logger.error("Salesforce token refresh failed: %s", e)
            raise

    async def _handle_401(self, resp: httpx.Response) -> bool:
        """Handle 401 by refreshing token. Returns True if token was refreshed."""
        if resp.status_code != 401:
            return False
        try:
            await self._refresh_token()
            return True
        except Exception as e:
            logger.error("Salesforce: 401 retry failed: %s", e)
            return False

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make request with automatic token refresh on 401."""
        await self._ensure_token()
        client = await self._get_client()

        # Inject auth header
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self.config.api_key}"
        headers["Content-Type"] = "application/json"
        kwargs["headers"] = headers

        resp = await getattr(client, method)(url, **kwargs)

        if resp.status_code == 401:
            # Token expired — refresh and retry once
            if await self._handle_401(resp):
                # Update auth header with new token
                headers["Authorization"] = f"Bearer {self.config.api_key}"
                resp = await getattr(client, method)(url, **kwargs)

        resp.raise_for_status()
        return resp

    async def create_contact(self, contact: CRMContact) -> tuple[SyncStatus, str, dict]:
        try:
            fields = self._byou_to_crm_fields(contact)
            # Salesforce expects LastName + FirstName
            name_parts = (contact.name or "").split(" ", 1)
            fields["LastName"] = name_parts[-1] if len(name_parts) > 1 else (contact.name or "Unknown")
            fields["FirstName"] = name_parts[0] if len(name_parts) > 1 else ""

            url = f"{self.instance_url}/services/data/v59.0/sobjects/Contact"
            resp = await self._request_with_retry("post", url, json=fields)
            data = resp.json()
            crm_id = data.get("id", "")
            logger.info("Salesforce: created Contact id=%s", crm_id)
            return SyncStatus.SUCCESS, crm_id, data
        except httpx.HTTPStatusError as e:
            logger.error("Salesforce create failed: %s %s", e.response.status_code, e.response.text)
            return SyncStatus.FAILED, "", {"error": str(e), "status": e.response.status_code}
        except Exception as e:
            logger.error("Salesforce create error: %s", e)
            return SyncStatus.FAILED, "", {"error": str(e)}

    async def update_contact(self, crm_id: str, contact: CRMContact) -> tuple[SyncStatus, dict]:
        try:
            fields = self._byou_to_crm_fields(contact)
            url = f"{self.instance_url}/services/data/v59.0/sobjects/Contact/{crm_id}"
            resp = await self._request_with_retry("patch", url, json=fields)
            return SyncStatus.SUCCESS, {"updated": True}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return SyncStatus.FAILED, {"error": "not_found", "status": 404}
            logger.error("Salesforce update failed: %s", e)
            return SyncStatus.FAILED, {"error": str(e)}
        except Exception as e:
            logger.error("Salesforce update error: %s", e)
            return SyncStatus.FAILED, {"error": str(e)}

    async def get_contact(self, crm_id: str) -> tuple[SyncStatus, CRMContact | None]:
        try:
            url = f"{self.instance_url}/services/data/v59.0/sobjects/Contact/{crm_id}"
            resp = await self._request_with_retry("get", url)
            data = resp.json()
            return SyncStatus.SUCCESS, self._sf_to_contact(data, crm_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return SyncStatus.SUCCESS, None
            return SyncStatus.FAILED, None
        except Exception as e:
            logger.error("Salesforce get error: %s", e)
            return SyncStatus.FAILED, None

    async def query_contacts(self, email: str = "", phone: str = "",
                            name: str = "") -> list[CRMContact]:
        try:
            where = []
            if email:
                where.append(f"Email='{email}'")
            if phone:
                where.append(f"Phone LIKE '%{phone}%'")
            if name:
                where.append(f"Name LIKE '%{name}%'")
            soql = "SELECT Id, Name, Email, Phone, Account.Name, Title FROM Contact"
            if where:
                soql += " WHERE " + " OR ".join(where)
            url = f"{self.instance_url}/services/data/v59.0/query"
            resp = await self._request_with_retry("get", url, params={"q": soql})
            data = resp.json()
            return [self._sf_to_contact(rec, rec["Id"]) for rec in data.get("records", [])]
        except Exception as e:
            logger.error("Salesforce query error: %s", e)
            return []

    def _sf_to_contact(self, data: dict, crm_id: str) -> CRMContact:
        name = data.get("Name", "")
        account_name = ""
        acct = data.get("Account", {})
        if isinstance(acct, dict):
            account_name = acct.get("Name", "")
        return CRMContact(
            crm_id=crm_id,
            name=name,
            email=data.get("Email", ""),
            phone=data.get("Phone", ""),
            title=data.get("Title", ""),
            company=account_name,
            raw_crm_data=data,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
            )
        return self._client

    # ── OAuth Helper Methods ────────────────────────────────────

    @classmethod
    def generate_auth_url(cls, client_id: str, redirect_uri: str,
                          instance_url: str = "https://login.salesforce.com") -> str:
        """Generate OAuth authorization URL for user to grant access."""
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "api refresh_token",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{instance_url}/services/oauth2/authorize?{query}"

    async def exchange_code_for_token(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        instance_url: str = "https://login.salesforce.com",
    ) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        token_url = f"{instance_url}/services/oauth2/token"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(token_url, data=data)
            resp.raise_for_status()
            token_data = resp.json()

        # Update config
        self.config.api_key = token_data["access_token"]
        self.config.oauth_refresh_token = token_data.get("refresh_token", "")
        expires_in = int(token_data.get("expires_in", 7200))
        self.config.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        self.instance_url = token_data.get("instance_url", self.instance_url).rstrip("/")

        return token_data


# ── HubSpot Provider ───────────────────────────────────────────

class HubSpotProvider(BaseCRMProvider):
    """HubSpot CRM REST API provider.

    Uses: /crm/v3/objects/contacts
    """

    async def create_contact(self, contact: CRMContact) -> tuple[SyncStatus, str, dict]:
        try:
            client = await self._get_client()
            fields = self._byou_to_crm_fields(contact)
            # HubSpot expects properties dict
            payload = {"properties": fields}
            url = "https://api.hubapi.com/crm/v3/objects/contacts"
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            crm_id = data.get("id", "")
            logger.info("HubSpot: created contact id=%s", crm_id)
            return SyncStatus.SUCCESS, crm_id, data
        except Exception as e:
            logger.error("HubSpot create error: %s", e)
            return SyncStatus.FAILED, "", {"error": str(e)}

    async def update_contact(self, crm_id: str, contact: CRMContact) -> tuple[SyncStatus, dict]:
        try:
            client = await self._get_client()
            fields = self._byou_to_crm_fields(contact)
            payload = {"properties": fields}
            url = f"https://api.hubapi.com/crm/v3/objects/contacts/{crm_id}"
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            resp = await client.patch(url, json=payload, headers=headers)
            resp.raise_for_status()
            return SyncStatus.SUCCESS, resp.json()
        except Exception as e:
            logger.error("HubSpot update error: %s", e)
            return SyncStatus.FAILED, {"error": str(e)}

    async def get_contact(self, crm_id: str) -> tuple[SyncStatus, CRMContact | None]:
        try:
            client = await self._get_client()
            url = f"https://api.hubapi.com/crm/v3/objects/contacts/{crm_id}"
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return SyncStatus.SUCCESS, self._hs_to_contact(data)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return SyncStatus.SUCCESS, None
            return SyncStatus.FAILED, None
        except Exception as e:
            logger.error("HubSpot get error: %s", e)
            return SyncStatus.FAILED, None

    async def query_contacts(self, email: str = "", phone: str = "",
                            name: str = "") -> list[CRMContact]:
        try:
            client = await self._get_client()
            # HubSpot search API
            url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            filters = []
            if email:
                filters.append({"propertyName": "email", "operator": "EQ", "value": email})
            if phone:
                filters.append({"propertyName": "phone", "operator": "CONTAINS_TOKEN", "value": phone})
            payload = {"filterGroups": [{"filters": filters}]} if filters else {}
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [self._hs_to_contact(rec) for rec in data.get("results", [])]
        except Exception as e:
            logger.error("HubSpot query error: %s", e)
            return []

    def _hs_to_contact(self, data: dict) -> CRMContact:
        props = data.get("properties", {})
        return CRMContact(
            crm_id=data.get("id", ""),
            name=props.get("full_name", props.get("email", "")),
            email=props.get("email", ""),
            phone=props.get("phone", ""),
            title=props.get("jobtitle", ""),
            company=props.get("company", ""),
            raw_crm_data=data,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client


# ── Provider Factory ───────────────────────────────────────────

def create_crm_provider(config: CRMConfig) -> BaseCRMProvider:
    """Create CRM provider instance based on config."""
    if config.provider == CRMProvider.SALESFORCE:
        return SalesforceProvider(config)
    elif config.provider == CRMProvider.HUBSPOT:
        return HubSpotProvider(config)
    else:
        return GenericCRMProvider(config)
