from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.invocation import ManagedChildInvocationV1


def invocation():
    namespace = ManagedNamespaceV1("/private/平台", 1000, "a" * 32)
    service = ManagedServiceKeyV1("coding", "/工作区")
    return ManagedChildInvocationV1(
        namespace, service,
        ManagedInstanceRefV1(namespace.namespace_key, service.service_id, "b" * 32),
        "c" * 32, "/private/runtime",
    )


@pytest.mark.parametrize("scratch", [None, "/private/scratch"])
def test_trace_window_uses_v3_and_preserves_disabled_wire_bytes(scratch):
    original = replace(invocation(), temporary_override=scratch)
    before = original.to_json()
    traced = replace(original, trace_deadline_ms=123456789)
    record = json.loads(traced.to_json())
    assert record["version"] == "loushang.managed-child/v3"
    assert record["traceDeadlineMs"] == 123456789
    assert ManagedChildInvocationV1.from_json(traced.to_json()) == traced
    assert replace(traced, trace_deadline_ms=None).to_json() == before
    for old_version in ("loushang.managed-child/v1", "loushang.managed-child/v2"):
        with pytest.raises(ManagedContractError):
            ManagedChildInvocationV1.from_json(json.dumps({**record, "version": old_version}))
    del record["traceDeadlineMs"]
    with pytest.raises(ManagedContractError):
        ManagedChildInvocationV1.from_json(json.dumps(record))


@pytest.mark.parametrize("deadline", [True, 0, -1, 10**15 + 1, 1.5, "100", None])
def test_trace_wire_rejects_invalid_deadlines(deadline):
    record = json.loads(invocation().to_json())
    record.update(version="loushang.managed-child/v3", traceDeadlineMs=deadline)
    with pytest.raises(ManagedContractError):
        ManagedChildInvocationV1.from_json(json.dumps(record))


def test_roundtrip_is_pure_immutable_and_does_not_echo_paths(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invocation must not admit native resources")

    monkeypatch.setattr(Path, "resolve", forbidden)
    value = invocation()
    payload = value.to_json()
    assert ManagedChildInvocationV1.from_json(payload) == value
    assert ManagedChildInvocationV1.from_json(payload).to_json() == payload
    assert "平台" in payload
    assert "/private" not in repr(value) and "/工作区" not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.attempt_id = "d" * 32


@pytest.mark.parametrize("key,value", [
    ("version", "loushang.managed-child/v2"), ("userId", True),
    ("userId", 1.0), ("userId", -1), ("userId", 2**32),
    ("workspace", "/a/../b"), ("platformHome", "/"),
    ("instanceId", "x"), ("attemptId", "c" * 31),
    ("runtimeRoot", "/private/平台/lmux"), ("profile", "local/v1"),
    ("productId", None), ("machineId", []), ("workspace", "/x\ud800"),
    ("factory", "attacker.module:factory"), ("fd", 4), ("key", "secret"),
    ("namespaceKey", "0" * 64), ("serviceId", "0" * 64),
])
def test_closed_fields_and_value_contracts(key, value):
    record = json.loads(invocation().to_json())
    record[key] = value
    with pytest.raises(ManagedContractError, match="^invalid_managed_contract$"):
        ManagedChildInvocationV1.from_json(json.dumps(record))


def test_every_field_is_required_and_duplicates_never_overwrite():
    record = json.loads(invocation().to_json())
    for key, value in record.items():
        missing = dict(record)
        del missing[key]
        with pytest.raises(ManagedContractError):
            ManagedChildInvocationV1.from_json(json.dumps(missing))
        duplicate = json.dumps(record)[:-1] + "," + json.dumps(key) + ":" + json.dumps(value) + "}"
        with pytest.raises(ManagedContractError):
            ManagedChildInvocationV1.from_json(duplicate)


@pytest.mark.parametrize("payload", [
    None, b"{}", "", "null", "true", "[]", "{}", "{", "\ud800",
    "[" * 2000 + "]" * 2000, " " * 65537, "\"" + "界" * 24000 + "\"",
    '{"userId":NaN}', '{"userId":Infinity}', '{"userId":-Infinity}',
])
def test_malformed_oversized_or_nonobject_input_is_bounded(payload):
    with pytest.raises(ManagedContractError, match="^invalid_managed_contract$"):
        ManagedChildInvocationV1.from_json(payload)


def test_byte_limit_is_inclusive_before_json_decode():
    payload = invocation().to_json()
    padded = payload + " " * (65536 - len(payload.encode("utf-8")))
    assert ManagedChildInvocationV1.from_json(padded) == invocation()
    with pytest.raises(ManagedContractError):
        ManagedChildInvocationV1.from_json(padded + " ")


@pytest.mark.parametrize("scratch", [False, True])
def test_all_maximum_unicode_paths_fit_wire_budget(scratch):
    namespace = ManagedNamespaceV1("/" + "\U0001f600" * 4095, 2**32 - 1, "a" * 32)
    service = ManagedServiceKeyV1("x" * 128, "/" + "\U0001f601" * 4095)
    value = ManagedChildInvocationV1(namespace, service, ManagedInstanceRefV1(
        namespace.namespace_key, service.service_id, "b" * 32,
    ), "c" * 32, "/" + "\U0001f602" * 4095)
    if scratch:
        value = replace(value, temporary_override="/" + "\U0001f603" * 4095)
        assert 65536 < len(value.to_json().encode("utf-8")) <= 96 * 1024
    assert ManagedChildInvocationV1.from_json(value.to_json()) == value


def test_constructor_requires_exact_namespace_service_and_instance_binding():
    value = invocation()
    for change in (
        {"instance": replace(value.instance, namespace_key="0" * 64)},
        {"instance": replace(value.instance, service_id="0" * 64)},
        {"namespace": None}, {"service": None}, {"instance": None},
        {"attempt_id": False}, {"runtime_root": "relative"},
    ):
        with pytest.raises(ManagedContractError):
            replace(value, **change)


def test_explicit_scratch_uses_closed_v2_without_changing_v1():
    original = invocation()
    assert json.loads(original.to_json())["version"] == "loushang.managed-child/v1"
    value = replace(original, temporary_override="/private/scratch")
    record = json.loads(value.to_json())
    assert record["version"] == "loushang.managed-child/v2"
    assert record["temporaryRoot"] == "/private/scratch"
    assert ManagedChildInvocationV1.from_json(value.to_json()) == value
    for change in ({"version": "loushang.managed-child/v1"}, {"temporaryRoot": None},
                   {"temporaryRoot": "relative"}, {"temporaryRoot": "/private/平台/state"}):
        with pytest.raises(ManagedContractError):
            ManagedChildInvocationV1.from_json(json.dumps({**record, **change}))
    del record["temporaryRoot"]
    with pytest.raises(ManagedContractError):
        ManagedChildInvocationV1.from_json(json.dumps(record))
