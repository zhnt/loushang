"""Product-owned Windows Worker receipt issuance for one selected Session."""

from __future__ import annotations

import os
from typing import cast

from loushang.harness.package_product._windows_worker_backend_release import (
    _WindowsBackendInstalledMethods,
)
from loushang.harness.package_product._worker_product_authority import (
    _capture_selected_worker_session_file,
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
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .package_product_worker_discovery import CodingWorkerTranscriptDiscoveryReader
from .package_product_worker_policy import (
    CodingWorkerPolicySelectionError,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptError,
    CodingWorkerReceiptRecordV1,
    CodingWorkerSelectedPayloadV1,
    CodingWorkerSessionDiscoveryReadPort,
    _CodingWorkerReceiptAuthority,
)
from .package_product_worker_windows_installed_backend import (
    CodingWindowsWorkerInstalledBackendError,
    CodingWindowsWorkerInstalledBackendReader,
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_opt_in_owner import (
    CodingWindowsWorkerProductOptInOwner,
)
from .package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from .session_manager import SessionManager


class CodingWindowsWorkerProductReceiptOwner(
    _WindowsWorkerProductReceiptAuthority[
        CodingWorkerReceiptRecordV1, CodingWorkerSelectedPayloadV1
    ],
    _CodingWorkerReceiptAuthority,
):
    """Keep original admission/data construction; all fixed custody is Core."""

    _stale_derivation_errors = (
        CodingWorkerPolicySelectionError,
        CodingWorkerReceiptError,
        CodingWindowsWorkerInstalledBackendError,
        PackageProductRuntimeActivationError,
        PackageProductRuntimeReadError,
        OSError,
        ValueError,
    )

    def __init__(
        self,
        *,
        product: WindowsLocalWheelProductSessionOwner,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
        session_discovery_reader: CodingWorkerSessionDiscoveryReadPort | None = None,
    ) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or type(runtime) is not PackageProductRuntimeBindingV1
            or type(selected) is not PackageProductSelectedPluginManifestV1
            or product.policy.product_id != "coding"
            or runtime.product_id != "coding"
            or runtime.session_id is None
            or runtime.product_runtime_id is None
            or selected.snapshot.installation_key.scope_id
            != product.policy.project_scope_id
            or (
                session_discovery_reader is not None
                and (
                    getattr(session_discovery_reader, "gc_gate", None)
                    is not product.gc_gate
                    or getattr(session_discovery_reader, "session_id", None)
                    != runtime.session_id
                    or not callable(
                        getattr(session_discovery_reader, "current_discovery", None)
                    )
                )
            )
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product.policy.bindings
            )
        ):
            raise ValueError("Windows Worker Product receipt owners changed")
        product.assert_session_runtime_current(runtime)
        runtime.assert_selected_plugin_manifest_current(selected)
        self._product: WindowsLocalWheelProductSessionOwner = product
        self._runtime = runtime
        self._selected = selected
        self._opt_in: CodingWindowsWorkerProductOptInOwner = (
            CodingWindowsWorkerProductOptInOwner(product)
        )
        self._native = CodingWindowsWorkerInstalledBackendReader(product)
        self._session_discovery_reader = session_discovery_reader
        self._journal = CodingWindowsWorkerReceiptJournal(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
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

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> CodingWorkerSelectedPayloadV1:
        """Read verified Windows PE bytes from the current Product selection."""

        return super().current_selected_payload(receipt)

    def current_payload_and_worker_owner_id(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[CodingWorkerSelectedPayloadV1, str]:
        """Capture payload and owner in one Product read with two full rechecks.

        Each witness verifies the complete installed backend. The selected
        root is captured between them; the final witness rechecks receipt and
        opt-in authority before either value is returned.
        """

        return super().current_payload_and_worker_owner_id(receipt)


def open_coding_windows_product_selected_worker_receipt_owner(
    *,
    product_owner: WindowsLocalWheelProductSessionOwner,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    transcript_directory: AgentTranscriptDirectoryRuntime,
    session_manager: SessionManager,
    active_session: bool = False,
) -> CodingWindowsWorkerProductReceiptOwner:
    """Bind an exact selected Windows Worker to its persisted Coding Session."""

    if type(product_owner) is not WindowsLocalWheelProductSessionOwner:
        raise TypeError("Windows Worker requires a Product owner")
    if type(runtime) is not PackageProductRuntimeBindingV1:
        raise TypeError("Windows Worker requires an active Product runtime")
    if (
        not isinstance(plugin_id, str)
        or not plugin_id
        or plugin_id != plugin_id.strip()
    ):
        raise ValueError("Windows Worker Plugin identity is invalid")
    if not isinstance(transcript_directory, AgentTranscriptDirectoryRuntime):
        raise TypeError("Windows Worker requires a Transcript directory owner")
    if not isinstance(session_manager, SessionManager):
        raise TypeError("Windows Worker requires a Coding Session owner")
    selected_session_file = _capture_selected_worker_session_file(
        session_manager=session_manager,
        transcript_directory=transcript_directory,
        runtime=runtime,
        product_owner=product_owner,
        invalid_owner="Windows Worker selected Session owner changed",
    )
    product_owner.assert_session_runtime_current(runtime)
    selected = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
    )
    discovery = CodingWorkerTranscriptDiscoveryReader(
        directory=transcript_directory,
        gc_gate=product_owner.gc_gate,
        session_id=cast(str, runtime.session_id),
        selected_session_file=selected_session_file,
        attached_session=session_manager if active_session else None,
    )
    return CodingWindowsWorkerProductReceiptOwner(
        product=product_owner,
        runtime=runtime,
        selected=selected,
        session_discovery_reader=discovery,
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
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        journal = CodingWindowsWorkerReceiptJournal(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        )
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            records = journal.records(directory_fd=root)
        return next(
            (
                record
                for record in records
                if record.receipt.fingerprint == receipt_fingerprint
            ),
            None,
        )


__all__ = [
    "CodingWindowsWorkerProductReceiptOwner",
    "open_coding_windows_product_selected_worker_receipt_owner",
    "read_coding_windows_product_worker_receipt_record",
]
