"""Product-owned Windows Worker PE materialization for one retained attempt.

The stage and marker are durable debt. This module neither starts a Worker nor
deletes a stage; native Job, Supervisor, and Package lease settlement must be
joined by a separate recovery owner before retirement is possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from loushang.harness.package_product._worker_windows_attempt import (
    WindowsProductWorkerPayload,
    verify_windows_product_worker_live_stage,
)
from loushang.harness.worker.contracts import (
    WorkerBindingError,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker.journal import WorkerSupervisorJournalError
from loushang.harness.worker.payload._selected_payload import (
    PendingPayloadMethods,
    worker_identity_from_receipt,
)
from loushang.harness.worker.payload._windows_stage_io import (
    require_payload_root,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .package_product_worker_receipt import CodingWorkerReceiptError
from .package_product_worker_windows_installed_backend import (
    CodingWindowsWorkerInstalledBackendError,
)
from .package_product_worker_windows_payload_inventory import (
    CodingWindowsWorkerPayloadInventoryError,
    inspect_windows_worker_payload_stages,
)
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningStateJournalError,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)
from .package_product_worker_windows_recovery_inventory import (
    _RECOVERY_ADMISSION,
    CodingWindowsWorkerRecoveryAttemptV1,
    _current_after_verified_retirements_under_gc_guard,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)

_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_RETAINED_ATTEMPTS = 1024
_MARKER = "worker-payload.json"


class CodingWindowsWorkerPayloadMaterializationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPayloadLeaseV1:
    """Physical input only; it grants no Worker start or recovery authority."""

    attempt_id: str
    runtime: WorkerRuntimeBindingV1
    receipt_fingerprint: str
    payload_digest: str
    owner_id: str
    stage_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class CodingWindowsProductWorkerPendingLaunchV1(PendingPayloadMethods):
    """Product-checked identity held before Windows payload materialization."""

    receipt_fingerprint: str
    identity: WorkerLaunchIdentityV1
    _pending_exact_identity = True
    _pending_invalid_message = "Windows Worker pending launch identity is invalid"


_windows_worker_identity = worker_identity_from_receipt


def _verify_stage_marker(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: CodingWindowsWorkerPayloadLeaseV1,
    entrypoint: str,
    initial: bool,
) -> None:
    verify_windows_product_worker_live_stage(
        receipt_owner.product_owner,
        receipt=receipt,
        payload_lease=payload_lease,
        runtime=payload_lease.runtime,
        entrypoint=entrypoint,
        initial=initial,
        marker_name=_MARKER,
        error_type=CodingWindowsWorkerPayloadMaterializationError,
        error_prefix="coding_worker_payload",
    )


_require_root = partial(
    require_payload_root,
    error_type=CodingWindowsWorkerPayloadMaterializationError,
    error_prefix="coding_worker_payload",
)


__all__ = [
    "CodingWindowsProductWorkerPendingLaunchV1",
    "CodingWindowsWorkerPayloadLeaseV1",
    "CodingWindowsWorkerPayloadMaterializationError",
    "bind_coding_windows_product_worker_launch_request",
    "materialize_coding_windows_product_worker_payload",
    "plan_coding_windows_product_worker_pending_launch",
]


def _payload_limits() -> tuple[int, int]:
    return _MAX_PAYLOAD_BYTES, _MAX_RETAINED_ATTEMPTS


_PAYLOAD_PROGRAM: WindowsProductWorkerPayload[
    CodingWindowsWorkerPayloadLeaseV1,
    CodingWindowsProductWorkerPendingLaunchV1,
    CodingWindowsWorkerRecoveryAttemptV1,
] = WindowsProductWorkerPayload(
    receipt_owner_type=CodingWindowsWorkerProductReceiptOwner,
    lease_type=CodingWindowsWorkerPayloadLeaseV1,
    pending_type=CodingWindowsProductWorkerPendingLaunchV1,
    inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
    current_attempts=_current_after_verified_retirements_under_gc_guard,
    inspect_payload=inspect_windows_worker_payload_stages,
    supervisor_journal=open_coding_windows_product_worker_supervisor_journal,
    admission=_RECOVERY_ADMISSION,
    limits=_payload_limits,
    marker_name=_MARKER,
    error_type=CodingWindowsWorkerPayloadMaterializationError,
    error_prefix="coding_worker_payload",
    stale_errors=(
        CodingWorkerReceiptError,
        CodingWindowsWorkerInstalledBackendError,
        CodingWindowsWorkerPayloadMaterializationError,
        CodingWindowsWorkerPayloadInventoryError,
        WindowsWorkerProvisioningStateJournalError,
        WorkerSupervisorJournalError,
        WorkerBindingError,
        OSError,
        ValueError,
    ),
    stale_message="Coding Windows Product Worker selection changed",
)


plan_coding_windows_product_worker_pending_launch = _PAYLOAD_PROGRAM.plan
materialize_coding_windows_product_worker_payload = _PAYLOAD_PROGRAM.materialize
bind_coding_windows_product_worker_launch_request = _PAYLOAD_PROGRAM.bind
