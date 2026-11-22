"""Fixed ordinary Worker preparation, borrowing original authorities.

Platform settlement remains distinct. Session alone publishes its graph;
these programs supply the original prepared binding and cleanup obligation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, AsyncExitStack
from dataclasses import dataclass
from typing import Protocol, TypeVar, cast

from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic
from loushang.harness.worker._native_profile_bridge import (
    ProductWorkerNativeProfilePort,
    _bind_windows_lpac_contained_product_worker_profile,
    _create_windows_lpac_product_worker_session_host,
    _WindowsLpacContainedProductWorkerProfile,
    _WindowsLpacProductWorkerProfilePlan,
    _WindowsLpacProvisioningStateStore,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerLaunchIdentityV1,
)
from loushang.harness.worker.gated_start import (
    WorkerGatedStartWitnessV1,
    bind_worker_gated_start_release,
)
from loushang.harness.worker.hosting_adapter import HostingManagedWorkerSessionAdapter
from loushang.harness.worker.journal import WorkerSupervisorJournal
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationAuthorityPort,
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupDebtV2,
    WorkerCleanupSettlementV1,
    WorkerCleanupSettlementV2,
    _ActivationStateStore,
    _CleanupDebtReasonV2,
)
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.hosting.runtime import create_child_session_host
from loushang.hosting.windows_backend_material import WINDOWS_LPAC_PLATFORM_IMPORTS

PayloadT = TypeVar("PayloadT")
SelectedT = TypeVar("SelectedT")


class _Evidence(Protocol):
    @property
    def authority_id(self) -> str: ...

    @property
    def authority_fingerprint(self) -> str: ...

    @property
    def host_identity(self) -> str: ...

    @property
    def boot_identity(self) -> str: ...

    def current_tree_witness(self, *, attempt_id: str) -> object: ...


class _ActivationInputs(Protocol):
    @property
    def _worker_activation_authority(self) -> ProductWorkerActivationAuthorityPort: ...

    def _worker_evidence(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1 | None = None,
    ) -> _Evidence: ...

    def _open_worker_state_store(self) -> _ActivationStateStore: ...

    def _open_worker_supervisor_journal(self) -> WorkerSupervisorJournal: ...


class _Gate(Protocol):
    @property
    def start_gate_read_fd(self) -> int: ...

    def close(self) -> None: ...

    def release(self, witness: WorkerGatedStartWitnessV1) -> None: ...


class _PosixSource(Protocol[PayloadT]):
    def _materialize_worker_payload(
        self, receipt: ProductWorkerActivationReceiptV1, attempt_id: str
    ) -> AbstractContextManager[PayloadT]: ...

    def _bind_worker_launch_request(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        payload: PayloadT,
        *,
        supervisor_epoch: int,
        pending_launch: _PendingLaunch | None = None,
    ) -> ManagedWorkerLaunchRequestV1: ...

    def _worker_start_gate(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        attempt_id: str,
    ) -> _Gate: ...

    def _worker_payload_profile(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        payload: PayloadT,
        request: ManagedWorkerLaunchRequestV1,
        gate: _Gate,
    ) -> ProductWorkerNativeProfilePort: ...


class _WindowsSource(Protocol[PayloadT, SelectedT]):
    def _materialize_worker_payload(
        self, receipt: ProductWorkerActivationReceiptV1, attempt_id: str
    ) -> PayloadT: ...

    def _bind_worker_launch_request(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        payload: PayloadT,
        *,
        supervisor_epoch: int,
        pending_launch: _PendingLaunch | None = None,
    ) -> ManagedWorkerLaunchRequestV1: ...

    def current_selected_manifest(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> SelectedT: ...

    def plan_current_native_attempt(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
    ) -> _WindowsLpacProductWorkerProfilePlan: ...

    def _commit_worker_launch_intent(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        payload: PayloadT,
    ) -> None: ...

    def _worker_provisioning_store(
        self,
        selected: SelectedT,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        plan: _WindowsLpacProductWorkerProfilePlan,
    ) -> _WindowsLpacProvisioningStateStore: ...


class _ResumeBinding(Protocol):
    def bind(self, coordinator: ProductWorkerActivationCoordinator) -> None: ...


class _PendingLaunch(Protocol):
    @property
    def identity(self) -> WorkerLaunchIdentityV1: ...


@dataclass(frozen=True, slots=True)
class _NativeWorkerAttempt:
    """Same acquired objects and raw cleanup; no copied lifecycle state."""

    request: ManagedWorkerLaunchRequestV1
    supervisor: WorkerSupervisor
    release: Callable[[], Awaitable[None]]
    commit_activation: Callable[[], None]


def _coordinator(
    inputs: _ActivationInputs, evidence: _Evidence
) -> ProductWorkerActivationCoordinator:
    return ProductWorkerActivationCoordinator(
        authority=inputs._worker_activation_authority,
        evidence_authority=evidence,
        trusted_evidence_authority_id=evidence.authority_id,
        trusted_evidence_authority_fingerprint=evidence.authority_fingerprint,
        state_store=inputs._open_worker_state_store(),
    )


def _publish_native_worker_activation(
    coordinator: ProductWorkerActivationCoordinator,
    receipt: ProductWorkerActivationReceiptV1,
    identity: WorkerLaunchIdentityV1,
    profile: ProductWorkerNativeProfilePort,
) -> None:
    coordinator.publish(
        receipt=receipt,
        attempt_id=identity.attempt_id,
        owner_generation=identity.owner_generation,
        realized_native_policy_closure_fingerprint=(
            profile.realized_native_policy_closure_fingerprint
        ),
        native_profile_catalog_revision=profile.native_profile_catalog_revision,
        native_profile_id=profile.native_profile_id,
    )


def _settle_posix_worker(
    coordinator: ProductWorkerActivationCoordinator,
    evidence: _Evidence,
    receipt: ProductWorkerActivationReceiptV1,
    identity: WorkerLaunchIdentityV1,
    *,
    host_identity: str,
    boot_identity: str,
) -> None:
    """Retire one POSIX attempt and attest its native tree under the original witness."""
    coordinator.retire_exact(
        receipt=receipt,
        attempt_id=identity.attempt_id,
        owner_generation=identity.owner_generation,
    )
    coordinator.record_protocol_terminal(
        receipt=receipt,
        attempt_id=identity.attempt_id,
        owner_generation=identity.owner_generation,
    )
    coordinator.record_cleanup_settlement(
        WorkerCleanupSettlementV1(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=identity.attempt_id,
            owner_generation=identity.owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
        ),
        witness=evidence.current_tree_witness(attempt_id=identity.attempt_id),
    )


async def _prepare_posix_native_worker(
    *,
    launch_source: _PosixSource[PayloadT],
    activation: _ActivationInputs,
    pending_launch: _PendingLaunch,
    receipt: ProductWorkerActivationReceiptV1,
    resume_parent_context: ResumeEffectParentContextV1 | None,
    resume_settlement: _ResumeBinding | None,
    failure: Callable[[str], RuntimeError],
    parent_failure: Callable[[str], RuntimeError],
    failure_code_prefix: str,
    task_name_prefix: str,
    cleanup_note: str,
    correlation_id: str,
) -> _NativeWorkerAttempt:
    stack = AsyncExitStack()
    coordinator: ProductWorkerActivationCoordinator | None = None
    cleanup_evidence: _Evidence | None = None
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
                    _settle_posix_worker(
                        coordinator,
                        cleanup_evidence,
                        receipt,
                        pending_launch.identity,
                        host_identity=host_identity,
                        boot_identity=boot_identity,
                    )

        task = asyncio.create_task(
            settle(), name=f"{task_name_prefix}{pending_launch.identity.attempt_id}"
        )
        await _await_cancellation_atomic(task)

    try:
        if resume_parent_context is not None:
            cleanup_evidence = activation._worker_evidence(receipt)
            coordinator = _coordinator(activation, cleanup_evidence)
            if (
                coordinator.evaluate(receipt.policy, receipt).get("reason")
                != "admitted"
            ):
                raise failure("c5_admission_refused")
            ProductWorkerActivationCoordinator.observe_or_enroll_resume_parent(
                coordinator,
                receipt=receipt,
                context=resume_parent_context,
                failure=parent_failure,
            )
        payload = stack.enter_context(
            launch_source._materialize_worker_payload(
                receipt, pending_launch.identity.attempt_id
            )
        )
        request = launch_source._bind_worker_launch_request(
            receipt,
            payload,
            supervisor_epoch=pending_launch.identity.supervisor_epoch,
            pending_launch=pending_launch,
        )
        if request.identity != pending_launch.identity:
            raise failure("launch_identity_changed")
        gate = launch_source._worker_start_gate(
            receipt, request, request.identity.attempt_id
        )
        stack.callback(gate.close)
        profile = launch_source._worker_payload_profile(receipt, payload, request, gate)
        stack.push_async_callback(profile.close)
        host = create_child_session_host(
            max_sessions=1, enable_posix_static_capture=True
        )
        stack.push_async_callback(host.close)
        supervisor = WorkerSupervisor(
            identity=request.identity,
            journal=activation._open_worker_supervisor_journal(),
            protocol=request.runtime.protocol,
            protocol_version=request.runtime.protocol_version,
        )

        async def settle_supervisor() -> None:
            try:
                if supervisor.status.state == "healthy":
                    await supervisor.shutdown()
                elif supervisor.status.state not in {"stopped", "failed", "fenced"}:
                    await supervisor.fence(
                        code=failure_code_prefix + "_graph_prepare_failed"
                    )
            finally:
                try:
                    await host.close()
                finally:
                    if supervisor.status.state in {"failed", "fenced"}:
                        await supervisor.settle_failed_process()

        stack.push_async_callback(settle_supervisor)
        if coordinator is None:
            cleanup_evidence = activation._worker_evidence(receipt)
            coordinator = _coordinator(activation, cleanup_evidence)
            if (
                coordinator.evaluate(receipt.policy, receipt).get("reason")
                != "admitted"
            ):
                raise failure("c5_admission_refused")
        if resume_settlement is not None:
            resume_settlement.bind(coordinator)
        assert cleanup_evidence is not None
        host_identity = cleanup_evidence.host_identity
        boot_identity = cleanup_evidence.boot_identity
        with coordinator.admission(
            policy=receipt.policy,
            receipt=receipt,
            attempt_id=request.identity.attempt_id,
            owner_generation=request.identity.owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
            cleanup_contract_version=profile.cleanup_contract_version,
            parent_context=resume_parent_context,
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
            correlation_id=correlation_id,
        )

        def commit_activation() -> None:
            assert coordinator is not None
            _publish_native_worker_activation(
                coordinator, receipt, request.identity, profile
            )
            ProductWorkerActivationCoordinator.seal_current_resume_parent(
                coordinator, context=resume_parent_context, failure=parent_failure
            )

        return _NativeWorkerAttempt(
            request=request,
            supervisor=supervisor,
            release=release,
            commit_activation=commit_activation,
        )
    except BaseException as error:
        try:
            await release()
        except BaseException as cleanup_error:
            error.add_note(cleanup_note + type(cleanup_error).__name__)
        raise


async def _prepare_windows_native_worker(
    *,
    launch_source: _WindowsSource[PayloadT, SelectedT],
    activation: _ActivationInputs,
    pending_launch: _PendingLaunch,
    receipt: ProductWorkerActivationReceiptV1,
    resume_parent_context: ResumeEffectParentContextV1 | None,
    resume_settlement: _ResumeBinding | None,
    failure: Callable[[str], RuntimeError],
    parent_failure: Callable[[str], RuntimeError],
    failure_code_prefix: str,
    task_name_prefix: str,
    cleanup_note: str,
    correlation_id: str,
) -> _NativeWorkerAttempt:
    stack = AsyncExitStack()
    coordinator: ProductWorkerActivationCoordinator | None = None
    cleanup_evidence: _Evidence | None = None
    profile: _WindowsLpacContainedProductWorkerProfile | None = None
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
                identity = pending_launch.identity
                coordinator.retire_exact(
                    receipt=receipt,
                    attempt_id=identity.attempt_id,
                    owner_generation=identity.owner_generation,
                )
                coordinator.record_protocol_terminal(
                    receipt=receipt,
                    attempt_id=identity.attempt_id,
                    owner_generation=identity.owner_generation,
                )
                coordinator.record_cleanup_settlement(
                    WorkerCleanupSettlementV2(
                        receipt_fingerprint=receipt.fingerprint,
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
                    native_containment_witness=profile.native_containment_settlement_witness(),
                )
            except BaseException as cleanup_error:
                if effect_started:
                    assert coordinator is not None
                    assert cleanup_evidence is not None
                    identity = pending_launch.identity
                    try:
                        coordinator.record_cleanup_debt(
                            WorkerCleanupDebtV2(
                                receipt_fingerprint=receipt.fingerprint,
                                attempt_id=identity.attempt_id,
                                owner_generation=identity.owner_generation,
                                host_identity=cleanup_evidence.host_identity,
                                boot_identity=cleanup_evidence.boot_identity,
                                process_tree_unknown=True,
                                native_containment_unknown=True,
                                reason=_CleanupDebtReasonV2.TREE_AND_NATIVE_CONTAINMENT_UNKNOWN,
                            )
                        )
                    except BaseException as debt_error:
                        cleanup_error.add_note(
                            "Windows Worker C5 cleanup debt write failed: "
                            + type(debt_error).__name__
                        )
                raise

        task = asyncio.create_task(
            settle(), name=task_name_prefix + pending_launch.identity.attempt_id
        )
        await _await_cancellation_atomic(task)

    try:
        if resume_parent_context is not None:
            enrollment_evidence = activation._worker_evidence(receipt)
            enrollment_coordinator = _coordinator(activation, enrollment_evidence)
            if (
                enrollment_coordinator.evaluate(receipt.policy, receipt).get("reason")
                != "admitted"
            ):
                raise failure("c5_admission_refused")
            ProductWorkerActivationCoordinator.observe_or_enroll_resume_parent(
                enrollment_coordinator,
                receipt=receipt,
                context=resume_parent_context,
                failure=parent_failure,
            )
        payload = launch_source._materialize_worker_payload(
            receipt, pending_launch.identity.attempt_id
        )
        request = launch_source._bind_worker_launch_request(
            receipt,
            payload,
            supervisor_epoch=pending_launch.identity.supervisor_epoch,
            pending_launch=pending_launch,
        )
        if request.identity != pending_launch.identity:
            raise failure("launch_identity_changed")
        selected = launch_source.current_selected_manifest(receipt)
        plan = launch_source.plan_current_native_attempt(receipt, request)
        launch_source._commit_worker_launch_intent(receipt, request, payload)
        native_store = launch_source._worker_provisioning_store(
            selected, receipt, request, plan
        )
        profile = cast(
            _WindowsLpacContainedProductWorkerProfile,
            _bind_windows_lpac_contained_product_worker_profile(
                receipt=receipt,
                worker_request=request,
                plan=plan,
                platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                provisioning_state_store=native_store,
            ),
        )

        async def close_unowned_profile() -> None:
            if supervisor is None or supervisor.status.state in {"created", "stopped"}:
                await cast(_WindowsLpacContainedProductWorkerProfile, profile).close()

        stack.push_async_callback(close_unowned_profile)
        cleanup_evidence = activation._worker_evidence(receipt, request)
        coordinator = _coordinator(activation, cleanup_evidence)
        if coordinator.evaluate(receipt.policy, receipt).get("reason") != "admitted":
            raise failure("c5_admission_refused")
        if resume_settlement is not None:
            resume_settlement.bind(coordinator)
        host = _create_windows_lpac_product_worker_session_host()
        stack.push_async_callback(host.close)
        supervisor = WorkerSupervisor(
            identity=request.identity,
            journal=activation._open_worker_supervisor_journal(),
            protocol=request.runtime.protocol,
            protocol_version=request.runtime.protocol_version,
        )

        async def settle_supervisor() -> None:
            if supervisor.status.state == "healthy":
                try:
                    selected = (
                        activation._worker_activation_authority.current_witness(receipt)
                        == receipt.authority_witness
                    )
                except PackageProductRuntimeReadError:
                    selected = False
                if selected:
                    await supervisor.shutdown()
                else:
                    await supervisor.fence(
                        code=failure_code_prefix + "_product_selection_stale"
                    )
            elif supervisor.status.state not in {"stopped", "failed", "fenced"}:
                await supervisor.fence(
                    code=failure_code_prefix + "_graph_prepare_failed"
                )
            if supervisor.status.state in {"failed", "fenced"}:
                await supervisor.settle_failed_process()

        stack.push_async_callback(settle_supervisor)
        with coordinator.admission(
            policy=receipt.policy,
            receipt=receipt,
            attempt_id=request.identity.attempt_id,
            owner_generation=request.identity.owner_generation,
            host_identity=cleanup_evidence.host_identity,
            boot_identity=cleanup_evidence.boot_identity,
            cleanup_contract_version=profile.cleanup_contract_version,
            parent_context=resume_parent_context,
        ) as admission:
            admission.begin_effect()
            effect_started = True
        await supervisor.start_session(
            session_port=HostingManagedWorkerSessionAdapter(
                hosting=host, preparation=profile
            ),
            launch_request=request,
            correlation_id=correlation_id,
        )

        def commit_activation() -> None:
            assert coordinator is not None
            _publish_native_worker_activation(
                coordinator, receipt, request.identity,
                cast(ProductWorkerNativeProfilePort, profile),
            )
            ProductWorkerActivationCoordinator.seal_current_resume_parent(
                coordinator, context=resume_parent_context, failure=parent_failure
            )

        return _NativeWorkerAttempt(
            request=request,
            supervisor=supervisor,
            release=release,
            commit_activation=commit_activation,
        )
    except BaseException as error:
        try:
            await release()
        except BaseException as cleanup_error:
            error.add_note(cleanup_note + type(cleanup_error).__name__)
        raise
