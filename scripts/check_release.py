"""Fail-fast source and wheel gates for the full-lazy 1.0.19 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from email.parser import Parser
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "crc-lnm-medical-agent"
VERSION = "1.0.19"
DEPENDENCIES = [
    "fastmcp==2.14.7",
    "pydantic==2.13.4",
    "numpy==2.1.3",
]
TOOLS = {
    "crc_lnm_get_model_info",
    "crc_lnm_case_data_qc",
    "crc_lnm_prepare_ct_features",
    "crc_lnm_prepare_pathology_features",
    "crc_lnm_predict_multimodal",
    "crc_lnm_generate_report",
}
SOURCE_ARCHIVE = ROOT / f"{PACKAGE}-{VERSION}-source.zip"
SOURCE_PREFIX = f"{PACKAGE}-{VERSION}-source/"
SOURCE_REQUIRED = {
    ".gitignore",
    ".github/workflows/release-matrix-1.0.19.yml",
    "CHANGELOG.md",
    "MANIFEST.in",
    "README.md",
    "RELEASE_CHECKSUMS.sha256",
    "modelscope-mcp.json",
    "pyproject.toml",
}
PORTABLE_SOURCE_PREFIXES = ("scripts/", "tests/", ".github/")
ABSOLUTE_DEVELOPER_PATH = re.compile(
    rb"(?:[A-Za-z]:[\\/]+"
    + rb"Us"
    + rb"ers[\\/]+[^\\/\s]+|/ho"
    + rb"me/[^/\s]+/)"
)


def check_source_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert names and all(name.startswith(SOURCE_PREFIX) for name in names)
        relative_names = {name.removeprefix(SOURCE_PREFIX) for name in names}
        assert SOURCE_REQUIRED.issubset(relative_names)
        assert any(name.startswith(".github/") for name in relative_names)
        forbidden_suffixes = (".pt", ".pth", ".ckpt")
        assert not any(name.lower().endswith(forbidden_suffixes) for name in relative_names)
        assert not any(
            part == ".git" or part.startswith(".venv")
            for name in relative_names
            for part in Path(name).parts
        )
        assert not any(
            part in {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
            for name in relative_names
            for part in Path(name).parts
        )
        for name in relative_names:
            if not name.startswith(PORTABLE_SOURCE_PREFIXES):
                continue
            try:
                payload = archive.read(SOURCE_PREFIX + name)
            except KeyError:
                continue
            assert ABSOLUTE_DEVELOPER_PATH.search(payload) is None, name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?", type=Path)
    parser.add_argument("--source-zip", type=Path)
    args = parser.parse_args()
    wheels = sorted((ROOT / "dist").glob("*.whl"))
    wheel = args.wheel or (wheels[0] if len(wheels) == 1 else None)
    if wheel is None:
        parser.error("provide a wheel or leave exactly one wheel in dist")

    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert project["name"] == PACKAGE
    assert project["version"] == VERSION
    assert project["dependencies"] == DEPENDENCIES
    expected_config = {
        "mcpServers": {PACKAGE: {"command": "uvx", "args": [PACKAGE]}}
    }
    assert json.loads((ROOT / "modelscope-mcp.json").read_text("utf-8")) == expected_config

    import asyncio

    from crc_lnm_mcp.server import mcp

    assert set(asyncio.run(mcp.get_tools())) == TOOLS
    assert "torch" not in __import__("sys").modules

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        manifest = json.loads(archive.read("crc_lnm_mcp/assets/model/deployment_manifest.json"))
        conversion = json.loads(archive.read("crc_lnm_mcp/assets/model/conversion_manifest.json"))
        runtime = archive.read("crc_lnm_mcp/assets/model/model_runtime.npz")
    assert metadata["Name"] == PACKAGE
    assert metadata["Version"] == VERSION
    assert metadata.get_all("Requires-Dist", []) == DEPENDENCIES
    assert all(n.startswith("crc_lnm_mcp/") or ".dist-info/" in n for n in names)
    assert not any("wei_multimodal" in n or "deployment_bundle" in n for n in names)
    forbidden_suffixes = (".pt", ".pth", ".ckpt", ".onnx")
    assert not any(n.lower().endswith(forbidden_suffixes) for n in names)
    runtime_models = [
        n
        for n in names
        if "/assets/model/" in n and n.lower().endswith((".npz", ".onnx"))
    ]
    assert runtime_models == ["crc_lnm_mcp/assets/model/model_runtime.npz"]
    assert hashlib.sha256(runtime).hexdigest() == manifest["runtime_asset_sha256"]
    assert manifest["runtime_backend"] == "numpy"
    assert manifest["source_framework"] == "pytorch"
    assert conversion["selected_seed"] == 2024
    assert conversion["member_count"] == 1
    assert conversion["ensemble_enabled"] is False
    assert conversion["parameter_count"] == 763842
    required = {
        "crc_lnm_mcp/assets/cases/demo_cases.jsonl",
        "crc_lnm_mcp/assets/model/deployment_manifest.json",
        "crc_lnm_mcp/assets/model/conversion_manifest.json",
        "crc_lnm_mcp/assets/model/model_architecture.json",
        "crc_lnm_mcp/assets/model/model_runtime.npz",
        "crc_lnm_mcp/assets/preprocessors/preprocessing.npz",
        "crc_lnm_mcp/assets/schemas/schema.json",
    }
    assert required.issubset(names)
    source_zip = args.source_zip
    if source_zip is not None:
        check_source_zip(source_zip)
    print("RELEASE CHECKS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
