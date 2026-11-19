"""Product-owned Windows Worker receipt issuance for one selected Session."""

from __future__ import annotations

import os

from loushang.coding.session.manager import SessionManager
from loushang.harness.package_product._windows_worker_backend_release import (
    _WindowsBackendInstalledMethods,
)
from loushang.harness.package_product._worker_product_authority import (
    _WindowsWorkerProductReceiptAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)

from .product_worker_discovery import CodingWorkerTranscriptDiscoveryReader
from .product_worker_policy import CodingWorkerPolicySelectionError
from .product_worker_receipt import (
    CodingWorkerReceiptError,
    CodingWorkerReceiptRecordV1,
    CodingWorkerSelectedPayloadV1,
    CodingWorkerSessionDiscoveryReadPort,
    _CodingWorkerReceiptAuthority,
)
from .product_worker_windows_installed_backend import (
    CodingWindowsWorkerInstalledBackendError,
    CodingWindowsWorkerInstalledBackendReader,
    read_coding_windows_worker_installed_backend_release,
)
from .product_worker_windows_opt_in_owner import CodingWindowsWorkerProductOptInOwner
from .product_worker_windows_receipt_journal import CodingWindowsWorkerReceiptJournal


class CodingWindowsWorkerProductReceiptOwner(
    _WindowsWorkerProductReceiptAuthority[
        CodingWorkerReceiptRecordV1, CodingWorkerSelectedPayloadV1
    ],
    _CodingWorkerReceiptAuthority,
):
    """Keep original admission/data construction; all fixed custody is Core."""

    _receipt_factory_label = "Windows Worker"
    _receipt_session_type = staticmethod(lambda: SessionManager)
    _receipt_discovery_type = staticmethod(
        lambda: CodingWorkerTranscriptDiscoveryReader
    )

    _stale_derivation_errors = (
        CodingWorkerPolicySelectionError,
        CodingWorkerReceiptError,
        CodingWindowsWorkerInstalledBackendError,
        PackageProductRuntimeActivationError,
        PackageProductRuntimeReadError,
        OSError,
        ValueError,
    )

    _opt_in: CodingWindowsWorkerProductOptInOwner
    _receipt_source_trust_class = "local-worker-candidate"
    _receipt_opt_in_factory = staticmethod(CodingWindowsWorkerProductOptInOwner)
    _receipt_native_factory = staticmethod(CodingWindowsWorkerInstalledBackendReader)
    _receipt_journal_factory = staticmethod(CodingWindowsWorkerReceiptJournal)

    def __init__(
        self,
        *,
        product: WindowsLocalWheelProductSessionOwner,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
        session_discovery_reader: CodingWorkerSessionDiscoveryReadPort | None = None,
    ) -> None:
        _WindowsWorkerProductReceiptAuthority._initialize_receipt_owner(
            self,
            product=product,
            runtime=runtime,
            selected=selected,
            session_discovery_reader=session_discovery_reader,
        )

    def latch_kill_switch(self, *, expected_generation: int) -> int:
        """Persist a Windows opt-in revocation before C5 retires its domain."""
        return self._latch_kill_switch(
            expected_generation=expected_generation,
            invalid_generation_message="Windows Worker kill-switch generation is invalid",
            revoke=lambda plugin_id, operation_id, decision: self._opt_in.revoke(
                plugin_id=plugin_id,
                operation_id=operation_id,
                expected_generation=decision.generation,
            ),
        )

    def _read_backend(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> _WindowsBackendInstalledMethods:
        return read_coding_windows_worker_installed_backend_release(product)


open_coding_windows_product_selected_worker_receipt_owner = (
    CodingWindowsWorkerProductReceiptOwner._open_selected
)


def read_coding_windows_product_worker_receipt_record(
    product: WindowsLocalWheelProductSessionOwner, *, receipt_fingerprint: str
) -> CodingWorkerReceiptRecordV1 | None:
    """Read an exact persisted Product receipt without a Session runtime."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or type(receipt_fingerprint) is not str
        or len(receipt_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in receipt_fingerprint)
    ):
        raise ValueError("Windows Worker receipt lookup is invalid")
    return CodingWindowsWorkerProductReceiptOwner._read_retained_receipt(
        product, receipt_fingerprint=receipt_fingerprint
    )


__all__ = [
    "CodingWindowsWorkerProductReceiptOwner",
    "open_coding_windows_product_selected_worker_receipt_owner",
    "read_coding_windows_product_worker_receipt_record",
]
