"""Private, attempt-scoped Linux payload copy for a selected Coding Worker.

The Product Store keeps every file non-executable. This owner copies only the
freshly verified Worker executable into a private 0500 file for Hosting's
descriptor-sealing capture. A context exit removes the copy; a crash leaves
an exact attempt name as debt and a replay refuses to reuse it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    PosixProductWorkerPayloadCustody,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.contracts import (
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
)
from loushang.harness.worker.payload._records import (
    EmptyPayloadPlanMethods,
    PayloadMemberMethods,
    PayloadPlanMethods,
    PayloadReviewMethods,
    PayloadValueTypes,
)
from loushang.harness.worker.payload._records import (
    plan_fields as plan_fields,
)
from loushang.harness.worker.payload._records import (
    unmarked_fields as unmarked_fields,
)
from loushang.harness.worker.payload._selected_payload import (
    PendingPayloadMethods,
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
from loushang.harness.worker.payload._storage import PayloadStorage

from .product_worker_installed_native import CodingWorkerNativeLaunchMaterialV1
from .product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    CodingWorkerReceiptError,
)
from .product_worker_supervisor_journal import CodingProductWorkerSupervisorJournal


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
class CodingProductWorkerPendingLaunchV1(PendingPayloadMethods):
    """No-effect identity pinned before asynchronous Worker preparation."""

    receipt_fingerprint: str
    identity: WorkerLaunchIdentityV1
    _pending_exact_identity = False
    _pending_invalid_message = "Coding Worker pending launch identity is invalid"


def open_coding_product_worker_supervisor_journal(
    product: PosixLocalWheelProductSessionOwner,
) -> CodingProductWorkerSupervisorJournal:
    """Bind every Coding Worker attempt to this Product's durable state root."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    product.assert_root_gc_authority_current()
    return CodingProductWorkerSupervisorJournal(product)


@dataclass(frozen=True, slots=True)
class CodingWorkerPayloadDebtPlanV1(PayloadPlanMethods):
    """Exact complete stage accepted for offline deletion."""

    attempt_id: str
    entrypoint: str
    payload_digest: str
    payload_size: int
    receipt_fingerprint: str
    stage_device: int
    stage_inode: int
    _invalid_message = "Coding Worker payload debt plan is invalid"


@dataclass(frozen=True, slots=True)
class CodingWorkerEmptyPayloadDebtPlanV1(EmptyPayloadPlanMethods):
    """An empty pre-marker stage for an attempt never claimed by Supervisor."""

    attempt_id: str
    stage_device: int
    stage_inode: int
    _invalid_message = "Coding Worker empty payload debt plan is invalid"


@dataclass(frozen=True, slots=True)
class CodingWorkerUnmarkedPayloadMemberV1(PayloadMemberMethods):
    """One no-follow member of an incomplete, single-path Product stage."""

    relative_path: str
    kind: str
    device: int
    inode: int
    mode: int
    size: int
    digest: str | None
    _invalid_message = "Coding Worker unmarked payload member is invalid"


@dataclass(frozen=True, slots=True)
class CodingWorkerUnmarkedPayloadDebtReviewV1(PayloadReviewMethods):
    """Exact tree evidence; cleanup needs a separate durable intent."""

    attempt_id: str
    stage_device: int
    stage_inode: int
    members: tuple[CodingWorkerUnmarkedPayloadMemberV1, ...]
    _invalid_message = "Coding Worker unmarked payload review is invalid"
    _invalid_member_message = "Coding Worker unmarked payload member is invalid"
    _chain_changed_message = "Coding Worker unmarked payload chain changed"
    _member_type = CodingWorkerUnmarkedPayloadMemberV1
    _maximum_depth = staticmethod(lambda: _MAX_UNMARKED_DEPTH)
    _maximum_path_bytes = staticmethod(lambda: _MAX_UNMARKED_PATH_BYTES)


@dataclass(frozen=True, slots=True)
class CodingWorkerPayloadRecoveryReviewV1:
    """Offline facts for one debt; only a stopped attempt records process wait."""

    plan: CodingWorkerPayloadDebtPlanV1
    attempt_record: WorkerAttemptRecordV1 | None

    @property
    def process_wait_recorded(self) -> bool:
        return self.attempt_record is not None and self.attempt_record.process_settled


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


_read_repair_file = _STORAGE._read_repair_file


_stage_exists = _STORAGE._stage_exists


_remove_empty_stage = _STORAGE._remove_empty_stage


class _CodingPosixPayloadCustody(
    PosixProductWorkerPayloadCustody[
        CodingWorkerPayloadDebtPlanV1,
        CodingWorkerEmptyPayloadDebtPlanV1,
        CodingWorkerUnmarkedPayloadDebtReviewV1,
        CodingWorkerPayloadRecoveryReviewV1,
        CodingProductWorkerPayloadLeaseV1,
        CodingProductWorkerPendingLaunchV1,
    ]
):
    __slots__ = ()
    _entry_receipt_owner_type = CodingWorkerProductReceiptOwner
    _entry_label = "Coding Worker"


_PAYLOAD_CUSTODY = _CodingPosixPayloadCustody(
    storage=_STORAGE,
    supervisor=open_coding_product_worker_supervisor_journal,
    recovery_type=CodingWorkerPayloadRecoveryReviewV1,
    lease_type=CodingProductWorkerPayloadLeaseV1,
    pending_type=CodingProductWorkerPendingLaunchV1,
    receipt_error_type=CodingWorkerReceiptError,
    error_prefix="coding_worker_payload",
    stale_message="Coding Product Worker selection changed",
    product_required_message="Coding Worker Product owner is required",
)

materialize_coding_product_worker_payload = _PAYLOAD_CUSTODY.materialize
plan_coding_product_worker_pending_launch = _PAYLOAD_CUSTODY.plan
bind_coding_product_worker_launch_request = _PAYLOAD_CUSTODY.bind
repair_coding_product_worker_unmarked_payload_debt = _PAYLOAD_CUSTODY.repair_unmarked
repair_coding_product_worker_payload_debt = _PAYLOAD_CUSTODY.repair_complete
repair_coding_product_worker_empty_payload_debt = _PAYLOAD_CUSTODY.repair_empty


_offline = _PAYLOAD_CUSTODY.offline


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


review_coding_product_worker_payload_recovery = _PAYLOAD_CUSTODY.review_complete
preview_coding_product_worker_payload_debt = _PAYLOAD_CUSTODY.preview_complete
preview_coding_product_worker_empty_payload_debt = _PAYLOAD_CUSTODY.preview_empty
review_coding_product_worker_unmarked_payload_debt = _PAYLOAD_CUSTODY.review_unmarked
reopen_coding_product_worker_unmarked_payload_repair = _PAYLOAD_CUSTODY.reopen_unmarked
read_coding_product_worker_unmarked_payload_repair_intent = (
    _PAYLOAD_CUSTODY.read_unmarked_intent
)
reopen_coding_product_worker_empty_payload_repair = _PAYLOAD_CUSTODY.reopen_empty
list_coding_product_worker_payload_debts = _PAYLOAD_CUSTODY.list_complete
reopen_coding_product_worker_payload_repair = _PAYLOAD_CUSTODY.reopen_complete
read_coding_product_worker_payload_repair_intent = _PAYLOAD_CUSTODY.read_complete_intent
