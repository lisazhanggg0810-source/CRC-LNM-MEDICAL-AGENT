"""Thread-safe lazy single-model prediction provider without top-level Torch imports."""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from crc_lnm_mcp.inference.predictor import SingleModelPredictor

    from .case_service import CaseAndFeatureProvider
    from .metadata_service import MetadataProvider


class PredictionProvider:
    def __init__(self, metadata: MetadataProvider, cases: CaseAndFeatureProvider) -> None:
        self._metadata = metadata
        self._cases = cases
        self._predictor: SingleModelPredictor | None = None
        self._load_error: str | None = None
        self._load_lock = threading.Lock()
        self._count_lock = threading.Lock()
        self.load_count = 0
        self.load_attempt_count = 0
        self.load_seconds = 0.0
        self.model_rss_delta = 0
        self.prediction_count = 0

    @staticmethod
    def _debug(message: str) -> None:
        if os.environ.get("CRC_SMOKE_DEBUG") == "1":
            print(f"prediction-provider:{message}", file=sys.stderr, flush=True)

    @staticmethod
    def _rss() -> int:
        try:
            import psutil

            return int(psutil.Process().memory_info().rss)
        except ImportError:
            return 0

    def _ensure_predictor(self) -> SingleModelPredictor:
        if self._predictor is not None:
            return self._predictor
        if self._load_error is not None:
            raise RuntimeError("model initialization previously failed")
        with self._load_lock:
            if self._predictor is not None:
                return self._predictor
            if self._load_error is not None:
                raise RuntimeError("model initialization previously failed")
            self.load_attempt_count += 1
            self._debug("load-start")
            started = time.perf_counter()
            rss_before = self._rss()
            try:
                if os.environ.get("CRC_SMOKE_DEBUG") == "1":
                    import faulthandler

                    faulthandler.dump_traceback_later(10, repeat=False)
                from crc_lnm_mcp.inference.model_loader import load_predictor

                if os.environ.get("CRC_SMOKE_DEBUG") == "1":
                    faulthandler.cancel_dump_traceback_later()
                self._debug("loader-imported")
                predictor = load_predictor(self._metadata.manifest())
                self._debug("predictor-loaded")
            except Exception as exc:
                self._load_error = type(exc).__name__
                raise RuntimeError("model initialization failed") from exc
            self.load_seconds = time.perf_counter() - started
            self.model_rss_delta = max(0, self._rss() - rss_before)
            self._predictor = predictor
            self.load_count = 1
            return predictor

    def predict(
        self,
        *,
        case_ref: str,
        qc_artifact_id: str,
        ct_artifact_id: str,
        pathology_artifact_id: str,
        clinical: dict[str, int | float],
        request_id: UUID,
        trace_id: UUID,
    ) -> dict[str, Any]:
        del request_id
        _record, binding = self._cases.validated_case(case_ref)
        qc = self._cases.require_artifact(
            qc_artifact_id,
            trace_id=trace_id,
            case_ref=case_ref,
            expected_type="case_qc",
        )
        ct = self._cases.require_artifact(
            ct_artifact_id,
            trace_id=trace_id,
            case_ref=case_ref,
            expected_type="ct_features",
        )
        pathology = self._cases.require_artifact(
            pathology_artifact_id,
            trace_id=trace_id,
            case_ref=case_ref,
            expected_type="pathology_features",
        )
        if any(item.case_binding_sha256 != binding for item in (qc, ct, pathology)):
            raise ValueError("prediction artifacts do not match the case binding")
        if set(clinical) != {"age", "male", "Type", "T"}:
            raise ValueError("clinical fields are invalid")
        started = time.perf_counter()
        self._debug("ensure-predictor")
        predictor = self._ensure_predictor()
        self._debug("forward-start")
        probability = predictor.predict(
            pathology.payload["values"],
            ct.payload["values"],
            clinical,
        )
        self._debug("forward-end")
        inference_seconds = time.perf_counter() - started
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise RuntimeError("model returned an invalid probability")
        manifest = self._metadata.manifest()
        threshold = float(manifest["threshold"])
        margin = probability - threshold
        distance = abs(margin)
        proximity = (
            "near_threshold"
            if distance <= 0.05
            else "intermediate"
            if distance <= 0.15
            else "far_from_threshold"
        )
        payload = {
            "positive_probability": probability,
            "threshold": threshold,
            "threshold_recalibrated": False,
            "predicted_class": int(probability >= threshold),
            "selected_model_id": manifest["selected_model_id"],
            "selected_seed": manifest["selected_seed"],
            "member_count": 1,
            "ensemble_enabled": False,
            "runtime_backend": manifest["runtime_backend"],
            "source_framework": manifest["source_framework"],
            "source_model_sha256": manifest["source_model_sha256"],
            "runtime_asset_sha256": manifest["runtime_asset_sha256"],
        }
        artifact = self._cases.put_artifact(
            "prediction",
            trace_id=trace_id,
            case_ref=case_ref,
            case_binding_sha256=binding,
            payload=payload,
        )
        with self._count_lock:
            self.prediction_count += 1
        return {
            "artifact": artifact.public_ref(),
            **payload,
            "decision_margin": margin,
            "absolute_threshold_distance": distance,
            "decision_proximity": proximity,
            "human_review_required": True,
            "review_priority": "elevated" if distance <= 0.05 else "routine",
            "review_reasons": ["SINGLE_MODEL_DEPLOYMENT", "THRESHOLD_NOT_RECALIBRATED"],
            "ct_source_used": "precomputed",
            "fallback_used": False,
            "fallback_reason": None,
            "model_version": manifest["runtime_asset_sha256"],
            "independent_test_claim": False,
            "research_use_only": True,
            "performance_reference": {"metric": "oof_roc_auc", "value": 0.7749},
            "load_seconds": self.load_seconds,
            "inference_seconds": inference_seconds,
        }


__all__ = ["PredictionProvider"]
