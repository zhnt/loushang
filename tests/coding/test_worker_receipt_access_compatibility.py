"""Original receipt policy/storage join with real journal bytes and fake authority."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_receipt as module
from loushang.coding.package_product_worker_opt_in import CodingWorkerOptInJournal
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.harness.worker.test_product_activation import _policy

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux Product receipt rooted history"
)
CASES = (
    "no-opt-in",
    "revoked",
    "derive-none",
    "first",
    "reuse",
    "nonce-error",
    "late-current",
    "v2-full",
    "v2-retained",
    "v2-issue",
    "changed-scope",
)


def observe_receipt(case, root, patch):
    root.chmod(0o700)
    trace = []
    checks = 0
    nonce_calls = 0
    policy = replace(_policy(), product_scope_id="scope")

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

    @contextmanager
    def guard(_self, *, require_write=False):
        trace.append(["guard-enter", require_write])
        try:
            yield
        finally:
            trace.append(["guard-exit", require_write])

    def current(_self):
        nonlocal checks
        checks += 1
        trace.append("current")
        if case == "late-current" and checks == 2:
            raise OSError("unexpected extra currentness")

    product = object.__new__(PosixLocalWheelProductSessionOwner)
    product_policy = Policy()
    gc_gate = PluginPackageGcReservationJournal(root / "gc-reservations.jsonl")
    for name, value in dict(
        state_root=root,
        policy=product_policy,
        gc_gate=gc_gate,
        epoch_runtime=SimpleNamespace(registry=Registry()),
    ).items():
        object.__setattr__(product, name, value)
    patch.setattr(PluginPackageGcReservationJournal, "guard", guard)
    patch.setattr(
        PosixLocalWheelProductSessionOwner, "assert_root_gc_authority_current", current
    )
    decision = (
        None
        if case == "no-opt-in"
        else SimpleNamespace(
            action="revoke" if case == "revoked" else "allow",
            opt_in=object(),
            decision_digest="a" * 64,
        )
    )

    def selected_decision(_self, plugin):
        assert plugin == policy.plugin_id
        trace.append("opt-in")
        return decision

    def derive(_self, opt_in):
        assert opt_in is decision.opt_in
        trace.append("derive")
        return None if case == "derive-none" else policy

    original_nonce = module.secrets.token_hex

    def nonce(size):
        nonlocal nonce_calls
        if size != 16:
            return original_nonce(size)
        trace.append("nonce")
        nonce_calls += 1
        if case == "nonce-error":
            raise OSError("nonce unavailable")
        return f"{nonce_calls:032x}"

    patch.setattr(CodingWorkerOptInJournal, "current", selected_decision)
    patch.setattr(module.CodingWorkerProductReceiptOwner, "_derive", derive)
    patch.setattr(module.secrets, "token_hex", nonce)
    runtime = object.__new__(PackageProductRuntimeBindingV1)
    for name, value in dict(
        product_id="coding",
        session_id=policy.session_id,
        product_runtime_id=policy.product_runtime_id,
    ).items():
        object.__setattr__(runtime, name, value)
    selected = object.__new__(PackageProductSelectedPluginManifestV1)
    object.__setattr__(
        selected,
        "snapshot",
        SimpleNamespace(
            installation_key=SimpleNamespace(
                scope_id="scope", plugin_id=policy.plugin_id
            ),
        ),
    )
    opt_in = CodingWorkerOptInJournal(
        root / "worker-opt-in.jsonl",
        scope_id="scope",
        gc_gate=gc_gate,
        store_id="store",
    )
    owner = module.CodingWorkerProductReceiptOwner(
        product_owner=product,
        runtime=runtime,
        selected=selected,
        opt_in_journal=opt_in,
        native_closure_reader=SimpleNamespace(
            gc_gate=gc_gate, current_closure=lambda: None
        ),
    )
    construction = list(trace)
    trace.clear()
    if case.startswith("v2-") or case == "changed-scope":
        with _rooted(root) as rooted:
            prepared = _write_sources(rooted)
            rooted.sibling("worker-activation-receipts.jsonl.lock").create_new(b"")
            rooted.sibling("worker-history-v2-owner.json").create_new(
                prepared.index.to_bytes()
            )
    if case == "changed-scope":
        product_policy.scope = "changed-after-construction"
    if case == "reuse":
        assert owner.issue() is not None
        trace.clear()
        checks = 0
        nonce_calls = 0

    def inventory():
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.glob("worker-activation-receipts.*")
            if path.is_file()
        }

    before = inventory()
    result = None
    error = None
    try:
        if case in {"v2-full", "v2-retained", "changed-scope"}:
            records = module.read_coding_product_worker_receipt_records(
                product,
                retained_only=case != "v2-full",
            )
            result = [item.to_dict() for item in records]
        else:
            receipt = owner.issue()
            result = None if receipt is None else receipt.to_dict()
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
    return dict(
        construction=construction,
        trace=trace,
        result=result,
        error=error,
        before=before,
        after=inventory(),
        nonce_calls=nonce_calls,
    )


@pytest.mark.parametrize("case", CASES)
def test_original_receipt_access(case, tmp_path, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/worker_receipt_access_v1.json").read_text()
    )
    assert observe_receipt(case, tmp_path, monkeypatch) == expected[case]
