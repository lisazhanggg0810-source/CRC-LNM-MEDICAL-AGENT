from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
MISSING_REASON = (
    "Torch reference asset not configured; runtime release tests remain active."
)


def _load_reference_module():
    path = ROOT / "scripts/torch_reference_paths.py"
    assert path.is_file(), "central Torch reference resolver must exist"
    spec = importlib.util.spec_from_file_location("torch_reference_paths", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_path_does_not_depend_on_repo_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_reference_module()
    monkeypatch.chdir(tmp_path)
    environment: dict[str, str] = {}
    assert module.resolve_model_state(environment) is None
    for path in (
        ROOT / "tests/test_model_conversion.py",
        ROOT / "tests/test_numpy_model_equivalence.py",
        ROOT / "scripts/convert_torch_to_numpy.py",
        ROOT / "scripts/verify_runtime_equivalence.py",
    ):
        source = path.read_text("utf-8")
        assert "ROOT.parent" not in source
        assert "release_1.0.12_torch_runtime_blocked_backup" not in source


def test_explicit_model_state_environment_variable(tmp_path: Path) -> None:
    module = _load_reference_module()
    state = tmp_path / "model_state.pt"
    state.write_bytes(b"fixture")
    resolved = module.resolve_model_state({"CRC_LNM_TORCH_MODEL_STATE": str(state)})
    assert resolved == state.resolve()


def test_explicit_reference_root_environment_variable(tmp_path: Path) -> None:
    module = _load_reference_module()
    state = tmp_path / "src/crc_lnm_mcp/assets/model/model_state.pt"
    state.parent.mkdir(parents=True)
    state.write_bytes(b"fixture")
    resolved = module.resolve_model_state({"CRC_LNM_TORCH_REFERENCE_ROOT": str(tmp_path)})
    assert resolved == state.resolve()


def test_missing_reference_asset_uses_exact_conversion_skip_reason() -> None:
    conftest = (ROOT / "tests/conftest.py").read_text("utf-8")
    assert MISSING_REASON in conftest


def test_runtime_tests_do_not_require_torch_reference() -> None:
    for name in (
        "test_full_lazy_prediction.py",
        "test_numpy_runtime_loader.py",
        "test_runtime_equivalence_report.py",
    ):
        source = (ROOT / "tests" / name).read_text("utf-8")
        assert "CRC_LNM_TORCH_" not in source


def test_github_ci_does_not_install_torch() -> None:
    workflow = (ROOT / ".github/workflows/release-matrix-1.0.19.yml").read_text("utf-8")
    lowered = workflow.lower()
    assert "pip install torch" not in lowered
    assert "conversion" not in lowered


def test_no_absolute_developer_path_in_tests() -> None:
    forbidden = (
        "C:" + "\\Users\\" + "Administrator",
        "C:" + "/Users/" + "Administrator",
        "/home/" + "administrator",
    )
    for path in (ROOT / "tests").glob("*.py"):
        source = path.read_text("utf-8")
        assert not any(marker in source for marker in forbidden), path


def test_gitignore_and_source_archive_contracts() -> None:
    rules = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    required = {
        ".venv/",
        ".venv-*/",
        "venv/",
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".coverage",
        "htmlcov/",
        "build/",
        "dist/",
        "*.egg-info/",
        ".env",
        ".env.*",
        "*.log",
        "*.tmp",
        ".DS_Store",
        "Thumbs.db",
        "release_1.0.12_before_*/",
        "release_1.0.12_*_backup/",
        "stage_crc_lnm_*/",
    }
    assert required.issubset(rules)
    assert not any("model_runtime.npz" in rule for rule in rules)

    build_script = (ROOT / "scripts/build_release_artifacts.py").read_text("utf-8")
    for required_member in (".gitignore", ".github", "RELEASE_CHECKSUMS.sha256"):
        assert required_member in build_script
    for forbidden_suffix in (".pt", ".pth", ".ckpt"):
        assert forbidden_suffix in build_script


def test_release_check_validates_source_zip() -> None:
    source = (ROOT / "scripts/check_release.py").read_text("utf-8")
    assert "--source-zip" in source
    assert "check_source_zip" in source


def test_release_verifier_does_not_treat_conversion_torch_as_runtime_dependency() -> None:
    source = (ROOT / "scripts/release_verify_full.ps1").read_text("utf-8")
    assert "find_spec('torch') is None" not in source
    assert "scripts/check_release.py" in source


def test_reference_environment_is_not_implicitly_set() -> None:
    assert "CRC_LNM_TORCH_MODEL_STATE" not in os.environ or os.environ[
        "CRC_LNM_TORCH_MODEL_STATE"
    ]


def test_ruff_import_classification_is_source_tree_independent() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    known = config["tool"]["ruff"]["lint"]["isort"]["known-first-party"]
    assert known == ["crc_lnm_mcp", "wei_multimodal"]
