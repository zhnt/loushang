"""Explicit fixed original complete history-proof observations; no recapture.

Real GC/Journal/Rooted IO, checkpoint/preflight/V2 owner bytes and repair readers.
Product current/pin/epoch/registry and native closure/group ports are controlled.
Some opt-in projections and GC pins are controlled values. V2 retirement uses
fixture unlink+ledger, not a full retirement transaction. Sync KI/CancelledError
and after-close failures do not prove Task.cancel or pre-close failure handling.
All raw original observations remain outside Product; this is not native crash,
ACL, real lease contention or complete registered-recovery evidence.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import os
import pickle
import re
import stat
import sys
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_worker_history_retention as code
from loushang.coding import package_product_worker_posix_gc_history as gc_code
from loushang.coding import package_product_worker_start_gate_recovery as gated_code
from loushang.coding.package_product_backup_types import _topology_bytes
from loushang.coding.package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from loushang.coding.package_product_worker_installed_native import (
    CodingProductInstalledWorkerReleaseReader,
)
from loushang.coding.package_product_worker_native_release import (
    CodingWorkerNativeReleaseError,
)
from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInJournal,
    _opt_in_line,
)
from loushang.coding.package_product_worker_payload import _STORAGE
from loushang.coding.package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
    _linux_receipt_line,
)
from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
)
from loushang.coding.package_product_worker_supervisor_journal import (
    CodingProductWorkerSupervisorJournal,
)
from loushang.harness.journal import _rooted_io
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.worker.gated_start import WorkerNativeProcessIdentityV1
from loushang.harness.worker.history._opt_in_store import OptInJournal
from loushang.harness.worker.history._snapshot_io import SnapshotHistory
from loushang.harness.worker.product_activation import (
    WorkerCleanupSettlementV1,
    _AttemptKey,
)
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)
from tests.coding.test_package_product_worker_history_commit_v2 import _locks
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.coding.test_package_product_worker_opt_in_base_v2 import _allow
from tests.harness.worker.test_journal import _identity, _settle
from tests.harness.worker.test_product_activation import _policy, _receipt

ATTEMPT = "a" * 32
COMMON = (
    "normal",
    "no-effect",
    "empty",
    "missing-receipt",
    "missing-c5",
    "native-error",
    "native-other",
    "native-second-error",
    "interrupt",
    "cancel-exception",
    "native-present",
    "native-prior-boot",
    "gate-mismatch",
    "unbound-gate",
    "unknown-name",
    "case-name",
    "payload-stage",
    "registered-stage",
    "supervisor-active",
    "activation-active",
    "opt-in-missing",
    "opt-in-duplicate",
    "opt-in-wrong-last",
    "current-first",
    "pin1-enter",
    "pin1-exit",
    "read-error",
    "cleanup-error",
    "body-and-cleanup",
    "repair-empty",
    "repair-unmarked",
    "repair-complete",
    "repair-registered",
    "repair-registered-mismatch",
    "global-unbound",
    "global-supervisor-active",
    "global-opt-in-unverified",
    "archive-exact",
    "archive-retired",
    "archive-repair-changed",
    "archive-missing-ledger",
)
RETENTION = (
    "backup-missing",
    "backup-changed",
    "active-leases",
    "snapshot-error",
    "snapshot-after",
    "snapshot-mismatch",
    "pin2-exit",
    "pin3-exit",
    "scope-invalid",
    "attempt-invalid",
    "quiescence-enter",
    "quiescence-exit",
    "gc-enter",
    "gc-exit",
    "gc-pins",
)
GC = (
    "inventory-first",
    "inventory-last",
    "inventory-type",
    "inventory-duplicate",
    "open-preparation",
    "repair-bad",
    "repair-stage",
    "receipt-product",
    "group-error",
    "group-interrupt",
    "group-cancel",
    "repair-registered-duplicate",
)
GATED = (
    "normal",
    "empty",
    "native-error",
    "native-other",
    "native-second-error",
    "interrupt",
    "cancel-exception",
    "gate-mismatch",
    "native-present",
    "native-prior-boot",
)
V2 = (
    "normal",
    "retired",
    "missing-ledger",
    "head-corrupt",
    "preparation-corrupt",
    "checkpoint-corrupt",
)
CASES = (
    tuple("retention:" + c for c in (*COMMON, *RETENTION))
    + tuple(
        "gc:" + c
        for c in (
            *tuple(
                c
                for c in COMMON
                if c
                not in {
                    "native-error",
                    "native-other",
                    "native-second-error",
                    "interrupt",
                    "cancel-exception",
                }
            ),
            *GC,
        )
    )
    + tuple("gated:" + c for c in GATED)
    + tuple("v2:" + c for c in V2)
)


def observe(name, base, patch):
    program, case = name.split(":")
    base.chmod(0o700)
    root = base / "root"
    root.mkdir(mode=0o700)
    trace, results = [], []
    phase = "seed"
    fired = False
    native_count = pin_count = current_count = 0
    fd_sequence = 0
    live = {}
    real_open, real_close, real_dup = os.open, os.close, os.dup
    real_read = _rooted_io.RootedFile.read_bytes
    real_cleanup = _rooted_io.RootedFileIO.cleanup
    real_capture = SnapshotHistory.capture
    real_projection = OptInJournal.retention_projection_under_gc_guard
    real_snapshot_guard = PluginPackageGcReservationJournal.read_snapshot_guard
    real_listdir = os.listdir

    def event(*row):
        if phase != "seed":
            trace.append(list(row))

    def inject(*wanted):
        return phase == "first" and case in wanted and not fired

    def fault():
        nonlocal fired
        fired = True
        event("fault", case)
        if case in {"interrupt", "group-interrupt"}:
            raise KeyboardInterrupt("injected history interruption")
        if case in {"cancel-exception", "group-cancel"}:
            raise asyncio.CancelledError("injected synchronous history cancellation")
        raise OSError("injected " + case)

    class Registry:
        store_id = "store"

        @contextmanager
        def exclusive_runtime_quiescence(self, **kwargs):
            event("quiescence-enter", kwargs)
            if inject("quiescence-enter"):
                fault()
            try:
                yield NS(
                    active_runtime_lease_ids=("active-lease",)
                    if case == "active-leases"
                    else ()
                )
            finally:
                event("quiescence-exit")
                if inject("quiescence-exit"):
                    fault()

    class Epoch(PackageProductPosixFencedRuntimeOwner):
        def __init__(self):
            self.registry = Registry()

        def assert_current(self):
            event("epoch-current")

    gate = PluginPackageGcReservationJournal(root / "package-gc-reservations.jsonl")
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    policy = NS(
        product_id="coding",
        project_scope_id="scope",
        bindings=(NS(source_trust_class="local-worker-candidate"),),
    )
    for key, value in dict(
        state_root=root, policy=policy, gc_gate=gate, epoch_runtime=Epoch()
    ).items():
        object.__setattr__(product, key, value)

    def current(self):
        nonlocal current_count
        assert self is product
        current_count += 1
        event("product-current", current_count)
        if inject("current-first") and current_count == 1:
            fault()

    @contextmanager
    def pin(self):
        nonlocal pin_count
        assert self is product
        pin_count += 1
        index = pin_count
        event("pin-enter", index)
        if inject("pin1-enter") and index == 1:
            fault()
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)
            event("pin-exit", index)
            if inject(f"pin{index}-exit"):
                fault()

    patch.setattr(
        PosixLocalWheelProductSessionOwner, "assert_root_gc_authority_current", current
    )
    patch.setattr(PosixLocalWheelProductSessionOwner, "pinned_state_root_gc_read", pin)

    def opened(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal fd_sequence
        related = str(name).startswith(str(root)) or dir_fd in live
        fd = real_open(name, flags, mode, dir_fd=dir_fd)
        if related:
            prior = live.pop(fd, None)
            if prior is not None:
                event("closed-by-file-object", prior)
            fd_sequence += 1
            live[fd] = "fd" + str(fd_sequence)
            event(
                "open",
                str(name).replace(str(base), "<ROOT>"),
                flags,
                mode,
                live.get(dir_fd),
                live[fd],
            )
        return fd

    def closed(fd):
        label = live.pop(fd, None)
        if label is not None:
            event("close", label)
        return real_close(fd)

    def dup(fd):
        nonlocal fd_sequence
        new = real_dup(fd)
        if fd in live:
            prior = live.pop(new, None)
            if prior is not None:
                event("closed-by-file-object", prior)
            fd_sequence += 1
            event("dup", live[fd], "fd" + str(fd_sequence))
            live[new] = "fd" + str(fd_sequence)
        return new

    def read(self, **kwargs):
        event("read", self._name, kwargs)
        if inject("read-error", "body-and-cleanup"):
            fault()
        return real_read(self, **kwargs)

    def cleanup(self):
        real_cleanup(self)
        event("cleanup")
        if phase == "first" and case == "body-and-cleanup":
            raise OSError("injected cleanup after body")
        if inject("cleanup-error"):
            fault()

    def native(self):
        nonlocal native_count, fired
        native_count += 1
        event("native-closure", native_count)
        if (
            inject("native-error")
            or inject("native-second-error")
            and native_count == 2
        ):
            fired = True
            event("native-fault", case, native_count)
            raise CodingWorkerNativeReleaseError("injected native unavailable")
        if inject("native-other", "interrupt", "cancel-exception"):
            fault()
        return NS(to_dict=lambda: {"closure": "original-fixed"})

    def native_status(identity):
        event(
            "native-status",
            identity.to_dict()
            if hasattr(identity, "to_dict")
            else dataclasses.asdict(identity),
        )
        if inject("group-error", "group-interrupt", "group-cancel"):
            fault()
        return (
            "present"
            if case == "native-present"
            else "prior_boot_absent"
            if case == "native-prior-boot"
            else "absent"
        )

    def capture(self, access):
        nonlocal fired
        event("snapshot-capture")
        if inject("snapshot-error"):
            fault()
        if inject("snapshot-mismatch"):
            from loushang.coding.package_product_worker_history_segments import (
                _head_bytes,
                _head_name,
            )
            from loushang.coding.package_product_worker_opt_in import (
                CodingWorkerOptInDecisionV1,
            )

            revoke = CodingWorkerOptInDecisionV1.create(
                journal_revision=2,
                scope_id="scope",
                plugin_id="plugin.one",
                operation_id="revoke-late",
                generation=2,
                kill_switch_generation=1,
                action="revoke",
                opt_in=None,
            )
            with _rooted(root) as rooted:
                target = rooted.sibling("worker-opt-in.jsonl")
                raw = target.read_bytes(max_bytes=1024 * 1024) + _opt_in_line(revoke)
                target.atomic_write(raw)
                target.sibling(_head_name("worker-opt-in", 0)).atomic_write(
                    _head_bytes("worker-opt-in", 0, raw)
                )
            fired = True
            event("snapshot-source-drift")
        value = real_capture(self, access)
        if inject("snapshot-after"):
            fault()
        return value

    def projection(self):
        event("opt-in-projection")
        value = real_projection(self)
        if case == "opt-in-duplicate" and value.reference_decisions:
            return dataclasses.replace(
                value,
                reference_decisions=(
                    *value.reference_decisions,
                    value.reference_decisions[0],
                ),
            )
        if case == "opt-in-wrong-last" and value.reference_decisions:
            wrong = NS(
                **{
                    f.name: getattr(value.reference_decisions[0], f.name)
                    for f in dataclasses.fields(value.reference_decisions[0])
                }
            )
            wrong.action = "revoke"
            return dataclasses.replace(
                value, reference_decisions=(*value.reference_decisions, wrong)
            )
        return value

    @contextmanager
    def read_snapshot_guard(self):
        event("gc-snapshot-enter")
        if inject("gc-enter"):
            fault()
        try:
            with real_snapshot_guard(self) as snapshot:
                if case == "gc-pins":
                    from loushang.harness.plugin_management.records import (
                        PluginPackageRevisionRefV1,
                    )

                    pins = tuple(
                        PluginPackageRevisionRefV1(
                            plugin_id="plugin.one",
                            plugin_version="1",
                            package_content_digest="a" * 64,
                            dependency_lock_digest=digest * 64,
                            package_source_identity="source-" + digest,
                        )
                        for digest in ("b", "c")
                    )
                    snapshot = dataclasses.replace(
                        snapshot,
                        journal_revision=9,
                        active=tuple(
                            NS(candidate=NS(package_revision=ref)) for ref in pins
                        ),
                    )
                yield snapshot
        finally:
            event("gc-snapshot-exit")
            if inject("gc-exit"):
                fault()

    listdir_count = 0

    def listdir(fd):
        nonlocal listdir_count
        value = real_listdir(fd)
        if phase != "seed" and isinstance(fd, int) and fd in live:
            listdir_count += 1
            event("listdir", live[fd], listdir_count)
            if inject("inventory-first") and listdir_count == 1:
                return [*value, "late-first"]
            if inject("inventory-last") and listdir_count == 2:
                return [*value, "late-last"]
        return value

    patch.setattr(os, "open", opened)
    patch.setattr(os, "close", closed)
    patch.setattr(os, "dup", dup)
    patch.setattr(os, "listdir", listdir)
    patch.setattr(_rooted_io.RootedFile, "read_bytes", read)
    patch.setattr(_rooted_io.RootedFileIO, "cleanup", cleanup)
    patch.setattr(CodingProductInstalledWorkerReleaseReader, "current_closure", native)
    for module in (code, gc_code, gated_code):
        if hasattr(module, "worker_native_group_status_after_restart"):
            patch.setattr(
                module, "worker_native_group_status_after_restart", native_status
            )
    if not hasattr(code, "worker_native_group_status_after_restart"):
        from loushang.harness.package_product import _linux_worker_history

        patch.setattr(
            _linux_worker_history,
            "worker_native_group_status_after_restart",
            native_status,
        )
    patch.setattr(SnapshotHistory, "capture", capture)
    patch.setattr(OptInJournal, "retention_projection_under_gc_guard", projection)
    patch.setattr(
        PluginPackageGcReservationJournal, "read_snapshot_guard", read_snapshot_guard
    )

    # The guard and all journal storage below are the original implementations.
    with gate.guard(require_write=True):
        pass
    (root / "coding-backup-types.json").write_bytes(_topology_bytes("scope"))
    (root / "coding-backup-types.json").chmod(0o600)

    if program == "v2":
        from loushang.coding.package_product_worker_history_deletion_v2 import (
            CodingWorkerV2DeletionLedger,
        )
        from loushang.coding.package_product_worker_history_segments import (
            _head_name,
            _segment_name,
        )
        from loushang.coding.package_product_worker_history_v2_names import (
            DELETION_LEDGER_NAME,
            PRODUCT_OWNER_INDEX_NAME,
        )

        with _rooted(root) as rooted:
            prepared = _write_sources(rooted)
            _locks(rooted)
            rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(
                prepared.index.to_bytes()
            )
            if case in {"retired", "missing-ledger"}:
                rooted.sibling(_segment_name("worker-supervisor", 0)).unlink()
                rooted.sibling(_head_name("worker-supervisor", 0)).unlink()
                if case == "retired":
                    rooted.sibling(DELETION_LEDGER_NAME).create_new(
                        CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
                    )
            if case == "head-corrupt":
                rooted.sibling(_head_name("worker-supervisor", 1)).atomic_write(b"{}")
            if case == "preparation-corrupt":
                rooted.sibling("worker-history-v2-preparation.json").atomic_write(b"{}")
            if case == "checkpoint-corrupt":
                rooted.sibling("worker-history-checkpoint-owner.json").atomic_write(
                    b"{}"
                )
    elif case != "empty":
        decision = _allow(
            plugin_id="plugin.one",
            revision=1,
            generation=1,
            kill=0,
            operation="allow-1",
        )
        activation_policy = dataclasses.replace(
            _policy(),
            product_scope_id="scope",
            owner_selection_generation=1,
            kill_switch_generation=0,
            product_id="other" if case == "receipt-product" else "coding",
            allowed_product_ids=("other",)
            if case == "receipt-product"
            else ("coding",),
        )
        receipt = dataclasses.replace(
            _receipt(policy=activation_policy),
            issue_sequence=1,
            issue_nonce="history-proof",
        )
        recorded = CodingWorkerReceiptRecordV1.create(
            journal_revision=1,
            scope_id="scope",
            opt_in_decision_digest=decision.decision_digest,
            receipt=receipt,
        )

        def write_stream(stem, raw):
            from loushang.coding.package_product_worker_history_segments import (
                _head_bytes,
                _head_name,
            )

            with _rooted(root) as rooted:
                target = rooted.sibling(stem + ".jsonl")
                target.create_new(raw)
                target.sibling(_head_name(stem, 0)).create_new(
                    _head_bytes(stem, 0, raw)
                )
            (root / (stem + ".jsonl.lock")).touch(mode=0o600)

        if case != "opt-in-missing":
            write_stream("worker-opt-in", _opt_in_line(decision))
        if case != "missing-receipt":
            write_stream("worker-activation-receipts", _linux_receipt_line(recorded))
        no_effect = case.startswith("archive-") or case in {
            "no-effect",
            "repair-empty",
            "repair-unmarked",
            "repair-registered",
            "repair-registered-mismatch",
            "repair-bad",
            "repair-stage",
            "repair-registered-duplicate",
        }
        identity = dataclasses.replace(
            _identity(attempt="a", epoch=1),
            plugin_id=activation_policy.plugin_id,
            plugin_revision_digest=activation_policy.plugin_revision_digest,
            contribution_id=activation_policy.contribution_id,
            product_id="coding",
            scope_id="scope",
            owner_generation=1,
            declaration_fingerprint=activation_policy.declaration_fingerprint,
            worker_configuration_fingerprint=activation_policy.worker_configuration_fingerprint,
        )
        supervisor = CodingProductWorkerSupervisorJournal(product)
        if not no_effect:
            supervisor.claim(identity, max_attempts=3)
            if case != "supervisor-active":
                _settle(supervisor, attempt_id=ATTEMPT, epoch=1)
        else:
            write_stream("worker-supervisor", b"")
        journal = CodingWorkerStartGateJournal(product)
        common = dict(
            attempt_id=ATTEMPT,
            worker_identity_fingerprint="e" * 64
            if case == "gate-mismatch"
            else identity.fingerprint,
            receipt_fingerprint=receipt.fingerprint,
            policy_fingerprint=receipt.policy.fingerprint,
            scope_id="scope",
            native_closure_digest=sha256(b'{"closure":"original-fixed"}').hexdigest(),
        )
        journal.append(phase="intent", **common)
        if not no_effect and case != "unbound-gate":
            journal.append(
                phase="bound",
                identity=WorkerNativeProcessIdentityV1(
                    pid=123456,
                    start_ticks=1,
                    boot_id="00000000-0000-0000-0000-000000000001",
                    user_id=1000,
                    pid_namespace_device=1,
                    pid_namespace_inode=2,
                ),
                **common,
            )
        c5 = CodingProductWorkerActivationStateJournal(
            root / "worker-activation-state.jsonl"
        )
        loaded = c5.load()
        if loaded is None:
            from loushang.harness.worker.product_activation import _initial_state

            state = _initial_state(restart_budget=3)
            assert c5.compare_and_swap(expected_revision=0, document=state)
        else:
            state = dict(loaded)
        key = _AttemptKey(receipt.fingerprint, ATTEMPT, 1).encoded
        attempt = _registered_attempt(receipt=receipt.fingerprint, attempt_id=ATTEMPT)
        attempt.update(ownerGeneration=1, policyFingerprint=receipt.policy.fingerprint)
        registered_state = _next_state(state)
        registered_state["attempts"] = {key: attempt}
        assert c5.compare_and_swap(
            expected_revision=state["stateRevision"], document=registered_state
        )
        if case != "activation-active":
            settled_state = _next_state(registered_state)
            settled_attempt = dict(
                attempt,
                phase="settled",
                domainRetired=True,
                protocolTerminal=True,
                cleanupSettlement=WorkerCleanupSettlementV1(
                    receipt_fingerprint=receipt.fingerprint,
                    attempt_id=ATTEMPT,
                    owner_generation=1,
                    host_identity="host-a",
                    boot_identity="boot-a",
                    protocol_terminal=True,
                    domain_retired=True,
                    tree_settled=True,
                    no_effect=no_effect,
                ).to_dict(),
            )
            settled_state["attempts"] = {key: settled_attempt}
            assert c5.compare_and_swap(
                expected_revision=registered_state["stateRevision"],
                document=settled_state,
            )
        if case == "missing-c5":
            for f in root.glob("worker-activation-state*"):
                f.unlink()
        if case == "repair-empty":
            from loushang.coding.package_product_worker_payload import (
                CodingWorkerEmptyPayloadDebtPlanV1,
            )

            value = CodingWorkerEmptyPayloadDebtPlanV1(ATTEMPT, 1, 2)
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                _STORAGE.empty.publish(fd, ATTEMPT, value)
            finally:
                os.close(fd)
        if case in {"repair-bad", "repair-stage"}:
            (root / f"worker-empty-repair-{ATTEMPT}.json").write_bytes(b"{}")
        if case == "repair-unmarked":
            from loushang.coding.package_product_worker_payload import (
                CodingWorkerUnmarkedPayloadDebtReviewV1,
                CodingWorkerUnmarkedPayloadMemberV1,
            )

            value = CodingWorkerUnmarkedPayloadDebtReviewV1(
                ATTEMPT,
                1,
                2,
                (
                    CodingWorkerUnmarkedPayloadMemberV1(
                        "probe", "file", 1, 3, 0o500, 8, "b" * 64
                    ),
                ),
            )
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                _STORAGE.unmarked.publish(fd, ATTEMPT, value)
            finally:
                os.close(fd)
        if case == "repair-complete":
            from loushang.coding.package_product_worker_payload import (
                CodingWorkerPayloadDebtPlanV1,
            )
            from loushang.harness.resources.packages.plugin_lifecycle.records import (
                canonical_json_bytes,
            )

            value = CodingWorkerPayloadDebtPlanV1(
                ATTEMPT, "probe", "b" * 64, 8, receipt.fingerprint, 1, 2
            )
            record = supervisor.status(ATTEMPT)
            assert record is not None
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                _STORAGE.complete.publish(
                    fd,
                    ATTEMPT,
                    (value, sha256(canonical_json_bytes(record.to_dict())).hexdigest()),
                )
            finally:
                os.close(fd)
        if case.startswith("archive-") or case in {
            "repair-registered",
            "repair-registered-mismatch",
            "repair-registered-duplicate",
        }:
            from loushang.coding.package_product_worker_payload import (
                CodingWorkerPayloadDebtPlanV1,
            )
            from loushang.coding.package_product_worker_registered_payload_repair import (
                CodingWorkerRegisteredPayloadRepairIntentV1,
                _repair_journal,
            )

            value = CodingWorkerPayloadDebtPlanV1(
                ATTEMPT, "probe", "b" * 64, 8, receipt.fingerprint, 1, 2
            )
            intent = CodingWorkerRegisteredPayloadRepairIntentV1(
                value,
                journal.current(ATTEMPT).record_digest,
                recorded.record_digest,
                "f" * 64
                if case == "repair-registered-mismatch"
                else receipt.policy.fingerprint,
                "e" * 64,
                "host-a",
                "boot-a",
                1,
            )
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                _repair_journal().publish(fd, ATTEMPT, intent)
            finally:
                os.close(fd)
        if case == "repair-stage":
            (root / f"worker-payload-{ATTEMPT}").mkdir(mode=0o700)
        if case in {
            "global-unbound",
            "global-supervisor-active",
            "global-opt-in-unverified",
        }:
            from loushang.coding.package_product_worker_history_segments import (
                _head_bytes,
                _head_name,
            )

            second_id = "b" * 32
            second_receipt = dataclasses.replace(
                receipt, issue_sequence=2, issue_nonce="history-global"
            )
            second_record = CodingWorkerReceiptRecordV1.create(
                journal_revision=2,
                scope_id="scope",
                opt_in_decision_digest="f" * 64
                if case == "global-opt-in-unverified"
                else decision.decision_digest,
                receipt=second_receipt,
            )
            with _rooted(root) as rooted:
                target = rooted.sibling("worker-activation-receipts.jsonl")
                raw = target.read_bytes(max_bytes=1024 * 1024) + _linux_receipt_line(
                    second_record
                )
                target.atomic_write(raw)
                target.sibling(
                    _head_name("worker-activation-receipts", 0)
                ).atomic_write(_head_bytes("worker-activation-receipts", 0, raw))
            second_identity = dataclasses.replace(
                identity,
                attempt_id=second_id,
                supervisor_epoch=2,
                session_nonce="e" * 64,
            )
            if case != "global-unbound":
                supervisor.claim(second_identity, max_attempts=3)
                if case != "global-supervisor-active":
                    _settle(supervisor, attempt_id=second_id, epoch=2)
            common2 = dict(
                common,
                attempt_id=second_id,
                worker_identity_fingerprint=second_identity.fingerprint,
                receipt_fingerprint=second_receipt.fingerprint,
            )
            journal.append(phase="intent", **common2)
            if case != "global-unbound":
                journal.append(
                    phase="bound",
                    identity=WorkerNativeProcessIdentityV1(
                        pid=123457,
                        start_ticks=2,
                        boot_id="00000000-0000-0000-0000-000000000001",
                        user_id=1000,
                        pid_namespace_device=1,
                        pid_namespace_inode=2,
                    ),
                    **common2,
                )
            before_second = dict(c5.load())
            second_key = _AttemptKey(second_receipt.fingerprint, second_id, 1).encoded
            second_attempt = _registered_attempt(
                receipt=second_receipt.fingerprint, attempt_id=second_id
            )
            second_attempt.update(
                ownerGeneration=1, policyFingerprint=second_receipt.policy.fingerprint
            )
            registration2 = _next_state(before_second)
            registration2["attempts"] = {
                **before_second["attempts"],
                second_key: second_attempt,
            }
            assert c5.compare_and_swap(
                expected_revision=before_second["stateRevision"], document=registration2
            )
            if case == "global-opt-in-unverified":
                settlement2 = _next_state(registration2)
                final_second = dict(
                    second_attempt,
                    phase="settled",
                    domainRetired=True,
                    protocolTerminal=True,
                    cleanupSettlement=WorkerCleanupSettlementV1(
                        receipt_fingerprint=second_receipt.fingerprint,
                        attempt_id=second_id,
                        owner_generation=1,
                        host_identity="host-a",
                        boot_identity="boot-a",
                        protocol_terminal=True,
                        domain_retired=True,
                        tree_settled=True,
                        no_effect=False,
                    ).to_dict(),
                )
                settlement2["attempts"] = {
                    **registration2["attempts"],
                    second_key: final_second,
                }
                assert c5.compare_and_swap(
                    expected_revision=registration2["stateRevision"],
                    document=settlement2,
                )

        if case.startswith("archive-"):
            from loushang.coding.package_product_worker_history_checkpoint import (
                publish_coding_product_worker_history_checkpoint,
            )
            from loushang.coding.package_product_worker_history_commit_v2 import (
                commit_coding_worker_v2_owner_under_guard,
            )
            from loushang.coding.package_product_worker_history_deletion_v2 import (
                CodingWorkerV2DeletionLedger,
            )
            from loushang.coding.package_product_worker_history_preflight_v2 import (
                _prepare_coding_product_worker_history_cutover_under_guard,
            )
            from loushang.coding.package_product_worker_history_segments import (
                CodingWorkerSegmentManifestV1,
                _head_name,
                _segment_name,
                read_coding_worker_segmented_history,
                seal_coding_worker_active_segment,
            )
            from loushang.coding.package_product_worker_history_stage_v2 import (
                stage_coding_worker_v2_preparation,
            )
            from loushang.coding.package_product_worker_history_v2_names import (
                DELETION_LEDGER_NAME,
            )
            from loushang.harness.resources.packages.plugin_lifecycle.records import (
                canonical_json_bytes,
            )

            opt_in = CodingWorkerOptInJournal(
                root / "worker-opt-in.jsonl",
                scope_id="scope",
                gc_gate=gate,
                store_id="store",
            )
            opt_in.change(
                plugin_id="plugin.one",
                operation_id="revoke-archive",
                expected_generation=1,
                action="revoke",
                opt_in=None,
            )
            with _rooted(root) as rooted:
                for stem in (
                    "worker-opt-in",
                    "worker-activation-receipts",
                    "worker-activation-state",
                    "worker-start-gates",
                ):
                    target = rooted.sibling(stem + ".jsonl")
                    history = read_coding_worker_segmented_history(
                        target,
                        stem=stem,
                        stream_id=stem,
                        max_segment_bytes=32 * 1024 * 1024,
                    )
                    seal_coding_worker_active_segment(
                        target,
                        stem=stem,
                        stream_id=stem,
                        history=history,
                        last_revision=sum(
                            len(raw.splitlines()) for raw in history.segments
                        ),
                    )
                rooted.sibling("worker-supervisor.segments.json").create_new(
                    CodingWorkerSegmentManifestV1(
                        stream_id="worker-supervisor", active_generation=0, sealed=()
                    ).to_bytes()
                )
            publish_coding_product_worker_history_checkpoint(
                product, attempt_id=ATTEMPT
            )
            with gate.guard(require_write=True):
                prepared = _prepare_coding_product_worker_history_cutover_under_guard(
                    product,
                    first_retained_generations=(1, 1, 1, 1, 0),
                    active_runtime_lease_ids=(),
                    gc_snapshot=gate.snapshot(),
                )
                assert prepared.no_effect_archive is not None
                with _rooted(root) as rooted:
                    stage_coding_worker_v2_preparation(rooted, prepared=prepared)
                    commit_coding_worker_v2_owner_under_guard(rooted, prepared=prepared)
                    if case in {"archive-retired", "archive-missing-ledger"}:
                        for stem in (
                            "worker-opt-in",
                            "worker-activation-receipts",
                            "worker-activation-state",
                            "worker-start-gates",
                        ):
                            rooted.sibling(_segment_name(stem, 0)).unlink()
                            rooted.sibling(_head_name(stem, 0)).unlink()
                        if case == "archive-retired":
                            rooted.sibling(DELETION_LEDGER_NAME).create_new(
                                CodingWorkerV2DeletionLedger.from_prepared(
                                    prepared
                                ).to_bytes()
                            )
                    if case == "archive-repair-changed":
                        changed = dataclasses.replace(intent, lease_id="f" * 64)
                        rooted.sibling(
                            f"worker-registered-repair-{ATTEMPT}.json"
                        ).atomic_write(canonical_json_bytes(changed.to_dict()) + b"\n")

    if case in {
        "unknown-name",
        "case-name",
        "payload-stage",
        "registered-stage",
        "open-preparation",
    }:
        leaf = {
            "unknown-name": "worker-other",
            "case-name": "Worker-other",
            "payload-stage": f"worker-payload-{ATTEMPT}",
            "registered-stage": f".worker-registered-repair-{ATTEMPT}.json.stage",
            "open-preparation": "worker-history-v2-preparation.json",
        }[case]
        (root / leaf).write_bytes(b"inert")
    if case == "backup-missing":
        (root / "coding-backup-types.json").unlink()
    if case == "backup-changed":
        (root / "coding-backup-types.json").write_bytes(b"{}")
    if case == "scope-invalid":
        policy.project_scope_id = ""

    def reap_closed():
        for fd, label in tuple(live.items()):
            try:
                os.fstat(fd)
            except OSError:
                live.pop(fd)
                event("closed-by-file-object", label)

    reap_closed()
    assert not live, live

    def normalize(value):
        if dataclasses.is_dataclass(value):
            return {
                "type": type(value).__module__ + "." + type(value).__qualname__,
                "fields": {
                    f.name: normalize(getattr(value, f.name))
                    for f in dataclasses.fields(value)
                },
            }
        if isinstance(value, dict):
            return {str(k): normalize(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [normalize(v) for v in value]
        if isinstance(value, str):
            return value.replace(str(base), "<ROOT>")
        return value

    def errors(exc, seen=None):
        if exc is None:
            return None
        seen = {} if seen is None else seen
        if id(exc) in seen:
            return {"ref": seen[id(exc)]}
        seen[id(exc)] = len(seen)
        return {
            "id": seen[id(exc)],
            "type": type(exc).__name__,
            "message": normalize(str(exc)),
            "code": getattr(exc, "code", None),
            "suppress": exc.__suppress_context__,
            "notes": getattr(exc, "__notes__", []),
            "cause": errors(exc.__cause__, seen),
            "context": errors(exc.__context__, seen),
        }

    def tree():
        return {
            p.name: {
                "mode": stat.S_IMODE(p.lstat().st_mode),
                "bytes": p.read_bytes().hex() if p.is_file() else None,
            }
            for p in sorted(root.iterdir())
        }

    for phase in ("first", "retry"):
        native_count = pin_count = current_count = listdir_count = fd_sequence = 0
        event("call", phase)
        before = tree()
        try:
            if program == "retention":
                result = code.review_coding_product_worker_history_retention(
                    product,
                    attempt_id="invalid" if case == "attempt-invalid" else ATTEMPT,
                )
                value = {
                    "review": normalize(result),
                    "attempt_reference": normalize(result.attempt_reference),
                    "no_effect_closure": result.no_effect_closure,
                    "missing_proofs": result.missing_proofs,
                    "pickle_identity": type(pickle.loads(pickle.dumps(result)))
                    is type(result),
                    "pickle_value_equal": pickle.loads(pickle.dumps(result)) == result,
                }
            elif program == "gc":
                names = tuple(sorted(p.name for p in root.iterdir()))
                if case == "inventory-type":
                    names = list(names)
                if case == "inventory-duplicate":
                    names = (*names, names[0])
                if case == "repair-registered-duplicate":
                    names = (*names, f"worker-registered-repair-{ATTEMPT}.json")
                with gate.guard(require_write=True):
                    value = gc_code.CodingPosixWorkerGcHistoryAuthority(
                        product
                    ).require_settled(observed_names=names)
            elif program == "gated":
                result = gated_code._review_offline(product, attempt_id=ATTEMPT)
                value = {
                    "review": normalize(result),
                    "settlement_candidate": result.settlement_candidate,
                    "pickle_identity": type(pickle.loads(pickle.dumps(result)))
                    is type(result),
                }
            else:
                fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    value = normalize(
                        gc_code._require_committed_v2_history(
                            state_root=root, root_fd=fd
                        )
                    )
                finally:
                    os.close(fd)
            reap_closed()
            results.append(
                {
                    "phase": phase,
                    "value": normalize(value),
                    "error": None,
                    "tree_changed": tree() != before,
                    "tree": tree(),
                    "fds": sorted(live.values()),
                }
            )
        except BaseException as exc:
            reap_closed()
            results.append(
                {
                    "phase": phase,
                    "value": None,
                    "error": errors(exc),
                    "tree_changed": tree() != before,
                    "tree": tree(),
                    "fds": sorted(live.values()),
                }
            )
    assert not live, live
    return {"results": results, "trace": normalize(trace)}


def reflect():
    return {
        cls.__name__: {
            "module": cls.__module__,
            "qualname": cls.__qualname__,
            "annotations": cls.__annotations__,
            "fields": [f.name for f in dataclasses.fields(cls)],
            "slots": list(cls.__slots__),
            "signature": str(inspect.signature(cls)),
            "properties": {
                name: str(inspect.signature(getattr(cls, name).fget))
                for name in ("attempt_reference", "no_effect_closure", "missing_proofs")
                if isinstance(getattr(cls, name, None), property)
            },
        }
        for cls in (
            code.CodingWorkerAttemptReferenceV1,
            code.CodingWorkerHistoryRetentionReviewV1,
            gated_code.CodingWorkerGatedRecoveryReviewV1,
        )
    }


TEMPORARY = re.compile(r"(?P<stem>\.[^/\s']+)\.(?P<nonce>[0-9a-f]{24})\.tmp")


def canonical_observation(value):
    names = {}

    def string(text):
        def replace(match):
            symbol = names.setdefault(match[0], len(names) + 1)
            return match["stem"] + f".<TMP{symbol}>.tmp"

        return TEMPORARY.sub(replace, text)

    def visit(item):
        if isinstance(item, str):
            return string(item)
        if isinstance(item, dict):
            return {string(k): visit(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [visit(v) for v in item]
        return item

    return visit(value)


def fingerprint(value):
    return sha256(
        json.dumps(
            canonical_observation(value), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


FIXED = json.loads(
    (Path(__file__).parent / "fixtures" / "worker_history_proof_v1.json").read_text()
)
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="fixed original Linux rooted history proof"
)


@pytest.mark.parametrize("case", CASES)
def test_original_complete_history_proof(case, tmp_path, monkeypatch):
    result = observe(case, tmp_path, monkeypatch)
    assert fingerprint(result) == FIXED["observations"][case]["sha256"], result


def test_original_complete_history_reflection():
    assert json.loads(json.dumps(reflect())) == FIXED["reflection"]
