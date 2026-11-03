from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from loushang.apphost.managed.admission_record import (
    MAX_ADMISSION_RECORD_BYTES,
    ManagedInitializationPhaseV1,
    ManagedNamespaceAdmissionRecordV1,
)
from loushang.apphost.managed.contracts import ManagedContractError, ManagedNamespaceV1
from loushang.apphost.managed.paths import (
    resolve_managed_admission_root,
    resolve_managed_registry_root,
)


def record(initialized=False):
    return ManagedNamespaceAdmissionRecordV1(
        "a" * 64, "b" * 32, "c" * 32,
        ManagedInitializationPhaseV1.INITIALIZED if initialized else ManagedInitializationPhaseV1.INITIALIZING,
        *((12, 345), (12, 346), (12, 347), (12, 348), (12, 349)) if initialized else (None,) * 5,
    )


@pytest.mark.parametrize("initialized", [False, True])
def test_record_roundtrip_is_bounded_immutable_and_not_service_ready(initialized):
    value = record(initialized)
    encoded = value.to_json()
    assert len(encoded.encode()) <= MAX_ADMISSION_RECORD_BYTES
    assert ManagedNamespaceAdmissionRecordV1.from_json(encoded) == value
    assert ManagedNamespaceAdmissionRecordV1.from_json(encoded).to_json() == encoded
    assert not hasattr(value, "ready") and not hasattr(value, "pid")
    assert "345" not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.operation_id = "d" * 32


@pytest.mark.parametrize("field,value", [
    ("namespace_key", "a" * 63), ("operation_id", "B" * 32), ("deployment_id", ""),
    ("phase", "initialized"), ("registry_root_identity", (12, 0)),
    ("database_identity", (True, 346)), ("registry_lock_identity", (12, 2**64)),
    ("registry_root_identity", [12, 345]), ("database_identity", (12, 345)),
    ("registry_lock_identity", None),
    ("admission_root_identity", (12, 345)), ("admission_lock_identity", None),
])
def test_constructor_rejects_incomplete_or_non_native_shapes(field, value):
    with pytest.raises(ManagedContractError, match="^invalid_managed_contract$"):
        replace(record(True), **{field: value})


def test_initializing_cannot_claim_partial_or_completed_identity():
    with pytest.raises(ManagedContractError):
        replace(record(), registry_root_identity=(12, 345))
    with pytest.raises(ManagedContractError):
        replace(record(), phase=ManagedInitializationPhaseV1.INITIALIZED)


@pytest.mark.parametrize("change", [
    lambda data: {**data, "version": "unknown/v2"},
    lambda data: {**data, "extra": True},
    lambda data: {key: value for key, value in data.items() if key != "operation"},
    lambda data: {**data, "phase": "ready"},
    lambda data: {**data, "database": [12, 0]},
    lambda data: {**data, "database": [12, False]},
    lambda data: {**data, "database": {"device": 12, "inode": 346}},
    lambda data: {**data, "namespace": "../secret/path"},
])
def test_decoder_rejects_unknown_schema_and_bad_values_without_echo(change):
    data = change(json.loads(record(True).to_json()))
    with pytest.raises(ManagedContractError, match="^invalid_managed_contract$"):
        ManagedNamespaceAdmissionRecordV1.from_json(json.dumps(data))


@pytest.mark.parametrize("raw", [
    "", "[]", "null", "{}", "{", "x" * (MAX_ADMISSION_RECORD_BYTES + 1),
    '"' + "汉" * 2000 + '"', "\ud800", "[" * 2000 + "]" * 2000,
])
def test_bad_or_oversized_encoding_is_bounded_error(raw):
    with pytest.raises(ManagedContractError, match="^invalid_managed_contract$"):
        ManagedNamespaceAdmissionRecordV1.from_json(raw)


def test_duplicate_keys_are_rejected():
    value = record().to_json()
    duplicated = '{"phase":"initialized",' + value[1:]
    with pytest.raises(ManagedContractError):
        ManagedNamespaceAdmissionRecordV1.from_json(duplicated)


def test_admission_path_is_pure_separate_from_lmux_and_namespace_bound(tmp_path, monkeypatch):
    namespace = ManagedNamespaceV1(str(tmp_path / "missing-platform"), 123, "a" * 32)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "unrelated"))
    monkeypatch.chdir(tmp_path)
    admission = resolve_managed_admission_root(namespace)
    registry = resolve_managed_registry_root(namespace)
    assert admission == Path(namespace.platform_home) / "state/managed-deployments" / namespace.namespace_key
    assert not admission.is_relative_to(Path(namespace.platform_home) / "lmux")
    assert not registry.is_relative_to(admission) and not admission.is_relative_to(registry)
    assert resolve_managed_admission_root(replace(namespace, machine_id="b" * 32)) != admission
    assert resolve_managed_admission_root(replace(namespace, user_id=124)) != admission
    assert not tuple(tmp_path.iterdir())
    with pytest.raises(ManagedContractError):
        resolve_managed_admission_root(None)
