"""Enrichment Subsystem — Data Merger.

多源数据归一化、去重、合并、provenance。
核心: MergePolicy.resolve() 决定字段级冲突。
"""

from __future__ import annotations

import logging
from typing import Any

from byou.tools.enrichment.types import (
    SourceType, SourcePriority, SourceRecord,
    CompanyProfile, DataProvenance, MergeDecision,
    EnrichmentRequest, EnrichmentResult,
)
from byou.tools.enrichment.policies import (
    SOURCE_PRIORITY_MAP, MergePolicy,
)

logger = logging.getLogger(__name__)


class DataMerger:
    """多源数据合并器。

    输入: 多个 SourceRecord + source priority
    输出: 合并后的 CompanyProfile (带 provenance + merge_decisions)
    """

    def __init__(self):
        self._decisions: list[MergeDecision] = []

    def merge_profiles(
        self, records: list[SourceRecord], base_name: str,
    ) -> tuple[CompanyProfile, list[MergeDecision]]:
        """合并多源 CompanyProfile 数据。

        Args:
            records: 所有 SourceRecord (raw_data 中需含 'profile' dict)
            base_name: 企业名 (兜底)

        Returns:
            (合并后的 CompanyProfile, merge decision 列表)
        """
        self._decisions = []

        # 收集所有源的 profile
        profiles_by_source: dict[SourceType, dict[str, Any]] = {}
        for r in records:
            if r.is_error:
                continue
            profile_data = r.raw_data.get("profile") if isinstance(r.raw_data, dict) else None
            if not profile_data:
                # 从 SourceRecord 的 provenance 或 raw 推断
                profile_data = r.raw_data if isinstance(r.raw_data, dict) else {}
            if profile_data:
                profiles_by_source[r.source] = profile_data

        # 所有字段
        all_fields = set()
        for p in profiles_by_source.values():
            all_fields.update(k for k, v in p.items() if v)

        # 逐字段合并
        merged: dict[str, Any] = {}
        provenance_list: list[DataProvenance] = []

        for field in sorted(all_fields):
            # 收集各源该字段的值
            values: dict[SourceType, str] = {}
            for src, profile in profiles_by_source.items():
                val = profile.get(field, "")
                if val:
                    values[src] = str(val)

            if not values:
                continue

            # 合并决策
            chosen_val, chosen_src, reason = MergePolicy.resolve(field, values)
            merged[field] = chosen_val

            decision = MergeDecision(
                field_name=field,
                values=values,
                chosen_source=chosen_src,
                chosen_value=chosen_val,
                conflict_detected=len(values) > 1,
                resolution=reason,
                reason=f"Chose {chosen_src}: {reason}" if chosen_src else "no_source",
            )
            self._decisions.append(decision)

            # Provenance
            if chosen_src:
                provenance_list.append(DataProvenance(
                    field_name=field,
                    source=chosen_src,
                    source_priority=SOURCE_PRIORITY_MAP.get(chosen_src, SourcePriority.FALLBACK),
                    raw_value=values.get(chosen_src, ""),
                    normalized_value=chosen_val,
                    confidence=0.85 if decision.conflict_detected else 0.95,
                ))

        # 构建 CompanyProfile
        profile = CompanyProfile(
            identity={"name": base_name},  # type: ignore  — 后面由 orchestrator 补充
            provenance=provenance_list,
            data_quality=self._quality_level(provenance_list),
        )

        # 安全赋值已知字段
        for field, val in merged.items():
            if field in CompanyProfile.model_fields:
                setattr(profile, field, val)

        return profile, self._decisions

    def _quality_level(self, provenance: list[DataProvenance]) -> str:
        """根据 provenance 评定数据质量"""
        primary_count = sum(1 for p in provenance if p.source_priority == SourcePriority.PRIMARY)
        total = len(provenance) or 1
        primary_ratio = primary_count / total

        if primary_ratio >= 0.6:
            return "high"
        elif primary_ratio >= 0.3:
            return "medium"
        return "low"

    @property
    def decisions(self) -> list[MergeDecision]:
        return self._decisions
