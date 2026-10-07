"""Fixed Windows Product custody for one LPAC Worker provisioning attempt.

This owner only stores the native bridge's exact attempt history. It grants no
Worker launch, native release approval, or recovery authority by itself.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.worker._native_profile_bridge import (
    _WINDOWS_LPAC_PROFILE_ID,
    _windows_lpac_provisioning_identity,
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
)
from loushang.hosting import observe_windows_worker_job_absent

from .package_product_worker_policy import coding_worker_session_scope_id
from .package_product_worker_windows_launch_intent import (
    _read_intent_under_gc_guard,
)
from .package_product_worker_windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
    WindowsWorkerProvisioningStateJournal,
    inspect_windows_worker_provisioning_attempts,
)


class CodingWindowsProductWorkerProvisioningStateStore:
    """Bind one exact LPAC attempt to the current Product state root."""

    def __init__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
        plan: _WindowsLpacProductWorkerProfilePlan,
    ) -> None:
        if os.name != "nt" or type(product) is not WindowsLocalWheelProductSessionOwner:
            raise OSError("Windows Worker Product provisioning owner is unavailable")
        if (
            type(selected) is not PackageProductSelectedPluginManifestV1
            or type(receipt) is not ProductWorkerActivationReceiptV1
            or type(worker_request) is not ManagedWorkerLaunchRequestV1
            or type(plan) is not _WindowsLpacProductWorkerProfilePlan
        ):
            raise ValueError("Windows Worker Product selection is invalid")
        if (
            type(runtime) is not PackageProductRuntimeBindingV1
            or runtime.product_id != "coding"
            or not runtime.lifecycle.active
            or runtime.session_id != receipt.policy.session_id
            or runtime.product_runtime_id != receipt.policy.product_runtime_id
        ):
            raise ValueError("Windows Worker Product runtime binding is invalid")
        assert runtime.session_id is not None
        session_scope_id = coding_worker_session_scope_id(runtime.session_id)
        product.assert_session_runtime_current(runtime)
        runtime.assert_selected_plugin_manifest_current(selected)
        selected_candidate = verify_product_selected_worker_candidate(
            selected,
            contribution_id=receipt.policy.contribution_id,
            native_platform="windows-amd64",
        )
        candidate = (
            tuple(
                binding
                for binding in product.policy.bindings
                if binding.source_trust_class == "local-worker-candidate"
                and binding.plugin_id == receipt.policy.plugin_id
                and binding.artifact_digest == receipt.policy.plugin_revision_digest
                and binding.worker_admission is not None
                and binding.worker_admission.contribution_id
                == receipt.policy.contribution_id
                and binding.worker_admission.owner_id
                == worker_request.identity.owner_id
                and binding.worker_admission.native_platform == "windows-amd64"
            )
            if type(receipt) is ProductWorkerActivationReceiptV1
            and type(worker_request) is ManagedWorkerLaunchRequestV1
            else ()
        )
        if (
            type(receipt) is not ProductWorkerActivationReceiptV1
            or type(worker_request) is not ManagedWorkerLaunchRequestV1
            or type(plan) is not _WindowsLpacProductWorkerProfilePlan
            or product.policy.product_id != "coding"
            or len(candidate) != 1
            or candidate[0].source_identity
            != selected.snapshot.package_revision.package_source_identity
            or candidate[0].artifact_digest
            != selected.snapshot.root_ref.artifact_digest
            or receipt.policy.product_id != "coding"
            or not receipt.policy.enabled
            or receipt.policy.product_scope_id != session_scope_id
            or receipt.policy.native_profile_id != _WINDOWS_LPAC_PROFILE_ID
            or receipt.policy.native_profile_catalog_revision
            != plan.native_profile_catalog_revision
            or worker_request.identity.product_id != "coding"
            or worker_request.identity.scope_id != session_scope_id
            or worker_request.identity.plugin_id != receipt.policy.plugin_id
            or worker_request.identity.plugin_revision_digest
            != receipt.policy.plugin_revision_digest
            or worker_request.identity.contribution_id != receipt.policy.contribution_id
            or worker_request.identity.owner_generation
            != receipt.policy.owner_selection_generation
            or worker_request.identity.declaration_fingerprint
            != receipt.policy.declaration_fingerprint
            or worker_request.identity.worker_configuration_fingerprint
            != receipt.policy.worker_configuration_fingerprint
            or selected_candidate.plugin_id != receipt.policy.plugin_id
            or selected_candidate.owner_id != worker_request.identity.owner_id
            or selected_candidate.reservation_fingerprint
            != receipt.policy.reservation_fingerprint
            or selected_candidate.declaration_fingerprint
            != receipt.policy.declaration_fingerprint
            or selected_candidate.worker_configuration_fingerprint
            != receipt.policy.worker_configuration_fingerprint
            or selected_candidate.executable_digest
            != worker_request.runtime.executable_digest
            or selected_candidate.executable_size
            != worker_request.runtime.executable_size
            or plan.worker_request_fingerprint != worker_request.fingerprint
            or plan.expected_native_policy_closure_fingerprint
            != receipt.policy.expected_native_policy_closure_fingerprint
        ):
            raise ValueError("Windows Worker Product provisioning binding is invalid")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard():
            self._require_launch_intent(
                product, receipt=receipt, worker_request=worker_request
            )
        identity = _windows_lpac_provisioning_identity(
            receipt=receipt,
            worker_request=worker_request,
            plan=plan,
        )
        attempt_id = worker_request.identity.attempt_id
        self._product = product
        self._runtime = runtime
        self._selected = selected
        self._receipt = receipt
        self._worker_request = worker_request
        self._journal = WindowsWorkerProvisioningStateJournal(
            product.state_root / f"worker-native-provisioning-{attempt_id}.jsonl",
            identity=identity,
        )
        product.assert_root_gc_authority_current()

    @property
    def path(self) -> Path:
        return self._journal.path

    @staticmethod
    def _require_launch_intent(
        product: WindowsLocalWheelProductSessionOwner,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
    ) -> None:
        intent = _read_intent_under_gc_guard(
            product, worker_request.identity.attempt_id
        )
        if (
            intent is None
            or intent.receipt_fingerprint != receipt.fingerprint
            or intent.request_fingerprint != worker_request.fingerprint
            or intent.identity_fingerprint != worker_request.identity.fingerprint
            or intent.runtime_fingerprint != worker_request.runtime.fingerprint
            or intent.payload_digest != worker_request.runtime.executable_digest
            or intent.stage_identity
            != (
                worker_request.runtime.cwd_device,
                worker_request.runtime.cwd_inode,
            )
            or intent.owner_id != worker_request.identity.owner_id
            or intent.supervisor_epoch != worker_request.identity.supervisor_epoch
        ):
            raise ValueError("Windows Worker Product launch intent is invalid")

    def load(self) -> Mapping[str, object] | None:
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            self._require_launch_intent(
                self._product,
                receipt=self._receipt,
                worker_request=self._worker_request,
            )
            self._product.assert_session_runtime_current(self._runtime)
            self._require_store_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                current = self._journal.load(directory_fd=root)
            self._product.assert_root_gc_authority_current()
            return current

    def compare_and_swap(
        self, *, expected_revision: int, document: Mapping[str, object]
    ) -> bool:
        with self._product.gc_gate.guard(require_write=True):
            self._product.assert_root_gc_authority_current()
            self._require_launch_intent(
                self._product,
                receipt=self._receipt,
                worker_request=self._worker_request,
            )
            self._product.assert_session_runtime_current(self._runtime)
            self._require_store_current()
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                committed = self._journal.compare_and_swap(
                    expected_revision=expected_revision,
                    document=document,
                    directory_fd=root,
                )
            self._product.assert_root_gc_authority_current()
            return committed

    def _require_store_current(self) -> None:
        try:
            self._runtime.assert_selected_plugin_manifest_current(self._selected)
            self._worker_request.validate_current()
            return
        except (PackageProductRuntimeReadError, WorkerBindingError) as stale:
            # Disable or update invalidates Product selection, and a stopped
            # Supervisor invalidates the launch request. Only the same exact
            # terminal attempt may finish native cleanup after process exit.
            from .package_product_worker_windows_recovery_inventory import (
                _current_after_verified_retirements_under_gc_guard,
                _inspect_windows_worker_recovery_inventory_under_gc_guard,
                require_coding_windows_worker_terminal_cleanup_attempt,
            )

            try:
                inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(
                    self._product
                )
                inventory = _current_after_verified_retirements_under_gc_guard(
                    self._product,
                    inventory,
                    attempt_id=self._worker_request.identity.attempt_id,
                )
                job_name = require_coding_windows_worker_terminal_cleanup_attempt(
                    inventory,
                    attempt_id=self._worker_request.identity.attempt_id,
                    payload_directory_identity=(
                        self._worker_request.runtime.cwd_device,
                        self._worker_request.runtime.cwd_inode,
                    ),
                    request_fingerprint=self._worker_request.fingerprint,
                    receipt_fingerprint=self._receipt.fingerprint,
                    identity_fingerprint=self._worker_request.identity.fingerprint,
                )
                self._worker_request.runtime.verify()
                if observe_windows_worker_job_absent(job_name) is not True:
                    raise ValueError("Windows Worker Job is still present")
            except (OSError, RuntimeError, ValueError) as error:
                raise stale from error


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

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise OSError("Windows Worker Product recovery inventory is unavailable")
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            attempts = inspect_windows_worker_provisioning_attempts(
                product.state_root, directory_fd=root
            )
        product.assert_root_gc_authority_current()
        return attempts


__all__ = [
    "CodingWindowsProductWorkerProvisioningStateStore",
    "inspect_coding_windows_product_worker_provisioning_attempts",
    "open_coding_windows_product_worker_provisioning_state_store",
]
