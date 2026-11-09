"""Frozen public and wire observations captured before Worker history extraction."""

from __future__ import annotations

import copy
import dataclasses
import importlib
import inspect
import json
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from loushang.coding.package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from loushang.coding.package_product_worker_history_stream_snapshot import (
    CodingWorkerHistoryStreamSnapshotV1,
)
from loushang.coding.package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorKeyBaseV2,
    CodingWorkerSupervisorSemanticBaseV2,
)

_FIXTURE = Path(__file__).with_name("fixtures") / "worker_history_public_values_v1.json"
_FAILURES = json.loads(
    _FIXTURE.with_name("worker_history_record_failures_v1.json").read_text()
)


@pytest.fixture(scope="module")
def observations():
    expected = json.loads(_FIXTURE.read_text())
    expected["values"].update(
        json.loads(
            _FIXTURE.with_name("worker_history_three_stream_values_v1.json").read_text()
        )["values"]
    )
    expected["values"].update(
        json.loads(
            _FIXTURE.with_name("worker_history_composite_values_v1.json").read_text()
        )["values"]
    )
    expected["values"].update(
        json.loads(
            _FIXTURE.with_name("worker_history_reader_values_v1.json").read_text()
        )["values"]
    )
    expected["values"].update(
        json.loads(
            _FIXTURE.with_name("worker_history_opt_in_projection_v1.json").read_text()
        )["values"]
    )
    return expected


@pytest.fixture(scope="module")
def samples(observations):
    expected = observations["values"]
    base = CodingWorkerSupervisorSemanticBaseV2.from_bytes(
        bytes.fromhex(expected["base"]["bytes"])
    )
    result = {
        "snapshot": CodingWorkerHistoryStreamSnapshotV1.from_dict(
            expected["snapshot"]["dict"]
        ),
        "key": CodingWorkerSupervisorKeyBaseV2.from_dict(expected["key"]["dict"]),
        "base": base,
        "replay": base.replay_retained(
            tuple(bytes.fromhex(raw) for raw in observations["replay_segments"])
        ),
        "retained": CodingProductWorkerRetainedAttemptV1(
            attempt_id="a" * 32,
            receipt_fingerprint="b" * 64,
            policy_fingerprint="c" * 64,
            owner_generation=1,
            cleanup_contract_version=1,
            host_identity="host",
            boot_identity="boot",
            phase="settled",
            last_seen_revision=2,
            current=False,
        ),
    }
    for name, observation in expected.items():
        recipe = observation.get("recipe")
        if recipe is None:
            if name.startswith("composite_"):
                cls = getattr(
                    importlib.import_module(observation["module"]), observation["name"]
                )
                if observation["bytes"] is not None:
                    result[name] = cls.from_bytes(bytes.fromhex(observation["bytes"]))
                elif observation["dict"] is not None:
                    result[name] = cls.from_dict(observation["dict"])
                else:
                    value = pickle.loads(bytes.fromhex(observation["pickle"]["4"]))
                    result[name] = dataclasses.replace(value)
            continue
        cls = getattr(
            importlib.import_module(observation["module"]), observation["name"]
        )
        if recipe["mode"] == "record":
            value = cls.from_dict(observation["dict"])
        elif recipe["mode"] == "base":
            value = cls.from_bytes(bytes.fromhex(observation["bytes"]))
        else:
            value = result[recipe["base"]].replay_retained(
                tuple(bytes.fromhex(raw) for raw in recipe["segments"])
            )
        assert type(value) is cls
        result[name] = value
    return result


