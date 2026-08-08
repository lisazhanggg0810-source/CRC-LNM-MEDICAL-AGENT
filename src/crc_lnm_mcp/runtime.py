"""Lightweight provider holder; medical layers are added lazily by later stages."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from .errors import ErrorCode
from .services.case_service import CaseAndFeatureProvider
from .services.metadata_service import MetadataProvider
from .services.prediction_service import PredictionProvider


class RuntimeProvider:
    """Own independently lazy runtime providers without eager initialization."""

    __slots__ = ("_cases", "_metadata", "prediction")

    def __init__(self) -> None:
        self._metadata = MetadataProvider()
        self._cases = CaseAndFeatureProvider()
        self.prediction = PredictionProvider(self._metadata, self._cases)

    @property
    def metadata(self) -> MetadataProvider:
        return self._metadata

    @property
    def cases(self) -> CaseAndFeatureProvider:
        return self._cases

    def not_ready(self, tool_name: str, request_id: UUID, trace_id: UUID) -> dict[str, Any]:
        return {
            "contract_version": "1.1.0",
            "request_id": str(request_id),
            "trace_id": str(trace_id),
            "tool_name": tool_name,
            "status": {
                "code": 5030,
                "name": ErrorCode.SERVICE_UNAVAILABLE,
                "message": "Tool runtime is not ready in this implementation stage.",
                "severity": "error",
                "retryable": True,
            },
            "data": None,
            "errors": [
                {
                    "field": None,
                    "code": ErrorCode.SERVICE_UNAVAILABLE,
                    "message": "Tool runtime is not ready in this implementation stage.",
                    "suggestion": "Retry after the next staged runtime component is enabled.",
                }
            ],
            "warnings": [],
            "provenance": {
                "service_version": "1.0.19",
                "model_version": None,
                "model_schema_version": None,
                "model_feature_order_sha256": None,
            },
        }


__all__ = ["RuntimeProvider"]
