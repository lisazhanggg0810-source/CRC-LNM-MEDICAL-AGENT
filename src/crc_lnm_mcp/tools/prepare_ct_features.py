"""Register the independent CT feature tool."""

from typing import Any, Literal
from uuid import UUID

from pydantic import UUID4

from crc_lnm_mcp.contracts.common import CaseRef
from crc_lnm_mcp.contracts.ct_features import PrepareCTInput
from crc_lnm_mcp.runtime import RuntimeProvider

TOOL_NAME = "crc_lnm_prepare_ct_features"
TOOL_DESCRIPTION = (
    "准备结直肠癌病例的CT影像特征，从预计算数据中提取并验证1409维CT特征向量。"
    "用于后续淋巴转移预测。"
)


def register(mcp: Any, runtime: RuntimeProvider) -> None:
    async def tool(
        contract_version: Literal["1.1.0"],
        request_id: UUID4,
        trace_id: UUID4,
        case_ref: CaseRef,
        input: PrepareCTInput,
    ) -> dict[str, Any]:
        del contract_version
        request_uuid = UUID(str(request_id))
        trace_uuid = UUID(str(trace_id))
        data = runtime.cases.prepare_ct_features(
            case_ref,
            qc_artifact_id=input.qc_artifact_id,
            request_id=request_uuid,
            trace_id=trace_uuid,
        )
        return {
            "contract_version": "1.1.0",
            "request_id": str(request_uuid),
            "trace_id": str(trace_uuid),
            "tool_name": TOOL_NAME,
            "status": {
                "code": 2000,
                "name": "OK",
                "message": "CT features prepared.",
                "severity": "info",
                "retryable": False,
            },
            "data": data,
            "errors": [],
            "warnings": [],
            "provenance": {
                "service_version": "1.0.19",
                "model_version": None,
                "model_schema_version": "1.0.0",
                "model_feature_order_sha256": None,
            },
        }

    mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)(tool)


__all__ = ["TOOL_NAME", "register"]