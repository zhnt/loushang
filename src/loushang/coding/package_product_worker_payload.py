"""Private, attempt-scoped Linux payload copy for a selected Coding Worker.

The Product Store keeps every file non-executable. This owner copies only the
freshly verified Worker executable into a private 0500 file for Hosting's
descriptor-sealing capture. A context exit removes the copy; a crash leaves
an exact attempt name as debt and a replay refuses to reuse it.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
    WorkerSupervisorJournalError,
)
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .package_product_worker_installed_native import CodingWorkerNativeLaunchMaterialV1
from .package_product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    CodingWorkerReceiptError,
)
from .package_product_worker_supervisor_journal import (
    CodingProductWorkerSupervisorJournal,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_DIR_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if os.name == "posix"
    else -1
)
_FILE_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    if os.name == "posix"
    else -1
)
_MARKER = "product-payload.json"
_MAX_MARKER_BYTES = 1024
_EMPTY_REPAIR_PREFIX = "worker-empty-repair-"
_MAX_EMPTY_REPAIR_BYTES = 512
_COMPLETE_REPAIR_PREFIX = "worker-complete-repair-"
_MAX_COMPLETE_REPAIR_BYTES = 2048
_MAX_UNMARKED_DEPTH = 16
_MAX_UNMARKED_PATH_BYTES = 1024
_UNMARKED_REPAIR_PREFIX = "worker-unmarked-repair-"
_MAX_UNMARKED_REPAIR_BYTES = 32768


class CodingWorkerPayloadMaterializationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingProductWorkerPayloadLeaseV1:
    """Physical input valid only while its materialization context is open."""

    attempt_id: str
    runtime: WorkerRuntimeBindingV1
    native_material: CodingWorkerNativeLaunchMaterialV1
    receipt_fingerprint: str


@dataclass(frozen=True, slots=True)
class CodingProductWorkerPendingLaunchV1:
    """No-effect identity pinned before asynchronous Worker preparation."""

    receipt_fingerprint: str
    identity: WorkerLaunchIdentityV1

    def __post_init__(self) -> None:
        if (
            type(self.receipt_fingerprint) is not str
            or _DIGEST.fullmatch(self.receipt_fingerprint) is None
            or not isinstance(self.identity, WorkerLaunchIdentityV1)
        ):
            raise ValueError("Coding Worker pending launch identity is invalid")


def open_coding_product_worker_supervisor_journal(
    product: PosixLocalWheelProductSessionOwner,
) -> CodingProductWorkerSupervisorJournal:
    """Bind every Coding Worker attempt to this Product's durable state root."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    product.assert_root_gc_authority_current()
    return CodingProductWorkerSupervisorJournal(product)


@dataclass(frozen=True, slots=True)
class CodingWorkerPayloadDebtPlanV1:
    """Exact complete stage accepted for offline deletion."""

    attempt_id: str
    entrypoint: str
    payload_digest: str
    payload_size: int
    receipt_fingerprint: str
    stage_device: int
    stage_inode: int

    def __post_init__(self) -> None:
        if (
            _ATTEMPT.fullmatch(self.attempt_id) is None
            or canonical_plugin_relative_path(self.entrypoint).as_posix()
            != self.entrypoint
            or _DIGEST.fullmatch(self.payload_digest) is None
            or _DIGEST.fullmatch(self.receipt_fingerprint) is None
            or type(self.payload_size) is not int
            or not 0 < self.payload_size <= 16 * 1024 * 1024
            or type(self.stage_device) is not int
            or self.stage_device < 0
            or type(self.stage_inode) is not int
            or self.stage_inode < 1
        ):
            raise ValueError("Coding Worker payload debt plan is invalid")

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(_plan_fields(self))).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWorkerEmptyPayloadDebtPlanV1:
    """An empty pre-marker stage for an attempt never claimed by Supervisor."""

    attempt_id: str
    stage_device: int
    stage_inode: int

    def __post_init__(self) -> None:
        if (
            _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.stage_device) is not int
            or self.stage_device < 0
            or type(self.stage_inode) is not int
            or self.stage_inode < 1
        ):
            raise ValueError("Coding Worker empty payload debt plan is invalid")

    @property
    def fingerprint(self) -> str:
        return sha256(
            canonical_json_bytes(
                {
                    "attemptId": self.attempt_id,
                    "stageDevice": self.stage_device,
                    "stageInode": self.stage_inode,
                    "version": 1,
                }
            )
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWorkerUnmarkedPayloadMemberV1:
    """One no-follow member of an incomplete, single-path Product stage."""

    relative_path: str
    kind: str
    device: int
    inode: int
    mode: int
    size: int
    digest: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.relative_path, str)
            or canonical_plugin_relative_path(self.relative_path).as_posix()
            != self.relative_path
            or self.kind not in {"directory", "file"}
            or type(self.device) is not int
            or self.device < 0
            or type(self.inode) is not int
            or self.inode < 1
            or type(self.mode) is not int
            or type(self.size) is not int
            or self.size < 0
            or (
                self.kind == "directory"
                and (self.mode != 0o700 or self.size != 0 or self.digest is not None)
            )
            or (
                self.kind == "file"
                and (
                    self.mode not in {0o600, 0o500}
                    or self.size > 16 * 1024 * 1024
                    or not isinstance(self.digest, str)
                    or _DIGEST.fullmatch(self.digest) is None
                )
            )
        ):
            raise ValueError("Coding Worker unmarked payload member is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "device": self.device,
            "digest": self.digest,
            "inode": self.inode,
            "kind": self.kind,
            "mode": self.mode,
            "relativePath": self.relative_path,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class CodingWorkerUnmarkedPayloadDebtReviewV1:
    """Exact tree evidence; cleanup needs a separate durable intent."""

    attempt_id: str
    stage_device: int
    stage_inode: int
    members: tuple[CodingWorkerUnmarkedPayloadMemberV1, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.attempt_id, str)
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.stage_device) is not int
            or self.stage_device < 0
            or type(self.stage_inode) is not int
            or self.stage_inode < 1
            or not isinstance(self.members, tuple)
            or not 1 <= len(self.members) <= _MAX_UNMARKED_DEPTH + 1
        ):
            raise ValueError("Coding Worker unmarked payload review is invalid")
        parent = ""
        for index, member in enumerate(self.members):
            if not isinstance(member, CodingWorkerUnmarkedPayloadMemberV1):
                raise ValueError("Coding Worker unmarked payload member is invalid")
            parts = canonical_plugin_relative_path(member.relative_path).parts
            if (
                len(parts) != index + 1
                or (parent and not member.relative_path.startswith(parent + "/"))
                or (member.kind == "file" and index != len(self.members) - 1)
                or len(os.fsencode(member.relative_path)) > _MAX_UNMARKED_PATH_BYTES
            ):
                raise ValueError("Coding Worker unmarked payload chain changed")
            parent = member.relative_path

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(_unmarked_repair_fields(self))).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWorkerPayloadRecoveryReviewV1:
    """Offline facts for one debt; only a stopped attempt records process wait."""

    plan: CodingWorkerPayloadDebtPlanV1
    attempt_record: WorkerAttemptRecordV1 | None

    @property
    def process_wait_recorded(self) -> bool:
        return self.attempt_record is not None and self.attempt_record.process_settled


