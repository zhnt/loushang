"""Frozen original recovery facts/admission, not native cleanup authority."""

from __future__ import annotations

import dataclasses
import inspect
import json
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import (
    package_product_worker_windows_recovery_inventory as recovery,
)
from loushang.coding import (
    package_product_worker_windows_stage_retirement as retirement,
)

_FIXTURE = Path(__file__).parent / "fixtures/windows_recovery_values_v1.json"
ATTEMPT = "7" * 32
REQUEST, RECEIPT, IDENTITY = "a" * 64, "b" * 64, "c" * 64


def outcome(action):
    try:
        return dict(value=action())
    except Exception as error:
        chain = []
        while error is not None:
            chain.append(
                [
                    type(error).__module__ + "." + type(error).__name__,
                    str(error),
                    getattr(error, "code", None),
                    error.__suppress_context__,
                ]
            )
            error = error.__cause__
        return dict(error=chain)


def records():
    cls = recovery.CodingWindowsWorkerRecoveryAttemptV1
    fresh = cls(ATTEMPT, (13, 37), None, None, None, None, None)
    phases = (
        "reserved",
        "profile_effect",
        "profile_created",
        "grant_effect",
        "grants_applied",
        "verified",
        "active",
        "cleaning",
        "revoke_effect",
        "grants_revoked",
        "delete_effect",
        "profile_deleted",
        "settled",
    )
    settled = dataclasses.replace(
        fresh,
        native_phase="settled",
        native_revision=13,
        native_phase_history=phases,
        native_witness_present_history=(False, False) + (True,) * 11,
        native_witness_state="SETTLED",
        native_worker_request_fingerprint=REQUEST,
        native_receipt_fingerprint=RECEIPT,
        native_job_name="Global\\Worker-test",
        supervisor_phase="stopped",
        supervisor_revision=6,
        supervisor_process_settled=True,
        supervisor_identity_fingerprint=IDENTITY,
        launch_request_fingerprint=REQUEST,
        launch_receipt_fingerprint=RECEIPT,
        launch_identity_fingerprint=IDENTITY,
        launch_stage_identity=(13, 37),
    )
    result = dict(
        fresh=fresh,
        settled=settled,
        fenced=dataclasses.replace(settled, supervisor_phase="process_settled"),
    )
    for f in dataclasses.fields(settled):
        for label, value in (
            ("none", None),
            ("boolean", True),
            ("negative", -1),
            ("changed", "changed"),
        ):
            result[f.name + ":" + label] = dataclasses.replace(
                settled, **{f.name: value}
            )
    return result


def observe_record(value):
    cls = type(value)
    frozen = outcome(lambda: setattr(value, "attempt_id", "changed"))
    return dict(
        data=dataclasses.asdict(value),
        representation=repr(value),
        constructor=str(inspect.signature(cls)),
        fields=[[f.name, str(f.type)] for f in dataclasses.fields(value)],
        has_dict=hasattr(value, "__dict__"),
        frozen=frozen,
        replaced_equal=dataclasses.replace(value) == value,
        properties={
            name: outcome(lambda name=name: getattr(value, name))
            for name in ["observed_debts", "clean_exit_settled", "fenced_exit_settled"]
        },
        admission=observe_admission((value,)),
    )


def observe_admission(inventory, **changes):
    common = dict(
        attempt_id=ATTEMPT,
        payload_directory_identity=(13, 37),
        request_fingerprint=REQUEST,
        receipt_fingerprint=RECEIPT,
        identity_fingerprint=IDENTITY,
    )
    common.update(changes)
    return dict(
        ongoing=outcome(
            lambda: recovery.require_coding_windows_worker_current_attempt(
                inventory, initial=False, **common
            )
        ),
        initial=outcome(
            lambda: recovery.require_coding_windows_worker_current_attempt(
                inventory,
                initial=True,
                **{
                    **common,
                    "request_fingerprint": None,
                    "receipt_fingerprint": None,
                    "identity_fingerprint": None,
                },
            )
        ),
        release=outcome(
            lambda: recovery.require_coding_windows_worker_native_release_attempt(
                inventory, **common
            )
        ),
        cleanup=outcome(
            lambda: recovery.require_coding_windows_worker_terminal_cleanup_attempt(
                inventory, **common
            )
        ),
    )


JOIN_CASES = (
    "empty",
    "all",
    "retirement-only",
    "last-wins",
    "sorted-mixed",
    "native-empty",
    "bad-native-identity",
    "current-failure",
)


