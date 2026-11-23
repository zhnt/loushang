"""One selected Worker query inside the existing Product Session lifetime.

Original Worker, Hosting, C5, Graph and Product owners retain their authority.
This fixed program holds only the original local resources and error domain;
it adds no controller, registry, journal, retry task or phase dispatcher.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.transcript.product_session import ProductTranscriptSession
from loushang.harness.worker._native_profile_bridge import (
    ProductWorkerNativeProfilePort,
)
from loushang.harness.worker._ordinary_prepare import (
    _ActivationInputs,
    _admitted_worker_coordinator,
    _Evidence,
    _Gate,
    _publish_native_worker_activation,
    _settle_posix_worker,
)
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
)
from loushang.harness.worker.contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerLaunchIdentityV1,
)
from loushang.harness.worker.gated_start import bind_worker_gated_start_release
from loushang.harness.worker.hosting_adapter import HostingManagedWorkerSessionAdapter
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationReceiptV1,
)
from loushang.harness.worker.supervisor import WorkerSupervisor
from loushang.hosting.runtime import create_child_session_host

from ._worker_provider import _admit_worker_query_adapter, _QueryAuthority
from .agent_product import AgentProductSession, _create_query_only_session
from .capability_composition_inputs import SessionCapabilityCompositionInputs

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PosixLocalWheelProductSessionOwner,
    )

_PayloadT = TypeVar("_PayloadT")
_NativeT = TypeVar("_NativeT")
_TranscriptT = TypeVar("_TranscriptT", bound=ProductTranscriptSession[Any, Any])


class _OperatorLaunchSource(_ActivationInputs, Protocol[_PayloadT, _NativeT]):
    def _materialize_worker_payload(
        self, receipt: ProductWorkerActivationReceiptV1, attempt_id: str
    ) -> AbstractContextManager[_PayloadT]: ...
    def _bind_worker_launch_request(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        payload: _PayloadT,
        *,
        supervisor_epoch: int,
    ) -> ManagedWorkerLaunchRequestV1: ...
    def current_native_launch_material(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> _NativeT: ...
    def _worker_start_gate(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        attempt_id: str,
    ) -> _Gate: ...
    def _worker_profile_from_material(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        native: _NativeT,
        request: ManagedWorkerLaunchRequestV1,
        gate: _Gate,
    ) -> ProductWorkerNativeProfilePort: ...


class _OperatorQueryPolicy(Protocol):
    @property
    def receipt(self) -> ProductWorkerActivationReceiptV1: ...

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
    def query(self, session: AgentProductSession, symbol: str) -> Awaitable[str]: ...


async def _query_selected_worker_once(
    *,
    product: PosixLocalWheelProductSessionOwner,
    product_id: str,
    workspace: Path,
    session_file: Path,
    transcript_type: type[_TranscriptT],
    open_query: Callable[
        [PackageProductRuntimeBindingV1, Path, _TranscriptT],
        tuple[_OperatorLaunchSource[_PayloadT, _NativeT], _OperatorQueryPolicy] | None,
    ],
    symbol: str,
    failure: Callable[[str], RuntimeError],
    error_prefix: str,
    correlation_id: str,
    cleanup_note: str,
) -> str:
    if session_file.is_symlink() or not session_file.is_file():
        raise failure(error_prefix + "_session_unavailable")
    session_file = session_file.resolve(strict=True)
    manager = await transcript_type.load(session_file)
    session_id = manager.get_header().conversation_id
    runtime = product.factory_for_session(
        session_id=session_id,
        cwd=workspace,
        runtime_id="worker-query-" + secrets.token_hex(16),
    ).create(
        PackageProductRuntimeRequestV1(
            product_id=product_id,
            session_id=session_id,
            cwd=str(workspace),
        )
    )
    receipt: ProductWorkerActivationReceiptV1 | None = None
    coordinator: ProductWorkerActivationCoordinator | None = None
    cleanup_evidence: _Evidence | None = None
    c5_identity: WorkerLaunchIdentityV1 | None = None
    host_identity: str | None = None
    boot_identity: str | None = None

    def settle_c5() -> None:
        if c5_identity is None:
            return
        assert receipt is not None
        assert coordinator is not None
        assert cleanup_evidence is not None
        assert host_identity is not None
        assert boot_identity is not None
        _settle_posix_worker(
            coordinator,
            cleanup_evidence,
            receipt,
            c5_identity,
            host_identity=host_identity,
            boot_identity=boot_identity,
        )

    query_error: BaseException | None = None
    try:
        runtime.activate()
        selected = open_query(runtime, session_file, manager)
        if selected is None:
            raise failure(error_prefix + "_not_selected")
        source, policy = selected
        receipt = policy.receipt
        attempt_id = secrets.token_hex(16)
        with source._materialize_worker_payload(receipt, attempt_id) as payload:
            journal = source._open_worker_supervisor_journal()
            probe = source._bind_worker_launch_request(
                receipt, payload, supervisor_epoch=1
            )
            next_epoch = journal.next_supervisor_epoch(probe.identity)
            request = (
                probe
                if next_epoch == 1
                else source._bind_worker_launch_request(
                    receipt, payload, supervisor_epoch=next_epoch
                )
            )
            native = source.current_native_launch_material(receipt)
            gate = source._worker_start_gate(receipt, request, attempt_id)
            profile = None
            host = None
            supervisor: WorkerSupervisor | None = None
            session: AgentProductSession | None = None
            try:
                profile = source._worker_profile_from_material(
                    receipt, native, request, gate
                )
                host = create_child_session_host(
                    max_sessions=1, enable_posix_static_capture=True
                )
                active_supervisor = supervisor = WorkerSupervisor(
                    identity=request.identity,
                    journal=journal,
                    protocol=request.runtime.protocol,
                    protocol_version=request.runtime.protocol_version,
                )
                adapter = HostingManagedWorkerSessionAdapter(
                    hosting=host,
                    preparation=profile,
                    start_gate=bind_worker_gated_start_release(gate),
                )
                cleanup_evidence = source._worker_evidence(receipt)
                coordinator = _admitted_worker_coordinator(
                    source, cleanup_evidence, receipt, failure,
                    refusal_code=error_prefix + "_c5_admission_refused",
                )
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
                    c5_identity = request.identity
                await active_supervisor.start_session(
                    session_port=adapter,
                    launch_request=request,
                    correlation_id=correlation_id,
                )
                owner, authority = policy.bind_authority(request)
                capability, admitted = await _admit_worker_query_adapter(
                    supervisor=active_supervisor,
                    authority=authority,
                    capability_id=policy.capability_id,
                    facet_id=policy.facet_id,
                    failure=failure,
                    descriptor_mismatch=error_prefix + "_contract_mismatch",
                )

                async def release_attempt() -> None:
                    if active_supervisor.status.state == "healthy":
                        await active_supervisor.shutdown()

                inputs = policy.prepare_inputs(
                    owner=owner,
                    authority=authority,
                    capability=capability,
                    admitted=admitted,
                    release_attempt=release_attempt,
                )
                session = _create_query_only_session(
                    manager, inputs, product_id=product_id,
                    failure=failure, error_prefix=error_prefix,
                )
                await session.prepare_model_call_runtime()
                _publish_native_worker_activation(
                    coordinator, receipt, request.identity, profile
                )
                result = await policy.query(session, symbol)
                if (
                    source._worker_activation_authority.current_witness(receipt)
                    != receipt.authority_witness
                ):
                    raise failure(error_prefix + "_receipt_stale")
                return result
            finally:
                try:
                    if supervisor is not None:
                        try:
                            if session is not None:
                                await session.dispose()
                        finally:
                            if supervisor.status.state == "healthy":
                                await supervisor.shutdown()
                            elif supervisor.status.state not in {"stopped", "failed", "fenced"}:
                                await supervisor.fence(code=error_prefix + "_failed")
                finally:
                    gate.close()
                    try:
                        if profile is not None:
                            await profile.close()
                    finally:
                        try:
                            if host is not None:
                                await host.close()
                        finally:
                            if supervisor is not None and supervisor.status.state in {"failed", "fenced"}:
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
