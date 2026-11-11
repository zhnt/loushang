"""Private, attempt-scoped Linux payload copy for a selected Coding Worker.

The Product Store keeps every file non-executable. This owner copies only the
freshly verified Worker executable into a private 0500 file for Hosting's
descriptor-sealing capture. A context exit removes the copy; a crash leaves
an exact attempt name as debt and a replay refuses to reuse it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

import loushang.harness.worker.payload._recovery as _recovery
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
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
)
from loushang.harness.worker.payload._records import (
    PayloadValueTypes,
    plan_fields,
    unmarked_fields,
)
from loushang.harness.worker.payload._selected_payload import (
    bind_selected_payload_request,
    materialize_selected_payload,
    plan_selected_payload_launch,
    worker_identity_from_receipt,
)
from loushang.harness.worker.payload._storage import (
    _COMPLETE_REPAIR_PREFIX as _COMPLETE_REPAIR_PREFIX,
)
from loushang.harness.worker.payload._storage import _DIR_FLAGS as _DIR_FLAGS
from loushang.harness.worker.payload._storage import (
    _EMPTY_REPAIR_PREFIX as _EMPTY_REPAIR_PREFIX,
)
from loushang.harness.worker.payload._storage import _FILE_FLAGS as _FILE_FLAGS
from loushang.harness.worker.payload._storage import _MARKER as _MARKER
from loushang.harness.worker.payload._storage import (
    _MAX_COMPLETE_REPAIR_BYTES as _MAX_COMPLETE_REPAIR_BYTES,
)
from loushang.harness.worker.payload._storage import (
    _MAX_EMPTY_REPAIR_BYTES as _MAX_EMPTY_REPAIR_BYTES,
)
from loushang.harness.worker.payload._storage import (
    _MAX_MARKER_BYTES as _MAX_MARKER_BYTES,
)
from loushang.harness.worker.payload._storage import (
    _MAX_UNMARKED_DEPTH as _MAX_UNMARKED_DEPTH,
)
from loushang.harness.worker.payload._storage import (
    _MAX_UNMARKED_PATH_BYTES as _MAX_UNMARKED_PATH_BYTES,
)
from loushang.harness.worker.payload._storage import (
    _MAX_UNMARKED_REPAIR_BYTES as _MAX_UNMARKED_REPAIR_BYTES,
)
from loushang.harness.worker.payload._storage import (
    _UNMARKED_REPAIR_PREFIX as _UNMARKED_REPAIR_PREFIX,
)
from loushang.harness.worker.payload._storage import PayloadStorage, repair_names
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

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        plan, record = _recovery.review_complete(
            _STORAGE,
            root_fd,
            attempt_id=attempt_id,
            supervisor=lambda: open_coding_product_worker_supervisor_journal(product),
        )
        return CodingWorkerPayloadRecoveryReviewV1(
            plan=cast("CodingWorkerPayloadDebtPlanV1", plan), attempt_record=record
        )


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
    with materialize_selected_payload(
        _STORAGE,
        root=state_root,
        authority=receipt_owner,
        receipt=receipt,
        attempt_id=attempt_id,
        guard=lambda write: (
            product.gc_gate.guard(require_write=True)
            if write
            else product.gc_gate.guard()
        ),
        assert_current=lambda: product.assert_root_gc_authority_current(),
        supervisor=lambda: open_coding_product_worker_supervisor_journal(product),
        lease_factory=CodingProductWorkerPayloadLeaseV1,
        error_prefix="coding_worker_payload",
    ) as lease:
        yield lease


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
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise TypeError("Coding Worker pending launch requires Product evidence")
    product = receipt_owner.product_owner
    return plan_selected_payload_launch(
        _STORAGE,
        authority=receipt_owner,
        receipt=receipt,
        attempt_id=attempt_id,
        guard=lambda write: (
            product.gc_gate.guard(require_write=True)
            if write
            else product.gc_gate.guard()
        ),
        assert_current=lambda: product.assert_root_gc_authority_current(),
        supervisor=lambda: open_coding_product_worker_supervisor_journal(product),
        pending_factory=CodingProductWorkerPendingLaunchV1,
        error_prefix="coding_worker_payload",
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
        or (not isinstance(payload_lease, CodingProductWorkerPayloadLeaseV1))
        or (payload_lease.receipt_fingerprint != receipt.fingerprint)
        or (
            payload_lease.runtime.package_root
            != receipt_owner.product_owner.state_root
            / f"worker-payload-{payload_lease.attempt_id}"
        )
    ):
        raise CodingWorkerPayloadMaterializationError(
            "coding_worker_payload_binding_mismatch"
        )
    return bind_selected_payload_request(
        _STORAGE,
        authority=receipt_owner,
        receipt=receipt,
        payload_lease=payload_lease,
        supervisor_epoch=supervisor_epoch,
        pending_launch=pending_launch,
        pending_type=CodingProductWorkerPendingLaunchV1,
        guard=lambda write: (
            receipt_owner.product_owner.gc_gate.guard(require_write=True)
            if write
            else receipt_owner.product_owner.gc_gate.guard()
        ),
        supervisor=lambda: open_coding_product_worker_supervisor_journal(
            receipt_owner.product_owner
        ),
        receipt_error_type=CodingWorkerReceiptError,
        stale_message="Coding Product Worker selection changed",
        error_prefix="coding_worker_payload",
    )


_new_worker_identity = worker_identity_from_receipt


_STORAGE = PayloadStorage(
    PayloadValueTypes(
        CodingWorkerPayloadDebtPlanV1,
        CodingWorkerEmptyPayloadDebtPlanV1,
        CodingWorkerUnmarkedPayloadMemberV1,
        CodingWorkerUnmarkedPayloadDebtReviewV1,
    ),
    CodingWorkerPayloadMaterializationError,
)

_write_payload = _STORAGE._write_payload


_write_marker = _STORAGE._write_marker


def _plan_fields(plan: CodingWorkerPayloadDebtPlanV1) -> dict[str, object]:
    return plan_fields(plan)


def preview_coding_product_worker_payload_debt(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerPayloadDebtPlanV1:
    """Read a complete abandoned stage only while Product Sessions are absent."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerPayloadDebtPlanV1",
            _recovery.preview_complete(_STORAGE, root_fd, attempt_id=attempt_id),
        )


