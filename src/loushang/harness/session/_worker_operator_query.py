"""One selected Worker query inside the existing Product Session lifetime.

Original Worker, Hosting, C5, Graph and Product owners retain their authority.
This fixed program holds only the original local resources and error domain;
it adds no controller, registry, journal, retry task or phase dispatcher.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Protocol, TypeVar

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.worker._native_profile_bridge import (
    ProductWorkerNativeProfilePort,
)
from loushang.harness.worker._ordinary_prepare import (
    _ActivationInputs,
    _coordinator,
    _Evidence,
    _Gate,
)
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.gated_start import bind_worker_gated_start_release
from loushang.harness.worker.hosting_adapter import HostingManagedWorkerSessionAdapter
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
    WorkerCleanupSettlementV1,
)
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.hosting.runtime import create_child_session_host

from ._worker_provider import _QueryAuthority
from .agent_product import AgentProductSession
from .capability_composition_inputs import SessionCapabilityCompositionInputs

_PayloadT = TypeVar("_PayloadT")
_NativeT = TypeVar("_NativeT")


class _OperatorLaunchSource(Protocol[_PayloadT, _NativeT]):
    @property
    def receipt(self) -> ProductWorkerActivationReceiptV1: ...

    @property
    def activation(self) -> _ActivationInputs: ...

    def materialize(self, attempt_id: str) -> AbstractContextManager[_PayloadT]: ...
    def bind_request(
        self, payload: _PayloadT, *, supervisor_epoch: int
    ) -> ManagedWorkerLaunchRequestV1: ...
    def read_native(self) -> _NativeT: ...
    def start_gate(
        self, request: ManagedWorkerLaunchRequestV1, attempt_id: str
    ) -> _Gate: ...
    def native_profile(
        self, native: _NativeT, request: ManagedWorkerLaunchRequestV1, gate: _Gate
    ) -> ProductWorkerNativeProfilePort: ...


class _OperatorQueryPolicy(Protocol):
    @property
    def capability_id(self) -> str: ...
    @property
    def facet_id(self) -> str: ...

    def bind_authority(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> tuple[CapabilityProviderOwnerAuthority, _QueryAuthority]: ...
    def prepare_inputs(
        self,
        *,
        owner: CapabilityProviderOwnerAuthority,
        authority: _QueryAuthority,
        capability: CapabilityQueryWorkerAdapter,
        admitted: CapabilityWorkerAdmissionV1,
        release_attempt: Callable[[], Awaitable[None]],
    ) -> SessionCapabilityCompositionInputs: ...
    def create_session(
        self, inputs: SessionCapabilityCompositionInputs
    ) -> AgentProductSession: ...
    def query(self, session: AgentProductSession, symbol: str) -> Awaitable[str]: ...


async def _query_selected_worker_once(
    *,
    runtime: PackageProductRuntimeBindingV1,
    open_query: Callable[
        [],
        tuple[_OperatorLaunchSource[_PayloadT, _NativeT], _OperatorQueryPolicy] | None,
    ],
    symbol: str,
    failure: Callable[[str], RuntimeError],
    error_prefix: str,
    correlation_id: str,
    cleanup_note: str,
) -> str:
    receipt: ProductWorkerActivationReceiptV1 | None = None
    coordinator: ProductWorkerActivationCoordinator | None = None
    cleanup_evidence: _Evidence | None = None
    c5_attempt_id: str | None = None
    c5_owner_generation: int | None = None
    host_identity: str | None = None
    boot_identity: str | None = None
    effect_started = False

    def settle_c5() -> None:
        if not effect_started:
            return
        assert receipt is not None
        assert coordinator is not None
        assert cleanup_evidence is not None
        assert c5_attempt_id is not None
        assert c5_owner_generation is not None
        assert host_identity is not None
        assert boot_identity is not None
        coordinator.retire_exact(
            receipt=receipt,
            attempt_id=c5_attempt_id,
            owner_generation=c5_owner_generation,
        )
        coordinator.record_protocol_terminal(
            receipt=receipt,
            attempt_id=c5_attempt_id,
            owner_generation=c5_owner_generation,
        )
        coordinator.record_cleanup_settlement(
            WorkerCleanupSettlementV1(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=c5_attempt_id,
                owner_generation=c5_owner_generation,
                host_identity=host_identity,
                boot_identity=boot_identity,
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
            ),
            witness=cleanup_evidence.current_tree_witness(attempt_id=c5_attempt_id),
        )

    query_error: BaseException | None = None
    try:
        runtime.activate()
        selected = open_query()
        if selected is None:
            raise failure(error_prefix + "_not_selected")
        source, policy = selected
        receipt = source.receipt
        activation = source.activation
        attempt_id = secrets.token_hex(16)
        with source.materialize(attempt_id) as payload:
            journal = activation.supervisor_journal()
            probe = source.bind_request(payload, supervisor_epoch=1)
            next_epoch = journal.next_supervisor_epoch(probe.identity)
            request = (
                probe
                if next_epoch == 1
                else source.bind_request(payload, supervisor_epoch=next_epoch)
            )
            native = source.read_native()
            gate = source.start_gate(request, attempt_id)
            try:
                profile = source.native_profile(native, request, gate)
            except BaseException:
                gate.close()
                raise
            try:
                host = create_child_session_host(
                    max_sessions=1, enable_posix_static_capture=True
                )
            except BaseException:
                gate.close()
                await profile.close()
                raise
            try:
                supervisor = WorkerSupervisor(
                    identity=request.identity,
                    journal=journal,
                    protocol=request.runtime.protocol,
                    protocol_version=request.runtime.protocol_version,
                )
            except BaseException:
                gate.close()
                try:
                    await profile.close()
                finally:
                    await host.close()
                raise
            session: AgentProductSession | None = None
            try:
                adapter = HostingManagedWorkerSessionAdapter(
                    hosting=host,
                    preparation=profile,
                    start_gate=bind_worker_gated_start_release(gate),
                )
                cleanup_evidence = activation.evidence()
                coordinator = _coordinator(activation, cleanup_evidence)
                if (
                    coordinator.evaluate(receipt.policy, receipt).get("reason")
                    != "admitted"
                ):
                    raise failure(error_prefix + "_c5_admission_refused")
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
                ) as c5_admission:
                    c5_admission.begin_effect()
                    c5_attempt_id = request.identity.attempt_id
                    c5_owner_generation = request.identity.owner_generation
                    effect_started = True
                await supervisor.start_session(
                    session_port=adapter,
                    launch_request=request,
                    correlation_id=correlation_id,
                )
                owner, authority = policy.bind_authority(request)
                capability = bind_capability_query_worker_adapter(
                    supervisor=supervisor,
                    binding=authority.binding,
                    authority_reader=authority.current_authority,
                    enabled=True,
                )
                admitted = capability.admit()
                descriptors = await capability.describe()
                if (
                    len(descriptors) != 1
                    or descriptors[0].capability_id != policy.capability_id
                    or descriptors[0].facet_ids != (policy.facet_id,)
                ):
                    raise failure(error_prefix + "_contract_mismatch")

                async def release_attempt() -> None:
                    if supervisor.status.state == "healthy":
                        await supervisor.shutdown()

                inputs = policy.prepare_inputs(
                    owner=owner,
                    authority=authority,
                    capability=capability,
                    admitted=admitted,
                    release_attempt=release_attempt,
                )
                session = policy.create_session(inputs)
                await session.prepare_model_call_runtime()
                coordinator.publish(
                    receipt=receipt,
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
                result = await policy.query(session, symbol)
                if (
                    activation.authority.current_witness(receipt)
                    != receipt.authority_witness
                ):
                    raise failure(error_prefix + "_receipt_stale")
                return result
            finally:
                try:
                    try:
                        if session is not None:
                            await session.dispose()
                    finally:
                        if supervisor.status.state == "healthy":
                            await supervisor.shutdown()
                        elif supervisor.status.state not in {
                            "stopped",
                            "failed",
                            "fenced",
                        }:
                            await supervisor.fence(code=error_prefix + "_failed")
                finally:
                    gate.close()
                    try:
                        await profile.close()
                    finally:
                        try:
                            await host.close()
                        finally:
                            if supervisor.status.state in {"failed", "fenced"}:
                                await supervisor.settle_failed_process()
    except BaseException as error:
        query_error = error
        raise
    finally:
        try:
            try:
                settle_c5()
            except BaseException as cleanup_error:
                if query_error is None:
                    raise
                query_error.add_note(cleanup_note + type(cleanup_error).__name__)
        finally:
            runtime.dispose_runtime()
