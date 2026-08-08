from __future__ import annotations

import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_has_one_console_script_and_audited_runtime_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert project["requires-python"] == ">=3.10"
    assert project["dependencies"] == [
        "fastmcp==2.14.7",
        "pydantic==2.13.4",
        "numpy==2.1.3",
    ]
    assert project["scripts"] == {"crc-lnm-medical-agent": "crc_lnm_mcp.server:run"}


def test_main_module_only_imports_and_calls_run() -> None:
    path = ROOT / "src/crc_lnm_mcp/__main__.py"
    tree = ast.parse(path.read_text("utf-8"))
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert len(imports) == 1
    assert imports[0].module == "server" and imports[0].level == 1
    assert [alias.name for alias in imports[0].names] == ["run"]
    assert len(calls) == 1
    assert isinstance(calls[0].func, ast.Name) and calls[0].func.id == "run"
