"""Register the independent single-model prediction tool."""

from typing import Any, Literal
from uuid import UUID

from pydantic import UUID4

from crc_lnm_mcp.contracts.common import CaseRef
from crc_lnm_mcp.contracts.prediction import PredictMultimodalInput
from crc_lnm_mcp.runtime import RuntimeProvider

TOOL_NAME = "crc_lnm_predict_multimodal"
TOOL_DESCRIPTION = (
    "基于CT影像特征、病理特征和临床信息进行结直肠癌淋巴结转移预测。"
    "使用NumPy单模型进行推理，返回转移概率、阈值判断和置信度信息。"
)


def register(mcp: Any, runtime: RuntimeProvider) -> None:
    async def tool(
        contract_version: Literal["1.1.0"],
        request_id: UUID4,
        trace_id: UUID4,
        case_ref: CaseRef,
        input: PredictMultimodalInput,
    ) -> dict[str, Any]:
        del contract_version
        request_uuid = UUID(str(request_id))
        trace_uuid = UUID(str(trace_id))
        try:
            data = runtime.prediction.predict(
                case_ref=case_ref,
                qc_artifact_id=input.qc_artifact_id,
                ct_artifact_id=input.ct_artifact_id,
                pathology_artifact_id=input.pathology_artifact_id,
                clinical=input.clinical.model_dump(),
                request_id=request_uuid,
                trace_id=trace_uuid,
            )
        except Exception:
            return {
                "contract_version": "1.1.0",
                "request_id": str(request_uuid),
                "trace_id": str(trace_uuid),
                "tool_name": TOOL_NAME,
                "status": {
                    "code": 5002,
                    "name": "INFERENCE_FAILURE",
                    "message": "Model inference could not be completed.",
                    "severity": "error",
                    "retryable": False,
                },
                "data": None,
                "errors": [
                    {
                        "field": None,
                        "code": "INFERENCE_FAILURE",
                        "message": "Model inference could not be completed.",
                        "suggestion": "Review model integrity diagnostics before retrying.",
                    }
                ],
                "warnings": [],
                "provenance": {
                    "service_version": "1.0.19",
                    "model_version": None,
                    "model_schema_version": "1.0.0",
                    "model_feature_order_sha256": None,
                },
            }
        return {
            "contract_version": "1.1.0",
            "request_id": str(request_uuid),
            "trace_id": str(trace_uuid),
            "tool_name": TOOL_NAME,
            "status": {
                "code": 2001,
                "name": "OK_WITH_WARNINGS",
                "message": "Single-model prediction completed.",
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
                "model_version": data["model_version"],
                "model_schema_version": "1.0.0",
                "model_feature_order_sha256": runtime.metadata.get_model_info()[
                    "feature_order_sha256"
                ],
            },
        }

    mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)(tool)


__all__ = ["TOOL_NAME", "register"]