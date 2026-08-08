from __future__ import annotations

import csv
import gc
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil
import torch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wei_multimodal.artifacts.bundle import (  # noqa: E402
    feature_order_sha256,
    preprocessed_to_batch,
    schema_from_dict,
)
from wei_multimodal.data.preprocessing import FoldPreprocessor  # noqa: E402
from wei_multimodal.models.baselines import build_neural_model  # noqa: E402

BUNDLE = ROOT / "models" / "deployment_bundle"
DEMO = ROOT / "demo" / "cases" / "demo_case_001"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
SEEDS = (2024, 3407, 5280, 7319, 9021)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rss_bytes() -> int:
    return int(psutil.Process().memory_info().rss)


def _demo_batch() -> tuple[Any, Any, dict[str, Any]]:
    schema = schema_from_dict(_read_json(BUNDLE / "schema.json"))
    preprocessor = FoldPreprocessor.load(BUNDLE, schema)
    pathology = _read_json(DEMO / "pathology_features.json")
    ct = _read_json(DEMO / "ct_features.json")
    clinical = _read_json(DEMO / "clinical.json")
    row = {
        **{f"pathology::{name}": pathology[name] for name in schema.pathology_features},
        **{f"ct::{name}": ct[name] for name in schema.all_ct_features},
        **clinical,
    }
    columns = [
        *schema.pathology_output_columns,
        *schema.ct_output_columns,
        "age",
        "male",
        "Type",
        "T",
    ]
    arrays = preprocessor.transform(pd.DataFrame([row], columns=columns))
    return preprocessed_to_batch(arrays), schema, clinical


