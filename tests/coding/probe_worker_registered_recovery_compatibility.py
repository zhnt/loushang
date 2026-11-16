"""Original synchronous recovery over real journals, payload and C5 coordinator.

Product current/pin, registry/epoch, machine/boot and native observations are
controlled. Registry changes are in-memory, not real lease locks or journals.
No process is launched. Interruptions are synchronous, not Task.cancel.
"""

from __future__ import annotations

import asyncio
import dataclasses
import errno
import inspect
import json
import os
import pickle
import re
import stat
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_worker_activation_state as activation
from loushang.coding import package_product_worker_cleanup_evidence as cleanup
from loushang.coding import package_product_worker_crash_c5_settlement as crash
from loushang.coding import (
    package_product_worker_registered_c5_settlement as registered_c5,
)
from loushang.coding import package_product_worker_registered_payload_repair as repair
from loushang.coding import package_product_worker_registered_recovery as registered
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
from loushang.coding.package_product_worker_opt_in import _opt_in_line
from loushang.coding.package_product_worker_payload import (
    _STORAGE,
    CodingWorkerPayloadDebtPlanV1,
)
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
from loushang.harness.package_product import _linux_worker_history as history
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.worker.gated_start import WorkerNativeProcessIdentityV1
from loushang.harness.worker.payload._repair import RepairJournal
from loushang.harness.worker.product_activation import _AttemptKey, _initial_state
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.coding.test_package_product_worker_opt_in_base_v2 import _allow
from tests.harness.worker.test_journal import _identity
from tests.harness.worker.test_product_activation import _policy, _receipt

ATTEMPT = "a" * 32
BOOT = "00000000-0000-0000-0000-000000000001"
NEXT_BOOT = "00000000-0000-0000-0000-000000000002"
RECOVER = (
    "normal",
    "same-boot",
    "already-repaired",
    "runtime-active",
    "owner-revision",
    "fence-absent",
    "unknown-name",
    "orphan-none",
    "orphan-multiple",
    "registry-review",
    "registry-repair-before",
    "registry-repair-after",
    "registry-repaired-read",
    "publish-before",
    "publish-after",
    "delete-before",
    "delete-after",
    "delete-marker-after",
    "delete-stage-after",
    "read-error",
    "cleanup-error",
    "body-and-cleanup",
    "pin-enter",
    "pin-exit",
    "host-error",
    "interrupt",
    "cancel-exception",
    "c5-cas1-before",
    "c5-cas1-after",
)
PAYLOAD = (
    "normal",
    "prior",
    "partial",
    "stage-absent",
    "changed-prior",
    "payload-changed",
)
CRASH = (
    "normal",
    "prior-boot",
    "live-payload",
    "intent-absent",
    "intent-hash",
    "native-error",
    "native-other",
    "group-present",
    "supervisor-active",
    "gate-policy",
    "host-error",
    "read-error",
    "cleanup-error",
    "body-and-cleanup",
    "pin-enter",
    "pin-exit",
    "interrupt",
    "cancel-exception",
    "c5-cas1-before",
    "c5-cas1-after",
    "c5-cas2-before",
    "c5-cas2-after",
    "c5-cas3-before",
    "c5-cas3-after",
    "prior-cas4-before",
    "prior-cas4-after",
)
CLEANUP = (
    "normal",
    "prior-boot",
    "wrong-host",
    "wrong-boot",
    "wrong-witness-type",
    "wrong-generation-type",
    "stale-witness",
    "host-error",
    "interrupt",
    "cancel-exception",
    "intent-hash",
    "intent-absent",
    "base-registered",
    "complete-read-error",
)
REGISTERED_VERIFY = (
    "normal",
    "host-error",
    "interrupt",
    "cancel-exception",
    "fresh-read-error",
    "wrong-generation-type",
)
EXTRA_CASES = tuple("registered-verify:" + c for c in REGISTERED_VERIFY) + (
    "cleanup:complete-read-error",
)
V2_CASES = tuple(
    "v2-reopen:" + c for c in ("normal", "retired", "intent-changed", "state-changed")
)
CASES = (
    tuple("recover:" + c for c in RECOVER)
    + tuple("payload:" + c for c in PAYLOAD)
    + tuple("crash:" + c for c in CRASH)
    + tuple("cleanup:" + c for c in CLEANUP)
    + tuple("registered-verify:" + c for c in REGISTERED_VERIFY)
    + V2_CASES
)