@pytest.mark.parametrize(
    "name",
    ["snapshot", "key", "base", "replay", "retained"]
    + [
        f"{stream}_{part}"
        for stream in ("opt_in", "receipt", "start_gate")
        for part in ("record", "base", "replay")
    ]
    + [
        f"composite_{part}"
        for part in (
            "anchor",
            "preview",
            "stream",
            "index",
            "prepared",
            "ledger",
            "proof",
            "archive",
            "intent",
            "retained_history",
            "opt_in_projection",
        )
    ],
)
def test_original_public_value_contract(name, samples, observations):
    value = samples[name]
    expected = observations["values"][name]
    cls = type(value)
    assert cls.__module__ == expected["module"]
    assert cls.__name__ == expected["name"]
    assert str(inspect.signature(cls)) == expected["signature"]
    assert cls.__annotations__ == expected["annotations"]
    assert [
        {
            "name": member.name,
            "type": member.type,
            "default": None
            if member.default is dataclasses.MISSING
            else member.default,
            "has_default": member.default is not dataclasses.MISSING,
        }
        for member in dataclasses.fields(cls)
    ] == expected["fields"]
    if expected["repr"] is not None:
        assert repr(value) == expected["repr"]
    else:
        # Dataclass repr includes a frozenset whose iteration order is not fixed.
        assert repr(value).startswith(cls.__name__ + "(")
    assert not hasattr(value, "__dict__")
    first_field = dataclasses.fields(cls)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, first_field, getattr(value, first_field))
    if expected["dict"] is not None:
        assert value.to_dict() == expected["dict"]
    if expected["bytes"] is not None:
        assert value.to_bytes() == bytes.fromhex(expected["bytes"])
    for protocol, raw in expected["pickle"].items():
        # Fixtures contain only locally constructed inert original-source values.
        loaded = pickle.loads(bytes.fromhex(raw))
        assert type(loaded) is cls
        assert loaded == value
        assert pickle.loads(pickle.dumps(value, protocol=int(protocol))) == value


def test_snapshot_exact_type_still_uses_public_class(samples):
    class DerivedSnapshot(CodingWorkerHistoryStreamSnapshotV1):
        __slots__ = ()

    current = samples["snapshot"]
    derived = DerivedSnapshot.from_dict(current.to_dict())
    assert not current.is_exact_prefix_of(derived, current_segments=(b"{}\n",))
    assert derived.is_exact_prefix_of(current, current_segments=(b"{}\n",))


def test_original_activation_and_opt_in_constructor_signatures():
    expected = json.loads(
        _FIXTURE.with_name("worker_history_opt_in_projection_v1.json").read_text()
    )["constructors"]
    for name, signature in expected.items():
        module, _, cls = name.rpartition(".")
        assert (
            str(inspect.signature(getattr(importlib.import_module(module), cls)))
            == signature
        )


