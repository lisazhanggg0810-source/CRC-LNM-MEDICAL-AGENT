from __future__ import annotations

import inspect
from pathlib import Path

import scripts.build_release_artifacts as release_artifacts
import scripts.smoke_common as smoke_common
import scripts.smoke_published_style_local_wheel as published_style

ROOT = Path(__file__).resolve().parents[1]
SMOKES = [
    "smoke_tool_01_model_info.py",
    "smoke_tool_02_case_qc.py",
    "smoke_tool_03_ct_features.py",
    "smoke_tool_04_pathology_features.py",
    "smoke_tool_05_prediction.py",
    "smoke_tool_06_report.py",
    "smoke_all_six_tools.py",
]


def test_default_command_uses_python_scripts_directory(monkeypatch, tmp_path) -> None:
    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    command = scripts_dir / "crc-lnm-medical-agent.exe"
    command.write_bytes(b"")
    monkeypatch.setattr(published_style.shutil, "which", lambda _name: None)
    monkeypatch.setattr(published_style.sysconfig, "get_path", lambda name: str(scripts_dir))
    monkeypatch.setattr(published_style.sys, "platform", "win32")

    assert published_style._default_command() == str(command.resolve())


def test_smoke_harness_accepts_published_style_console_arguments() -> None:
    parameters = inspect.signature(smoke_common.run_smoke).parameters
    assert "server_args" in parameters
    source = (ROOT / "scripts/smoke_common.py").read_text("utf-8")
    assert "--server-arg" in source


def test_published_style_wrapper_enforces_wheel_origin_and_invariants() -> None:
    path = ROOT / "scripts/smoke_published_style_local_wheel.py"
    source = path.read_text("utf-8")
    for marker in (
        "site-packages",
        "run_smoke",
        "server_args",
        "member_count",
        "ensemble_enabled",
        "selected_seed",
        "model_runtime.npz",
        "torch_imported_before_prediction",
        "load_count",
    ):
        assert marker in source


def test_linux_scripts_are_fail_fast_and_emit_exact_pass_marker() -> None:
    verifier = (ROOT / "scripts/release_verify_full_linux.sh").read_text("utf-8")
    audit = (ROOT / "scripts/audit_linux_uvx_cold_start.sh").read_text("utf-8")
    assert "set -euo pipefail" in verifier
    assert verifier.rstrip().endswith('echo "LINUX FULL RELEASE VERIFICATION: PASS"')
    assert "pip install" in verifier and "-e " not in verifier
    assert 'BASE_PYTHON="${PYTHON:-python}"' in verifier
    assert 'UV="${UV:-$(command -v uv || true)}"' in verifier
    assert '"$UV" pip install --python "$PYTHON"' in verifier
    assert "find_spec('torch') is None" in verifier
    for smoke in SMOKES:
        assert smoke in verifier
    for marker in (
        '"$UV" --version',
        "cold_cache",
        "warm_cache",
        "dependency_resolution_seconds",
        "dependency_install_seconds",
        "initialize_seconds",
        "first_prediction_seconds",
        "second_prediction_seconds",
        "peak_rss_bytes",
        "installed_bytes",
        "site_packages_bytes",
        "forbidden_runtime_packages",
    ):
        assert marker in audit
    assert "torch==2.9.1" not in audit
    assert "torch_installed_bytes" not in audit
    assert "COMMON=(--command" not in audit
    assert audit.count("--server-arg=--cache-dir") == 3


def test_windows_verifier_emits_exact_pass_marker_only_at_end() -> None:
    source = (ROOT / "scripts/release_verify_full.ps1").read_text("utf-8")
    assert source.rstrip().endswith('Write-Host "WINDOWS FULL RELEASE VERIFICATION: PASS"')
    assert "--force-reinstall" in source
    assert "CANARY_WHEEL" in source


def test_github_actions_has_six_wheel_only_cells_and_artifacts() -> None:
    source = (ROOT / ".github/workflows/release-matrix-1.0.19.yml").read_text("utf-8")
    for marker in (
        "ubuntu-latest",
        "windows-latest",
        '"3.10"',
        '"3.11"',
        '"3.12"',
        "actions/download-artifact@v4",
        "actions/upload-artifact@v4",
        "pip check",
        "smoke_published_style_local_wheel.py",
    ):
        assert marker in source
    wrapper = (ROOT / "scripts/smoke_published_style_local_wheel.py").read_text("utf-8")
    assert "range(1, 8)" in wrapper
    assert "pip install -e" not in source
    assert "secrets." not in source
    assert "find_spec('torch') is None" in source


def test_release_source_archive_includes_ci_and_risk_documents() -> None:
    assert ".github" in release_artifacts.TREES
    assert (ROOT / "docs/MODELSCOPE_RUNTIME_RISK_1.0.12.md").is_file()
    assert (ROOT / "docs/CROSS_PLATFORM_RELEASE_GATE_1.0.12.md").is_file()


def test_model_and_public_semantics_remain_locked() -> None:
    manifest = (ROOT / "src/crc_lnm_mcp/assets/model/deployment_manifest.json").read_text("utf-8")
    for marker in (
        '"selected_seed": 2024',
        '"member_count": 1',
        '"ensemble_enabled": false',
        '"threshold": 0.3529504342004657',
    ):
        assert marker in manifest