def review_coding_product_worker_payload_recovery(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerPayloadRecoveryReviewV1:
    """Correlate an exact Product stage with its canonical Supervisor journal.

    An absent or failed/fenced attempt does not establish process settlement.
    This review does not authorize deleting the payload or restarting a Worker.
    """

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            plan = _verify_debt(root_fd, attempt_id)
            record = open_coding_product_worker_supervisor_journal(product).status(
                attempt_id
            )
            if _verify_debt(root_fd, attempt_id) != plan:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            return CodingWorkerPayloadRecoveryReviewV1(plan=plan, attempt_record=record)
        finally:
            os.close(root_fd)


@contextmanager
def materialize_coding_product_worker_payload(
    *,
    receipt_owner: CodingWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
) -> Iterator[CodingProductWorkerPayloadLeaseV1]:
    """Copy a current Product selection into one private, exact attempt root."""

    if not isinstance(receipt_owner, CodingWorkerProductReceiptOwner):
        raise TypeError("Coding Worker Product receipt owner is required")
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    product = receipt_owner.product_owner
    state_root = product.state_root
    root_fd = os.open(state_root, _DIR_FLAGS)
    stage_name = f"worker-payload-{attempt_id}"
    stage_fd = -1
    created = False
    cleanup_entrypoint: str | None = None
    cleanup_plan: CodingWorkerPayloadDebtPlanV1 | None = None
    try:
        _require_private_visible_root(state_root, root_fd)
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            payload = receipt_owner.current_selected_payload(receipt)
            native_material = receipt_owner.current_native_launch_material(receipt)
            if sha256(payload.body).hexdigest() != payload.digest:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_digest_changed"
                )
            cleanup_entrypoint = payload.configuration.entrypoint
            try:
                os.stat(stage_name, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_attempt_debt"
                )
            if (
                open_coding_product_worker_supervisor_journal(product).status(
                    attempt_id
                )
                is not None
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_attempt_reused"
                )
            try:
                os.mkdir(stage_name, 0o700, dir_fd=root_fd)
            except FileExistsError as exc:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_attempt_debt"
                ) from exc
            created = True
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            _write_payload(stage_fd, payload.configuration.entrypoint, payload.body)
            stage_stat = os.fstat(stage_fd)
            plan = CodingWorkerPayloadDebtPlanV1(
                attempt_id=attempt_id,
                entrypoint=payload.configuration.entrypoint,
                payload_digest=payload.digest,
                payload_size=len(payload.body),
                receipt_fingerprint=receipt.fingerprint,
                stage_device=stage_stat.st_dev,
                stage_inode=stage_stat.st_ino,
            )
            _write_marker(stage_fd, plan)
            cleanup_plan = plan
            stage_path = state_root / stage_name
            _require_visible_stage(stage_name, root_fd, stage_fd)
            binding = WorkerRuntimeBindingV1.capture(
                package_root=stage_path,
                configuration=payload.configuration,
            )
            if (
                binding.executable_digest != payload.digest
                or binding.executable_size != len(payload.body)
                or receipt_owner.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_selection_stale"
                )
            _require_visible_stage(stage_name, root_fd, stage_fd)
            lease = CodingProductWorkerPayloadLeaseV1(
                attempt_id=attempt_id,
                runtime=binding,
                native_material=native_material,
                receipt_fingerprint=receipt.fingerprint,
            )
        yield lease
    finally:
        try:
            if created:
                with product.gc_gate.guard(require_write=True):
                    _require_visible_stage(stage_name, root_fd, stage_fd)
                    if cleanup_plan is not None:
                        current = _verify_debt(root_fd, attempt_id)
                        if current != cleanup_plan:
                            raise CodingWorkerPayloadMaterializationError(
                                "coding_worker_payload_stage_changed"
                            )
                        attempt = open_coding_product_worker_supervisor_journal(
                            product
                        ).status(attempt_id)
                        if attempt is None or attempt.process_settled:
                            _remove_verified_stage(
                                root_fd, stage_fd, stage_name, cleanup_plan
                            )
                    elif stage_fd >= 0 and cleanup_entrypoint is not None:
                        _remove_partial_stage(
                            root_fd, stage_fd, stage_name, cleanup_entrypoint
                        )
        finally:
            if stage_fd >= 0:
                os.close(stage_fd)
            os.close(root_fd)


def plan_coding_product_worker_pending_launch(
    *,
    receipt_owner: CodingWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
) -> CodingProductWorkerPendingLaunchV1:
    """Read current Product authority without creating a payload or Worker."""

    if (
        not isinstance(receipt_owner, CodingWorkerProductReceiptOwner)
        or not isinstance(receipt, ProductWorkerActivationReceiptV1)
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise TypeError("Coding Worker pending launch requires Product evidence")
    product = receipt_owner.product_owner
    with product.gc_gate.guard():
        if receipt_owner.current_witness(receipt) != receipt.authority_witness:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_selection_stale"
            )
        selected = receipt_owner.current_selected_payload(receipt)
        if (
            selected.configuration.fingerprint
            != receipt.policy.worker_configuration_fingerprint
        ):
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_selection_stale"
            )
        receipt_owner.current_native_launch_material(receipt)
        owner_id = receipt_owner.current_worker_owner_id(receipt)
        identity = _new_worker_identity(
            receipt=receipt,
            owner_id=owner_id,
            attempt_id=attempt_id,
            supervisor_epoch=1,
            session_nonce=secrets.token_hex(32),
        )
        journal = open_coding_product_worker_supervisor_journal(product)
        if journal.status(attempt_id) is not None:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_attempt_reused"
            )
        epoch = journal.next_supervisor_epoch(identity)
        product.assert_root_gc_authority_current()
        return CodingProductWorkerPendingLaunchV1(
            receipt_fingerprint=receipt.fingerprint,
            identity=replace(identity, supervisor_epoch=epoch),
        )


def bind_coding_product_worker_launch_request(
    *,
    receipt_owner: CodingWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: CodingProductWorkerPayloadLeaseV1,
    supervisor_epoch: int,
    pending_launch: CodingProductWorkerPendingLaunchV1 | None = None,
) -> ManagedWorkerLaunchRequestV1:
    """Bind the Product receipt and live payload copy to one supervised attempt."""

    if (
        not isinstance(receipt_owner, CodingWorkerProductReceiptOwner)
        or not isinstance(receipt, ProductWorkerActivationReceiptV1)
        or not isinstance(payload_lease, CodingProductWorkerPayloadLeaseV1)
        or payload_lease.receipt_fingerprint != receipt.fingerprint
        or payload_lease.runtime.package_root
        != receipt_owner.product_owner.state_root
        / f"worker-payload-{payload_lease.attempt_id}"
    ):
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_binding_mismatch"
        )
    with receipt_owner.product_owner.gc_gate.guard():
        owner_id = receipt_owner.current_worker_owner_id(receipt)
        selected = receipt_owner.current_selected_payload(receipt)
        native = receipt_owner.current_native_launch_material(receipt)
        if (
            selected.digest != payload_lease.runtime.executable_digest
            or selected.configuration.fingerprint
            != payload_lease.runtime.worker_configuration_fingerprint
            or native != payload_lease.native_material
        ):
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_binding_mismatch"
            )
        payload_lease.runtime.verify()
        if pending_launch is not None and (
            type(pending_launch) is not CodingProductWorkerPendingLaunchV1
            or pending_launch.receipt_fingerprint != receipt.fingerprint
            or pending_launch.identity
            != _new_worker_identity(
                receipt=receipt,
                owner_id=owner_id,
                attempt_id=payload_lease.attempt_id,
                supervisor_epoch=supervisor_epoch,
                session_nonce=pending_launch.identity.session_nonce,
            )
            or open_coding_product_worker_supervisor_journal(
                receipt_owner.product_owner
            ).next_supervisor_epoch(pending_launch.identity)
            != supervisor_epoch
        ):
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_pending_launch_changed"
            )

    def validate_current() -> None:
        try:
            with receipt_owner.product_owner.gc_gate.guard():
                current, current_native, current_owner_id = (
                    receipt_owner.current_runtime_binding(receipt)
                )
                if (
                    current.digest != payload_lease.runtime.executable_digest
                    or current_native != payload_lease.native_material
                    or current_owner_id != owner_id
                ):
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_binding_mismatch"
                    )
                payload_lease.runtime.verify()
                attempt = open_coding_product_worker_supervisor_journal(
                    receipt_owner.product_owner
                ).status(payload_lease.attempt_id)
                if attempt is not None and attempt.terminal:
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_attempt_settled"
                    )
        except (
            CodingWorkerReceiptError,
            CodingWorkerPayloadMaterializationError,
            WorkerBindingError,
            WorkerSupervisorJournalError,
        ) as exc:
            raise WorkerBindingError(
                "Coding Product Worker selection changed",
                code="worker_product_selection_stale",
            ) from exc

    identity = (
        pending_launch.identity
        if pending_launch is not None
        else _new_worker_identity(
            receipt=receipt,
            owner_id=owner_id,
            attempt_id=payload_lease.attempt_id,
            supervisor_epoch=supervisor_epoch,
            session_nonce=secrets.token_hex(32),
        )
    )
    return ManagedWorkerLaunchRequestV1(
        identity=identity,
        runtime=payload_lease.runtime,
        validate_current=validate_current,
    )