def test_shared_history_cold_import_has_no_coding_dependency():
    probe = """
import importlib.abc
import sys

class RefuseCoding(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'loushang.coding' or fullname.startswith('loushang.coding.'):
            raise AssertionError('Worker imported Coding: ' + fullname)

sys.meta_path.insert(0, RefuseCoding())
from loushang.harness.worker.history import _activation, _activation_base, _activation_store, _anchor, _checkpoint, _checkpoint_history, _cutover, _deletion, _no_effect, _opt_in, _opt_in_store, _preparation, _prepared, _preview, _publication, _read_v2, _receipt_store, _receipts, _snapshot, _start_gate, _start_gate_store, _supervisor, _v2_names
from loushang.harness.worker.payload import _records, _repair, _storage, _windows_stage_io, _windows_stage_retirement
from loushang.harness.worker.history import _checkpoint_commands, _snapshot_io, _windows_recovery, _windows_sources
assert not any(n == 'loushang.coding' or n.startswith('loushang.coding.') for n in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", probe], check=True, capture_output=True, text=True
    )


def _describe_error(error):
    return {
        "type": type(error).__module__ + "." + type(error).__name__,
        "message": str(error),
        "cause": None if error.__cause__ is None else _describe_error(error.__cause__),
    }


def _record_inputs():
    for cls in (CodingWorkerHistoryCheckpointV1, CodingWorkerSupervisorKeyBaseV2):
        expected = _FAILURES[cls.__name__]
        wire = expected["valid"]["value"]["wire"]
        values = [
            ("valid", wire),
            ("non-object", None),
            ("unknown-key", {**wire, "unexpected": 1}),
        ]
        for key in wire:
            missing = {k: value for k, value in wire.items() if k != key}
            values.append(("missing:" + key, missing))
            for i, bad in enumerate(
                (None, True, "", -1, {}, [], "different-namespace")
            ):
                values.append((f"{key}:{i}", {**wire, key: bad}))
        if "backupTopologyRevision" in wire:
            values.append(
                (
                    "prefix-before-digest",
                    {
                        **wire,
                        "backupTopologyRevision": "foreign:x",
                        "recordDigest": "broken",
                    },
                )
            )
        assert {label for label, _ in values} == set(expected)
        for label, incoming in values:
            yield pytest.param(
                cls, incoming, expected[label], id=cls.__name__ + ":" + label
            )


@pytest.mark.parametrize("cls,incoming,expected", list(_record_inputs()))
def test_original_record_admission_and_first_error(cls, incoming, expected):
    incoming = copy.deepcopy(incoming)
    before = copy.deepcopy(incoming)
    try:
        value = cls.from_dict(incoming)
    except Exception as error:
        actual = {"error": _describe_error(error)}
    else:
        assert type(value) is cls
        frozen = {}
        for name in (dataclasses.fields(cls)[0].name, "not_an_existing_field"):
            try:
                setattr(value, name, "mutation")
            except Exception as error:
                frozen[name] = _describe_error(error)
            else:
                frozen[name] = "unexpected mutation accepted"
        actual = {
            "value": {
                "public_type": cls.__module__ + "." + cls.__qualname__,
                "signature": str(inspect.signature(cls)),
                "fields": [
                    (f.name, str(f.type), f.init, f.compare, f.repr)
                    for f in dataclasses.fields(cls)
                ],
                "wire": value.to_dict(),
                "repr": repr(value),
                "has_dict": hasattr(value, "__dict__"),
                "frozen": frozen,
            }
        }
    assert json.loads(json.dumps(actual)) == expected
    assert incoming == before


def test_receipt_base_preserves_call_time_codec_capacity(
    samples, observations, monkeypatch
):
    from loushang.coding import package_product_worker_receipt as module

    monkeypatch.setattr(module, "_MAX_RECEIPTS", 0)
    segments = observations["values"]["receipt_replay"]["recipe"]["segments"]
    with pytest.raises(ValueError, match="receipt V2 segment is invalid") as error:
        samples["receipt_base"].replay_retained(
            tuple(bytes.fromhex(x) for x in segments)
        )
    assert type(error.value.__cause__) is module.CodingWorkerReceiptError
    assert error.value.__cause__.code == "coding_worker_receipt_capacity"


@pytest.mark.parametrize("stream", ["opt_in", "start_gate"])
def test_v2_parsers_preserve_import_time_capacity(stream, observations, monkeypatch):
    suffix = "opt_in" if stream == "opt_in" else "start_gate_journal"
    module = importlib.import_module(f"loushang.coding.package_product_worker_{suffix}")
    base = importlib.import_module(
        f"loushang.coding.package_product_worker_{stream}_base_v2"
    )
    monkeypatch.setattr(module, "_MAX_EVENTS", 0)
    segments = observations["values"][f"{stream}_replay"]["recipe"]["segments"]
    raw = bytes.fromhex(segments[0])
    if stream == "opt_in":
        assert base._parse_opt_in_segment(raw)
    else:
        assert base._parse_start_gate_segment(raw, first_revision=4)


def _base_wire_cases(wire):
    def encode(value):
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()

    yield "valid", encode(wire)
    yield "empty", b""
    yield "non-object", b"[]"
    yield "not-bytes", None
    yield "invalid-utf8", b"\xff"
    yield "deep-recursion", b"[" * 2000 + b"0" + b"]" * 2000
    yield "noncanonical", json.dumps(wire, sort_keys=True).encode()
    yield "unknown-key", encode({**wire, "unknown": 1})
    # Duplicate keys must retain the original json.loads / canonical order.
    first_key = next(iter(wire))
    repeated = encode({first_key: wire[first_key]})[1:-1]
    yield "duplicate-key", encode(wire)[:-1] + b"," + repeated + b"}"
    for key in wire:
        yield "missing:" + key, encode({k: v for k, v in wire.items() if k != key})
        for i, bad in enumerate((None, True, "", -1, {}, [], "wrong")):
            yield f"{key}:{i}", encode({**wire, key: bad})


def _base_wire_observation(cls, raw):
    try:
        value = cls.from_bytes(raw)
    except Exception as error:
        return {"error": _describe_error(error)}
    return {
        "type": type(value).__module__ + "." + type(value).__name__,
        "bytes": value.to_bytes().hex(),
        "repr": repr(value),
    }


def _base_wire_parameters():
    for name in (
        "worker_history_base_wire_v1.json",
        "worker_history_composite_values_v1.json",
        "worker_history_reader_values_v1.json",
    ):
        for spec in json.loads(_FIXTURE.with_name(name).read_text())["values"].values():
            if "wire" not in spec:
                continue
            cls = getattr(importlib.import_module(spec["module"]), spec["name"])
            cases = dict(_base_wire_cases(spec["wire"]))
            assert set(cases) == set(spec["outcomes"])
            for label, raw in cases.items():
                yield pytest.param(
                    cls, raw, spec["outcomes"][label], id=cls.__name__ + ":" + label
                )


@pytest.mark.parametrize("cls,raw,expected", list(_base_wire_parameters()))
def test_original_base_wire_admission_and_error_order(cls, raw, expected):
    assert _base_wire_observation(cls, raw) == expected


def _large_stream_value():
    from hashlib import sha256

    from loushang.coding.package_product_worker_history_cutover_v2 import (
        CodingWorkerStreamCutoverV2,
    )
    from loushang.coding.package_product_worker_history_segments import (
        CodingWorkerSealedSegmentV1,
    )
    from loushang.coding.package_product_worker_history_stream_snapshot import (
        _stream_fingerprint,
    )

    count = 8192
    seals = tuple(
        CodingWorkerSealedSegmentV1(
            generation=i,
            first_revision=i + 1,
            last_revision=i + 1,
            byte_count=2,
            digest="a" * 64,
        )
        for i in range(count)
    )
    empty = sha256(b"").hexdigest()
    fingerprint = _stream_fingerprint(
        stem="worker-opt-in",
        active_generation=count,
        last_sealed_revision=count,
        total_revision=count,
        counts=(2,) * count + (0,),
        digests=("a" * 64,) * count + (empty,),
    )
    return CodingWorkerStreamCutoverV2(
        stem="worker-opt-in",
        checkpoint_revision=1,
        checkpoint_digest="b" * 64,
        source_fingerprint=fingerprint,
        first_retained_generation=1,
        first_retained_revision=2,
        active_generation=count,
        retired_sealed=seals[:1],
        retained_sealed=seals[1:],
        active_byte_count=0,
        active_digest=empty,
        total_revision=count,
        semantic_base_digest="c" * 64,
    )


def test_original_stream_encoder_retains_asymmetric_capacity():
    from hashlib import sha256

    expected = json.loads(
        _FIXTURE.with_name("worker_history_large_stream_v1.json").read_text()
    )
    stream = _large_stream_value()
    raw = stream.to_bytes()
    assert len(raw) == expected["bytes"]
    assert sha256(raw).hexdigest() == expected["sha256"]
    assert len(raw) > 1024 * 1024
    with pytest.raises(ValueError, match="stream cutover bytes are invalid"):
        type(stream).from_bytes(raw)


def test_no_effect_product_restriction_stays_in_coding(samples):
    from loushang.coding.package_product_worker_no_effect_closure import (
        is_coding_worker_no_effect_closure,
    )
    from loushang.harness.worker.history._no_effect import is_no_effect_closure

    proof = samples["composite_proof"]
    policy = dataclasses.replace(
        proof.receipt.receipt.policy,
        product_id="other-product",
        allowed_product_ids=("other-product",),
    )
    receipt = dataclasses.replace(proof.receipt.receipt, policy=policy)
    record = type(proof.receipt).create(
        journal_revision=proof.receipt.journal_revision,
        scope_id=proof.receipt.scope_id,
        opt_in_decision_digest=proof.receipt.opt_in_decision_digest,
        receipt=receipt,
    )
    gate = type(proof.gate).create(
        journal_revision=proof.gate.journal_revision,
        phase=proof.gate.phase,
        attempt_id=proof.gate.attempt_id,
        worker_identity_fingerprint=proof.gate.worker_identity_fingerprint,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint=policy.fingerprint,
        scope_id=proof.gate.scope_id,
        native_closure_digest=proof.gate.native_closure_digest,
        identity=proof.gate.identity,
    )
    activation = dataclasses.replace(
        proof.activation,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint=policy.fingerprint,
    )
    facts = dict(gate=gate, activation=activation, supervisor=None, receipt=record)
    assert not is_coding_worker_no_effect_closure(**facts)
    assert is_no_effect_closure(**facts, product_id="other-product")
