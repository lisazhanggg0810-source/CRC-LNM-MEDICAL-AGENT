from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_exposes_exact_post_publish_uvx_command() -> None:
    path = ROOT / "scripts/smoke_stdio.py"
    tree = ast.parse(path.read_text("utf-8"))
    assignments = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    assert assignments["PUBLISHED_UVX_PACKAGE"] == "crc-lnm-medical-agent"
    assert "--published-uvx" in path.read_text("utf-8")


def test_one_command_release_verifier_has_required_fail_fast_gates() -> None:
    script = (ROOT / "scripts/release_verify.ps1").read_text("utf-8")
    required = (
        "$ErrorActionPreference = \"Stop\"",
        "python -m build",
        "python -m twine check",
        "scripts/check_release.py",
        "scripts/inspect_wheel.py",
        "python -m pytest -q",
        "scripts/smoke_stdio.py",
        "RELEASE_CHECKSUMS.sha256",
        "source.zip",
        "LOCAL RELEASE VERIFICATION: PASS",
    )
    assert all(marker in script for marker in required)
    assert "twine upload" not in script
    assert "git push" not in script


def test_release_verifier_uses_only_the_project_release_python() -> None:
    verifier = (ROOT / "scripts/release_verify.ps1").read_text("utf-8")
    release_python_assignment = (
        '$ReleasePython = Join-Path $ProjectRoot ".venv-release\\Scripts\\python.exe"'
    )
    assert release_python_assignment in verifier
    assert '[string]$Python = "python"' not in verifier
    assert (
        "Release virtual environment not found. Run scripts/setup_release_env.ps1 first."
        in verifier
    )
    assert "& $ReleasePython @Arguments" in verifier
    for supported_minor in ("3.10", "3.11", "3.12"):
        assert supported_minor in verifier


def test_release_environment_setup_contract() -> None:
    setup_path = ROOT / "scripts/setup_release_env.ps1"
    assert setup_path.exists(), "scripts/setup_release_env.ps1 must be provided"
    setup = setup_path.read_text("utf-8")
    gitignore = (ROOT / ".gitignore").read_text("utf-8").splitlines()

    assert setup.index('"3.12"') < setup.index('"3.11"') < setup.index('"3.10"')
    assert "import build, twine, pytest, psutil" in setup
    assert "verification dependencies: ok" in setup
    assert "RELEASE ENVIRONMENT SETUP: PASS" in setup
    assert ".venv-release/" in gitignore
    assert (ROOT / ".gitignore").is_file()
    assert "dist/" in gitignore
    assert "__pycache__/" in gitignore
    assert not any("model_runtime.npz" in rule for rule in gitignore)

    lowered = setup.lower()
    for forbidden in ("twine upload", "git push", "modelscope upload"):
        assert forbidden not in lowered


def test_uvx_audit_script_and_report_exist() -> None:
    script = (ROOT / "scripts/audit_uvx_cold_start.ps1").read_text("utf-8")
    report = (ROOT / "docs/UVX_COLD_START_AUDIT.md").read_text("utf-8")
    for marker in (
        "uv --version",
        "uv cache dir",
        "python find",
        "uv venv",
        "uv pip compile",
        "uv pip install",
        "--from",
        "cold",
        "warm",
    ):
        assert marker in script.lower()
    assert "100.377" in report
    assert "ModelScope" in report


def test_uvx_audit_targets_the_six_tool_prediction_harness() -> None:
    script = (ROOT / "scripts/audit_uvx_cold_start.ps1").read_text("utf-8")
    assert "scripts/smoke_tool_05_prediction.py" in script
    assert "scripts/smoke_stdio.py" not in script
    assert '"--server-arg=' in script
    assert '"--arg=' not in script
    assert '"--allow-network"' not in script
    assert "$Runtime = [IO.Path]::GetFullPath($Runtime)" in script


def test_formal_deployment_docs_do_not_use_unversioned_package_argument() -> None:
    formal_paths = (
        ROOT / "README.md",
        ROOT / "docs/MODELSCOPE_MANUAL_DEPLOYMENT.md",
        ROOT / "docs/MODELSCOPE_CANARY_RELEASE.md",
    )
    forbidden = '"args": ["crc-lnm-medical-agent"]'
    for path in formal_paths:
        assert forbidden not in path.read_text("utf-8"), path


def test_default_pytest_scope_is_the_lightweight_canary() -> None:
    conftest = (ROOT / "tests/conftest.py").read_text("utf-8")
    for legacy_test in (
        "test_jsonl_case_packages.py",
        "test_release_contract.py",
        "test_release_runtime.py",
        "test_tool_execution.py",
    ):
        assert legacy_test in conftest
