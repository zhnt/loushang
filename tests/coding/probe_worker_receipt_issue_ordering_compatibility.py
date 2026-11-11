"""Explicit frozen receipt issue observations with controlled append/root ports.

No physical Journal, FD, durability, or native Windows coverage is claimed.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_receipt as code
import loushang.coding.package_product_worker_windows_receipt as windows
import loushang.harness.worker.history._receipt_store as storage
import loushang.harness.worker.history._receipts as receipt_values
import loushang.harness.worker.history._windows_record_journals as windows_records
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)
from tests.harness.worker.test_product_activation import _policy

EXPECTED = Path(__file__).parent / "fixtures" / "worker_receipt_issue_ordering_v1.json"
CASES = (
    "first",
    "reuse",
    "different-digest",
    "different-policy",
    "older-match",
    "no-record-match",
    "override-latest",
    "high-checkpoint",
    "high-last",
    "no-decision",
    "revoked",
    "derive-none",
    "guard-error",
    "current-error",
    "opt-in-error",
    "derive-error",
    "position-error",
    "latest-error",
    "digest-error",
    "fingerprint-error",
    "nonce-error",
    "nonce-interrupt",
    "nonce-cancel",
    "receipt-error",
    "append-error",
    "append-committed-error",
    "position-exit-error",
    "guard-exit-error",
    "append-and-position-exit",
    "append-and-both-exits",
    "changing-digest",
)


def error_data(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return dict(
        type=f"{type(error).__module__}.{type(error).__qualname__}",
        args=list(error.args),
        notes=getattr(error, "__notes__", []),
        cause=error_data(error.__cause__, seen.copy()),
        context=error_data(error.__context__, seen.copy()),
        suppress=error.__suppress_context__,
    )


def observe(case, monkeypatch):
    trace = []
    policy = _policy()
    old_policy = replace(policy)
    other_policy = replace(policy, product_policy_revision="other-revision")
    seed1 = ProductWorkerActivationReceiptV1(old_policy, 1, "1" * 32)
    seed2 = ProductWorkerActivationReceiptV1(other_policy, 2, "2" * 32)
    rec1 = SimpleNamespace(receipt=seed1, opt_in_decision_digest="a" * 64)
    rec2 = SimpleNamespace(receipt=seed2, opt_in_decision_digest="a" * 64)
    records = ()
    if case in {"reuse", "digest-error", "fingerprint-error"}:
        records = (rec1,)
    if case in {"different-policy", "changing-digest"}:
        records = (rec2,)
    if case == "older-match":
        records = (rec1, rec2)
    if case == "different-digest":
        records = (SimpleNamespace(receipt=seed1, opt_in_decision_digest="c" * 64),)
    if case in {"no-record-match", "override-latest"}:
        foreign = replace(policy, session_id="foreign-session")
        records = (
            SimpleNamespace(
                receipt=ProductWorkerActivationReceiptV1(foreign, 1, "3" * 32),
                opt_in_decision_digest="a" * 64,
            ),
        )
    failures = {}
    fired = []
    fault_names = {
        "guard-error": ("guard.enter",),
        "current-error": ("current",),
        "opt-in-error": ("opt-in",),
        "derive-error": ("derive",),
        "position-error": ("position.enter",),
        "latest-error": ("latest",),
        "digest-error": ("decision.digest",),
        "fingerprint-error": ("fingerprint",),
        "nonce-error": ("nonce",),
        "nonce-interrupt": ("nonce",),
        "nonce-cancel": ("nonce",),
        "receipt-error": ("receipt.construct",),
        "append-error": ("append",),
        "append-committed-error": ("append.ack",),
        "position-exit-error": ("position.exit",),
        "guard-exit-error": ("guard.exit",),
        "append-and-position-exit": ("append", "position.exit"),
        "append-and-both-exits": ("append", "position.exit", "guard.exit"),
    }
    for name in fault_names.get(case, ()):
        failures[name] = (
            KeyboardInterrupt("fault", name)
            if case == "nonce-interrupt"
            else asyncio.CancelledError("fault", name)
            if case == "nonce-cancel"
            else OSError(5, "fault:" + name)
        )

    def event(name, *args):
        trace.append([name, *args])
        if name in failures:
            fired.append(name)
            raise failures[name]

    class Decision:
        action = "revoke" if case == "revoked" else "allow"
        opt_in = object()
        reads = 0

        @property
        def decision_digest(self):
            self.reads += 1
            event("decision.digest", self.reads)
            return ("b" if case == "changing-digest" and self.reads > 1 else "a") * 64

    decision = Decision()

    @contextmanager
    def guard(**kwargs):
        event("guard.enter", kwargs)
        try:
            yield
        finally:
            event("guard.exit")

    @contextmanager
    def position():
        event("position.enter")
        try:
            yield SimpleNamespace(
                records=records,
                last_revision=20 if case == "high-last" else len(records),
                checkpoint_revision=40 if case == "high-checkpoint" else 0,
            )
        finally:
            event("position.exit")

    owner = object.__new__(code.CodingWorkerProductReceiptOwner)
    owner._product = SimpleNamespace(
        gc_gate=SimpleNamespace(guard=guard),
        assert_root_gc_authority_current=lambda: event("current"),
    )
    owner._selected = SimpleNamespace(
        snapshot=SimpleNamespace(
            installation_key=SimpleNamespace(plugin_id=policy.plugin_id)
        )
    )

    def opt_in(plugin_id):
        event("opt-in", plugin_id)
        return None if case == "no-decision" else decision

    def derive(value):
        event("derive", value is decision.opt_in)
        return None if case == "derive-none" else policy

    original_latest = code.CodingWorkerProductReceiptOwner._latest

    def latest(received, selected):
        event("latest", received is records, selected is policy)
        return (
            rec1 if case == "override-latest" else original_latest(received, selected)
        )

    appended = []

    def append(received_position, *, next_revision, receipt, decision):
        # Controlled persistence boundary; digest is deliberately read only here.
        event("append", next_revision, receipt.issue_sequence)
        digest = decision.decision_digest
        appended.append([next_revision, receipt.issue_nonce, digest])
        event("append.ack")

    owner._opt_in = SimpleNamespace(current=opt_in)
    owner._derive = derive
    owner._append_position = position
    owner._latest = latest
    owner._append_record = append
    original_init = ProductWorkerActivationReceiptV1.__init__
    original_fingerprint = ProductWorkerActivationPolicyV1.fingerprint

    def make_receipt(self, *args, **kwargs):
        event(
            "receipt.construct", kwargs.get("issue_sequence"), kwargs.get("issue_nonce")
        )
        original_init(self, *args, **kwargs)

    def fingerprint(value):
        event("fingerprint", "requested" if value is policy else "historical")
        return original_fingerprint.fget(value)

    def nonce(size):
        event("nonce", size)
        return "b" * 32

    result = None
    failure = None
    with monkeypatch.context() as patch:
        for module in (code, storage):
            if hasattr(module, "secrets"):
                patch.setattr(module.secrets, "token_hex", nonce)
        patch.setattr(ProductWorkerActivationReceiptV1, "__init__", make_receipt)
        patch.setattr(
            ProductWorkerActivationPolicyV1, "fingerprint", property(fingerprint)
        )
        try:
            result = owner.issue()
        except BaseException as error:
            failure = error_data(error)
    assert fired == list(fault_names.get(case, ())), (case, fired, trace)
    if failures:
        assert failure is not None and result is None, (case, failure, trace)
    else:
        assert failure is None, (case, failure, trace)
        if case in {"no-decision", "revoked", "derive-none"}:
            assert result is None and not appended
            assert not any(
                row[0] in {"position.enter", "nonce", "append"} for row in trace
            )
        else:
            assert result is not None
    if case in {"reuse", "override-latest"}:
        assert result is seed1 and not appended
        assert not any(
            row[0] in {"nonce", "receipt.construct", "append"} for row in trace
        )
    if case == "high-checkpoint":
        assert result.issue_sequence == 41
    if case == "high-last":
        assert result.issue_sequence == 21
    if case == "older-match":
        assert result is not seed1 and result.issue_sequence == 3
    if case == "changing-digest":
        assert decision.reads == 2 and appended[-1][2] == "b" * 64
    if case in {"different-digest", "no-record-match"}:
        assert not any(row[0] == "fingerprint" for row in trace)
    latest_posix = original_latest(records, policy)
    latest_windows = windows.CodingWindowsWorkerProductReceiptOwner._latest(
        records, policy
    )

    def selected_record(value):
        return (
            None
            if value is None
            else dict(
                position=next(
                    index for index, record in enumerate(records) if record is value
                ),
                receipt=value.receipt.to_dict(),
            )
        )

    return dict(
        fired=fired,
        latest_posix=selected_record(latest_posix),
        latest_windows=selected_record(latest_windows),
        trace=trace,
        failure=failure,
        digest_reads=decision.reads,
        appended=appended,
        result=None
        if result is None
        else dict(
            record=result.to_dict(),
            same_old1=result is seed1,
            same_old2=result is seed2,
        ),
    )


def source_guard():
    root = Path(__file__).resolve().parents[2]
    modules = (
        (code, "src/loushang/coding/package_product_worker_receipt.py"),
        (windows, "src/loushang/coding/package_product_worker_windows_receipt.py"),
        (storage, "src/loushang/harness/worker/history/_receipt_store.py"),
        (receipt_values, "src/loushang/harness/worker/history/_receipts.py"),
        (
            windows_records,
            "src/loushang/harness/worker/history/_windows_record_journals.py",
        ),
    )
    for module, name in modules:
        assert Path(module.__file__).resolve() == root / name


_ROWS = json.loads(EXPECTED.read_text())


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row["case"])
def test_replay(row, monkeypatch):
    source_guard()
    actual = observe(row["case"], monkeypatch)
    assert json.dumps(actual, sort_keys=True) == json.dumps(
        row["result"], sort_keys=True
    )
