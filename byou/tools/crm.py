"""CRM Tool — external CRM integration with shared config."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from byou.config import get_settings

logger = logging.getLogger(__name__)


class CRMTool:
    """CRM system integration."""

    def __init__(self):
        settings = get_settings()
        self.api_url = settings.crm_api_url
        self.api_key = settings.crm_api_key
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    async def connect(self) -> bool:
        if not self.api_url:
            logger.warning("CRM API URL not configured")
            return False
        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )
        self._connected = True
        logger.info("CRM connected: %s", self.api_url)
        return True

    async def create_or_update_contact(self, contact_data: dict) -> dict:
        logger.info("CRM: upsert contact %s", contact_data.get("name"))
        return {"status": "ok", "action": "upsert", "contact": contact_data}

    async def add_note(self, contact_id: str, note: str) -> dict:
        logger.info("CRM: add note contact=%s", contact_id)
        return {"status": "ok", "action": "add_note", "contact_id": contact_id}

    async def create_task(self, task_data: dict) -> dict:
        logger.info("CRM: create task %s", task_data.get("description", ""))
        return {"status": "ok", "action": "create_task", "task": task_data}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            self._connected = False
