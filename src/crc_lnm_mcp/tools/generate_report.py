"""Register the independent artifact-only report tool."""

from typing import Any, Literal
from uuid import UUID

from pydantic import UUID4

from crc_lnm_mcp.contracts.common import CaseRef
from crc_lnm_mcp.contracts.report import GenerateReportInput
from crc_lnm_mcp.runtime import RuntimeProvider

TOOL_NAME = "crc_lnm_generate_report"
TOOL_DESCRIPTION = (
    "生成基于质控结果和预测结果的综合研究报告，整合淋巴转移预测结果，"
    "生成结构化的研究报告供医学专业人员参考。"
)


def register(mcp: Any, runtime: RuntimeProvider) -> None:
    async def tool(
        contract_version: Literal["1.1.0"],
        request_id: UUID4,
        trace_id: UUID4,
        case_ref: CaseRef,
        input: GenerateReportInput,
    ) -> dict[str, Any]:
        del contract_version
        request_uuid = UUID(str(request_id))
        trace_uuid = UUID(str(trace_id))
        data = runtime.cases.generate_report(
            case_ref,
            qc_artifact_id=input.qc_artifact_id,
            prediction_artifact_id=input.prediction_artifact_id,
            request_id=request_uuid,
            trace_id=trace_uuid,
        )
        return {
            "contract_version": "1.1.0",
            "request_id": str(request_uuid),
            "trace_id": str(trace_uuid),
            "tool_name": TOOL_NAME,
            "status": {
                "code": 2001,
                "name": "OK_WITH_WARNINGS",
                "message": "Research report generated.",
                "severity": "warning",
                "retryable": False,
            },
            "data": data,
            "errors": [],
            "warnings": [
                {
                    "code": "RESEARCH_USE_ONLY",
                    "message": "The report is not a clinical diagnosis.",
                    "field": "data.safety_statement",
                    "review_required": True,
                }
            ],
            "provenance": {
                "service_version": "1.0.19",
                "model_version": None,
                "model_schema_version": "1.0.0",
                "model_feature_order_sha256": runtime.metadata.get_model_info()[
                    "feature_order_sha256"
                ],
            },
        }

    mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)(tool)


__all__ = ["TOOL_NAME", "register"]