def _new_worker_identity(
    *,
    receipt: ProductWorkerActivationReceiptV1,
    owner_id: str,
    attempt_id: str,
    supervisor_epoch: int,
    session_nonce: str,
) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id=receipt.policy.plugin_id,
        plugin_revision_digest=receipt.policy.plugin_revision_digest,
        contribution_id=receipt.policy.contribution_id,
        owner_id=owner_id,
        product_id=receipt.policy.product_id,
        scope_id=receipt.policy.product_scope_id,
        owner_generation=receipt.policy.owner_selection_generation,
        declaration_fingerprint=receipt.policy.declaration_fingerprint,
        worker_configuration_fingerprint=(
            receipt.policy.worker_configuration_fingerprint
        ),
        attempt_id=attempt_id,
        supervisor_epoch=supervisor_epoch,
        session_nonce=session_nonce,
    )


def _write_payload(stage_fd: int, entrypoint: str, body: bytes) -> None:
    relative = canonical_plugin_relative_path(entrypoint)
    if relative.as_posix() != entrypoint or not body:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_entrypoint_invalid"
        )
    components = relative.parts
    opened: list[int] = []
    current = stage_fd
    try:
        for component in components[:-1]:
            os.mkdir(component, 0o700, dir_fd=current)
            current = os.open(component, _DIR_FLAGS, dir_fd=current)
            opened.append(current)
        file_fd = os.open(components[-1], _FILE_FLAGS, 0o600, dir_fd=current)
        try:
            remaining = memoryview(body)
            while remaining:
                written = os.write(file_fd, remaining)
                if written < 1:
                    raise OSError("Worker payload write made no progress")
                remaining = remaining[written:]
            os.fchmod(file_fd, 0o500)
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        os.fsync(current)
        os.fsync(stage_fd)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _write_marker(stage_fd: int, plan: CodingWorkerPayloadDebtPlanV1) -> None:
    body = canonical_json_bytes(_plan_fields(plan)) + b"\n"
    descriptor = os.open(_MARKER, _FILE_FLAGS, 0o600, dir_fd=stage_fd)
    try:
        remaining = memoryview(body)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                raise OSError("Worker payload marker write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(stage_fd)


def _plan_fields(plan: CodingWorkerPayloadDebtPlanV1) -> dict[str, object]:
    return {
        "attemptId": plan.attempt_id,
        "entrypoint": plan.entrypoint,
        "payloadDigest": plan.payload_digest,
        "payloadSize": plan.payload_size,
        "receiptFingerprint": plan.receipt_fingerprint,
        "stageDevice": plan.stage_device,
        "stageInode": plan.stage_inode,
        "version": 1,
    }


def preview_coding_product_worker_payload_debt(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerPayloadDebtPlanV1:
    """Read a complete abandoned stage only while Product Sessions are absent."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            return _verify_debt(root_fd, attempt_id)
        finally:
            os.close(root_fd)


def preview_coding_product_worker_empty_payload_debt(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1:
    """Review only an empty stage with no durable Supervisor claim."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            plan = _verify_empty_debt(root_fd, attempt_id)
            if (
                open_coding_product_worker_supervisor_journal(product).status(
                    attempt_id
                )
                is not None
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_attempt_claimed"
                )
            if _verify_empty_debt(root_fd, attempt_id) != plan:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            return plan
        finally:
            os.close(root_fd)


def review_coding_product_worker_unmarked_payload_debt(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1:
    """Inspect a nonempty pre-marker stage without granting cleanup authority."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            review = _scan_unmarked_debt(root_fd, attempt_id)
            if (
                open_coding_product_worker_supervisor_journal(product).status(
                    attempt_id
                )
                is not None
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_attempt_claimed"
                )
            if _scan_unmarked_debt(root_fd, attempt_id) != review:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            return review
        finally:
            os.close(root_fd)


def repair_coding_product_worker_unmarked_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerUnmarkedPayloadDebtReviewV1,
) -> CodingWorkerUnmarkedPayloadDebtReviewV1:
    """Remove an exact pre-marker stage under offline, unclaimed authority."""

    if not isinstance(expected_review, CodingWorkerUnmarkedPayloadDebtReviewV1):
        raise TypeError("Coding Worker unmarked payload review is required")
    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            prior = _read_unmarked_repair_intent(root_fd, expected_review.attempt_id)
            if prior is not None and prior != expected_review:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            _require_unclaimed_attempt(product, expected_review.attempt_id)
            if prior is not None and not _stage_exists(
                root_fd, expected_review.attempt_id
            ):
                _settle_unmarked_repair_intent(root_fd, expected_review)
                return expected_review
            if prior is None and (
                _scan_unmarked_debt(root_fd, expected_review.attempt_id)
                != expected_review
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            stage_name = f"worker-payload-{expected_review.attempt_id}"
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            try:
                _verify_unmarked_repair_remainder(
                    root_fd, stage_fd, stage_name, expected_review,
                    allow_partial=prior is not None,
                )
                _publish_unmarked_repair_intent(root_fd, expected_review)
                _require_unclaimed_attempt(product, expected_review.attempt_id)
                _remove_unmarked_repair_remainder(
                    root_fd, stage_fd, stage_name, expected_review,
                    allow_partial=True,
                )
            finally:
                os.close(stage_fd)
            return expected_review
        finally:
            os.close(root_fd)


def reopen_coding_product_worker_unmarked_payload_repair(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1 | None:
    """Reopen a published, completed pre-marker cleanup after a process crash."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            prior = _read_unmarked_repair_intent(root_fd, attempt_id)
            if prior is None or _stage_exists(root_fd, attempt_id):
                return None
            _require_unclaimed_attempt(product, attempt_id)
            return prior
        finally:
            os.close(root_fd)


def read_coding_product_worker_unmarked_payload_repair_intent(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1 | None:
    """Read a durable cleanup intent even when its exact stage remains."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            prior = _read_unmarked_repair_intent(root_fd, attempt_id)
            if prior is not None:
                _require_unclaimed_attempt(product, attempt_id)
            return prior
        finally:
            os.close(root_fd)


def _require_unclaimed_attempt(
    product: PosixLocalWheelProductSessionOwner, attempt_id: str
) -> None:
    if open_coding_product_worker_supervisor_journal(product).status(attempt_id) is not None:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_attempt_claimed"
        )


def reopen_coding_product_worker_empty_payload_repair(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1 | None:
    """Read a durable repair result only after its exact stage disappeared."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            plan = _read_empty_repair_intent(root_fd, attempt_id)
            if plan is None:
                return None
            if _stage_exists(root_fd, attempt_id):
                return None
            if (
                open_coding_product_worker_supervisor_journal(product).status(
                    attempt_id
                )
                is not None
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_attempt_claimed"
                )
            return plan
        finally:
            os.close(root_fd)


def list_coding_product_worker_payload_debts(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerPayloadDebtPlanV1, ...]:
    """Enumerate every complete attempt stage under offline Product authority.

    A malformed stage name or body makes the whole inventory unavailable. GC
    and recovery callers must not infer that an unreadable attempt is absent.
    """

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            try:
                names = tuple(os.listdir(root_fd))
            except OSError as exc:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_unverified"
                ) from exc
            plans: list[CodingWorkerPayloadDebtPlanV1] = []
            for name in sorted(names):
                if not name.startswith("worker-payload-"):
                    continue
                attempt_id = name.removeprefix("worker-payload-")
                if _ATTEMPT.fullmatch(attempt_id) is None:
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_debt_unverified"
                    )
                plans.append(_verify_debt(root_fd, attempt_id))
            return tuple(plans)
        finally:
            os.close(root_fd)


def repair_coding_product_worker_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_plan: CodingWorkerPayloadDebtPlanV1,
) -> CodingWorkerPayloadDebtPlanV1:
    """Delete an exact stage only after its Supervisor recorded process exit."""

    if not isinstance(expected_plan, CodingWorkerPayloadDebtPlanV1):
        raise TypeError("Coding Worker payload debt plan is required")
    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            prior = _read_complete_repair_intent(root_fd, expected_plan.attempt_id)
            if prior is not None and prior[0] != expected_plan:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            if prior is None:
                current = _verify_debt(root_fd, expected_plan.attempt_id)
                if current != expected_plan:
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_debt_plan_stale"
                    )
            supervisor_fingerprint = _settled_supervisor_fingerprint(
                product, expected_plan.attempt_id
            )
            if prior is not None and prior[1] != supervisor_fingerprint:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            if prior is not None and not _stage_exists(
                root_fd, expected_plan.attempt_id
            ):
                _settle_complete_repair_intent(
                    root_fd, expected_plan, supervisor_fingerprint
                )
                return expected_plan
            stage_name = f"worker-payload-{expected_plan.attempt_id}"
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            try:
                _verify_complete_repair_remainder(
                    root_fd, stage_fd, stage_name, expected_plan
                )
                _publish_complete_repair_intent(
                    root_fd, expected_plan, supervisor_fingerprint
                )
                if (
                    _settled_supervisor_fingerprint(product, expected_plan.attempt_id)
                    != supervisor_fingerprint
                ):
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_debt_plan_stale"
                    )
                _verify_complete_repair_remainder(
                    root_fd, stage_fd, stage_name, expected_plan
                )
                if prior is None:
                    _remove_verified_stage(
                        root_fd, stage_fd, stage_name, expected_plan
                    )
                else:
                    _remove_partial_stage(
                        root_fd, stage_fd, stage_name, expected_plan.entrypoint
                    )
            finally:
                os.close(stage_fd)
            return expected_plan
        finally:
            os.close(root_fd)