def observe(name, base, patch):
    program, case = name.split(":")
    base.chmod(0o700)
    root = base / "root"
    root.mkdir(mode=0o700)
    trace, results = [], []
    phase = "seed"
    fired = False
    fault_scope_ready = program != "registered-verify"
    counters = dict(current=0, pin=0, cas=0, native=0)
    live, fd_sequence = {}, 0
    original_open, original_close, original_dup = os.open, os.close, os.dup
    original_read, original_cleanup = (
        _rooted_io.RootedFile.read_bytes,
        _rooted_io.RootedFileIO.cleanup,
    )
    original_publish = RepairJournal.publish
    original_repair_read = RepairJournal.read
    original_cas = activation.CodingProductWorkerActivationStateStore.compare_and_swap
    original_unlink, original_rmdir = os.unlink, os.rmdir
    is_registered = program in {"recover", "payload", "registered-verify", "v2-reopen"}
    prior_boot = is_registered or case == "prior-boot" or case.startswith("prior-cas")
    current_boot = BOOT if case == "same-boot" or not prior_boot else NEXT_BOOT

    def event(*args):
        if phase != "seed":
            trace.append(list(args))

    def active_fault(*names):
        return phase == "first" and case in names and not fired and fault_scope_ready

    def fault(label=None):
        nonlocal fired
        fired = True
        event("fault", label or case)
        if case == "interrupt":
            raise KeyboardInterrupt("injected recovery interruption")
        if case == "cancel-exception":
            raise asyncio.CancelledError("injected synchronous recovery cancellation")
        raise OSError("injected " + (label or case))

    class Registry:
        store_id = "store"
        repaired = (
            program in {"payload", "registered-verify"} or case == "already-repaired"
        )
        owner_revision = 4
        lease = None

        def review_orphans(self, **kwargs):
            event("review-orphans", kwargs)
            if active_fault("registry-review"):
                fault()
            value = () if self.repaired or case == "orphan-none" else (self.lease,)
            return (*value, *value) if case == "orphan-multiple" else value

        def repaired_orphan_for_runtime(self, **kwargs):
            event("repaired-orphan-read", kwargs)
            if active_fault("registry-repaired-read"):
                fault()
            return (self.owner_revision, self.lease) if self.repaired else None

        def repair_orphan(self, lease_id, **kwargs):
            event("repair-orphan", lease_id, kwargs)
            assert lease_id == self.lease.lease_id
            assert kwargs == {"require_exclusive_active": True}
            if active_fault("registry-repair-before"):
                fault()
            self.repaired = True
            if active_fault("registry-repair-after"):
                fault()

        @contextmanager
        def exclusive_runtime_quiescence(self, **kwargs):
            event("quiet-enter", kwargs)
            try:
                yield NS(
                    active_runtime_lease_ids=("busy",)
                    if case == "runtime-active"
                    else (),
                    owner_revision=self.owner_revision
                    + (1 if case == "owner-revision" else 0),
                )
            finally:
                event("quiet-exit")

    registry = Registry()

    class Epoch(PackageProductPosixFencedRuntimeOwner):
        def __init__(self):
            self.registry = registry
            self.cutover_result = NS(
                fence=None
                if case == "fence-absent"
                else NS(epoch=1, fenced_root_identity="9" * 64)
            )

        def assert_current(self):
            event("epoch-current")

    gate = PluginPackageGcReservationJournal(root / "package-gc-reservations.jsonl")
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    for key, value in dict(
        state_root=root,
        policy=NS(
            product_id="coding",
            project_scope_id="scope",
            bindings=(NS(source_trust_class="local-worker-candidate"),),
        ),
        gc_gate=gate,
        epoch_runtime=Epoch(),
    ).items():
        object.__setattr__(product, key, value)

    def current(self):
        assert self is product
        counters["current"] += 1
        event("product-current", counters["current"])

    @contextmanager
    def pinned(self):
        assert self is product
        counters["pin"] += 1
        index = counters["pin"]
        event("pin-enter", index)
        if active_fault("pin-enter"):
            fault()
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)
            event("pin-exit", index)
            if active_fault("pin-exit"):
                fault()

    def opened(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal fd_sequence
        related = str(path).startswith(str(root)) or dir_fd in live
        fd = original_open(path, flags, mode, dir_fd=dir_fd)
        if related:
            prior = live.pop(fd, None)
            if prior is not None:
                event("file-object-closed", prior)
            fd_sequence += 1
            live[fd] = "FD" + str(fd_sequence)
            event(
                "open",
                str(path).replace(str(base), "<ROOT>"),
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
        return original_close(fd)

    def dup(fd):
        nonlocal fd_sequence
        new = original_dup(fd)
        if fd in live:
            prior = live.pop(new, None)
            if prior is not None:
                event("file-object-closed", prior)
            fd_sequence += 1
            live[new] = "FD" + str(fd_sequence)
            event("dup", live[fd], live[new])
        return new

    def read(self, **kwargs):
        event("read", self._name, kwargs)
        if active_fault("read-error", "body-and-cleanup", "fresh-read-error"):
            fault()
        return original_read(self, **kwargs)

    def io_cleanup(self):
        original_cleanup(self)
        event("io-cleanup")
        if phase == "first" and case == "body-and-cleanup":
            raise OSError("injected cleanup after body")
        if active_fault("cleanup-error"):
            fault()

    def native(self):
        counters["native"] += 1
        event("native-closure", counters["native"])
        if phase == "first" and case == "native-error":
            raise CodingWorkerNativeReleaseError("injected native unavailable")
        if active_fault("native-other"):
            fault()
        return NS(to_dict=lambda: {"closure": "fixed-original"})

    def native_status(identity):
        event("native-group", dataclasses.asdict(identity))
        if case == "group-present":
            return "present"
        return "prior_boot_absent" if prior_boot else "absent"

    def host_identity(**kwargs):
        event("host", kwargs)
        if active_fault("host-error", "interrupt", "cancel-exception"):
            fault()
        return "host-a"

    def boot_identity():
        event("boot")
        return current_boot

    def publish(self, fd, attempt, value):
        event("repair-publish", self.names(attempt)[0])
        if is_registered and active_fault("publish-before"):
            fault()
        result = original_publish(self, fd, attempt, value)
        if is_registered and active_fault("publish-after"):
            fault()
        return result

    def repair_read(self, fd, attempt):
        if (
            program == "cleanup"
            and self.names(attempt)[0].startswith("worker-complete-repair-")
            and active_fault("complete-read-error")
        ):
            fault()
        return original_repair_read(self, fd, attempt)

    def cas(self, *, expected_revision, document):
        counters["cas"] += 1
        index = counters["cas"]
        event(
            "c5-cas",
            index,
            expected_revision,
            [x["phase"] for x in document["attempts"].values()],
        )
        if active_fault(f"c5-cas{index}-before", f"prior-cas{index}-before"):
            fault()
        value = original_cas(
            self, expected_revision=expected_revision, document=document
        )
        event("c5-cas-result", index, value)
        if active_fault(f"c5-cas{index}-after", f"prior-cas{index}-after"):
            fault()
        return value

    def unlinked(path, *, dir_fd=None):
        event("unlink", str(path), live.get(dir_fd))
        if str(path) == "worker" and active_fault("delete-before"):
            fault()
        value = original_unlink(path, dir_fd=dir_fd)
        if str(path) == "worker" and active_fault("delete-after"):
            fault()
        if str(path) == "product-payload.json" and active_fault("delete-marker-after"):
            fault()
        return value

    def removed(path, *, dir_fd=None):
        event("rmdir", str(path), live.get(dir_fd))
        value = original_rmdir(path, dir_fd=dir_fd)
        if str(path) == "worker-payload-" + ATTEMPT and active_fault(
            "delete-stage-after"
        ):
            fault()
        return value

    patch.setattr(
        PosixLocalWheelProductSessionOwner, "assert_root_gc_authority_current", current
    )
    patch.setattr(
        PosixLocalWheelProductSessionOwner, "pinned_state_root_gc_read", pinned
    )
    patch.setattr(os, "open", opened)
    patch.setattr(os, "close", closed)
    patch.setattr(os, "dup", dup)
    patch.setattr(os, "unlink", unlinked)
    patch.setattr(os, "rmdir", removed)
    patch.setattr(_rooted_io.RootedFile, "read_bytes", read)
    patch.setattr(_rooted_io.RootedFileIO, "cleanup", io_cleanup)
    patch.setattr(CodingProductInstalledWorkerReleaseReader, "current_closure", native)
    patch.setattr(history, "worker_native_group_status_after_restart", native_status)
    if hasattr(cleanup, "linux_machine_key"):
        identity_owner = cleanup
    else:
        from loushang.harness.package_product import _linux_worker_recovery

        identity_owner = _linux_worker_recovery
    patch.setattr(identity_owner, "linux_machine_key", host_identity)
    patch.setattr(identity_owner, "linux_current_boot_id", boot_identity)
    patch.setattr(RepairJournal, "publish", publish)
    patch.setattr(RepairJournal, "read", repair_read)
    patch.setattr(
        activation.CodingProductWorkerActivationStateStore, "compare_and_swap", cas
    )

    # Seed uses existing typed constructors, head codec, journal CAS and Storage.
    with gate.guard(require_write=True):
        pass
    (root / "coding-backup-types.json").write_bytes(_topology_bytes("scope"))
    (root / "coding-backup-types.json").chmod(0o600)
    decision = _allow(
        plugin_id="plugin.one", revision=1, generation=1, kill=0, operation="allow-1"
    )
    policy = dataclasses.replace(
        _policy(),
        product_scope_id="scope",
        owner_selection_generation=1,
        kill_switch_generation=0,
    )
    receipt = dataclasses.replace(
        _receipt(policy=policy),
        issue_sequence=1,
        issue_nonce="registered-runtime-fixed",
    )
    recorded = CodingWorkerReceiptRecordV1.create(
        journal_revision=1,
        scope_id="scope",
        opt_in_decision_digest=decision.decision_digest,
        receipt=receipt,
    )
    registry.lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id=receipt.policy.product_runtime_id,
        runtime_epoch=1,
        store_root_identity="9" * 64,
        registration_receipt_id="8" * 64,
    )

    def write_stream(stem, raw):
        from loushang.coding.package_product_worker_history_segments import (
            _head_bytes,
            _head_name,
        )

        with _rooted(root) as rooted:
            target = rooted.sibling(stem + ".jsonl")
            target.create_new(raw)
            target.sibling(_head_name(stem, 0)).create_new(_head_bytes(stem, 0, raw))
        (root / (stem + ".jsonl.lock")).touch(mode=0o600)

    write_stream("worker-opt-in", _opt_in_line(decision))
    write_stream("worker-activation-receipts", _linux_receipt_line(recorded))
    identity = dataclasses.replace(
        _identity(attempt="a", epoch=1),
        plugin_id=policy.plugin_id,
        plugin_revision_digest=policy.plugin_revision_digest,
        contribution_id=policy.contribution_id,
        product_id="coding",
        scope_id="scope",
        owner_generation=1,
        declaration_fingerprint=policy.declaration_fingerprint,
        worker_configuration_fingerprint=policy.worker_configuration_fingerprint,
    )
    supervisor = CodingProductWorkerSupervisorJournal(product)
    if is_registered:
        write_stream("worker-supervisor", b"")
    else:
        claimed = supervisor.claim(identity, max_attempts=3)
        if case != "supervisor-active":
            failed = supervisor.transition(
                ATTEMPT,
                expected_phase=claimed.phase,
                next_phase="failed",
                expected_record_revision=claimed.record_revision,
                expected_supervisor_epoch=1,
                failure_code="coding_worker_host_lost",
            )
            supervisor.transition(
                ATTEMPT,
                expected_phase=failed.phase,
                next_phase="process_settled",
                expected_record_revision=failed.record_revision,
                expected_supervisor_epoch=1,
                failure_code=failed.failure_code,
            )
    gates = CodingWorkerStartGateJournal(product)
    gate_args = dict(
        attempt_id=ATTEMPT,
        worker_identity_fingerprint=identity.fingerprint,
        receipt_fingerprint=receipt.fingerprint,
        policy_fingerprint="f" * 64
        if case == "gate-policy"
        else receipt.policy.fingerprint,
        scope_id="scope",
        native_closure_digest=sha256(
            canonical_json_bytes({"closure": "fixed-original"})
        ).hexdigest(),
    )
    gates.append(phase="intent", **gate_args)
    if not is_registered:
        gates.append(
            phase="bound",
            identity=WorkerNativeProcessIdentityV1(
                pid=123456,
                start_ticks=1,
                boot_id=BOOT,
                user_id=1000,
                pid_namespace_device=1,
                pid_namespace_inode=2,
            ),
            **gate_args,
        )
    journal = CodingProductWorkerActivationStateJournal(
        root / "worker-activation-state.jsonl", scope_id="scope", store_id="store"
    )
    initial = _initial_state(restart_budget=3)
    assert journal.compare_and_swap(expected_revision=0, document=initial)
    key = _AttemptKey(receipt.fingerprint, ATTEMPT, 1).encoded
    attempt = _registered_attempt(receipt=receipt.fingerprint, attempt_id=ATTEMPT)
    attempt.update(
        ownerGeneration=1,
        policyFingerprint=policy.fingerprint,
        hostIdentity="host-a",
        bootIdentity=BOOT,
        evidenceAuthorityId=cleanup._AUTHORITY_ID,
        evidenceAuthorityFingerprint=cleanup._AUTHORITY_FINGERPRINT,
    )
    state = _next_state(initial)
    state["attempts"] = {key: attempt}
    assert journal.compare_and_swap(expected_revision=1, document=state)
    if not is_registered:
        launched = _next_state(state)
        launched["attempts"] = {key: dict(attempt, phase="effect_started")}
        assert journal.compare_and_swap(expected_revision=2, document=launched)

    stage_name = "worker-payload-" + ATTEMPT
    stage = root / stage_name
    if program == "v2-reopen":
        # A pre-existing completed deletion debt is modeled here with fixed
        # historical IDs. No fake V2 reader/store is used, and these IDs are not
        # claimed to describe a physical stage deleted by this V2 fixture.
        plan = CodingWorkerPayloadDebtPlanV1(
            ATTEMPT,
            "bin/worker",
            sha256(b"fixed-payload").hexdigest(),
            len(b"fixed-payload"),
            receipt.fingerprint,
            1,
            2,
        )
        intent = repair.CodingWorkerRegisteredPayloadRepairIntentV1(
            plan,
            gates.current(ATTEMPT).record_digest,
            recorded.record_digest,
            policy.fingerprint,
            registry.lease.lease_id,
            "host-a",
            BOOT,
            1,
        )
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            repair._repair_journal().publish(fd, intent.attempt_id, intent)
        finally:
            os.close(fd)
    else:
        stage.mkdir(mode=0o700)
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            _STORAGE._write_payload(stage_fd, "bin/worker", b"fixed-payload")
            metadata = os.fstat(stage_fd)
            plan = CodingWorkerPayloadDebtPlanV1(
                ATTEMPT,
                "bin/worker",
                sha256(b"fixed-payload").hexdigest(),
                len(b"fixed-payload"),
                receipt.fingerprint,
                metadata.st_dev,
                metadata.st_ino,
            )
            _STORAGE._write_marker(stage_fd, plan)
            if not is_registered:
                status = supervisor.status(ATTEMPT)
                assert status is not None
                if case != "intent-absent" or program == "cleanup":
                    digest = (
                        "0" * 64
                        if case == "intent-hash" and program != "cleanup"
                        else sha256(canonical_json_bytes(status.to_dict())).hexdigest()
                    )
                    _STORAGE.complete.publish(root_fd, ATTEMPT, (plan, digest))
                if case != "live-payload":
                    _STORAGE._remove_verified_stage(root_fd, stage_fd, stage_name, plan)
        finally:
            os.close(stage_fd)
            os.close(root_fd)
    if is_registered and (
        case in {"prior", "partial", "stage-absent", "changed-prior"}
        or program == "registered-verify"
    ):
        review = registered.review_coding_product_worker_registered_orphan(
            product, attempt_id=ATTEMPT
        )
        intent = repair._expected_intent(review)
        if case == "changed-prior":
            intent = dataclasses.replace(intent, lease_id="f" * 64)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            repair._repair_journal().publish(fd, intent.attempt_id, intent)
            if case == "stage-absent" or program == "registered-verify":
                sf = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    _STORAGE._remove_verified_stage(fd, sf, stage_name, plan)
                finally:
                    os.close(sf)
        finally:
            os.close(fd)
        if case == "partial":
            (stage / "bin/worker").unlink()
    if case == "payload-changed":
        leaf = stage / "bin/worker"
        leaf.chmod(0o700)
        leaf.write_bytes(b"wrong-payload")
        leaf.chmod(0o500)
    if case == "unknown-name":
        (root / "worker-unknown-reference").write_bytes(b"inert")

    # Cleanup needs retired + terminal state; execute the ordinary real program
    # first with faults disabled, then reopen an actual witness for each verifier.
    if program == "cleanup":
        crash.settle_coding_product_worker_crash_c5(product, attempt_id=ATTEMPT)
        completed_path = root / f"worker-complete-repair-{ATTEMPT}.json"
        if case == "intent-absent":
            completed_path.unlink()
        elif case == "intent-hash":
            raw = json.loads(completed_path.read_bytes())
            raw["supervisorFingerprint"] = "0" * 64
            completed_path.write_bytes(canonical_json_bytes(raw) + b"\n")

    if program == "v2-reopen":
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
        from loushang.coding.package_product_worker_opt_in import (
            CodingWorkerOptInJournal,
        )

        closed = registered.recover_coding_product_worker_registered_no_effect(
            product, attempt_id=ATTEMPT
        )
        assert closed.phase == "settled" and closed.no_effect and registry.repaired
        opt_in = CodingWorkerOptInJournal(
            root / "worker-opt-in.jsonl",
            scope_id="scope",
            gc_gate=gate,
            store_id="store",
        )
        opt_in.change(
            plugin_id="plugin.one",
            operation_id="revoke-v2",
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
                retained = read_coding_worker_segmented_history(
                    target,
                    stem=stem,
                    stream_id=stem,
                    max_segment_bytes=32 * 1024 * 1024,
                )
                seal_coding_worker_active_segment(
                    target,
                    stem=stem,
                    stream_id=stem,
                    history=retained,
                    last_revision=sum(
                        len(raw.splitlines()) for raw in retained.segments
                    ),
                )
            rooted.sibling("worker-supervisor.segments.json").create_new(
                CodingWorkerSegmentManifestV1(
                    stream_id="worker-supervisor", active_generation=0, sealed=()
                ).to_bytes()
            )
        publish_coding_product_worker_history_checkpoint(product, attempt_id=ATTEMPT)
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
                if case == "retired":
                    for stem in (
                        "worker-opt-in",
                        "worker-activation-receipts",
                        "worker-activation-state",
                        "worker-start-gates",
                    ):
                        rooted.sibling(_segment_name(stem, 0)).unlink()
                        rooted.sibling(_head_name(stem, 0)).unlink()
                    rooted.sibling(DELETION_LEDGER_NAME).create_new(
                        CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
                    )
                if case == "intent-changed":
                    changed = dataclasses.replace(
                        intent,
                        plan=dataclasses.replace(intent.plan, payload_digest="0" * 64),
                    )
                    rooted.sibling(
                        f"worker-registered-repair-{ATTEMPT}.json"
                    ).atomic_write(canonical_json_bytes(changed.to_dict()) + b"\n")
                if case == "state-changed":
                    rooted.sibling(
                        _head_name("worker-activation-state", 1)
                    ).atomic_write(b"{}")

    def reap():
        for fd, label in tuple(live.items()):
            try:
                os.fstat(fd)
            except OSError as error:
                assert error.errno == errno.EBADF
                live.pop(fd)
                event("file-object-closed", label)

    reap()
    assert not live, live

    def normalized(value):
        if dataclasses.is_dataclass(value):
            return {
                "type": type(value).__module__ + "." + type(value).__qualname__,
                "fields": {
                    f.name: normalized(getattr(value, f.name))
                    for f in dataclasses.fields(value)
                },
            }
        if isinstance(value, dict):
            return {str(k): normalized(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalized(v) for v in value]
        if isinstance(value, str):
            return value.replace(str(base), "<ROOT>")
        return value

    def errors(error, seen=None):
        if error is None:
            return None
        seen = {} if seen is None else seen
        if id(error) in seen:
            return {"ref": seen[id(error)]}
        seen[id(error)] = len(seen)
        return dict(
            id=seen[id(error)],
            type=type(error).__name__,
            message=normalized(str(error)),
            code=getattr(error, "code", None),
            suppress=error.__suppress_context__,
            notes=getattr(error, "__notes__", []),
            cause=errors(error.__cause__, seen),
            context=errors(error.__context__, seen),
        )

    def tree():
        return {
            str(p.relative_to(root)): {
                "mode": stat.S_IMODE(p.lstat().st_mode),
                "bytes": p.read_bytes().hex() if p.is_file() else None,
            }
            for p in sorted(root.rglob("*"))
        }

    for phase in ("first", "retry"):
        fault_scope_ready = program != "registered-verify"
        counters.update(current=0, pin=0, cas=0, native=0)
        fd_sequence = 0
        event("call", phase)
        before = tree()
        try:
            if program == "recover":
                result = registered.recover_coding_product_worker_registered_no_effect(
                    product, attempt_id=ATTEMPT
                )
            elif program == "payload":
                review = registered.review_coding_product_worker_registered_orphan(
                    product, attempt_id=ATTEMPT
                )
                result = repair.repair_coding_product_worker_registered_payload_debt(
                    product, expected_review=review
                )
            elif program == "crash":
                result = crash.settle_coding_product_worker_crash_c5(
                    product, attempt_id=ATTEMPT
                )
            elif program == "registered-verify":
                review = registered.review_coding_product_worker_registered_orphan(
                    product, attempt_id=ATTEMPT
                )
                assert review.payload_repair_candidate
                with registry.exclusive_runtime_quiescence(
                    store_id=registry.store_id
                ) as quiet:
                    with gate.guard(require_write=True):
                        evidence = (
                            registered_c5._UnderGuardRegisteredCleanupEvidenceAuthority(
                                product,
                                review=review,
                                active_runtime_lease_ids=quiet.active_runtime_lease_ids,
                                gc_snapshot=gate.snapshot(),
                            )
                        )
                        witness = evidence.current_tree_witness(attempt_id=ATTEMPT)
                        fault_scope_ready = True
                        result = evidence.verify_registered_lease_expired(
                            receipt_fingerprint=receipt.fingerprint,
                            attempt_id=ATTEMPT,
                            owner_generation=True
                            if case == "wrong-generation-type"
                            else 1,
                            host_identity="host-a",
                            boot_identity=BOOT,
                            current_boot_identity=current_boot,
                            witness=witness,
                            evidence_authority_id=evidence.authority_id,
                            evidence_authority_fingerprint=evidence.authority_fingerprint,
                        )
            elif program == "v2-reopen":
                from loushang.coding.package_product_worker_posix_gc_history import (
                    CodingPosixWorkerGcHistoryAuthority,
                )

                result = {}
                try:
                    settled = registered_c5.settle_coding_product_worker_registered_c5(
                        product, attempt_id=ATTEMPT
                    )
                    result["settled_reopen"] = dict(
                        value=normalized(settled), error=None
                    )
                except BaseException as error:
                    result["settled_reopen"] = dict(value=None, error=errors(error))
                with registry.exclusive_runtime_quiescence(store_id=registry.store_id):
                    with gate.guard(require_write=True):
                        try:
                            CodingPosixWorkerGcHistoryAuthority(
                                product
                            ).require_settled(observed_names=tuple(os.listdir(root)))
                            result["strict_gc"] = dict(value=None, error=None)
                        except BaseException as error:
                            result["strict_gc"] = dict(value=None, error=errors(error))
            else:
                authority = cleanup.CodingPosixWorkerCleanupEvidenceAuthority(product)
                witness = authority.current_tree_witness(attempt_id=ATTEMPT)
                if case == "stale-witness":
                    witness = dataclasses.replace(
                        witness,
                        gc_reservation_revision=witness.gc_reservation_revision + 1,
                    )
                arguments = dict(
                    receipt_fingerprint=receipt.fingerprint,
                    attempt_id=ATTEMPT,
                    owner_generation=True if case == "wrong-generation-type" else 1,
                    host_identity="wrong" if case == "wrong-host" else "host-a",
                    boot_identity="wrong" if case == "wrong-boot" else BOOT,
                    witness=object() if case == "wrong-witness-type" else witness,
                    evidence_authority_id=authority.authority_id,
                    evidence_authority_fingerprint=authority.authority_fingerprint,
                )
                if case == "base-registered":
                    result = authority.verify_registered_lease_expired(**arguments)
                elif prior_boot:
                    result = authority.verify_changed_boot_absence(
                        **arguments, current_boot_identity=current_boot
                    )
                else:
                    result = authority.verify_tree_settlement(**arguments)
            reap()
            value = normalized(result)
            if dataclasses.is_dataclass(result):
                value = dict(
                    result=value,
                    pickle_identity=type(pickle.loads(pickle.dumps(result)))
                    is type(result),
                )
            results.append(
                dict(
                    phase=phase,
                    value=value,
                    error=None,
                    tree_changed=tree() != before,
                    tree=tree(),
                    registry_repaired=registry.repaired,
                    fds=sorted(live.values()),
                )
            )
        except BaseException as error:
            reap()
            results.append(
                dict(
                    phase=phase,
                    value=None,
                    error=errors(error),
                    tree_changed=tree() != before,
                    tree=tree(),
                    registry_repaired=registry.repaired,
                    fds=sorted(live.values()),
                )
            )
    assert not live, live
    value = dict(results=results, trace=normalized(trace), fault_fired=fired)
    value[
        "modeled_stage_identity"
        if program == "v2-reopen"
        else "physical_stage_identity"
    ] = [plan.stage_device, plan.stage_inode]
    return value


def canonical_observation(value):
    """Normalize only fixture's original physical stage ID and unique tmp names."""
    names = {}
    dev, inode = value.get(
        "physical_stage_identity", value.get("modeled_stage_identity")
    )
    temporary = re.compile(r"(?P<stem>\.[^/\s']+)\.(?P<nonce>[0-9a-f]{24})\.tmp")

    def string(text):
        def replace(match):
            symbol = names.setdefault(match[0], len(names) + 1)
            return match["stem"] + f".<TMP{symbol}>.tmp"

        text = temporary.sub(replace, text)
        try:
            body = bytes.fromhex(text)
        except ValueError:
            return text
        if b'"stageDevice":' in body and b'"stageInode":' in body:
            body = body.replace(
                b'"stageDevice":' + str(dev).encode() + b",",
                b'"stageDevice":<STAGE_DEV>,',
            )
            body = body.replace(
                b'"stageInode":' + str(inode).encode() + b",",
                b'"stageInode":<STAGE_INODE>,',
            )
            return body.hex()
        return text

    def visit(item, key=None):
        if key in {"physical_stage_identity", "modeled_stage_identity"}:
            return ["<STAGE_DEV>", "<STAGE_INODE>"]
        if key == "stage_device" and item == dev:
            return "<STAGE_DEV>"
        if key == "stage_inode" and item == inode:
            return "<STAGE_INODE>"
        if isinstance(item, str):
            return string(item)
        if isinstance(item, dict):
            return {string(k): visit(v, k) for k, v in item.items()}
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


def reflect():
    return {
        cls.__name__: dict(
            module=cls.__module__,
            qualname=cls.__qualname__,
            annotations=cls.__annotations__,
            fields=[f.name for f in dataclasses.fields(cls)],
            slots=list(cls.__slots__),
            signature=str(inspect.signature(cls)),
        )
        for cls in (
            registered.CodingWorkerRegisteredOrphanReviewV1,
            repair.CodingWorkerRegisteredPayloadRepairIntentV1,
        )
    }


_FIXED = json.loads(
    (Path(__file__).parent / "fixtures/worker_registered_recovery_v1.json").read_text()
)


@pytest.mark.parametrize("case", CASES)
def test_fixed_registered_recovery(case, tmp_path, monkeypatch):
    """Replay frozen original IO/bytes/ordered trace, including same-disk retry."""
    value = observe(case, tmp_path, monkeypatch)
    assert fingerprint(value) == _FIXED["observations"][case]["sha256"], case


def test_fixed_registered_recovery_reflection():
    assert json.loads(json.dumps(reflect())) == _FIXED["reflection"]
