"""The old import path resolves the actual Harness storage, without a wrapper."""

from __future__ import annotations

import importlib
import inspect
import json
import pickle
from pathlib import Path

import pytest

from loushang.harness.worker import _segmented_history as storage

legacy = importlib.import_module(
    "loushang.coding.package_product_worker_history_segments"
)
expected = json.loads(
    (Path(__file__).parent / "fixtures" / "worker_segment_public_v1.json").read_text()
)


def test_legacy_exports_are_actual_harness_objects_with_original_signatures():
    assert legacy.__all__ == expected["all"]
    for name, signature in expected["signatures"].items():
        value = getattr(legacy, name)
        assert value is getattr(storage, name)
        assert value.__module__ == storage.__name__
        assert str(inspect.signature(value)) == signature


@pytest.mark.parametrize("index", range(4))
def test_original_object_reference_and_repr_survive_owner_change(index):
    record = expected["objects"][index]
    value = pickle.loads(bytes.fromhex(record["pickle_protocol4_hex"]))
    assert type(value) is getattr(storage, record["class"])
    assert repr(value) == record["repr"]


def test_original_manifest_bytes_survive_owner_change():
    manifest = storage.CodingWorkerSegmentManifestV1.from_bytes(
        bytes.fromhex(expected["manifest_bytes_hex"]), stream_id="worker-history"
    )
    assert manifest.to_bytes().hex() == expected["manifest_bytes_hex"]
