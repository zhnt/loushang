"""Fixed Windows Product custody for one LPAC Worker provisioning attempt.

This owner only stores the native bridge's exact attempt history. It grants no
Worker launch, native release approval, or recovery authority by itself.
"""

from __future__ import annotations

import os
from typing import cast

from loushang.coding.harness.worker.windows_admission import is_windows_product
from loushang.harness.package_product._worker_windows_attempt import (
    WindowsProductWorkerPayload,
    WindowsProductWorkerProvisioningAccess,
    WindowsWorkerLaunchPayload,
    read_windows_product_worker_attempts,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.worker._native_profile_bridge import (
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
)
from loushang.harness.worker.history._windows_recovery import WindowsRecoveryAttemptV1
from loushang.harness.worker.payload._selected_payload import _PendingPayload
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)

from .product_worker_policy import coding_worker_session_scope_id
from .product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
    WindowsWorkerProvisioningStateJournal,
    inspect_windows_worker_provisioning_attempts,
)


class CodingWindowsProductWorkerProvisioningStateStore(
    WindowsProductWorkerProvisioningAccess
):
    """Bind one exact LPAC attempt to the current Product state root."""

    _product_id = "coding"
    _provisioning_journal_type = WindowsWorkerProvisioningStateJournal
    _session_scope_id = staticmethod(coding_worker_session_scope_id)

    _read_launch_intent = staticmethod(_read_intent_under_gc_guard)

    def _recovery_payload(
        self,
    ) -> WindowsProductWorkerPayload[
        WindowsWorkerLaunchPayload, _PendingPayload, WindowsRecoveryAttemptV1
    ]:
        from .product_worker_windows_payload import _PAYLOAD_PROGRAM

        return cast(
            "WindowsProductWorkerPayload[WindowsWorkerLaunchPayload, _PendingPayload, WindowsRecoveryAttemptV1]",
            _PAYLOAD_PROGRAM,
        )


def open_coding_windows_product_worker_provisioning_state_store(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    runtime: PackageProductRuntimeBindingV1,
    selected: PackageProductSelectedPluginManifestV1,
    receipt: ProductWorkerActivationReceiptV1,
    worker_request: ManagedWorkerLaunchRequestV1,
    plan: _WindowsLpacProductWorkerProfilePlan,
) -> CodingWindowsProductWorkerProvisioningStateStore:
    """Open the sole Product-fixed state store for this exact native attempt."""

    return CodingWindowsProductWorkerProvisioningStateStore(
        product,
        runtime=runtime,
        selected=selected,
        receipt=receipt,
        worker_request=worker_request,
        plan=plan,
    )


def inspect_coding_windows_product_worker_provisioning_attempts(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[WindowsWorkerProvisioningAttemptV1, ...]:
    """Reopen all LPAC attempt histories for Product-owned recovery review."""

    if not is_windows_product(
        product, "coding", os.name, WindowsLocalWheelProductSessionOwner
    ):
        raise OSError("Windows Worker Product recovery inventory is unavailable")
    return read_windows_product_worker_attempts(
        product,
        inspect_attempts=lambda state_root, root: (
            inspect_windows_worker_provisioning_attempts(state_root, directory_fd=root)
        ),
    )


__all__ = [
    "CodingWindowsProductWorkerProvisioningStateStore",
    "inspect_coding_windows_product_worker_provisioning_attempts",
    "open_coding_windows_product_worker_provisioning_state_store",
]
