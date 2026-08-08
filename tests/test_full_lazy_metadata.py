from __future__ import annotations

import builtins
import json

from crc_lnm_mcp.runtime import RuntimeProvider


def test_model_info_reports_selected_single_model_without_torch(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "torch" or name.startswith("torch."):
            raise RuntimeError("torch import blocked for metadata operation")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    runtime = RuntimeProvider()
    data = runtime.metadata.get_model_info()
    assert data["package_version"] == "1.0.19"
    assert data["deployment_profile"] == "single_model_modelscope"
    assert data["member_count"] == 1
    assert data["ensemble_enabled"] is False
    assert data["selected_model_id"] == "seed_2024"
    assert data["selected_seed"] == 2024
    assert data["research_use_only"] is True
    assert data["independent_test_claim"] is False


def test_model_info_preserves_dimensions_threshold_and_feature_order() -> None:
    data = RuntimeProvider().metadata.get_model_info()
    assert data["pathology_feature_count"] == 768
    assert data["ct_feature_count"] == 1409
    assert data["ct_group_counts"] == {
        "shape": 14,
        "original": 93,
        "wavelet": 744,
        "transformed": 558,
    }
    assert data["clinical_features"] == ["age", "male", "Type", "T"]
    assert data["threshold"] == 0.3529504342004657
    assert data["threshold_recalibrated_for_single_model"] is False
    assert data["feature_order_sha256"] == (
        "d4a5ecb56733db87f505473a7be1497a7fdd174c0994748d5b9574f7373d3200"
    )


def test_metadata_does_not_disclose_absolute_paths() -> None:
    serialized = json.dumps(RuntimeProvider().metadata.get_model_info(), sort_keys=True)
    assert ":\\" not in serialized
    assert "C:/" not in serialized
    assert "C:\\" not in serialized


def test_metadata_provider_reads_manifest_only_on_first_use() -> None:
    runtime = RuntimeProvider()
    assert runtime.metadata.manifest_read_count == 0
    first = runtime.metadata.get_model_info()
    second = runtime.metadata.get_model_info()
    assert first == second
    assert runtime.metadata.manifest_read_count == 1
