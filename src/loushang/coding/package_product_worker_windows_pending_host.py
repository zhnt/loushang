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
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
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
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupDebtV2,
    WorkerCleanupSettlementV2,
    _CleanupDebtReasonV2,
)
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.hosting.windows_backend_material import WINDOWS_LPAC_PLATFORM_IMPORTS

from .package_product_worker_activation_state import (
    open_coding_windows_product_worker_activation_state_store,
)
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
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
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


def _require_uncoupled_windows_host_c5_absent(
    product: WindowsLocalWheelProductSessionOwner,
) -> None:
    """Refuse a retained C5 owner until this Host writes and settles C5 itself."""

    present, _state = CodingWindowsWorkerActivationStateJournal(
        product
    ).load_with_presence_read_only()
    if present:
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_c5_owner_requires_recovery"
        )


def _require_windows_host_c5_recovered(
    product: WindowsLocalWheelProductSessionOwner,
) -> None:
    """Keep interrupted initialization and unfinished attempts out of a new Host."""

    present, state = CodingWindowsWorkerActivationStateJournal(
        product
    ).load_with_presence_read_only()
    if present and state is None:
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_c5_owner_requires_recovery"
        )
    if state is not None and any(
        attempt.phase != "settled"
        for attempt in CodingWindowsWorkerActivationStateJournal(
            product
        ).retained_attempts_read_only()
    ):
        raise CodingWindowsWorkerPendingHostError(
            "coding_worker_pending_c5_owner_requires_recovery"
        )


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
        _require_windows_host_c5_recovered(self.receipt_owner.product_owner)
        stack = AsyncExitStack()
        coordinator: ProductWorkerActivationCoordinator | None = None
        cleanup_evidence: CodingWindowsWorkerCleanupEvidenceAuthority | None = None
        profile = None
        supervisor: WorkerSupervisor | None = None
        effect_started = False

        async def release() -> None:
            async def settle() -> None:
                try:
                    await stack.aclose()
                    if not effect_started:
                        return
                    assert coordinator is not None
                    assert cleanup_evidence is not None
                    assert profile is not None
                    identity = self.pending_launch.identity
                    coordinator.retire_exact(
                        receipt=self.receipt,
                        attempt_id=identity.attempt_id,
                        owner_generation=identity.owner_generation,
                    )
                    coordinator.record_protocol_terminal(
                        receipt=self.receipt,
                        attempt_id=identity.attempt_id,
                        owner_generation=identity.owner_generation,
                    )
                    coordinator.record_cleanup_settlement(
                        WorkerCleanupSettlementV2(
                            receipt_fingerprint=self.receipt.fingerprint,
                            attempt_id=identity.attempt_id,
                            owner_generation=identity.owner_generation,
                            host_identity=cleanup_evidence.host_identity,
                            boot_identity=cleanup_evidence.boot_identity,
                            protocol_terminal=True,
                            domain_retired=True,
                            tree_settled=True,
                            native_containment_settled=True,
                        ),
                        witness=cleanup_evidence.current_tree_witness(
                            attempt_id=identity.attempt_id
                        ),
                        native_containment_witness=(
                            profile.native_containment_settlement_witness()
                        ),
                    )
                except BaseException as cleanup_error:
                    if effect_started:
                        assert coordinator is not None
                        assert cleanup_evidence is not None
                        identity = self.pending_launch.identity
                        try:
                            coordinator.record_cleanup_debt(
                                WorkerCleanupDebtV2(
                                    receipt_fingerprint=self.receipt.fingerprint,
                                    attempt_id=identity.attempt_id,
                                    owner_generation=identity.owner_generation,
                                    host_identity=cleanup_evidence.host_identity,
                                    boot_identity=cleanup_evidence.boot_identity,
                                    process_tree_unknown=True,
                                    native_containment_unknown=True,
                                    reason=(
                                        _CleanupDebtReasonV2.TREE_AND_NATIVE_CONTAINMENT_UNKNOWN
                                    ),
                                )
                            )
                        except BaseException as debt_error:
                            cleanup_error.add_note(
                                "Windows Worker C5 cleanup debt write failed: "
                                + type(debt_error).__name__
                            )
                    raise

            task = asyncio.create_task(
                settle(),
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
            plan = self.receipt_owner.plan_current_native_attempt(self.receipt, request)
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

            async def close_unowned_profile() -> None:
                # Once Supervisor starts a process, Hosting owns preparation
                # release and invokes it only after the process tree settles.
                # Do not bypass that ordering when a failed close leaves a
                # fenced attempt and its native cleanup debt behind.
                if supervisor is None or supervisor.status.state in {
                    "created",
                    "stopped",
                }:
                    await profile.close()

            stack.push_async_callback(close_unowned_profile)
            cleanup_evidence = CodingWindowsWorkerCleanupEvidenceAuthority(
                receipt_owner=self.receipt_owner,
                receipt=self.receipt,
                request=request,
            )
            coordinator = ProductWorkerActivationCoordinator(
                authority=self.receipt_owner,
                evidence_authority=cleanup_evidence,
                trusted_evidence_authority_id=cleanup_evidence.authority_id,
                trusted_evidence_authority_fingerprint=(
                    cleanup_evidence.authority_fingerprint
                ),
                state_store=open_coding_windows_product_worker_activation_state_store(
                    self.receipt_owner.product_owner
                ),
            )
            if (
                coordinator.evaluate(self.receipt.policy, self.receipt).get("reason")
                != "admitted"
            ):
                raise CodingWindowsWorkerPendingHostError(
                    "coding_worker_pending_c5_admission_refused"
                )
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
            with coordinator.admission(
                policy=self.receipt.policy,
                receipt=self.receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
                host_identity=cleanup_evidence.host_identity,
                boot_identity=cleanup_evidence.boot_identity,
                cleanup_contract_version=profile.cleanup_contract_version,
            ) as admission:
                admission.begin_effect()
                effect_started = True
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
