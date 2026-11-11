"""Original gate access timing, query side effects, and late authority reads."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux Product Worker gate history"
)

CASES = (
    "empty-current",
    "empty-attempts",
    "late-current",
    "late-attempts",
    "v2-current",
    "v2-attempts",
    "changed-scope",
)


def observe_gate(case: str, root: Path, patch) -> dict:
    root.chmod(0o700)
    trace = []
    checks = 0

    class Policy:
        product_id = "coding"
        scope = "scope"

        @property
        def project_scope_id(self):
            trace.append(["scope", self.scope])
            return self.scope

    class Registry:
        @property
        def store_id(self):
            trace.append(["store", "store"])
            return "store"

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
        if case.startswith("late-") and checks == 2:
            raise OSError("late currentness failure")

    policy = Policy()
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    for name, value in dict(
        state_root=root,
        policy=policy,
        gc_gate=Gate(),
        epoch_runtime=SimpleNamespace(registry=Registry()),
    ).items():
        object.__setattr__(product, name, value)
    patch.setattr(
        PosixLocalWheelProductSessionOwner, "assert_root_gc_authority_current", current
    )
    if case.startswith("v2-") or case == "changed-scope":
        with _rooted(root) as rooted:
            prepared = _write_sources(rooted)
            rooted.sibling("worker-start-gates.jsonl.lock").create_new(b"")
            rooted.sibling("worker-history-v2-owner.json").create_new(
                prepared.index.to_bytes()
            )
    journal = CodingWorkerStartGateJournal(product)
    if case == "changed-scope":
        policy.scope = "changed-after-construction"

    def inventory():
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*")
            if path.is_file()
        }

    before = inventory()
    result = None
    error = None
    try:
        if case.endswith("attempts"):
            result = [item.to_dict() for item in journal.attempts()]
        else:
            record = journal.current("b" * 32)
            result = None if record is None else record.to_dict()
    except Exception as exc:
        error = []
        while exc is not None:
            error.append(
                [
                    type(exc).__name__,
                    str(exc),
                    getattr(exc, "code", None),
                    exc.__suppress_context__,
                ]
            )
            exc = exc.__cause__
    assert before == inventory(), "queries must preserve original physical history"
    return dict(trace=trace, result=result, error=error)


@pytest.mark.parametrize("case", CASES)
def test_original_gate_access(case, tmp_path, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/worker_gate_access_v1.json").read_text()
    )
    assert observe_gate(case, tmp_path, monkeypatch) == expected[case]
