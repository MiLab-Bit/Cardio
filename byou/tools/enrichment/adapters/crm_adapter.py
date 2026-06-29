"""Enrichment Subsystem — CRM Adapter (Salesforce / HubSpot).

只读优先的 CRM 适配器。
核心原则:
- ResearcherAgent 默认只读 CRM
- 写操作需要 explicit allow_crm_write + allowed_crm_fields
- 所有写操作记录 audit log
- CRM 无权限 → 静默跳过，不阻断 pipeline
"""

from __future__ import annotations

import logging
from typing import Any

from byou.tools.enrichment.types import (
    SourceType, SourcePriority, SourceRecord, EnrichmentRequest,
    CRMAccountRef, DataProvenance,
)

logger = logging.getLogger(__name__)

# 不允许自动写入的字段
_NEVER_WRITE_FIELDS = {
    "unified_social_credit_code", "legal_person", "risk_score",
    "data_quality", "provenance", "enrichment_timestamp",
}

# 允许写入的字段 (需审批)
_ALLOWED_WRITE_FIELDS = {
    "website", "contact_emails", "contact_phones", "company_description",
    "industry", "employee_count_range", "revenue_range",
    "social_links", "products_services",
}


class CRMAdapter:
    """CRM 系统适配器 (当前为只读占位)。

    优先级:
    1. 如果有 Salesforce MCP → 对接
    2. 如果有 HubSpot MCP → 对接
    3. 如果都没有 → 静默跳过 (不阻断 pipeline)

    写入边界:
    - ResearcherAgent 默认不写 CRM
    - 只有 request.allow_crm_write=True + allowed_crm_fields 指定时才写
    - write 前弹出 approval gate (预留)
    """

    def __init__(self, crm_type: SourceType = SourceType.CRM_SALESFORCE):
        self.crm_type = crm_type
        self._connected = False  # 设为 True 当 MCP 连接成功
        self._mcp_client = None   # 预留 MCP client 引用

    async def enrich(
        self, request: EnrichmentRequest,
    ) -> list[SourceRecord]:
        """查询 CRM 中是否有企业记录。

        Returns:
            一个或多个 SourceRecord (可能跨多个 CRM)
        """
        if not self._connected:
            return self._no_crm_record("CRM not connected")

        # TODO: 对接真实 MCP
        # 权限: ResearcherAgent 默认可以 query CRM (只读)
        # await self._mcp_client.call_tool("query", {"object": "Account", "where": f"Name LIKE '%{company_name}%'"})
        return self._no_crm_record("mock — not implemented")

    async def write_back(
        self, request: EnrichmentRequest, fields: dict[str, Any],
    ) -> SourceRecord:
        """回写 CRM (需审批)。

        Args:
            request: 必须 allow_crm_write=True
            fields: 要写入的字段, 必须全部在 allowed_crm_fields 内

        Returns:
            SourceRecord 记录写入结果
        """
        # 安全检查
        if not request.allow_crm_write:
            return SourceRecord(
                source=self.crm_type,
                source_priority=SourcePriority.PRIMARY,
                is_error=True,
                error_message="CRM write not allowed: allow_crm_write=False",
            )

        # 过滤不允许写入的字段
        write_fields = {}
        for k, v in fields.items():
            if k in _NEVER_WRITE_FIELDS:
                logger.warning("CRM write blocked: field=%s is never-writable", k)
                continue
            if k not in _ALLOWED_WRITE_FIELDS:
                logger.warning("CRM write blocked: field=%s not in allowed list", k)
                continue
            if request.allowed_crm_fields and k not in request.allowed_crm_fields:
                logger.warning("CRM write blocked: field=%s not in request allowed_crm_fields", k)
                continue
            write_fields[k] = v

        if not write_fields:
            return SourceRecord(
                source=self.crm_type,
                source_priority=SourcePriority.PRIMARY,
                is_error=True,
                error_message="No fields allowed for write",
            )

        # 预留 approval gate
        # if not await self._request_approval(write_fields):
        #     return SourceRecord(..., error_message="Approval denied")

        # TODO: 对接真实 MCP
        return SourceRecord(
            source=self.crm_type,
            source_priority=SourcePriority.PRIMARY,
            raw_data={"written_fields": write_fields},
            error_message="mock — not implemented",
        )

    def _no_crm_record(self, reason: str) -> list[SourceRecord]:
        return [SourceRecord(
            source=self.crm_type,
            source_priority=SourcePriority.PRIMARY,
            is_error=True,
            error_message=reason,
        )]

    def connect(self) -> bool:
        """尝试连接 CRM — 预留"""
        logger.info("CRM adapter (%s): connection stub", self.crm_type)
        return self._connected

    @property
    def is_available(self) -> bool:
        return self._connected
