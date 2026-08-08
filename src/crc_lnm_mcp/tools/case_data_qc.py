"""Register the independent case quality-control tool."""

from typing import Any, Literal
from uuid import UUID

from pydantic import UUID4

from crc_lnm_mcp.contracts.case_qc import CaseQCInput
from crc_lnm_mcp.contracts.common import CaseRef
from crc_lnm_mcp.runtime import RuntimeProvider

TOOL_NAME = "crc_lnm_case_data_qc"
TOOL_DESCRIPTION = (
    "对结直肠癌病例数据进行质量控制检查，验证临床信息、CT影像特征和病理特征的"
    "完整性和一致性，支持回退策略配置。"
)


def register(mcp: Any, runtime: RuntimeProvider) -> None:
    async def tool(
        contract_version: Literal["1.1.0"],
        request_id: UUID4,
        trace_id: UUID4,
        case_ref: CaseRef,
        input: CaseQCInput,
    ) -> dict[str, Any]:
        del contract_version
        request_uuid = UUID(str(request_id))
        trace_uuid = UUID(str(trace_id))
        data = runtime.cases.case_data_qc(
            case_ref,
            request_id=request_uuid,
            trace_id=trace_uuid,
        )
        data["ct_source_preference"] = input.ct_source_preference
        data["fallback_policy"] = input.fallback_policy
        return {
            "contract_version": "1.1.0",
            "request_id": str(request_uuid),
            "trace_id": str(trace_uuid),
            "tool_name": TOOL_NAME,
            "status": {
                "code": 2001,
                "name": "OK_WITH_WARNINGS",
                "message": "Demo case quality control completed.",
                "severity": "warning",
                "retryable": False,
            },
            "data": data,
            "errors": [],
            "warnings": [
                {
                    "code": "DEMO_CASE",
                    "message": (
                        "This packaged record is synthetic and validates deployment flow only."
                    ),
                    "field": "case_ref",
                    "review_required": True,
                }
            ],
            "provenance": {
                "service_version": "1.0.19",
                "model_version": None,
                "model_schema_version": None,
                "model_feature_order_sha256": None,
            },
        }

    mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)(tool)


__all__ = ["TOOL_NAME", "register"]