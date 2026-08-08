from __future__ import annotations

import hashlib
import json
from importlib.resources import as_file

import numpy as np

from crc_lnm_mcp.settings import package_asset


def test_conversion_manifest_checksum_is_line_ending_independent(tmp_path) -> None:
    from crc_lnm_mcp.inference.checksums import canonical_json_bytes

    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    changed = tmp_path / "changed.json"
    lf.write_bytes(b'{\n  "b": 2,\n  "a": 1\n}\n')
    crlf.write_bytes(b'{\r\n  "a": 1,\r\n  "b": 2\r\n}\r\n')
    changed.write_bytes(b'{\n  "a": 1,\n  "b": 3\n}\n')

    def digest(path):
        return hashlib.sha256(canonical_json_bytes(path)).hexdigest()

    assert digest(lf) == digest(crlf)
    assert digest(lf) != digest(changed)


def test_runtime_parameter_loader_validates_complete_inventory() -> None:
    from crc_lnm_mcp.inference.model_loader import load_runtime_parameters

    manifest = json.loads(package_asset("model", "conversion_manifest.json").read_text("utf-8"))
    with as_file(package_asset("model", "model_runtime.npz")) as runtime_path:
        parameters = load_runtime_parameters(runtime_path, manifest)
    assert len(parameters) == 66
    assert sum(array.size for array in parameters.values()) == 763842
    assert all(array.dtype == np.float32 for array in parameters.values())
    assert all(np.isfinite(array).all() for array in parameters.values())
