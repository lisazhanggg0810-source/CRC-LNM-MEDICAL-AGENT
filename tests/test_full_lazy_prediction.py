# ruff: noqa: E501

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from crc_lnm_mcp.runtime import RuntimeProvider

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROBABILITY = 0.5726384520530701


def _prepared(runtime: RuntimeProvider) -> tuple[UUID, dict[str, object]]:
    trace_id = uuid4()
    qc = runtime.cases.case_data_qc("demo_case_001", request_id=uuid4(), trace_id=trace_id)
    ct = runtime.cases.prepare_ct_features(
        "demo_case_001",
        qc_artifact_id=qc["artifact"]["artifact_id"],
        request_id=uuid4(),
        trace_id=trace_id,
    )
    pathology = runtime.cases.prepare_pathology_features(
        "demo_case_001",
        qc_artifact_id=qc["artifact"]["artifact_id"],
        request_id=uuid4(),
        trace_id=trace_id,
    )
    return trace_id, {
        "case_ref": "demo_case_001",
        "qc_artifact_id": qc["artifact"]["artifact_id"],
        "ct_artifact_id": ct["artifact"]["artifact_id"],
        "pathology_artifact_id": pathology["artifact"]["artifact_id"],
        "clinical": {"age": 60, "male": 0, "Type": 1, "T": 1},
        "request_id": uuid4(),
        "trace_id": trace_id,
    }


def test_runtime_construction_and_first_five_operations_do_not_import_torch() -> None:
    code = """
import builtins
import sys
from uuid import uuid4
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'torch' or name.startswith('torch.'):
        raise RuntimeError('torch blocked')
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
from crc_lnm_mcp.runtime import RuntimeProvider
r = RuntimeProvider()
r.metadata.get_model_info()
t = uuid4()
q = r.cases.case_data_qc('demo_case_001', request_id=uuid4(), trace_id=t)
r.cases.prepare_ct_features('demo_case_001', qc_artifact_id=q['artifact']['artifact_id'], request_id=uuid4(), trace_id=t)
r.cases.prepare_pathology_features('demo_case_001', qc_artifact_id=q['artifact']['artifact_id'], request_id=uuid4(), trace_id=t)
assert r.prediction.load_count == 0
assert not any(k == 'torch' or k.startswith('torch.') for k in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_first_prediction_loads_one_model_and_second_reuses_it() -> None:
    runtime = RuntimeProvider()
    trace_id, request = _prepared(runtime)
    assert runtime.prediction.load_count == 0
    first = runtime.prediction.predict(**request)
    second = runtime.prediction.predict(**{**request, "request_id": uuid4()})
    assert runtime.prediction.load_count == 1
    assert runtime.prediction.load_attempt_count == 1
    assert runtime.prediction.prediction_count == 2
    assert first["positive_probability"] == pytest.approx(EXPECTED_PROBABILITY, abs=1e-6)
    assert second["positive_probability"] == first["positive_probability"]
    assert first["member_count"] == 1
    assert first["ensemble_enabled"] is False
    assert first["selected_model_id"] == "seed_2024"
    assert first["selected_seed"] == 2024
    assert first["threshold"] == 0.3529504342004657
    assert first["predicted_class"] == 1
    artifact = runtime.cases.require_artifact(
        first["artifact"]["artifact_id"],
        trace_id=trace_id,
        case_ref="demo_case_001",
        expected_type="prediction",
    )
    assert artifact.payload["positive_probability"] == first["positive_probability"]


def test_concurrent_first_prediction_loads_once() -> None:
    runtime = RuntimeProvider()
    _trace_id, request = _prepared(runtime)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda index: runtime.prediction.predict(**{**request, "request_id": uuid4()}),
                range(4),
            )
        )
    assert runtime.prediction.load_count == 1
    assert runtime.prediction.load_attempt_count == 1
    assert runtime.prediction.prediction_count == 4
    assert {row["positive_probability"] for row in results} == {results[0]["positive_probability"]}

def test_preprocessing_equivalence_report_passes() -> None:
    path = ROOT / "reports" / "preprocessing_equivalence.json"
    assert path.is_file()
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["maximum_absolute_delta"] <= 1e-7
    assert report["feature_order_sha256"] == (
        "d4a5ecb56733db87f505473a7be1497a7fdd174c0994748d5b9574f7373d3200"
    )
