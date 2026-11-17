"""Product-owned Windows Worker PE materialization for one retained attempt.

The stage and marker are durable debt. This module neither starts a Worker nor
deletes a stage; native Job, Supervisor, and Package lease settlement must be
joined by a separate recovery owner before retirement is possible.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import partial

from loushang.harness.package_product._worker_windows_attempt import (
    WindowsProductWorkerPayload,
    verify_windows_product_worker_live_stage,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
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

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
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


def plan_coding_windows_product_worker_pending_launch(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
) -> CodingWindowsProductWorkerPendingLaunchV1:
    """Pin a current Windows Worker identity before any payload or process."""
    if (
        os.name != "nt"
        or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(receipt) is not ProductWorkerActivationReceiptV1
        or (type(attempt_id) is not str)
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise ValueError("Windows Worker pending launch request is invalid")
    return _payload_program().plan(
        receipt_owner=receipt_owner, receipt=receipt, attempt_id=attempt_id
    )


def materialize_coding_windows_product_worker_payload(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
) -> CodingWindowsWorkerPayloadLeaseV1:
    """Copy one current selected PE to a fresh, Product-private attempt stage.

    A failure after directory creation deliberately leaves all bytes in place
    as recovery debt. Retrying the same attempt ID never overwrites them.
    """
    if (
        os.name != "nt"
        or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(receipt) is not ProductWorkerActivationReceiptV1
        or (type(attempt_id) is not str)
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise ValueError("Windows Worker payload request is invalid")
    return _payload_program().materialize(
        receipt_owner=receipt_owner, receipt=receipt, attempt_id=attempt_id
    )


_windows_worker_identity = worker_identity_from_receipt


def bind_coding_windows_product_worker_launch_request(
    *,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    payload_lease: CodingWindowsWorkerPayloadLeaseV1,
    supervisor_epoch: int,
    pending_launch: CodingWindowsProductWorkerPendingLaunchV1 | None = None,
) -> ManagedWorkerLaunchRequestV1:
    """Build an exact request for a staged PE; no process effect occurs here."""
    if (
        os.name != "nt"
        or type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(receipt) is not ProductWorkerActivationReceiptV1
        or (type(payload_lease) is not CodingWindowsWorkerPayloadLeaseV1)
    ):
        raise CodingWindowsWorkerPayloadMaterializationError(
            "coding_worker_payload_binding_mismatch"
        )
    return _payload_program().bind(
        receipt_owner=receipt_owner,
        receipt=receipt,
        payload_lease=payload_lease,
        supervisor_epoch=supervisor_epoch,
        pending_launch=pending_launch,
    )


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


def _payload_program() -> WindowsProductWorkerPayload[
    CodingWindowsWorkerPayloadLeaseV1,
    CodingWindowsProductWorkerPendingLaunchV1,
    CodingWindowsWorkerRecoveryAttemptV1,
]:
    return WindowsProductWorkerPayload(
        lease_type=CodingWindowsWorkerPayloadLeaseV1,
        pending_type=CodingWindowsProductWorkerPendingLaunchV1,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        current_attempts=_current_after_verified_retirements_under_gc_guard,
        inspect_payload=inspect_windows_worker_payload_stages,
        supervisor_journal=open_coding_windows_product_worker_supervisor_journal,
        admission=_RECOVERY_ADMISSION,
        limits=lambda: (_MAX_PAYLOAD_BYTES, _MAX_RETAINED_ATTEMPTS),
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