def reopen_coding_product_worker_payload_repair(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerPayloadDebtPlanV1 | None:
    """Read one completed, exact payload repair without accepting stage debt."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            prior = _read_complete_repair_intent(root_fd, attempt_id)
            if prior is None or _stage_exists(root_fd, attempt_id):
                return None
            plan, recorded_supervisor = prior
            if _settled_supervisor_fingerprint(product, attempt_id) != (
                recorded_supervisor
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            return plan
        finally:
            os.close(root_fd)


def read_coding_product_worker_payload_repair_intent(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerPayloadDebtPlanV1 | None:
    """Read a durable settled cleanup intent while its stage may remain."""

    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            prior = _read_complete_repair_intent(root_fd, attempt_id)
            if prior is None:
                return None
            plan, recorded_supervisor = prior
            if _settled_supervisor_fingerprint(product, attempt_id) != (
                recorded_supervisor
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            return plan
        finally:
            os.close(root_fd)


def _settled_supervisor_fingerprint(
    product: PosixLocalWheelProductSessionOwner, attempt_id: str
) -> str:
    record = open_coding_product_worker_supervisor_journal(product).status(attempt_id)
    if record is None or not record.process_settled:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_process_unsettled"
        )
    return sha256(canonical_json_bytes(record.to_dict())).hexdigest()


def repair_coding_product_worker_empty_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_plan: CodingWorkerEmptyPayloadDebtPlanV1,
) -> CodingWorkerEmptyPayloadDebtPlanV1:
    """Remove an exact empty stage only when Supervisor never claimed it."""

    if not isinstance(expected_plan, CodingWorkerEmptyPayloadDebtPlanV1):
        raise TypeError("Coding Worker empty payload debt plan is required")
    with _offline(product):
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            prior = _read_empty_repair_intent(root_fd, expected_plan.attempt_id)
            if prior is not None and prior != expected_plan:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            if prior is not None and not _stage_exists(
                root_fd, expected_plan.attempt_id
            ):
                if (
                    open_coding_product_worker_supervisor_journal(product).status(
                        expected_plan.attempt_id
                    )
                    is not None
                ):
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_attempt_claimed"
                    )
                _settle_empty_repair_intent(root_fd, expected_plan)
                return expected_plan
            current = _verify_empty_debt(root_fd, expected_plan.attempt_id)
            if current != expected_plan:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            if (
                open_coding_product_worker_supervisor_journal(product).status(
                    current.attempt_id
                )
                is not None
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_attempt_claimed"
                )
            stage_name = f"worker-payload-{current.attempt_id}"
            stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
            try:
                _require_visible_stage(stage_name, root_fd, stage_fd)
                opened = os.fstat(stage_fd)
                if (
                    opened.st_dev,
                    opened.st_ino,
                ) != (current.stage_device, current.stage_inode) or os.listdir(
                    stage_fd
                ):
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_debt_plan_stale"
                    )
                _publish_empty_repair_intent(root_fd, current)
                _require_visible_stage(stage_name, root_fd, stage_fd)
                _remove_empty_stage(root_fd, stage_name)
            finally:
                os.close(stage_fd)
            return current
        finally:
            os.close(root_fd)


def _empty_repair_fields(
    plan: CodingWorkerEmptyPayloadDebtPlanV1,
) -> dict[str, object]:
    return {
        "attemptId": plan.attempt_id,
        "stageDevice": plan.stage_device,
        "stageInode": plan.stage_inode,
        "version": 1,
    }


def _empty_repair_names(attempt_id: str) -> tuple[str, str]:
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    name = f"{_EMPTY_REPAIR_PREFIX}{attempt_id}.json"
    return name, f".{name}.stage"


def _read_repair_file(
    root_fd: int, name: str, *, maximum_bytes: int, error_code: str
) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd
    )
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != os.geteuid()
            or opened.st_nlink not in {1, 2}
            or not 0 < opened.st_size <= maximum_bytes
        ):
            raise CodingWorkerPayloadMaterializationError(error_code)
        body = os.read(descriptor, maximum_bytes + 1)
        after = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            len(body) != opened.st_size
            or os.read(descriptor, 1)
            or (visible.st_dev, visible.st_ino)
            != (opened.st_dev, opened.st_ino)
            or (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_uid,
                opened.st_nlink,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
        ):
            raise CodingWorkerPayloadMaterializationError(error_code)
        return body, opened
    finally:
        os.close(descriptor)


def _read_empty_repair_intent(
    root_fd: int, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1 | None:
    name, staging = _empty_repair_names(attempt_id)
    try:
        body, opened = _read_repair_file(
            root_fd,
            name,
            maximum_bytes=_MAX_EMPTY_REPAIR_BYTES,
            error_code="coding_worker_payload_empty_repair_unverified",
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_empty_repair_unverified"
        ) from exc
    try:
        value = json.loads(body)
        if type(value) is not dict or set(value) != {
            "attemptId",
            "stageDevice",
            "stageInode",
            "version",
        } or value["version"] != 1:
            raise ValueError("Worker empty repair record is invalid")
        plan = CodingWorkerEmptyPayloadDebtPlanV1(
            attempt_id=value["attemptId"],
            stage_device=value["stageDevice"],
            stage_inode=value["stageInode"],
        )
        if (
            plan.attempt_id != attempt_id
            or body != canonical_json_bytes(_empty_repair_fields(plan)) + b"\n"
        ):
            raise ValueError("Worker empty repair record changed")
        if opened.st_nlink == 2:
            sibling = os.stat(staging, dir_fd=root_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(sibling.st_mode)
                or (sibling.st_dev, sibling.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                raise ValueError("Worker empty repair publication changed")
        return plan
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_empty_repair_unverified"
        ) from exc


def _publish_empty_repair_intent(
    root_fd: int, plan: CodingWorkerEmptyPayloadDebtPlanV1
) -> None:
    name, staging = _empty_repair_names(plan.attempt_id)
    existing = _read_empty_repair_intent(root_fd, plan.attempt_id)
    if existing is not None:
        if existing != plan:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_debt_plan_stale"
            )
        _settle_empty_repair_intent(root_fd, plan)
        return
    body = canonical_json_bytes(_empty_repair_fields(plan)) + b"\n"
    try:
        staged, metadata = _read_repair_file(
            root_fd,
            staging,
            maximum_bytes=_MAX_EMPTY_REPAIR_BYTES,
            error_code="coding_worker_payload_empty_repair_unverified",
        )
    except FileNotFoundError:
        descriptor = os.open(staging, _FILE_FLAGS, 0o600, dir_fd=root_fd)
        try:
            remaining = memoryview(body)
            while remaining:
                written = os.write(descriptor, remaining)
                if written < 1:
                    raise OSError("Worker empty repair intent write made no progress")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        if staged != body or metadata.st_nlink != 1:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_empty_repair_unverified"
            )
    with suppress(FileExistsError):
        os.link(
            staging,
            name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
    os.fsync(root_fd)
    if _read_empty_repair_intent(root_fd, plan.attempt_id) != plan:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_empty_repair_unverified"
        )
    _settle_empty_repair_intent(root_fd, plan)


def _settle_empty_repair_intent(
    root_fd: int, plan: CodingWorkerEmptyPayloadDebtPlanV1
) -> None:
    name, staging = _empty_repair_names(plan.attempt_id)
    if _read_empty_repair_intent(root_fd, plan.attempt_id) != plan:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_empty_repair_unverified"
        )
    metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    if metadata.st_nlink == 2:
        os.unlink(staging, dir_fd=root_fd)
        os.fsync(root_fd)


def _complete_repair_names(attempt_id: str) -> tuple[str, str]:
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    name = f"{_COMPLETE_REPAIR_PREFIX}{attempt_id}.json"
    return name, f".{name}.stage"


def _complete_repair_fields(
    plan: CodingWorkerPayloadDebtPlanV1, supervisor_fingerprint: str
) -> dict[str, object]:
    return {
        "plan": _plan_fields(plan),
        "supervisorFingerprint": supervisor_fingerprint,
        "version": 1,
    }


def _read_complete_repair_intent(
    root_fd: int, attempt_id: str
) -> tuple[CodingWorkerPayloadDebtPlanV1, str] | None:
    name, staging = _complete_repair_names(attempt_id)
    try:
        body, opened = _read_repair_file(
            root_fd,
            name,
            maximum_bytes=_MAX_COMPLETE_REPAIR_BYTES,
            error_code="coding_worker_payload_complete_repair_unverified",
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_complete_repair_unverified"
        ) from exc
    try:
        value = json.loads(body)
        if (
            type(value) is not dict
            or set(value) != {"plan", "supervisorFingerprint", "version"}
            or value["version"] != 1
            or type(value["plan"]) is not dict
            or set(value["plan"])
            != {
                "attemptId",
                "entrypoint",
                "payloadDigest",
                "payloadSize",
                "receiptFingerprint",
                "stageDevice",
                "stageInode",
                "version",
            }
        ):
            raise ValueError("Worker complete repair record is invalid")
        raw_plan = value["plan"]
        plan = CodingWorkerPayloadDebtPlanV1(
            attempt_id=raw_plan["attemptId"],
            entrypoint=raw_plan["entrypoint"],
            payload_digest=raw_plan["payloadDigest"],
            payload_size=raw_plan["payloadSize"],
            receipt_fingerprint=raw_plan["receiptFingerprint"],
            stage_device=raw_plan["stageDevice"],
            stage_inode=raw_plan["stageInode"],
        )
        supervisor_fingerprint = value["supervisorFingerprint"]
        if (
            raw_plan["version"] != 1
            or plan.attempt_id != attempt_id
            or not isinstance(supervisor_fingerprint, str)
            or _DIGEST.fullmatch(supervisor_fingerprint) is None
            or body
            != canonical_json_bytes(
                _complete_repair_fields(plan, supervisor_fingerprint)
            )
            + b"\n"
        ):
            raise ValueError("Worker complete repair record changed")
        if opened.st_nlink == 2:
            sibling = os.stat(staging, dir_fd=root_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(sibling.st_mode)
                or (sibling.st_dev, sibling.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                raise ValueError("Worker complete repair publication changed")
        return plan, supervisor_fingerprint
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_complete_repair_unverified"
        ) from exc


def _publish_complete_repair_intent(
    root_fd: int, plan: CodingWorkerPayloadDebtPlanV1, supervisor_fingerprint: str
) -> None:
    name, staging = _complete_repair_names(plan.attempt_id)
    expected = (plan, supervisor_fingerprint)
    existing = _read_complete_repair_intent(root_fd, plan.attempt_id)
    if existing is not None:
        if existing != expected:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_debt_plan_stale"
            )
        _settle_complete_repair_intent(root_fd, *expected)
        return
    body = canonical_json_bytes(_complete_repair_fields(*expected)) + b"\n"
    try:
        staged, metadata = _read_repair_file(
            root_fd,
            staging,
            maximum_bytes=_MAX_COMPLETE_REPAIR_BYTES,
            error_code="coding_worker_payload_complete_repair_unverified",
        )
    except FileNotFoundError:
        descriptor = os.open(staging, _FILE_FLAGS, 0o600, dir_fd=root_fd)
        try:
            remaining = memoryview(body)
            while remaining:
                written = os.write(descriptor, remaining)
                if written < 1:
                    raise OSError("Worker complete repair intent write made no progress")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        if staged != body or metadata.st_nlink != 1:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_complete_repair_unverified"
            )
    with suppress(FileExistsError):
        os.link(
            staging,
            name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
    os.fsync(root_fd)
    if _read_complete_repair_intent(root_fd, plan.attempt_id) != expected:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_complete_repair_unverified"
        )
    _settle_complete_repair_intent(root_fd, *expected)


def _settle_complete_repair_intent(
    root_fd: int, plan: CodingWorkerPayloadDebtPlanV1, supervisor_fingerprint: str
) -> None:
    name, staging = _complete_repair_names(plan.attempt_id)
    if _read_complete_repair_intent(root_fd, plan.attempt_id) != (
        plan,
        supervisor_fingerprint,
    ):
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_complete_repair_unverified"
        )
    metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    if metadata.st_nlink == 2:
        os.unlink(staging, dir_fd=root_fd)
        os.fsync(root_fd)


def _unmarked_repair_fields(
    review: CodingWorkerUnmarkedPayloadDebtReviewV1,
) -> dict[str, object]:
    return {
        "attemptId": review.attempt_id,
        "members": [member.to_dict() for member in review.members],
        "stageDevice": review.stage_device,
        "stageInode": review.stage_inode,
        "version": 1,
    }


def _unmarked_repair_names(attempt_id: str) -> tuple[str, str]:
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    name = f"{_UNMARKED_REPAIR_PREFIX}{attempt_id}.json"
    return name, f".{name}.stage"


def _read_unmarked_repair_intent(
    root_fd: int, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1 | None:
    name, staging = _unmarked_repair_names(attempt_id)
    try:
        body, opened = _read_repair_file(
            root_fd,
            name,
            maximum_bytes=_MAX_UNMARKED_REPAIR_BYTES,
            error_code="coding_worker_payload_unmarked_repair_unverified",
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_unmarked_repair_unverified"
        ) from exc
    try:
        value = json.loads(body)
        if (
            type(value) is not dict
            or set(value) != {"attemptId", "members", "stageDevice", "stageInode", "version"}
            or value["version"] != 1
            or type(value["members"]) is not list
            or not 1 <= len(value["members"]) <= _MAX_UNMARKED_DEPTH + 1
        ):
            raise ValueError("Worker unmarked repair record is invalid")
        members: list[CodingWorkerUnmarkedPayloadMemberV1] = []
        for raw in value["members"]:
            if type(raw) is not dict or set(raw) != {
                "device", "digest", "inode", "kind", "mode", "relativePath", "size"
            }:
                raise ValueError("Worker unmarked repair member is invalid")
            members.append(
                CodingWorkerUnmarkedPayloadMemberV1(
                    relative_path=raw["relativePath"],
                    kind=raw["kind"],
                    device=raw["device"],
                    inode=raw["inode"],
                    mode=raw["mode"],
                    size=raw["size"],
                    digest=raw["digest"],
                )
            )
        review = CodingWorkerUnmarkedPayloadDebtReviewV1(
            attempt_id=value["attemptId"],
            stage_device=value["stageDevice"],
            stage_inode=value["stageInode"],
            members=tuple(members),
        )
        if (
            review.attempt_id != attempt_id
            or body != canonical_json_bytes(_unmarked_repair_fields(review)) + b"\n"
        ):
            raise ValueError("Worker unmarked repair record changed")
        if opened.st_nlink == 2:
            sibling = os.stat(staging, dir_fd=root_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(sibling.st_mode)
                or (sibling.st_dev, sibling.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                raise ValueError("Worker unmarked repair publication changed")
        return review
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_unmarked_repair_unverified"
        ) from exc


def _publish_unmarked_repair_intent(
    root_fd: int, review: CodingWorkerUnmarkedPayloadDebtReviewV1
) -> None:
    name, staging = _unmarked_repair_names(review.attempt_id)
    existing = _read_unmarked_repair_intent(root_fd, review.attempt_id)
    if existing is not None:
        if existing != review:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_debt_plan_stale"
            )
        _settle_unmarked_repair_intent(root_fd, review)
        return
    body = canonical_json_bytes(_unmarked_repair_fields(review)) + b"\n"
    if len(body) > _MAX_UNMARKED_REPAIR_BYTES:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_unmarked_repair_unverified"
        )
    try:
        staged, metadata = _read_repair_file(
            root_fd,
            staging,
            maximum_bytes=_MAX_UNMARKED_REPAIR_BYTES,
            error_code="coding_worker_payload_unmarked_repair_unverified",
        )
    except FileNotFoundError:
        descriptor = os.open(staging, _FILE_FLAGS, 0o600, dir_fd=root_fd)
        try:
            remaining = memoryview(body)
            while remaining:
                written = os.write(descriptor, remaining)
                if written < 1:
                    raise OSError("Worker unmarked repair intent write made no progress")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        if staged != body or metadata.st_nlink != 1:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_unmarked_repair_unverified"
            )
    with suppress(FileExistsError):
        os.link(
            staging,
            name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
    os.fsync(root_fd)
    if _read_unmarked_repair_intent(root_fd, review.attempt_id) != review:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_unmarked_repair_unverified"
        )
    _settle_unmarked_repair_intent(root_fd, review)


def _settle_unmarked_repair_intent(
    root_fd: int, review: CodingWorkerUnmarkedPayloadDebtReviewV1
) -> None:
    name, staging = _unmarked_repair_names(review.attempt_id)
    if _read_unmarked_repair_intent(root_fd, review.attempt_id) != review:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_unmarked_repair_unverified"
        )
    metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    if metadata.st_nlink == 2:
        os.unlink(staging, dir_fd=root_fd)
        os.fsync(root_fd)


def _stage_exists(root_fd: int, attempt_id: str) -> bool:
    try:
        os.stat(
            f"worker-payload-{attempt_id}", dir_fd=root_fd, follow_symlinks=False
        )
    except FileNotFoundError:
        return False
    return True


def _remove_empty_stage(root_fd: int, stage_name: str) -> None:
    os.rmdir(stage_name, dir_fd=root_fd)
    os.fsync(root_fd)


@contextmanager
def _offline(product: PosixLocalWheelProductSessionOwner) -> Iterator[None]:
    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_runtime_active"
            )
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard():
            yield
        product.assert_root_gc_authority_current()


def _verify_debt(root_fd: int, attempt_id: str) -> CodingWorkerPayloadDebtPlanV1:
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    stage_name = f"worker-payload-{attempt_id}"
    try:
        stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
        try:
            _require_visible_stage(stage_name, root_fd, stage_fd)
            marker_fd = os.open(
                _MARKER,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=stage_fd,
            )
            try:
                marker_stat = os.fstat(marker_fd)
                if (
                    not stat.S_ISREG(marker_stat.st_mode)
                    or stat.S_IMODE(marker_stat.st_mode) != 0o600
                    or marker_stat.st_nlink != 1
                    or marker_stat.st_uid != os.geteuid()
                ):
                    raise ValueError("Worker payload marker is unsafe")
                body = os.read(marker_fd, 1025)
                if len(body) > 1024 or os.read(marker_fd, 1):
                    raise ValueError("Worker payload marker exceeds budget")
            finally:
                os.close(marker_fd)
            value = json.loads(body)
            fields = {
                "attemptId",
                "entrypoint",
                "payloadDigest",
                "payloadSize",
                "receiptFingerprint",
                "stageDevice",
                "stageInode",
                "version",
            }
            if type(value) is not dict or set(value) != fields or value["version"] != 1:
                raise ValueError("Worker payload marker is invalid")
            plan = CodingWorkerPayloadDebtPlanV1(
                attempt_id=value["attemptId"],
                entrypoint=value["entrypoint"],
                payload_digest=value["payloadDigest"],
                payload_size=value["payloadSize"],
                receipt_fingerprint=value["receiptFingerprint"],
                stage_device=value["stageDevice"],
                stage_inode=value["stageInode"],
            )
            opened = os.fstat(stage_fd)
            if (
                body != canonical_json_bytes(_plan_fields(plan)) + b"\n"
                or plan.attempt_id != attempt_id
                or (opened.st_dev, opened.st_ino)
                != (plan.stage_device, plan.stage_inode)
            ):
                raise ValueError("Worker payload marker changed")
            _verify_debt_file(stage_fd, plan)
            _require_visible_stage(stage_name, root_fd, stage_fd)
            return plan
        finally:
            os.close(stage_fd)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_debt_unverified"
        ) from exc


def _verify_empty_debt(
    root_fd: int, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1:
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    stage_name = f"worker-payload-{attempt_id}"
    try:
        stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
        try:
            _require_visible_stage(stage_name, root_fd, stage_fd)
            stage = os.fstat(stage_fd)
            if (
                stage.st_uid != os.geteuid()
                or stat.S_IMODE(stage.st_mode) != 0o700
                or os.listdir(stage_fd)
            ):
                raise ValueError("Worker empty payload stage is unsafe")
            return CodingWorkerEmptyPayloadDebtPlanV1(
                attempt_id=attempt_id,
                stage_device=stage.st_dev,
                stage_inode=stage.st_ino,
            )
        finally:
            os.close(stage_fd)
    except (OSError, ValueError, TypeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_empty_debt_unverified"
        ) from exc


def _scan_unmarked_debt(
    root_fd: int, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1:
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Coding Worker attempt identity is invalid")
    stage_name = f"worker-payload-{attempt_id}"
    stage_fd = -1
    opened: list[int] = []
    try:
        stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
        _require_visible_stage(stage_name, root_fd, stage_fd)
        stage = os.fstat(stage_fd)
        if stage.st_uid != os.geteuid() or stat.S_IMODE(stage.st_mode) != 0o700:
            raise ValueError("Worker unmarked stage is unsafe")
        current = stage_fd
        members: list[CodingWorkerUnmarkedPayloadMemberV1] = []
        parts: list[str] = []
        for depth in range(_MAX_UNMARKED_DEPTH + 1):
            names = tuple(os.listdir(current))
            if not names:
                if not members:
                    raise ValueError("Worker empty stage has a separate review")
                break
            if len(names) != 1 or names[0] == _MARKER:
                raise ValueError("Worker unmarked stage is not a single path")
            name = names[0]
            parts.append(name)
            relative = "/".join(parts)
            if (
                canonical_plugin_relative_path(relative).as_posix() != relative
                or len(os.fsencode(relative)) > _MAX_UNMARKED_PATH_BYTES
            ):
                raise ValueError("Worker unmarked path is invalid")
            visible = os.stat(name, dir_fd=current, follow_symlinks=False)
            if stat.S_ISDIR(visible.st_mode):
                if depth >= _MAX_UNMARKED_DEPTH:
                    raise ValueError("Worker unmarked directory depth exceeded")
                child = os.open(name, _DIR_FLAGS, dir_fd=current)
                opened.append(child)
                metadata = os.fstat(child)
                if (
                    metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o700
                    or (metadata.st_dev, metadata.st_ino)
                    != (visible.st_dev, visible.st_ino)
                ):
                    raise ValueError("Worker unmarked directory changed")
                members.append(
                    CodingWorkerUnmarkedPayloadMemberV1(
                        relative_path=relative,
                        kind="directory",
                        device=metadata.st_dev,
                        inode=metadata.st_ino,
                        mode=0o700,
                        size=0,
                        digest=None,
                    )
                )
                current = child
                continue
            if not stat.S_ISREG(visible.st_mode):
                raise ValueError("Worker unmarked member is unsafe")
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current
            )
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != os.geteuid()
                    or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) not in {0o600, 0o500}
                    or not 0 <= before.st_size <= 16 * 1024 * 1024
                    or (before.st_dev, before.st_ino)
                    != (visible.st_dev, visible.st_ino)
                ):
                    raise ValueError("Worker unmarked file is unsafe")
                digest = sha256()
                remaining = before.st_size
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError("Worker unmarked file was truncated")
                    digest.update(chunk)
                    remaining -= len(chunk)
                after = os.fstat(descriptor)
                if (
                    os.read(descriptor, 1)
                    or (before.st_dev, before.st_ino, before.st_size,
                        before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise ValueError("Worker unmarked file changed")
                members.append(
                    CodingWorkerUnmarkedPayloadMemberV1(
                        relative_path=relative,
                        kind="file",
                        device=before.st_dev,
                        inode=before.st_ino,
                        mode=stat.S_IMODE(before.st_mode),
                        size=before.st_size,
                        digest=digest.hexdigest(),
                    )
                )
            finally:
                os.close(descriptor)
            break
        else:
            raise ValueError("Worker unmarked stage exceeds depth budget")
        _require_visible_stage(stage_name, root_fd, stage_fd)
        return CodingWorkerUnmarkedPayloadDebtReviewV1(
            attempt_id=attempt_id,
            stage_device=stage.st_dev,
            stage_inode=stage.st_ino,
            members=tuple(members),
        )
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_unmarked_debt_unverified"
        ) from exc
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
        if stage_fd >= 0:
            os.close(stage_fd)


@contextmanager
def _open_unmarked_repair_remainder(
    root_fd: int,
    stage_fd: int,
    stage_name: str,
    review: CodingWorkerUnmarkedPayloadDebtReviewV1,
    *,
    allow_partial: bool,
) -> Iterator[tuple[list[tuple[int, str, int]], tuple[int, str, int] | None]]:
    directories: list[tuple[int, str, int]] = []
    leaf: tuple[int, str, int] | None = None
    try:
        _require_visible_stage(stage_name, root_fd, stage_fd)
        stage = os.fstat(stage_fd)
        if (
            stage.st_uid != os.geteuid()
            or stat.S_IMODE(stage.st_mode) != 0o700
            or (stage.st_dev, stage.st_ino)
            != (review.stage_device, review.stage_inode)
        ):
            raise ValueError("Worker unmarked stage changed")
        current = stage_fd
        count = 0
        for member in review.members:
            name = member.relative_path.rsplit("/", 1)[-1]
            names = set(os.listdir(current))
            if not names:
                break
            if names != {name}:
                raise ValueError("Worker unmarked remainder has foreign members")
            visible = os.stat(name, dir_fd=current, follow_symlinks=False)
            if member.kind == "directory":
                child = os.open(name, _DIR_FLAGS, dir_fd=current)
                directories.append((current, name, child))
                opened = os.fstat(child)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or opened.st_uid != os.geteuid()
                    or stat.S_IMODE(opened.st_mode) != member.mode
                    or (opened.st_dev, opened.st_ino)
                    != (visible.st_dev, visible.st_ino)
                    or (opened.st_dev, opened.st_ino)
                    != (member.device, member.inode)
                ):
                    raise ValueError("Worker unmarked directory changed")
                current = child
            else:
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=current,
                )
                leaf = (current, name, descriptor)
                _verify_unmarked_repair_file(current, name, descriptor, member, visible)
            count += 1
        if count != len(review.members) and not allow_partial:
            raise ValueError("Worker unmarked stage changed before repair intent")
        if (
            count == len(review.members)
            and review.members[-1].kind == "directory"
            and os.listdir(current)
        ):
            raise ValueError("Worker unmarked directory gained a member")
        _require_visible_stage(stage_name, root_fd, stage_fd)
        yield directories, leaf
    except (OSError, ValueError, TypeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_debt_plan_stale"
        ) from exc
    finally:
        if leaf is not None:
            os.close(leaf[2])
        for _, _, descriptor in reversed(directories):
            os.close(descriptor)


def _verify_unmarked_repair_file(
    parent_fd: int,
    name: str,
    descriptor: int,
    member: CodingWorkerUnmarkedPayloadMemberV1,
    visible: os.stat_result,
) -> None:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != member.mode
        or before.st_size != member.size
        or (before.st_dev, before.st_ino)
        != (visible.st_dev, visible.st_ino)
        or (before.st_dev, before.st_ino)
        != (member.device, member.inode)
    ):
        raise ValueError("Worker unmarked file changed")
    digest = sha256()
    remaining = before.st_size
    while remaining:
        chunk = os.read(descriptor, min(remaining, 1024 * 1024))
        if not chunk:
            raise ValueError("Worker unmarked file was truncated")
        digest.update(chunk)
        remaining -= len(chunk)
    after = os.fstat(descriptor)
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        digest.hexdigest() != member.digest
        or os.read(descriptor, 1)
        or (before.st_dev, before.st_ino, before.st_mode, before.st_uid,
            before.st_nlink, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_mode, after.st_uid,
            after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
    ):
        raise ValueError("Worker unmarked file changed")


def _verify_unmarked_repair_remainder(
    root_fd: int,
    stage_fd: int,
    stage_name: str,
    review: CodingWorkerUnmarkedPayloadDebtReviewV1,
    *,
    allow_partial: bool,
) -> None:
    with _open_unmarked_repair_remainder(
        root_fd, stage_fd, stage_name, review, allow_partial=allow_partial
    ):
        pass


def _remove_unmarked_repair_remainder(
    root_fd: int,
    stage_fd: int,
    stage_name: str,
    review: CodingWorkerUnmarkedPayloadDebtReviewV1,
    *,
    allow_partial: bool,
) -> None:
    with _open_unmarked_repair_remainder(
        root_fd, stage_fd, stage_name, review, allow_partial=allow_partial
    ) as (directories, leaf):
        if leaf is not None:
            parent, name, descriptor = leaf
            opened = os.fstat(descriptor)
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)
        for parent, name, descriptor in reversed(directories):
            opened = os.fstat(descriptor)
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino)
                or os.listdir(descriptor)
            ):
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_debt_plan_stale"
                )
            os.rmdir(name, dir_fd=parent)
            os.fsync(parent)
        _require_visible_stage(stage_name, root_fd, stage_fd)
        if os.listdir(stage_fd):
            raise CodingWorkerPayloadMaterializationError(
                "coding_worker_payload_debt_plan_stale"
            )
        os.rmdir(stage_name, dir_fd=root_fd)
        os.fsync(root_fd)


def _verify_debt_file(stage_fd: int, plan: CodingWorkerPayloadDebtPlanV1) -> None:
    parts = canonical_plugin_relative_path(plan.entrypoint).parts
    current = stage_fd
    opened: list[int] = []
    try:
        for component in parts[:-1]:
            expected = {_MARKER, component} if current == stage_fd else {component}
            if set(os.listdir(current)) != expected:
                raise ValueError("Worker payload stage has extra members")
            current = os.open(component, _DIR_FLAGS, dir_fd=current)
            opened.append(current)
            directory = os.fstat(current)
            if (
                directory.st_uid != os.geteuid()
                or stat.S_IMODE(directory.st_mode) != 0o700
            ):
                raise ValueError("Worker payload directory is unsafe")
        expected_leaf = {_MARKER, parts[-1]} if current == stage_fd else {parts[-1]}
        if set(os.listdir(current)) != expected_leaf:
            raise ValueError("Worker payload stage has extra members")
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=current,
        )
        try:
            metadata = os.fstat(file_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o500
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or metadata.st_size != plan.payload_size
            ):
                raise ValueError("Worker payload file is unsafe")
            digest = sha256()
            remaining = plan.payload_size
            while remaining:
                chunk = os.read(file_fd, min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError("Worker payload file is truncated")
                digest.update(chunk)
                remaining -= len(chunk)
            if os.read(file_fd, 1) or digest.hexdigest() != plan.payload_digest:
                raise ValueError("Worker payload file changed")
        finally:
            os.close(file_fd)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _verify_complete_repair_remainder(
    root_fd: int,
    stage_fd: int,
    stage_name: str,
    plan: CodingWorkerPayloadDebtPlanV1,
) -> None:
    """Accept only a prefix of this owner's leaf, parents, marker deletion."""

    try:
        _require_visible_stage(stage_name, root_fd, stage_fd)
        stage = os.fstat(stage_fd)
        if (
            (stage.st_dev, stage.st_ino) != (plan.stage_device, plan.stage_inode)
            or stage.st_uid != os.geteuid()
            or stat.S_IMODE(stage.st_mode) != 0o700
        ):
            raise ValueError("Worker complete repair stage changed")
        parts = canonical_plugin_relative_path(plan.entrypoint).parts
        root_members = set(os.listdir(stage_fd))
        if root_members - {_MARKER, parts[0]}:
            raise ValueError("Worker complete repair has extra members")
        if _MARKER not in root_members:
            if root_members:
                raise ValueError("Worker complete repair marker disappeared early")
            return
        marker, metadata = _read_repair_file(
            stage_fd,
            _MARKER,
            maximum_bytes=_MAX_MARKER_BYTES,
            error_code="coding_worker_payload_debt_unverified",
        )
        if (
            metadata.st_nlink != 1
            or marker != canonical_json_bytes(_plan_fields(plan)) + b"\n"
        ):
            raise ValueError("Worker complete repair marker changed")
        current = stage_fd
        opened: list[int] = []
        try:
            for index, component in enumerate(parts):
                members = set(os.listdir(current))
                allowed = {component, _MARKER} if current == stage_fd else {component}
                if members - allowed:
                    raise ValueError("Worker complete repair has extra members")
                if component not in members:
                    break
                if index == len(parts) - 1:
                    _verify_complete_repair_leaf(current, component, plan)
                    break
                child = os.open(component, _DIR_FLAGS, dir_fd=current)
                opened.append(child)
                child_stat = os.fstat(child)
                visible = os.stat(
                    component, dir_fd=current, follow_symlinks=False
                )
                if (
                    child_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(child_stat.st_mode) != 0o700
                    or (child_stat.st_dev, child_stat.st_ino)
                    != (visible.st_dev, visible.st_ino)
                ):
                    raise ValueError("Worker complete repair directory changed")
                current = child
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)
        _require_visible_stage(stage_name, root_fd, stage_fd)
    except (OSError, ValueError, TypeError) as exc:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_debt_unverified"
        ) from exc


