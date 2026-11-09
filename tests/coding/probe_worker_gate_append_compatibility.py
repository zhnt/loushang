"""Product activation coordination retains original ordering inside gate storage."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_start_gate_journal as gate_module
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker._segmented_history import CodingWorkerSegmentedHistoryV1

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux Product Worker gate history"
)

CASES = (
    "first-intent",
    "late-first-intent",
    "bound-without-intent",
    "existing-missing-activation",
    "candidate-denied",
    "binding-changed",
    "v2-empty-current",
    "v2-nonempty-current",
)


def observe_append(case, root, patch):
    root.chmod(0o700)
    trace = []
    checks = 0

    class Gate:
        @contextmanager
        def guard(self, *, require_write=False):
            trace.append(["guard-enter", require_write])
            try:
                yield
            finally:
                trace.append(["guard-exit", require_write])

    def current(_self):
        nonlocal checks
        checks += 1
        trace.append("current")
        if case == "late-first-intent" and checks == 2:
            raise OSError("unexpected extra currentness")

    product = object.__new__(PosixLocalWheelProductSessionOwner)
    policy = SimpleNamespace(
        product_id="coding",
        project_scope_id="scope",
        bindings=()
        if case == "candidate-denied"
        else (SimpleNamespace(source_trust_class="local-worker-candidate"),),
    )
    for name, value in dict(
        state_root=root,
        policy=policy,
        gc_gate=Gate(),
        epoch_runtime=SimpleNamespace(registry=SimpleNamespace(store_id="store")),
    ).items():
        object.__setattr__(product, name, value)
    patch.setattr(
        PosixLocalWheelProductSessionOwner, "assert_root_gc_authority_current", current
    )
    journal = gate_module.CodingWorkerStartGateJournal(product)
    command = dict(
        phase="bound" if case == "bound-without-intent" else "intent",
        attempt_id="a" * 32,
        worker_identity_fingerprint="1" * 64,
        receipt_fingerprint="2" * 64,
        policy_fingerprint="3" * 64,
        scope_id="session-scope",
        native_closure_digest="4" * 64,
    )
    if case in {"existing-missing-activation", "binding-changed"}:
        journal.append(**command)
        if case == "existing-missing-activation":
            for path in root.glob("worker-activation-state.*"):
                path.unlink()
            command["attempt_id"] = "b" * 32
        else:
            command["phase"] = "bound"
            command["receipt_fingerprint"] = "5" * 64
        trace.clear()
        checks = 0
    if case.startswith("v2-"):
        # The typed state has a valid positive historical high water with zero
        # current gates. Stop at activation.load so this probe tests the join,
        # not a fabricated physical V2 segment set.
        @contextmanager
        def bound():
            trace.append("bound-enter")
            try:
                yield object()
            finally:
                trace.append("bound-exit")

        history = CodingWorkerSegmentedHistoryV1(None, (b"",))
        replay = SimpleNamespace(
            current_records=()
            if case == "v2-empty-current"
            else (SimpleNamespace(attempt_id="b" * 32),),
            last_revision=4,
            retired_attempt_ids=frozenset(),
        )
        patch.setattr(journal, "_bound_journal", bound)
        patch.setattr(journal, "_v2_owner_exists", lambda rooted: True)
        patch.setattr(journal, "_checkpoint_writer_fence", lambda rooted: ())
        patch.setattr(journal, "_load_v2_state", lambda rooted: (history, replay))

        class Activation:
            def __init__(self, path):
                assert path == root / "worker-activation-state.jsonl"
                trace.append("activation-construct")

            def initialized_read_only(self):
                trace.append("activation-presence")
                return False

            def load(self):
                trace.append("activation-load")
                raise OSError("stop at original activation load")

        patch.setattr(
            gate_module, "CodingProductWorkerActivationStateJournal", Activation
        )
    result = None
    error = None
    try:
        result = journal.append(**command).to_dict()
    except Exception as exc:
        error = []
        while exc is not None:
            error.append(
                [
                    type(exc).__name__,
                    str(exc).replace(str(root), "<root>"),
                    getattr(exc, "code", None),
                    exc.__suppress_context__,
                ]
            )
            exc = exc.__cause__
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    return dict(trace=trace, result=result, error=error, files=files)


@pytest.mark.parametrize("case", CASES)
def test_original_gate_append(case, tmp_path, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/worker_gate_append_v1.json").read_text()
    )
    assert observe_append(case, tmp_path, monkeypatch) == expected[case]
