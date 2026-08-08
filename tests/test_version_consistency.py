from __future__ import annotations

import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_project_and_deployment_manifest_are_version_1_0_19() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert project["version"] == "1.0.19"
    manifest = __import__("json").loads(
        (ROOT / "src/crc_lnm_mcp/assets/model/deployment_manifest.json").read_text("utf-8")
    )
    assert manifest["package_version"] == project["version"]


def test_built_wheel_metadata_matches_pyproject_when_present() -> None:
    wheels = list((ROOT / "dist").glob("*.whl")) if (ROOT / "dist").exists() else []
    if not wheels:
        return
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    with zipfile.ZipFile(wheels[0]) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
    assert f"Version: {project['version']}\n" in metadata.replace("\r\n", "\n")
