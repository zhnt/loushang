"""Product facts and source selection for ordinary Worker preparation.

These adapters borrow existing owners. They do not schedule, publish a graph,
hold cleanup state, or implement another filesystem/process backend.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import ClassVar, cast

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import ResolvedCapabilityProvider
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.session._worker_provider import _QueryAuthority
from loushang.harness.worker._native_profile_bridge import (
    ProductWorkerNativeProfilePort,
    _bind_posix_static_contained_product_worker_profile,
    _WindowsLpacProductWorkerProfilePlan,
    _WindowsLpacProvisioningStateStore,
)
from loushang.harness.worker._ordinary_prepare import _Gate
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerBindingV1,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.journal import WorkerSupervisorJournal
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationReceiptV1,
    _ActivationStateStore,
)

from .package_product_worker_activation_state import (
    open_coding_product_worker_activation_state_store,
    open_coding_windows_product_worker_activation_state_store,
)
from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_installed_native import CodingWorkerNativeLaunchMaterialV1
from .package_product_worker_payload import (
    CodingProductWorkerPayloadLeaseV1,
    CodingProductWorkerPendingLaunchV1,
    bind_coding_product_worker_launch_request,
    materialize_coding_product_worker_payload,
    open_coding_product_worker_supervisor_journal,
)
from .package_product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    prepare_coding_selected_worker_provider_candidate,
)
from .package_product_worker_provider_host import (
    _read_coding_worker_provider_inputs,
)
from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_FACET_ID,
    bind_coding_worker_query_facet_owner,
)
from .package_product_worker_receipt import CodingWorkerProductReceiptOwner
from .package_product_worker_start_gate import CodingProductWorkerStartGate
from .package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_windows_launch_intent import (
    commit_coding_windows_product_worker_launch_intent,
)
from .package_product_worker_windows_payload import (
    CodingWindowsProductWorkerPendingLaunchV1,
    CodingWindowsWorkerPayloadLeaseV1,
    bind_coding_windows_product_worker_launch_request,
    materialize_coding_windows_product_worker_payload,
)
from .package_product_worker_windows_provisioning import (
    open_coding_windows_product_worker_provisioning_state_store,
)
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)


class _PosixSelectedWorkerSource:
    """Shared selected facts for ordinary and operator Product adapters."""

    __slots__ = ()
    receipt_owner: CodingWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1

    def materialize(
        self, attempt_id: str
    ) -> AbstractContextManager[CodingProductWorkerPayloadLeaseV1]:
        return materialize_coding_product_worker_payload(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            attempt_id=attempt_id,
        )

    def _profile_from_material(
        self,
        native: CodingWorkerNativeLaunchMaterialV1,
        request: ManagedWorkerLaunchRequestV1,
        gate: _Gate,
    ) -> ProductWorkerNativeProfilePort:
        return _bind_posix_static_contained_product_worker_profile(
            receipt=self.receipt,
            worker_request=request,
            native_profile_catalog_revision=native.closure.native_profile_catalog_revision,
            launcher_path=native.launcher_path,
            launcher_sha256=native.closure.containment_launcher_digest,
            containment_profile_sha256=native.closure.containment_profile_digest,
            start_gate_read_fd=gate.start_gate_read_fd,
        )


@dataclass(frozen=True, slots=True)
class _PosixLaunchInputs(_PosixSelectedWorkerSource):
    receipt_owner: CodingWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    pending_launch: CodingProductWorkerPendingLaunchV1

    def bind_request(
        self, payload: CodingProductWorkerPayloadLeaseV1
    ) -> ManagedWorkerLaunchRequestV1:
        return bind_coding_product_worker_launch_request(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            payload_lease=payload,
            supervisor_epoch=self.pending_launch.identity.supervisor_epoch,
            pending_launch=self.pending_launch,
        )

    def start_gate(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> CodingProductWorkerStartGate:
        return CodingProductWorkerStartGate(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            worker_request=request,
            attempt_id=request.identity.attempt_id,
        )

    def native_profile(
        self,
        payload: CodingProductWorkerPayloadLeaseV1,
        request: ManagedWorkerLaunchRequestV1,
        gate: _Gate,
    ) -> ProductWorkerNativeProfilePort:
        return self._profile_from_material(payload.native_material, request, gate)


@dataclass(frozen=True, slots=True)
class _WindowsLaunchInputs:
    receipt_owner: CodingWindowsWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    pending_launch: CodingWindowsProductWorkerPendingLaunchV1

    def materialize(self, attempt_id: str) -> CodingWindowsWorkerPayloadLeaseV1:
        return materialize_coding_windows_product_worker_payload(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            attempt_id=attempt_id,
        )

    def bind_request(
        self, payload: CodingWindowsWorkerPayloadLeaseV1
    ) -> ManagedWorkerLaunchRequestV1:
        return bind_coding_windows_product_worker_launch_request(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            payload_lease=payload,
            supervisor_epoch=self.pending_launch.identity.supervisor_epoch,
            pending_launch=self.pending_launch,
        )

    def selected_manifest(self) -> PackageProductSelectedPluginManifestV1:
        return self.receipt_owner.current_selected_manifest(self.receipt)

    def native_plan(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> _WindowsLpacProductWorkerProfilePlan:
        return self.receipt_owner.plan_current_native_attempt(self.receipt, request)

    def commit_launch_intent(
        self,
        request: ManagedWorkerLaunchRequestV1,
        payload: CodingWindowsWorkerPayloadLeaseV1,
    ) -> None:
        commit_coding_windows_product_worker_launch_intent(
            self.receipt_owner.product_owner,
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            request=request,
            payload_lease=payload,
        )

    def provisioning_store(
        self,
        selected: PackageProductSelectedPluginManifestV1,
        request: ManagedWorkerLaunchRequestV1,
        plan: _WindowsLpacProductWorkerProfilePlan,
    ) -> _WindowsLpacProvisioningStateStore:
        return open_coding_windows_product_worker_provisioning_state_store(
            self.receipt_owner.product_owner,
            runtime=self.receipt_owner.product_runtime,
            selected=selected,
            receipt=self.receipt,
            worker_request=request,
            plan=plan,
        )


@dataclass(frozen=True, slots=True)
class _PosixActivationInputs:
    receipt_owner: CodingWorkerProductReceiptOwner

    @property
    def authority(self) -> CodingWorkerProductReceiptOwner:
        return self.receipt_owner

    def evidence(
        self, request: ManagedWorkerLaunchRequestV1 | None = None
    ) -> CodingPosixWorkerCleanupEvidenceAuthority:
        return CodingPosixWorkerCleanupEvidenceAuthority(
            self.receipt_owner.product_owner
        )

    def state_store(self) -> _ActivationStateStore:
        return open_coding_product_worker_activation_state_store(
            self.receipt_owner.product_owner
        )

    def supervisor_journal(self) -> WorkerSupervisorJournal:
        return open_coding_product_worker_supervisor_journal(
            self.receipt_owner.product_owner
        )


@dataclass(frozen=True, slots=True)
class _WindowsActivationInputs:
    receipt_owner: CodingWindowsWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1

    @property
    def authority(self) -> CodingWindowsWorkerProductReceiptOwner:
        return self.receipt_owner

    def evidence(
        self, request: ManagedWorkerLaunchRequestV1 | None = None
    ) -> CodingWindowsWorkerCleanupEvidenceAuthority:
        if request is None:
            return CodingWindowsWorkerCleanupEvidenceAuthority.for_resume_parent_enrollment(
                receipt_owner=self.receipt_owner, receipt=self.receipt
            )
        return CodingWindowsWorkerCleanupEvidenceAuthority(
            receipt_owner=self.receipt_owner, receipt=self.receipt, request=request
        )

    def state_store(self) -> _ActivationStateStore:
        return open_coding_windows_product_worker_activation_state_store(
            self.receipt_owner.product_owner
        )

    def supervisor_journal(self) -> WorkerSupervisorJournal:
        return open_coding_windows_product_worker_supervisor_journal(
            self.receipt_owner.product_owner
        )


@dataclass(frozen=True, slots=True)
class _CodingWorkerProviderPolicy:
    receipt_owner: (
        CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
    )
    receipt: ProductWorkerActivationReceiptV1
    binding: CapabilityWorkerBindingV1
    provider_owner: CapabilityProviderOwnerAuthority
    clock: Callable[[], int]
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding
    capability_id: ClassVar[str] = CODING_WORKER_QUERY_CAPABILITY_ID
    facet_id: ClassVar[str] = CODING_WORKER_QUERY_FACET_ID

    def bind_authority(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> CodingProductWorkerCapabilityAuthority:
        facet_owner = bind_coding_worker_query_facet_owner(
            binding=self.binding,
            provider_owner=self.provider_owner,
            current_owner_snapshot=self.provider_owner.snapshot,
        )
        return CodingProductWorkerCapabilityAuthority(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            request=request,
            binding=self.binding,
            owner_policy=facet_owner,
        )

    def capture(
        self,
        *,
        resolved: ResolvedCapabilityProvider,
        capability_authority: _QueryAuthority,
        adapter: CapabilityQueryWorkerAdapter,
        worker_admission: CapabilityWorkerAdmissionV1,
        graph_generation: int,
        release_attempt: Callable[[], Awaitable[None]],
        on_graph_publication: Callable[[], None],
    ) -> tuple[CapabilityProviderCandidateEnvelope, CapabilityWorkerBindingV1]:
        return _read_coding_worker_provider_inputs(
            resolved=resolved,
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            capability_authority=cast(
                CodingProductWorkerCapabilityAuthority, capability_authority
            ),
            adapter=adapter,
            worker_admission=worker_admission,
            graph_generation=graph_generation,
            clock=self.clock,
            release_attempt=release_attempt,
            base_policy_binding=self.base_policy_binding,
            renewing_provider_owner=self.provider_owner,
            on_graph_publication=on_graph_publication,
        )

    def read_candidate(
        self, resolved: ResolvedCapabilityProvider
    ) -> CapabilityProviderCandidateEnvelope:
        return prepare_coding_selected_worker_provider_candidate(
            receipt_owner=self.receipt_owner,
            receipt=self.receipt,
            definition=resolved.definition,
            provider=resolved.provider,
            base_policy_binding=self.base_policy_binding,
        )