def _verify_complete_repair_leaf(
    parent_fd: int, name: str, plan: CodingWorkerPayloadDebtPlanV1
) -> None:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
    )
    try:
        opened = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o500
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or opened.st_size != plan.payload_size
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise ValueError("Worker complete repair payload changed")
        digest = sha256()
        remaining = plan.payload_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError("Worker complete repair payload was truncated")
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1) or digest.hexdigest() != plan.payload_digest:
            raise ValueError("Worker complete repair payload changed")
    finally:
        os.close(descriptor)


def _remove_verified_stage(
    root_fd: int,
    stage_fd: int,
    stage_name: str,
    plan: CodingWorkerPayloadDebtPlanV1,
) -> None:
    """Remove only the verified stage's members through captured directories."""

    _require_visible_stage(stage_name, root_fd, stage_fd)
    _verify_debt_file(stage_fd, plan)
    parts = canonical_plugin_relative_path(plan.entrypoint).parts
    parents = [stage_fd]
    try:
        for component in parts[:-1]:
            parents.append(os.open(component, _DIR_FLAGS, dir_fd=parents[-1]))
        os.unlink(parts[-1], dir_fd=parents[-1])
        os.fsync(parents[-1])
        for index in range(len(parts) - 2, -1, -1):
            os.rmdir(parts[index], dir_fd=parents[index])
            os.fsync(parents[index])
        os.unlink(_MARKER, dir_fd=stage_fd)
        os.fsync(stage_fd)
        _require_visible_stage(stage_name, root_fd, stage_fd)
        os.rmdir(stage_name, dir_fd=root_fd)
        os.fsync(root_fd)
    finally:
        for descriptor in reversed(parents[1:]):
            os.close(descriptor)


