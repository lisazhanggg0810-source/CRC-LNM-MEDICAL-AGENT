from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "mcpServers": {
        "crc-lnm-medical-agent": {
            "command": "uvx",
            "args": ["crc-lnm-medical-agent"],
        }
    }
}


def test_only_one_formal_modelscope_configuration_exists() -> None:
    configs = sorted(ROOT.rglob("modelscope-mcp.json"))
    assert configs == [ROOT / "modelscope-mcp.json"]


def test_modelscope_configuration_is_exact_minimal_utf8_without_bom() -> None:
    path = ROOT / "modelscope-mcp.json"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8")) == EXPECTED


def test_readme_first_json_block_matches_formal_configuration() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\{.*?\})\s*```", readme, re.DOTALL)
    assert match is not None
    assert json.loads(match.group(1)) == EXPECTED
    assert json.loads((ROOT / "modelscope-mcp.json").read_text("utf-8")) == EXPECTED