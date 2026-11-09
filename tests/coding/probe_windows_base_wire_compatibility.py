"""Six source-bound value codecs compared with guarded original observations.

These pure value/format checks do not establish native Windows authority.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import pickle
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentError,
)

ROLES = ("opt_in", "receipt", "supervisor", "c5", "launch_intent", "provisioning")
CLASS_NAMES = (
    "CodingWindowsWorkerOptInSemanticBaseV1",
    "CodingWindowsWorkerReceiptSemanticBaseV1",
    "CodingWindowsWorkerSupervisorSemanticBaseV1",
    "CodingWindowsWorkerC5SemanticBaseV1",
    "CodingWindowsWorkerLaunchIntentSemanticBaseV1",
    "CodingWindowsWorkerNativeProvisioningSemanticBaseV1",
)
MODULES = tuple(
    importlib.import_module(
        "loushang.coding.package_product_worker_windows_" + role + "_base"
    )
    for role in ROLES
)
TYPES = {
    role: getattr(module, name)
    for role, module, name in zip(ROLES, MODULES, CLASS_NAMES, strict=True)
}
_FIXTURE = Path(__file__).parent / "fixtures/windows_base_wire_v1.json"


def describe_error(error):
    result = []
    while error is not None:
        result.append(
            [
                type(error).__module__ + "." + type(error).__name__,
                str(error),
                error.__suppress_context__,
            ]
        )
        error = error.__cause__
    return result


def describe_value(value):
    cls = type(value)
    try:
        value.scope_id = "changed"
    except Exception as error:
        frozen_error = [type(error).__module__ + "." + type(error).__name__, str(error)]
    else:
        raise AssertionError("the original value must be frozen")
    return dict(
        type=cls.__module__ + "." + cls.__name__,
        constructor=str(inspect.signature(cls)),
        fields=[
            [f.name, str(f.type), f.init, f.compare] for f in dataclasses.fields(cls)
        ],
        slots=list(cls.__slots__),
        has_dict=hasattr(value, "__dict__"),
        frozen_error=frozen_error,
        unsigned=list(value._unsigned_dict().items()),
        wire=value.to_bytes().hex(),
        pickle_roundtrip=pickle.loads(pickle.dumps(value)) == value,
    )


def variants(raw):
    doc = json.loads(raw)
    result = {
        "valid": raw,
        "empty": b"",
        "none": None,
        "text": raw.decode(),
        "bytearray": bytearray(raw),
        "bad-json": b"{",
        "bad-utf8": b"\xff",
        "array": b"[]",
        "null": b"null",
        "linefeed": raw + b"\n",
        "leading-space": b" " + raw,
        "deep-json": b"[" * 1200 + b"0" + b"]" * 1200,
        "extra-key": json.dumps({**doc, "foreign": 1}).encode(),
        "noncanonical": json.dumps(doc).encode(),
        "duplicate-key": b'{"version":1,' + raw[1:],
        "read-cap": raw,
        "write-cap": raw,
        "exact-cap": raw,
    }
    for key in doc:
        result["missing:" + key] = json.dumps(
            {k: v for k, v in doc.items() if k != key}
        ).encode()
        for label, value in (("null", None), ("boolean", True), ("object", {})):
            result[label + ":" + key] = json.dumps(
                {**doc, key: value}, sort_keys=True, separators=(",", ":")
            ).encode()
    for name in (
        "KeyError",
        "RecursionError",
        "TypeError",
        "UnicodeError",
        "ValueError",
        "LaunchIntentError",
    ):
        result["injected:" + name] = raw
    return result


def observe(role, raw, case, patch):
    cls = TYPES[role]
    candidate = variants(raw)[case]
    module = MODULES[ROLES.index(role)]
    with patch.context() as bound:
        try:
            if case == "write-cap":
                value = cls.from_bytes(raw)
                bound.setattr(module, "_MAX_BASE_BYTES", len(raw) - 1)
                value.to_bytes()
                raise AssertionError("output capacity must reject")
            if case in {"read-cap", "exact-cap"}:
                bound.setattr(
                    module, "_MAX_BASE_BYTES", len(raw) - (case == "read-cap")
                )
            if case.startswith("injected:"):
                error = {
                    "KeyError": KeyError("codec key"),
                    "RecursionError": RecursionError("codec recursion"),
                    "TypeError": TypeError("codec type"),
                    "UnicodeError": UnicodeError("codec unicode"),
                    "ValueError": ValueError("codec value"),
                    "LaunchIntentError": CodingWindowsWorkerLaunchIntentError(
                        "codec domain"
                    ),
                }[case.split(":", 1)[1]]

                def fail(_):
                    raise error

                bound.setattr(json, "loads", fail)
            value = cls.from_bytes(candidate)
            result = describe_value(value)
        except Exception as error:
            return dict(error=describe_error(error))
    # Convert only the observation to JSON shape; preserve dict insertion order.
    return dict(value=json.loads(json.dumps(result)))


@pytest.mark.parametrize("role", ROLES)
def test_original_six_base_wire_contracts(role, monkeypatch):
    fixture = json.loads(_FIXTURE.read_text())
    for family, raw_hex in fixture["records"][role].items():
        raw = bytes.fromhex(raw_hex)
        for case in variants(raw):
            assert (
                observe(role, raw, case, monkeypatch)
                == fixture["observations"][role][family][case]
            ), (role, family, case)


@pytest.mark.parametrize("role", ROLES)
def test_original_six_base_pickles_load_in_current_types(role):
    original = json.loads(
        _FIXTURE.with_name("windows_base_pickles_v1.json").read_text()
    )
    wire = json.loads(_FIXTURE.read_text())["records"][role]
    for family, raw_hex in original[role].items():
        restored = pickle.loads(bytes.fromhex(raw_hex))
        assert type(restored) is TYPES[role]
        assert restored.to_bytes().hex() == wire[family]
