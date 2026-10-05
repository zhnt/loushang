"""Start a selected Windows Worker during async Coding graph preparation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProviderSet,
)
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.worker._native_profile_bridge import (
    _bind_windows_lpac_contained_product_worker_profile,
    _create_windows_lpac_product_worker_session_host,
)
from loushang.harness.worker.capability_query import (
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.hosting_adapter import HostingManagedWorkerSessionAdapter
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.hosting.windows_backend_material import WINDOWS_LPAC_PLATFORM_IMPORTS

from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_provider import CodingWorkerBaseCompositionPolicyBinding
from .package_product_worker_provider_host import (
    CodingPreparedWorkerProvider,
    prepare_coding_worker_provider_binding,
)
from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_FACET_ID,
    CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
    bind_coding_worker_query_facet_owner,
    coding_worker_query_owner_authority,
)
from .package_product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)
from .package_product_worker_windows_launch_intent import (
    commit_coding_windows_product_worker_launch_intent,
)
from .package_product_worker_windows_payload import (
    CodingWindowsProductWorkerPendingLaunchV1,
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


class CodingWindowsWorkerPendingHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsProductWorkerPendingHost:
    resolved_providers: ResolvedCapabilityProviderSet
    provider_owner: CapabilityProviderOwnerAuthority
    receipt_owner: CodingWindowsWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    pending_launch: CodingWindowsProductWorkerPendingLaunchV1
    expected_admission: CapabilityWorkerAdmissionV1
    binding: CapabilityWorkerBindingV1
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding
    clock: Callable[[], int]

    async def prepare(self, graph_generation: int) -> CodingPreparedWorkerProvider:
        """Own the native attempt from payload creation through graph disposal."""

        if type(graph_generation) is not int or graph_generation < 1:
            raise TypeError("Windows Worker graph generation is invalid")
        self.base_policy_binding.assert_current()
        stack = AsyncExitStack()

        async def release() -> None:
            task = asyncio.create_task(
                stack.aclose(),
                name=(
                    "coding-windows-worker-release-"
                    + self.pending_launch.identity.attempt_id
                ),
            )
            await _await_cancellation_atomic(task)

        try:
            payload = materialize_coding_windows_product_worker_payload(
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                attempt_id=self.pending_launch.identity.attempt_id,
            )
            request = bind_coding_windows_product_worker_launch_request(
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                payload_lease=payload,
                supervisor_epoch=self.pending_launch.identity.supervisor_epoch,
                pending_launch=self.pending_launch,
            )
            if request.identity != self.pending_launch.identity:
                raise CodingWindowsWorkerPendingHostError(
                    "coding_worker_pending_launch_identity_changed"
                )
            selected = self.receipt_owner.current_selected_manifest(self.receipt)
            plan = self.receipt_owner.plan_current_native_attempt(
                self.receipt, request
            )
            commit_coding_windows_product_worker_launch_intent(
                self.receipt_owner.product_owner,
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                request=request,
                payload_lease=payload,
            )
            native_store = open_coding_windows_product_worker_provisioning_state_store(
                self.receipt_owner.product_owner,
                runtime=self.receipt_owner.product_runtime,
                selected=selected,
                receipt=self.receipt,
                worker_request=request,
                plan=plan,
            )
            profile = _bind_windows_lpac_contained_product_worker_profile(
                receipt=self.receipt,
                worker_request=request,
                plan=plan,
                platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                provisioning_state_store=native_store,
            )
            stack.push_async_callback(profile.close)
            host = _create_windows_lpac_product_worker_session_host()
            stack.push_async_callback(host.close)
            supervisor = WorkerSupervisor(
                identity=request.identity,
                journal=open_coding_windows_product_worker_supervisor_journal(
                    self.receipt_owner.product_owner
                ),
                protocol=request.runtime.protocol,
                protocol_version=request.runtime.protocol_version,
            )

            async def settle_supervisor() -> None:
                if supervisor.status.state == "healthy":
                    await supervisor.shutdown()
                elif supervisor.status.state not in {"stopped", "failed", "fenced"}:
                    await supervisor.fence(code="coding_worker_graph_prepare_failed")
                if supervisor.status.state in {"failed", "fenced"}:
                    await supervisor.settle_failed_process()

            stack.push_async_callback(settle_supervisor)
            await supervisor.start_session(
                session_port=HostingManagedWorkerSessionAdapter(
                    hosting=host,
                    preparation=profile,
                ),
                launch_request=request,
                correlation_id="coding-product-windows-worker-ordinary-session",
            )
            facet_owner = bind_coding_worker_query_facet_owner(
                binding=self.binding,
                provider_owner=self.provider_owner,
                current_owner_snapshot=self.provider_owner.snapshot,
            )
            authority = CodingProductWorkerCapabilityAuthority(
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                request=request,
                binding=self.binding,
                owner_policy=facet_owner,
            )
            adapter = bind_capability_query_worker_adapter(
                supervisor=supervisor,
                binding=authority.binding,
                authority_reader=authority.current_authority,
                enabled=True,
            )
            admitted = adapter.admit()
            if admitted != self.expected_admission:
                raise CodingWindowsWorkerPendingHostError(
                    "coding_worker_pending_admission_changed"
                )
            descriptors = await adapter.describe()
            if (
                len(descriptors) != 1
                or descriptors[0].capability_id != CODING_WORKER_QUERY_CAPABILITY_ID
                or descriptors[0].facet_ids != (CODING_WORKER_QUERY_FACET_ID,)
            ):
                raise CodingWindowsWorkerPendingHostError(
                    "coding_worker_pending_descriptor_mismatch"
                )
            [resolved] = self.resolved_providers.entries
            return prepare_coding_worker_provider_binding(
                resolved=resolved,
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                capability_authority=authority,
                adapter=adapter,
                worker_admission=admitted,
                graph_generation=graph_generation,
                clock=self.clock,
                release_attempt=release,
                base_policy_binding=self.base_policy_binding,
                renewing_provider_owner=self.provider_owner,
            )
        except BaseException as error:
            try:
                await release()
            except BaseException as cleanup_error:
                error.add_note(
                    "Windows Worker pending graph cleanup also failed: "
                    + type(cleanup_error).__name__
                )
            raise


def prepare_coding_windows_product_worker_pending_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    pending_launch: CodingWindowsProductWorkerPendingLaunchV1,
    evaluated_at: int,
    clock: Callable[[], int],
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding,
) -> SessionCapabilityCompositionInputs:
    """Compile one Windows Worker whose effects begin during graph prepare."""

    if (
        type(receipt_owner) is not CodingWindowsWorkerProductReceiptOwner
        or type(pending_launch) is not CodingWindowsProductWorkerPendingLaunchV1
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(base_policy_binding, CodingWorkerBaseCompositionPolicyBinding)
        or base_policy_binding.receipt_owner is not receipt_owner
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id
        != CODING_WORKER_QUERY_CAPABILITY_ID
        or resolved_providers.entries[0].definition != CODING_WORKER_QUERY_DEFINITION
        or provider_owner.policy != coding_worker_query_owner_authority().policy
    ):
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_selection_invalid"
        )
    base_policy_binding.assert_current()
    identity = pending_launch.identity
    binding = CapabilityWorkerBindingV1(
        plugin_id=identity.plugin_id,
        contribution_id=identity.contribution_id,
        product_id=identity.product_id,
        scope_id=identity.scope_id,
        owner_id=identity.owner_id,
        allowed_capability_ids=(CODING_WORKER_QUERY_CAPABILITY_ID,),
        authority=CapabilityWorkerAuthorityV1(
            plugin_revision_digest=identity.plugin_revision_digest,
            declaration_fingerprint=identity.declaration_fingerprint,
            owner_generation=identity.owner_generation,
            product_policy_revision=receipt.policy.product_policy_revision,
            owner_policy_revision=CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
            revocation_epoch=0,
        ),
    )
    admission = CapabilityWorkerAdmissionV1(
        binding_fingerprint=binding.fingerprint,
        authority_fingerprint=binding.authority.fingerprint,
        worker_identity_fingerprint=identity.fingerprint,
        worker_attempt_id=identity.attempt_id,
        worker_supervisor_epoch=identity.supervisor_epoch,
    )
    host = CodingWindowsProductWorkerPendingHost(
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        pending_launch=pending_launch,
        expected_admission=admission,
        binding=binding,
        base_policy_binding=base_policy_binding,
        clock=clock,
    )
    return prepare_coding_product_worker_session_inputs(
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        capability_authority=None,
        adapter=None,
        worker_admission=admission,
        evaluated_at=evaluated_at,
        clock=clock,
        release_attempt=None,
        base_policy_binding=base_policy_binding,
        deferred_prepare=host.prepare,
    )


__all__ = [
    "CodingWindowsProductWorkerPendingHost",
    "CodingWindowsWorkerPendingHostError",
    "prepare_coding_windows_product_worker_pending_session_inputs",
]
