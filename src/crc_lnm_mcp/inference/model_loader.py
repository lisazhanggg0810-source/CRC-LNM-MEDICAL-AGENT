"""Inventory-validated loader for one packaged NumPy model."""

from __future__ import annotations

import json
from importlib.resources import as_file
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from crc_lnm_mcp.settings import MAX_CASE_RECORD_BYTES, MAX_METADATA_BYTES, package_asset

from .numpy_model import NumpyMCAT
from .numpy_predictor import SingleModelPredictor
from .preprocessing import NumpyPreprocessor

Float32Array = NDArray[np.float32]

def _json(resource: Any, limit: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    with resource.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise RuntimeError("model JSON exceeds size limit")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("model JSON is invalid")
    return value


def load_runtime_parameters(
    runtime_path: Path,
    conversion_manifest: dict[str, Any],
) -> dict[str, Float32Array]:
    rows = conversion_manifest.get("arrays")
    if not isinstance(rows, list) or conversion_manifest.get("array_count") != len(rows):
        raise RuntimeError("runtime array manifest is invalid")
    expected = {str(row["asset_key"]): row for row in rows}
    parameters: dict[str, Float32Array] = {}
    with np.load(runtime_path, allow_pickle=False) as archive:
        if set(archive.files) != set(expected):
            raise RuntimeError("runtime array inventory mismatch")
        for name in sorted(expected):
            row = expected[name]
            array = np.asarray(archive[name]).copy()
            if list(array.shape) != row["shape"]:
                raise RuntimeError(f"runtime array shape mismatch: {name}")
            if str(array.dtype) != row["dtype"] or array.dtype != np.float32:
                raise RuntimeError(f"runtime array dtype mismatch: {name}")
            if int(array.size) != int(row["parameter_count"]):
                raise RuntimeError(f"runtime array parameter count mismatch: {name}")
            if not np.isfinite(array).all():
                raise RuntimeError(f"runtime array is non-finite: {name}")
            parameters[name] = np.asarray(array, dtype=np.float32)
    total = sum(array.size for array in parameters.values())
    if total != int(conversion_manifest["parameter_count"]):
        raise RuntimeError("runtime total parameter count mismatch")
    return parameters


def load_predictor(manifest: dict[str, Any]) -> SingleModelPredictor:
    runtime_resource = package_asset("model", str(manifest["runtime_asset_file"]))
    conversion_resource = package_asset("model", str(manifest["conversion_manifest_file"]))
    architecture_resource = package_asset("model", str(manifest["model_architecture_file"]))
    schema_resource = package_asset("schemas", str(manifest["schema_file"]))
    metadata_resource = package_asset("preprocessors", str(manifest["preprocessing_metadata_file"]))
    arrays_resource = package_asset("preprocessors", str(manifest["preprocessing_file"]))
    conversion = _json(conversion_resource)
    architecture = _json(architecture_resource)
    if architecture.get("runtime_backend") != "numpy":
        raise RuntimeError("runtime architecture backend mismatch")
    schema = _json(schema_resource, MAX_CASE_RECORD_BYTES)
    with as_file(runtime_resource) as runtime_path:
        parameters = load_runtime_parameters(runtime_path, conversion)
    with as_file(metadata_resource) as metadata_path, as_file(arrays_resource) as arrays_path:
        preprocessor = NumpyPreprocessor.from_files(schema, metadata_path, arrays_path)
    return SingleModelPredictor(
        NumpyMCAT(parameters),
        preprocessor,
        model_id=str(manifest["selected_model_id"]),
        seed=int(manifest["selected_seed"]),
    )


__all__ = ["load_predictor", "load_runtime_parameters"]