def _load_and_predict(seed: int, batch: Any) -> dict[str, Any]:
    member = BUNDLE / f"seed_{seed}"
    config = _read_json(member / "model_config.json")
    state_path = member / "model_state.pt"
    rss_before = _rss_bytes()
    started = time.perf_counter()
    model = build_neural_model(
        str(config["architecture"]),
        type_vocab_size=int(config["type_vocab_size"]),
        t_stage_vocab_size=int(config["t_stage_vocab_size"]),
        hidden_dim=int(config["hidden_dim"]),
        num_heads=int(config["num_heads"]),
        dropout=float(config["dropout"]),
    )
    state = torch.load(state_path, weights_only=True, map_location="cpu")
    model.load_state_dict(state, strict=True)
    model.eval()
    load_seconds = time.perf_counter() - started
    rss_after_load = _rss_bytes()
    started = time.perf_counter()
    with torch.inference_mode():
        probability = float(torch.softmax(model(batch).logits, dim=1)[0, 1].item())
    inference_seconds = time.perf_counter() - started
    result = {
        "model_id": f"seed_{seed}",
        "seed": seed,
        "architecture": config["architecture"],
        "state_dict_tensor_count": len(state),
        "file_size_bytes": state_path.stat().st_size,
        "model_sha256": _sha256(state_path),
        "load_seconds": load_seconds,
        "inference_seconds": inference_seconds,
        "rss_before_bytes": rss_before,
        "rss_after_load_bytes": rss_after_load,
        "model_rss_delta_bytes": max(0, rss_after_load - rss_before),
        "observed_peak_rss_bytes": max(rss_before, rss_after_load, _rss_bytes()),
        "validation_metrics": None,
        "positive_probability": probability,
    }
    del state, model
    gc.collect()
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_docs(selection: dict[str, Any], regression: dict[str, Any], schema: Any) -> None:
    candidates = selection["candidates"]
    selected = next(row for row in candidates if row["selected"])
    audit_rows = "\n".join(
        f"- `{row['model_id']}`: {row['file_size_bytes']} bytes, load "
        f"{row['load_seconds']:.6f}s, inference {row['inference_seconds']:.6f}s, "
        f"observed RSS {row['observed_peak_rss_bytes']} bytes."
        for row in candidates
    )
    (DOCS / "FULL_RUNTIME_BASELINE_AUDIT.md").write_text(
        "# Full Runtime Baseline Audit\n\n"
        "## Legacy implementation\n\n"
        "The six tool adapters are under `src/wei_multimodal/mcp_server/tools`; their business "
        "services are under `src/wei_multimodal/mcp_server/services`. The 1.0.11 canary shell "
        "is under `src/crc_lnm_mcp`. The legacy lifespan eagerly expands case JSONL and creates "
        "the five-member prediction service.\n\n"
        "## Models\n\n"
        f"All five members use `{candidates[0]['architecture']}` and the same schema and "
        "preprocessor.\n\n"
        f"{audit_rows}\n\n"
        "## Locked inference contract\n\n"
        f"- Pathology dimensions: {len(schema.pathology_features)}.\n"
        f"- CT dimensions: {schema.ct_feature_count} (14/93/744/558).\n"
        "- Clinical order used by inference: age, male, Type, T.\n"
        f"- Feature-order SHA-256: `{selection['feature_ordering_checksum']}`.\n"
        f"- Threshold: {selection['threshold']} from the evaluation-bundle OOF Youden record.\n"
        "- Prior measured entry import: about 8.7s and 364 MB RSS; prior 1.0.11 wheel: "
        "4,307 bytes. Current per-member measurements are listed above.\n",
        encoding="utf-8",
    )
    (DOCS / "SINGLE_MODEL_SELECTION.md").write_text(
        "# Single Model Selection\n\n"
        "No same-split per-seed validation metrics were found. Selection therefore used only "
        "the non-private synthetic `demo_case_001`, without labels or the release JSONL. Each "
        "single-member probability was compared with the arithmetic mean of all five members.\n\n"
        f"Selected `{selected['model_id']}` (seed {selected['seed']}) with absolute probability "
        f"error {selected['mae_to_ensemble']:.12f}.\n\n"
        "This one-case result is a deployment-proximity selection, not evidence that the member "
        "is performance-optimal. The original ensemble threshold is retained and has not been "
        "recalibrated for this member. Research use only; no independent-test claim.\n",
        encoding="utf-8",
    )
    (DOCS / "SINGLE_VS_ENSEMBLE_REGRESSION.md").write_text(
        "# Single Model vs Ensemble Regression\n\n"
        f"For `{regression['case_ref']}`, the ensemble probability was "
        f"{regression['ensemble_probability']:.12f} and selected single-model probability was "
        f"{regression['single_model_probability']:.12f}; absolute delta "
        f"{regression['absolute_delta']:.12f}. Predicted class changed: "
        f"{str(regression['predicted_class_changed']).lower()}. The threshold remains "
        f"{regression['threshold']:.12f}. The new probability is the regression baseline and is "
        "not required to equal the former ensemble output.\n",
        encoding="utf-8",
    )


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    batch, schema, _clinical = _demo_batch()
    candidates = [_load_and_predict(seed, batch) for seed in SEEDS]
    ensemble_probability = float(
        np.mean([row["positive_probability"] for row in candidates], dtype=np.float64)
    )
    for row in candidates:
        row["mae_to_ensemble"] = abs(row["positive_probability"] - ensemble_probability)
    selected = min(
        candidates,
        key=lambda row: (
            row["mae_to_ensemble"],
            row["file_size_bytes"],
            row["load_seconds"],
            row["inference_seconds"],
            row["model_id"],
        ),
    )
    for row in candidates:
        row["selected"] = row is selected
    manifest = _read_json(BUNDLE / "manifest.json")
    threshold = float(manifest["threshold"])
    preprocessing_checksum = str(manifest["payload_sha256"]["preprocessing.npz"])
    ordering_checksum = feature_order_sha256(schema)
    selection = {
        "package_target_version": "1.0.19",
        "selection_dataset": "demo_case_001",
        "selection_dataset_case_count": 1,
        "selection_method": "minimum_mae_to_ensemble",
        "test_labels_used": False,
        "release_case_jsonl_used": False,
        "ensemble_probability": ensemble_probability,
        "selected_model_id": selected["model_id"],
        "selected_seed": selected["seed"],
        "threshold": threshold,
        "threshold_source": "evaluation_bundle_oof_youden_not_recalibrated_for_single_model",
        "preprocessing_checksum": preprocessing_checksum,
        "feature_ordering_checksum": ordering_checksum,
        "candidates": candidates,
        "selection_bias": "One synthetic demo case may not represent deployment inputs.",
        "limitations": [
            "No comparable per-seed validation metrics were present.",
            "Only one synthetic demo case was available for deployment-proximity selection.",
            "The ensemble threshold has not been recalibrated for the selected model.",
        ],
    }
    ensemble_class = int(ensemble_probability >= threshold)
    single_probability = float(selected["positive_probability"])
    single_class = int(single_probability >= threshold)
    regression = {
        "case_ref": "demo_case_001",
        "ensemble_probability": ensemble_probability,
        "single_model_probability": single_probability,
        "absolute_delta": abs(single_probability - ensemble_probability),
        "ensemble_predicted_class": ensemble_class,
        "predicted_class": single_class,
        "predicted_class_changed": ensemble_class != single_class,
        "threshold": threshold,
        "threshold_unchanged": True,
        "selected_model_id": selected["model_id"],
        "selected_seed": selected["seed"],
        "member_count": 1,
        "ensemble_enabled": False,
        "preprocessing_checksum": preprocessing_checksum,
        "feature_ordering_checksum": ordering_checksum,
    }
    _write_json(REPORTS / "single_model_selection.json", selection)
    _write_json(REPORTS / "single_model_regression.json", regression)
    fieldnames = [
        "model_id",
        "seed",
        "architecture",
        "file_size_bytes",
        "model_sha256",
        "state_dict_tensor_count",
        "load_seconds",
        "inference_seconds",
        "rss_before_bytes",
        "rss_after_load_bytes",
        "model_rss_delta_bytes",
        "observed_peak_rss_bytes",
        "validation_metrics",
        "positive_probability",
        "mae_to_ensemble",
        "selected",
    ]
    with (REPORTS / "single_model_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fieldnames} for row in candidates)
    _write_docs(selection, regression, schema)
    print(
        json.dumps({"selected_model_id": selected["model_id"], "selected_seed": selected["seed"]})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