def _remove_partial_stage(
    root_fd: int, stage_fd: int, stage_name: str, entrypoint: str
) -> None:
    """Clean a failed write from the original stage without following its name."""

    _require_visible_stage(stage_name, root_fd, stage_fd)
    parts = canonical_plugin_relative_path(entrypoint).parts
    opened: list[int] = []
    current = stage_fd
    try:
        for component in parts[:-1]:
            allowed = {_MARKER, component} if current == stage_fd else {component}
            visible = set(os.listdir(current))
            if visible - allowed:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_stage_changed"
                )
            if component not in visible:
                break
            child = os.open(component, _DIR_FLAGS, dir_fd=current)
            directory = os.fstat(child)
            if (
                directory.st_uid != os.geteuid()
                or stat.S_IMODE(directory.st_mode) != 0o700
            ):
                os.close(child)
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_stage_changed"
                )
            opened.append(child)
            current = child
        if len(opened) == len(parts) - 1:
            allowed_leaf = {_MARKER, parts[-1]} if current == stage_fd else {parts[-1]}
            visible = set(os.listdir(current))
            if visible - allowed_leaf:
                raise CodingWorkerPayloadMaterializationError(
                    "coding_worker_payload_stage_changed"
                )
            if parts[-1] in visible:
                leaf_fd = os.open(
                    parts[-1],
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=current,
                )
                try:
                    leaf = os.fstat(leaf_fd)
                    if (
                        not stat.S_ISREG(leaf.st_mode)
                        or leaf.st_uid != os.geteuid()
                        or leaf.st_nlink != 1
                        or stat.S_IMODE(leaf.st_mode) not in {0o600, 0o500}
                    ):
                        raise CodingWorkerPayloadMaterializationError(
                            "coding_worker_payload_stage_changed"
                        )
                finally:
                    os.close(leaf_fd)
                os.unlink(parts[-1], dir_fd=current)
                os.fsync(current)
        for index in range(len(opened) - 1, -1, -1):
            parent = stage_fd if index == 0 else opened[index - 1]
            os.rmdir(parts[index], dir_fd=parent)
            os.fsync(parent)
        if _MARKER in os.listdir(stage_fd):
            marker_fd = os.open(
                _MARKER,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=stage_fd,
            )
            try:
                marker = os.fstat(marker_fd)
                if (
                    not stat.S_ISREG(marker.st_mode)
                    or marker.st_uid != os.geteuid()
                    or marker.st_nlink != 1
                    or stat.S_IMODE(marker.st_mode) != 0o600
                ):
                    raise CodingWorkerPayloadMaterializationError(
                        "coding_worker_payload_stage_changed"
                    )
            finally:
                os.close(marker_fd)
            os.unlink(_MARKER, dir_fd=stage_fd)
            os.fsync(stage_fd)
        _require_visible_stage(stage_name, root_fd, stage_fd)
        os.rmdir(stage_name, dir_fd=root_fd)
        os.fsync(root_fd)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _require_private_visible_root(path: Path, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    visible = path.lstat()
    if (
        not stat.S_ISDIR(opened.st_mode)
        or opened.st_uid != os.geteuid()
        or stat.S_IMODE(opened.st_mode) & 0o077
        or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
    ):
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_root_unsafe"
        )


def _require_visible_stage(name: str, parent_fd: int, stage_fd: int) -> None:
    if stage_fd < 0:
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_stage_unavailable"
        )
    opened = os.fstat(stage_fd)
    visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or stat.S_IMODE(opened.st_mode) & 0o077
        or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
    ):
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_stage_changed"
        )