def preview_coding_product_worker_empty_payload_debt(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1:
    """Review only an empty stage with no durable Supervisor claim."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerEmptyPayloadDebtPlanV1",
            _recovery.preview_empty(
                _STORAGE,
                root_fd,
                attempt_id=attempt_id,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def review_coding_product_worker_unmarked_payload_debt(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1:
    """Inspect a nonempty pre-marker stage without granting cleanup authority."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerUnmarkedPayloadDebtReviewV1",
            _recovery.review_unmarked(
                _STORAGE,
                root_fd,
                attempt_id=attempt_id,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def repair_coding_product_worker_unmarked_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerUnmarkedPayloadDebtReviewV1,
) -> CodingWorkerUnmarkedPayloadDebtReviewV1:
    """Remove an exact pre-marker stage under offline, unclaimed authority."""

    if not isinstance(expected_review, CodingWorkerUnmarkedPayloadDebtReviewV1):
        raise TypeError("Coding Worker unmarked payload review is required")
    with (
        _offline(product, require_write=True),
        _STORAGE.open_root(lambda: product.state_root) as root_fd,
    ):
        return cast(
            "CodingWorkerUnmarkedPayloadDebtReviewV1",
            _recovery.repair_unmarked(
                _STORAGE,
                root_fd,
                expected_review=expected_review,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def reopen_coding_product_worker_unmarked_payload_repair(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1 | None:
    """Reopen a published, completed pre-marker cleanup after a process crash."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerUnmarkedPayloadDebtReviewV1 | None",
            _recovery.reopen_unmarked(
                _STORAGE,
                root_fd,
                attempt_id=attempt_id,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def read_coding_product_worker_unmarked_payload_repair_intent(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1 | None:
    """Read a durable cleanup intent even when its exact stage remains."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerUnmarkedPayloadDebtReviewV1 | None",
            _recovery.read_unmarked_intent(
                _STORAGE,
                root_fd,
                attempt_id=attempt_id,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def reopen_coding_product_worker_empty_payload_repair(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1 | None:
    """Read a durable repair result only after its exact stage disappeared."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerEmptyPayloadDebtPlanV1 | None",
            _recovery.reopen_empty(
                _STORAGE,
                root_fd,
                attempt_id=attempt_id,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def list_coding_product_worker_payload_debts(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerPayloadDebtPlanV1, ...]:
    """Enumerate every complete attempt stage under offline Product authority.

    A malformed stage name or body makes the whole inventory unavailable. GC
    and recovery callers must not infer that an unreadable attempt is absent.
    """

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "tuple[CodingWorkerPayloadDebtPlanV1, ...]",
            _recovery.list_complete(_STORAGE, root_fd),
        )


def repair_coding_product_worker_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_plan: CodingWorkerPayloadDebtPlanV1,
) -> CodingWorkerPayloadDebtPlanV1:
    """Delete an exact stage only after its Supervisor recorded process exit."""

    if not isinstance(expected_plan, CodingWorkerPayloadDebtPlanV1):
        raise TypeError("Coding Worker payload debt plan is required")
    with (
        _offline(product, require_write=True),
        _STORAGE.open_root(lambda: product.state_root) as root_fd,
    ):
        return cast(
            "CodingWorkerPayloadDebtPlanV1",
            _recovery.repair_complete(
                _STORAGE,
                root_fd,
                expected_plan=expected_plan,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def reopen_coding_product_worker_payload_repair(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerPayloadDebtPlanV1 | None:
    """Read one completed, exact payload repair without accepting stage debt."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerPayloadDebtPlanV1 | None",
            _recovery.reopen_complete(
                _STORAGE,
                root_fd,
                attempt_id=attempt_id,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def read_coding_product_worker_payload_repair_intent(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerPayloadDebtPlanV1 | None:
    """Read a durable settled cleanup intent while its stage may remain."""

    with _offline(product), _STORAGE.open_root(lambda: product.state_root) as root_fd:
        return cast(
            "CodingWorkerPayloadDebtPlanV1 | None",
            _recovery.read_complete_intent(
                _STORAGE,
                root_fd,
                attempt_id=attempt_id,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def repair_coding_product_worker_empty_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_plan: CodingWorkerEmptyPayloadDebtPlanV1,
) -> CodingWorkerEmptyPayloadDebtPlanV1:
    """Remove an exact empty stage only when Supervisor never claimed it."""

    if not isinstance(expected_plan, CodingWorkerEmptyPayloadDebtPlanV1):
        raise TypeError("Coding Worker empty payload debt plan is required")
    with (
        _offline(product, require_write=True),
        _STORAGE.open_root(lambda: product.state_root) as root_fd,
    ):
        return cast(
            "CodingWorkerEmptyPayloadDebtPlanV1",
            _recovery.repair_empty(
                _STORAGE,
                root_fd,
                expected_plan=expected_plan,
                supervisor=lambda: open_coding_product_worker_supervisor_journal(
                    product
                ),
            ),
        )


def _empty_repair_names(attempt_id: str) -> tuple[str, str]:
    return repair_names(attempt_id, _EMPTY_REPAIR_PREFIX)


_read_repair_file = _STORAGE._read_repair_file


def _read_empty_repair_intent(
    root_fd: int, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1 | None:
    return cast(
        "CodingWorkerEmptyPayloadDebtPlanV1 | None",
        _STORAGE.empty.read(root_fd, attempt_id),
    )


def _publish_empty_repair_intent(
    root_fd: int, plan: CodingWorkerEmptyPayloadDebtPlanV1
) -> None:
    return _STORAGE.empty.publish(root_fd, plan.attempt_id, plan)


def _complete_repair_names(attempt_id: str) -> tuple[str, str]:
    return repair_names(attempt_id, _COMPLETE_REPAIR_PREFIX)


def _read_complete_repair_intent(
    root_fd: int, attempt_id: str
) -> tuple[CodingWorkerPayloadDebtPlanV1, str] | None:
    return cast(
        "tuple[CodingWorkerPayloadDebtPlanV1, str] | None",
        _STORAGE.complete.read(root_fd, attempt_id),
    )


def _publish_complete_repair_intent(
    root_fd: int, plan: CodingWorkerPayloadDebtPlanV1, supervisor_fingerprint: str
) -> None:
    return _STORAGE.complete.publish(
        root_fd, plan.attempt_id, (plan, supervisor_fingerprint)
    )


def _unmarked_repair_fields(
    review: CodingWorkerUnmarkedPayloadDebtReviewV1,
) -> dict[str, object]:
    return unmarked_fields(review)


def _unmarked_repair_names(attempt_id: str) -> tuple[str, str]:
    return repair_names(attempt_id, _UNMARKED_REPAIR_PREFIX)


def _read_unmarked_repair_intent(
    root_fd: int, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1 | None:
    return cast(
        "CodingWorkerUnmarkedPayloadDebtReviewV1 | None",
        _STORAGE.unmarked.read(root_fd, attempt_id),
    )


def _publish_unmarked_repair_intent(
    root_fd: int, review: CodingWorkerUnmarkedPayloadDebtReviewV1
) -> None:
    return _STORAGE.unmarked.publish(root_fd, review.attempt_id, review)


_stage_exists = _STORAGE._stage_exists


_remove_empty_stage = _STORAGE._remove_empty_stage


@contextmanager
def _offline(
    product: PosixLocalWheelProductSessionOwner, *, require_write: bool = False
) -> Iterator[None]:
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
        with product.gc_gate.guard(require_write=require_write):
            yield
        product.assert_root_gc_authority_current()


def _verify_debt(root_fd: int, attempt_id: str) -> CodingWorkerPayloadDebtPlanV1:
    return cast(
        "CodingWorkerPayloadDebtPlanV1", _STORAGE._verify_debt(root_fd, attempt_id)
    )


def _verify_empty_debt(
    root_fd: int, attempt_id: str
) -> CodingWorkerEmptyPayloadDebtPlanV1:
    return cast(
        "CodingWorkerEmptyPayloadDebtPlanV1",
        _STORAGE._verify_empty_debt(root_fd, attempt_id),
    )


def _scan_unmarked_debt(
    root_fd: int, attempt_id: str
) -> CodingWorkerUnmarkedPayloadDebtReviewV1:
    return cast(
        "CodingWorkerUnmarkedPayloadDebtReviewV1",
        _STORAGE._scan_unmarked_debt(root_fd, attempt_id),
    )


_open_unmarked_repair_remainder = _STORAGE._open_unmarked_repair_remainder


_verify_unmarked_repair_file = _STORAGE._verify_unmarked_repair_file


_verify_unmarked_repair_remainder = _STORAGE._verify_unmarked_repair_remainder


_remove_unmarked_repair_remainder = _STORAGE._remove_unmarked_repair_remainder


_verify_debt_file = _STORAGE._verify_debt_file


_verify_complete_repair_remainder = _STORAGE._verify_complete_repair_remainder


_verify_complete_repair_leaf = _STORAGE._verify_complete_repair_leaf


_remove_verified_stage = _STORAGE._remove_verified_stage


_remove_partial_stage = _STORAGE._remove_partial_stage


_require_private_visible_root = _STORAGE._require_private_visible_root


_require_visible_stage = _STORAGE._require_visible_stage
