"""Run the complete gate against a non-editable installed local wheel."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from smoke_common import run_smoke

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROBABILITY = 0.5726384520530701


def _default_command() -> str:
    names = ["crc-lnm-medical-agent"]
    if sys.platform == "win32":
        names.append("crc-lnm-medical-agent.exe")
    for name in names:
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())

    scripts_dir = Path(sysconfig.get_path("scripts"))
    filename = "crc-lnm-medical-agent.exe" if sys.platform == "win32" else names[0]
    command = (scripts_dir / filename).resolve()
    if command.is_file():
        return str(command)
    raise FileNotFoundError(
        "installed console script is missing; "
        f"sys.executable={sys.executable}; scripts={scripts_dir}; "
        f"PATH present={bool(os.environ.get('PATH'))}"
    )


def _installed_origin() -> str:
    code = "import crc_lnm_mcp; print(crc_lnm_mcp.__file__)"
    with tempfile.TemporaryDirectory(prefix="crc-lnm-origin-") as cwd:
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(f"installed-origin probe failed: {result.stderr}")
    origin = result.stdout.strip()
    if "site-packages" not in origin.replace("\\", "/").lower():
        raise AssertionError(f"package was not imported from site-packages: {origin}")
    if str(ROOT / "src").lower() in origin.lower():
        raise AssertionError(f"package resolved to the source tree: {origin}")
    return origin


def _wheel_integrity(wheel: Path) -> dict[str, Any]:
    with zipfile.ZipFile(wheel) as archive:
        forbidden_weights = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".pt", ".pth", ".ckpt"))
        ]
        manifest = json.loads(archive.read("crc_lnm_mcp/assets/model/deployment_manifest.json"))
        runtime_name = "crc_lnm_mcp/assets/model/model_runtime.npz"
        runtime = archive.read(runtime_name)
        runtime_models = [
            name
            for name in archive.namelist()
            if "/assets/model/" in name and name.lower().endswith((".npz", ".onnx"))
        ]
    runtime_sha256 = hashlib.sha256(runtime).hexdigest()
    if forbidden_weights:
        raise AssertionError(f"forbidden model weights: {forbidden_weights}")
    if runtime_models != [runtime_name]:
        raise AssertionError(f"unexpected runtime models: {runtime_models}")
    if runtime_sha256 != manifest["runtime_asset_sha256"]:
        raise AssertionError("model_runtime.npz checksum does not match the manifest")
    return {
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "wheel_size_bytes": wheel.stat().st_size,
        "runtime_model_count": len(runtime_models),
        "runtime_asset_sha256": runtime_sha256,
        "source_model_sha256": manifest["source_model_sha256"],
    }


def _runtime_invariants() -> dict[str, Any]:
    torch_imported_before_prediction = any(
        name == "torch" or name.startswith("torch.") for name in sys.modules
    )
    from crc_lnm_mcp.runtime import RuntimeProvider

    runtime = RuntimeProvider()
    info = runtime.metadata.get_model_info()
    trace_id = uuid4()
    qc = runtime.cases.case_data_qc("demo_case_001", request_id=uuid4(), trace_id=trace_id)
    qc_id = qc["artifact"]["artifact_id"]
    ct = runtime.cases.prepare_ct_features(
        "demo_case_001",
        qc_artifact_id=qc_id,
        request_id=uuid4(),
        trace_id=trace_id,
    )
    pathology = runtime.cases.prepare_pathology_features(
        "demo_case_001",
        qc_artifact_id=qc_id,
        request_id=uuid4(),
        trace_id=trace_id,
    )
    torch_imported_after_lightweight_tools = any(
        name == "torch" or name.startswith("torch.") for name in sys.modules
    )
    request = {
        "case_ref": "demo_case_001",
        "qc_artifact_id": qc_id,
        "ct_artifact_id": ct["artifact"]["artifact_id"],
        "pathology_artifact_id": pathology["artifact"]["artifact_id"],
        "clinical": {"age": 60, "male": 0, "Type": 1, "T": 1},
        "request_id": uuid4(),
        "trace_id": trace_id,
    }
    first = runtime.prediction.predict(**request)
    second = runtime.prediction.predict(**{**request, "request_id": uuid4()})
    if torch_imported_before_prediction or torch_imported_after_lightweight_tools:
        raise AssertionError("Torch was imported before prediction")
    if runtime.prediction.load_count != 1 or runtime.prediction.load_attempt_count != 1:
        raise AssertionError("single model was not loaded exactly once")
    if first["positive_probability"] != second["positive_probability"]:
        raise AssertionError("second prediction changed the probability")
    if abs(first["positive_probability"] - EXPECTED_PROBABILITY) > 1e-6:
        raise AssertionError("demo probability exceeded the locked tolerance")
    expected = {
        "member_count": 1,
        "ensemble_enabled": False,
        "selected_seed": 2024,
    }
    for key, value in expected.items():
        if first[key] != value or info[key] != value:
            raise AssertionError(f"locked invariant changed: {key}")
    return {
        "torch_imported_before_prediction": torch_imported_before_prediction,
        "torch_imported_after_lightweight_tools": torch_imported_after_lightweight_tools,
        "load_count": runtime.prediction.load_count,
        "load_attempt_count": runtime.prediction.load_attempt_count,
        "prediction_count": runtime.prediction.prediction_count,
        "first_probability": first["positive_probability"],
        "second_probability": second["positive_probability"],
        "member_count": first["member_count"],
        "ensemble_enabled": first["ensemble_enabled"],
        "selected_seed": first["selected_seed"],
    }


async def _run_all(
    command: str,
    server_args: list[str],
    output_dir: Path,
) -> list[dict[str, Any]]:
    reports = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for target in range(1, 8):
        report = await run_smoke(target, command, server_args=server_args)
        reports.append(report)
        name = f"smoke_{target:02d}.json" if target < 7 else "smoke_full.json"
        (output_dir / name).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--command")
    parser.add_argument("--server-arg", action="append", default=[])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports/lightweight_cross_platform_gate",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--invariants-only", action="store_true")
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file():
        raise FileNotFoundError(wheel)
    reports = []
    if not args.invariants_only:
        reports = asyncio.run(
            _run_all(args.command or _default_command(), args.server_arg, args.output_dir)
        )
    result = {
        "status": "PASS",
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "installed_origin": _installed_origin(),
        **_wheel_integrity(wheel),
        "runtime_invariants": _runtime_invariants(),
        "smoke_count": len(reports),
        "peak_rss_bytes": max((row["peak_rss_bytes"] for row in reports), default=0),
        "smokes": reports,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
