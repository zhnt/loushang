"""Start a Product-selected Linux Worker only during async graph preparation."""

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
    _bind_posix_static_contained_product_worker_profile,
)
from loushang.harness.worker.capability_query import (
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.gated_start import bind_worker_gated_start_release
from loushang.harness.worker.hosting_adapter import HostingManagedWorkerSessionAdapter
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupSettlementV1,
)
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.hosting.runtime import create_child_session_host

from .package_product_worker_activation_state import (
    open_coding_product_worker_activation_state_store,
)
from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_payload import (
    CodingProductWorkerPendingLaunchV1,
    bind_coding_product_worker_launch_request,
    materialize_coding_product_worker_payload,
    open_coding_product_worker_supervisor_journal,
)
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
from .package_product_worker_receipt import CodingWorkerProductReceiptOwner
from .package_product_worker_session_composition import (
    prepare_coding_product_worker_session_inputs,
)
from .package_product_worker_start_gate import CodingProductWorkerStartGate


class CodingWorkerPendingHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingProductWorkerPendingHost:
    resolved_providers: ResolvedCapabilityProviderSet
    provider_owner: CapabilityProviderOwnerAuthority
    receipt_owner: CodingWorkerProductReceiptOwner
    receipt: ProductWorkerActivationReceiptV1
    pending_launch: CodingProductWorkerPendingLaunchV1
    expected_admission: CapabilityWorkerAdmissionV1
    binding: CapabilityWorkerBindingV1
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding
    clock: Callable[[], int]

    async def prepare(self, graph_generation: int) -> CodingPreparedWorkerProvider:
        """Own all effects from payload creation through graph disposal."""

        if type(graph_generation) is not int or graph_generation < 1:
            raise TypeError("Coding Worker graph generation is invalid")
        if self.base_policy_binding is not None:
            self.base_policy_binding.assert_current()
        stack = AsyncExitStack()
        coordinator: ProductWorkerActivationCoordinator | None = None
        cleanup_evidence: CodingPosixWorkerCleanupEvidenceAuthority | None = None
        host_identity: str | None = None
        boot_identity: str | None = None
        effect_started = False

        async def release() -> None:
            async def settle() -> None:
                try:
                    await stack.aclose()
                finally:
                    if effect_started:
                        assert coordinator is not None
                        assert cleanup_evidence is not None
                        assert host_identity is not None
                        assert boot_identity is not None
                        attempt_id = self.pending_launch.identity.attempt_id
                        owner_generation = self.pending_launch.identity.owner_generation
                        coordinator.retire_exact(
                            receipt=self.receipt,
                            attempt_id=attempt_id,
                            owner_generation=owner_generation,
                        )
                        coordinator.record_protocol_terminal(
                            receipt=self.receipt,
                            attempt_id=attempt_id,
                            owner_generation=owner_generation,
                        )
                        coordinator.record_cleanup_settlement(
                            WorkerCleanupSettlementV1(
                                receipt_fingerprint=self.receipt.fingerprint,
                                attempt_id=attempt_id,
                                owner_generation=owner_generation,
                                host_identity=host_identity,
                                boot_identity=boot_identity,
                                protocol_terminal=True,
                                domain_retired=True,
                                tree_settled=True,
                            ),
                            witness=cleanup_evidence.current_tree_witness(
                                attempt_id=attempt_id
                            ),
                        )

            task = asyncio.create_task(
                settle(),
                name=f"coding-worker-release-{self.pending_launch.identity.attempt_id}",
            )
            await _await_cancellation_atomic(task)

        try:
            payload = stack.enter_context(
                materialize_coding_product_worker_payload(
                    receipt_owner=self.receipt_owner,
                    receipt=self.receipt,
                    attempt_id=self.pending_launch.identity.attempt_id,
                )
            )
            request = bind_coding_product_worker_launch_request(
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                payload_lease=payload,
                supervisor_epoch=self.pending_launch.identity.supervisor_epoch,
                pending_launch=self.pending_launch,
            )
            if request.identity != self.pending_launch.identity:
                raise CodingWorkerPendingHostError(
                    "coding_worker_pending_launch_identity_changed"
                )
            gate = CodingProductWorkerStartGate(
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                worker_request=request,
                attempt_id=request.identity.attempt_id,
            )
            stack.callback(gate.close)
            native = payload.native_material
            profile = _bind_posix_static_contained_product_worker_profile(
                receipt=self.receipt,
                worker_request=request,
                native_profile_catalog_revision=(
                    native.closure.native_profile_catalog_revision
                ),
                launcher_path=native.launcher_path,
                launcher_sha256=native.closure.containment_launcher_digest,
                containment_profile_sha256=native.closure.containment_profile_digest,
                start_gate_read_fd=gate.start_gate_read_fd,
            )
            stack.push_async_callback(profile.close)
            host = create_child_session_host(
                max_sessions=1, enable_posix_static_capture=True
            )
            stack.push_async_callback(host.close)
            supervisor = WorkerSupervisor(
                identity=request.identity,
                journal=open_coding_product_worker_supervisor_journal(
                    self.receipt_owner.product_owner
                ),
                protocol=request.runtime.protocol,
                protocol_version=request.runtime.protocol_version,
            )

            async def settle_supervisor() -> None:
                try:
                    if supervisor.status.state == "healthy":
                        await supervisor.shutdown()
                    elif supervisor.status.state not in {
                        "stopped",
                        "failed",
                        "fenced",
                    }:
                        await supervisor.fence(
                            code="coding_worker_graph_prepare_failed"
                        )
                finally:
                    try:
                        await host.close()
                    finally:
                        if supervisor.status.state in {"failed", "fenced"}:
                            await supervisor.settle_failed_process()

            stack.push_async_callback(settle_supervisor)
            cleanup_evidence = CodingPosixWorkerCleanupEvidenceAuthority(
                self.receipt_owner.product_owner
            )
            coordinator = ProductWorkerActivationCoordinator(
                authority=self.receipt_owner,
                evidence_authority=cleanup_evidence,
                trusted_evidence_authority_id=cleanup_evidence.authority_id,
                trusted_evidence_authority_fingerprint=(
                    cleanup_evidence.authority_fingerprint
                ),
                state_store=open_coding_product_worker_activation_state_store(
                    self.receipt_owner.product_owner
                ),
            )
            if (
                coordinator.evaluate(self.receipt.policy, self.receipt).get("reason")
                != "admitted"
            ):
                raise CodingWorkerPendingHostError(
                    "coding_worker_pending_c5_admission_refused"
                )
            host_identity = cleanup_evidence.host_identity
            boot_identity = cleanup_evidence.boot_identity
            with coordinator.admission(
                policy=self.receipt.policy,
                receipt=self.receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
                host_identity=host_identity,
                boot_identity=boot_identity,
                cleanup_contract_version=profile.cleanup_contract_version,
            ) as admission:
                admission.begin_effect()
                effect_started = True
            await supervisor.start_session(
                session_port=HostingManagedWorkerSessionAdapter(
                    hosting=host,
                    preparation=profile,
                    start_gate=bind_worker_gated_start_release(gate),
                ),
                launch_request=request,
                correlation_id="coding-product-worker-ordinary-session",
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
                raise CodingWorkerPendingHostError(
                    "coding_worker_pending_admission_changed"
                )
            descriptors = await adapter.describe()
            if (
                len(descriptors) != 1
                or descriptors[0].capability_id != CODING_WORKER_QUERY_CAPABILITY_ID
                or descriptors[0].facet_ids != (CODING_WORKER_QUERY_FACET_ID,)
            ):
                raise CodingWorkerPendingHostError(
                    "coding_worker_pending_descriptor_mismatch"
                )

            def commit_c5() -> None:
                assert coordinator is not None
                coordinator.publish(
                    receipt=self.receipt,
                    attempt_id=request.identity.attempt_id,
                    owner_generation=request.identity.owner_generation,
                    realized_native_policy_closure_fingerprint=(
                        profile.realized_native_policy_closure_fingerprint
                    ),
                    native_profile_catalog_revision=(
                        profile.native_profile_catalog_revision
                    ),
                    native_profile_id=profile.native_profile_id,
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
                on_graph_publication=commit_c5,
            )
        except BaseException as error:
            try:
                await release()
            except BaseException as cleanup_error:
                error.add_note(
                    "Coding Worker pending graph cleanup also failed: "
                    + type(cleanup_error).__name__
                )
            raise


def prepare_coding_product_worker_pending_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: CodingWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    pending_launch: CodingProductWorkerPendingLaunchV1,
    evaluated_at: int,
    clock: Callable[[], int],
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding,
) -> SessionCapabilityCompositionInputs:
    """Compile a Worker request whose native effects start during graph prepare."""

    if (
        not isinstance(pending_launch, CodingProductWorkerPendingLaunchV1)
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(base_policy_binding, CodingWorkerBaseCompositionPolicyBinding)
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id
        != CODING_WORKER_QUERY_CAPABILITY_ID
        or resolved_providers.entries[0].definition != CODING_WORKER_QUERY_DEFINITION
        or provider_owner.policy != coding_worker_query_owner_authority().policy
    ):
        raise CodingWorkerPendingHostError("coding_worker_pending_selection_invalid")
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
    host = CodingProductWorkerPendingHost(
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
    "CodingProductWorkerPendingHost",
    "CodingWorkerPendingHostError",
    "prepare_coding_product_worker_pending_session_inputs",
]
