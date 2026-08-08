"""Register the independent model-information tool."""

from typing import Any, Literal
from uuid import UUID

from pydantic import UUID4

from crc_lnm_mcp.contracts.model_info import ModelInfoInput
from crc_lnm_mcp.runtime import RuntimeProvider

TOOL_NAME = "crc_lnm_get_model_info"
TOOL_DESCRIPTION = (
    "获取CRC-LNM单模型部署的元数据信息，包括模型ID、版本、阈值、训练参数等。"
    "该工具用于查询当前部署模型的规格和配置信息。"
)


def register(mcp: Any, runtime: RuntimeProvider) -> None:
    async def tool(
        contract_version: Literal["1.1.0"],
        request_id: UUID4,
        trace_id: UUID4,
        input: ModelInfoInput,
    ) -> dict[str, Any]:
        del contract_version, input
        request_uuid = UUID(str(request_id))
        trace_uuid = UUID(str(trace_id))
        data = runtime.metadata.get_model_info()
        return {
            "contract_version": "1.1.0",
            "request_id": str(request_uuid),
            "trace_id": str(trace_uuid),
            "tool_name": TOOL_NAME,
            "status": {
                "code": 2001,
                "name": "OK_WITH_WARNINGS",
                "message": "Single-model deployment metadata loaded.",
                "severity": "warning",
                "retryable": False,
            },
            "data": data,
            "errors": [],
            "warnings": [
                {
                    "code": "SINGLE_MODEL_DEPLOYMENT",
                    "message": "One selected model replaces the former five-member ensemble.",
                    "field": "data.member_count",
                    "review_required": True,
                },
                {
                    "code": "THRESHOLD_NOT_RECALIBRATED",
                    "message": (
                        "The former ensemble threshold is retained without "
                        "single-model recalibration."
                    ),
                    "field": "data.threshold",
                    "review_required": True,
                },
            ],
            "provenance": {
                "service_version": "1.0.19",
                "model_version": data["selected_model_id"],
                "model_schema_version": data["model_schema_version"],
                "model_feature_order_sha256": data["feature_order_sha256"],
            },
        }

    mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)(tool)


__all__ = ["TOOL_NAME", "register"]