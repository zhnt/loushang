"""Original Product access timing and append debt across rooted Supervisor calls."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.package_product_worker_supervisor_journal import (
    CodingProductWorkerSupervisorJournal,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.coding.test_package_product_worker_supervisor_segments import _identity

CASES = (
    "construct",
    "empty",
    "claim",
    "late-current",
    "failed-transition",
    "v2",
    "changed-scope",
)


def observe_access(case: str, root: Path, patch) -> dict:
    root.chmod(0o700)
    trace = []
    fail_late = case == "late-current"
    checks = 0

    class Policy:
        product_id = "coding"
        value = "scope"

        @property
        def project_scope_id(self):
            trace.append(["scope", self.value])
            return self.value

    class Registry:
        @property
        def store_id(self):
            trace.append(["store", "store"])
            return "store"

    class Gate:
        @contextmanager
        def guard(self, *, require_write):
            trace.append(["guard-enter", require_write])
            try:
                yield
            finally:
                trace.append(["guard-exit", require_write])

    def current(_self):
        nonlocal checks
        checks += 1
        trace.append("current")
        if fail_late and checks == 2:
            raise OSError("late currentness failure")

    policy = Policy()
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    for key, value in dict(
        state_root=root,
        policy=policy,
        epoch_runtime=SimpleNamespace(registry=Registry()),
        gc_gate=Gate(),
    ).items():
        object.__setattr__(product, key, value)
    patch.setattr(
        PosixLocalWheelProductSessionOwner, "assert_root_gc_authority_current", current
    )
    if case in {"v2", "changed-scope"}:
        with _rooted(root) as rooted:
            prepared = _write_sources(rooted)
            rooted.sibling("worker-supervisor.jsonl.lock").create_new(b"")
            rooted.sibling("worker-history-v2-owner.json").create_new(
                prepared.index.to_bytes()
            )
    journal = CodingProductWorkerSupervisorJournal(product)
    if case == "changed-scope":
        policy.value = "changed-after-construction"
    result = None
    error = None
    try:
        if case == "empty":
            result = journal.status("a" * 32)
        elif case in {"claim", "late-current", "failed-transition"}:
            result = journal.claim(_identity(attempt="1", epoch=1), max_attempts=3)
            if case == "failed-transition":
                journal.transition(
                    result.attempt_id,
                    expected_phase="healthy",
                    next_phase="draining",
                    expected_record_revision=result.record_revision,
                    expected_supervisor_epoch=1,
                )
        elif case in {"v2", "changed-scope"}:
            result = journal.status("e" * 32)
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
            exc = exc.__cause__ or exc.__context__
    # A late failure leaves original append debt; a later query can still see it.
    if case == "late-current":
        fail_late = False
        result = journal.status("1" * 32)
    return dict(
        trace=trace,
        result=None if result is None else result.to_dict(),
        error=error,
        files=sorted(p.name for p in root.iterdir()),
        active_cleared=all(
            getattr(journal, key) is None
            for key in ("_active_rooted", "_active_history", "_active_replay")
        ),
    )


@pytest.mark.parametrize("case", CASES)
@pytest.mark.skipif(sys.platform != "linux", reason="Linux rooted Supervisor profile")
def test_original_supervisor_access_timing_and_append_debt(case, tmp_path, monkeypatch):
    expected = json.loads(
        (
            Path(__file__).with_name("fixtures") / "worker_supervisor_access_v1.json"
        ).read_text()
    )
    assert observe_access(case, tmp_path, monkeypatch) == expected["cases"][case]


def test_rooted_supervisor_cold_import_has_no_coding_dependency():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys
class NoCoding(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'loushang.coding' or fullname.startswith('loushang.coding.'):
            raise AssertionError(fullname)
sys.meta_path.insert(0, NoCoding())
import loushang.harness.worker.history._rooted_supervisor
assert not any(n.startswith('loushang.coding') for n in sys.modules)
""",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
