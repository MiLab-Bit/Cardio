"""Byou exceptions — shared exception hierarchy."""

from __future__ import annotations

from typing import Any


class ByouError(Exception):
    """Base Byou exception."""


class PipelineRejected(ByouError):
    """Raised when a pipeline stage is rejected by the approval system.

    Carries structured context so the caller can surface why and what was rejected.
    """

    def __init__(
        self,
        message: str,
        *,
        pipeline_id: str = "",
        stage: str = "",
        request_id: str = "",
        rejected_by: str = "",
        reason: str = "",
    ):
        super().__init__(message)
        self.pipeline_id = pipeline_id
        self.stage = stage
        self.request_id = request_id
        self.rejected_by = rejected_by
        self.reason = reason