def observe_join(case, patch):
    events = []

    class Product:
        def assert_root_gc_authority_current(self):
            events.append("current")
            if case == "current-failure":
                raise ValueError("current authority changed")

    payload = SimpleNamespace(attempt_id=ATTEMPT, directory_identity=(13, 37))
    intent = SimpleNamespace(
        attempt_id=ATTEMPT,
        request_fingerprint=REQUEST,
        receipt_fingerprint=RECEIPT,
        identity_fingerprint=IDENTITY,
        stage_identity=(13, 37),
    )
    native = SimpleNamespace(
        attempt_id=ATTEMPT,
        phase="active",
        state_revision=7,
        phase_history=("reserved", "active"),
        witness_present_history=(False, True),
        last_witness_state="ACTIVE",
        identity=dict(
            workerRequestFingerprint=REQUEST,
            receiptFingerprint=RECEIPT,
            jobObjectName="job",
        ),
    )
    supervised = SimpleNamespace(
        attempt_id=ATTEMPT,
        phase="healthy",
        record_revision=4,
        process_settled=False,
        identity_fingerprint=IDENTITY,
    )
    payloads = [] if case in {"empty", "retirement-only"} else [payload]
    if case == "last-wins":
        payloads.append(
            SimpleNamespace(attempt_id=ATTEMPT, directory_identity=(99, 100))
        )
    if case == "sorted-mixed":
        payloads.extend(
            [
                SimpleNamespace(attempt_id="8" * 32, directory_identity=(3, 4)),
                SimpleNamespace(attempt_id="1" * 32, directory_identity=(1, 2)),
            ]
        )
    if case == "bad-native-identity":
        del native.identity["receiptFingerprint"]
    populated = case not in {"empty", "retirement-only"}

    def supplied(name, value):
        def read(*_, **__):
            events.append(name)
            return value

        return read

    with patch.context() as bound:
        bound.setattr(recovery, "os", SimpleNamespace(name="nt"))
        bound.setattr(recovery, "WindowsLocalWheelProductSessionOwner", Product)
        bound.setattr(
            retirement,
            "_inspect_retirement_attempt_ids_under_gc_guard",
            supplied(
                "retirement",
                frozenset({"6" * 32}) if case == "retirement-only" else frozenset(),
            ),
        )
        bound.setattr(
            recovery,
            "inspect_coding_windows_product_worker_payload_attempts",
            supplied("payloads", payloads),
        )
        bound.setattr(
            recovery,
            "_inspect_intents_under_gc_guard",
            supplied("intents", (intent,) if populated else ()),
        )
        bound.setattr(
            recovery,
            "inspect_coding_windows_product_worker_provisioning_attempts",
            supplied("native", (native,) if populated else ()),
        )
        bound.setattr(
            recovery,
            "open_coding_windows_product_worker_supervisor_journal",
            lambda _: SimpleNamespace(
                inspect_records=supplied(
                    "supervisor", (supervised,) if populated else ()
                )
            ),
        )
        kwargs = dict(native_attempts=()) if case == "native-empty" else {}
        result = outcome(
            lambda: [
                observe_record(v)
                for v in recovery._inspect_windows_worker_recovery_inventory_under_gc_guard(
                    Product(), **kwargs
                )
            ]
        )
    return dict(result=result, events=events)


def canonical(value):
    return json.loads(json.dumps(value))


@pytest.mark.parametrize("case", tuple(records()))
def test_original_recovery_values(case):
    expected = json.loads(_FIXTURE.read_text())
    assert canonical(observe_record(records()[case])) == expected["records"][case]


@pytest.mark.parametrize("case", JOIN_CASES)
def test_original_recovery_join(case, monkeypatch):
    assert (
        canonical(observe_join(case, monkeypatch))
        == json.loads(_FIXTURE.read_text())["join"][case]
    )


def test_original_recovery_pickle_loads_in_current_record():
    for name, raw in json.loads(_FIXTURE.read_text())["pickles"].items():
        value = pickle.loads(bytes.fromhex(raw))
        assert type(value) is recovery.CodingWindowsWorkerRecoveryAttemptV1
        assert value == records()[name]


def test_original_recovery_constructor_hints_resolve():
    from typing import get_type_hints

    expected = json.loads(
        _FIXTURE.with_name("windows_recovery_ctor_hints_v1.json").read_text()
    )
    hints = get_type_hints(recovery.CodingWindowsWorkerRecoveryAttemptV1.__init__)
    assert {name: str(value) for name, value in hints.items()} == expected
