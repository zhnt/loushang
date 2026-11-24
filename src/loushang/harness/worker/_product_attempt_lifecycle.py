"""One exact hosted Worker attempt over the existing lifecycle authorities.

This layer serializes the original start/rollback/recover/close program. It
neither selects a Product nor creates authority, a second state machine, native
resources or durable facts. Domain error/status projection stays at the caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Generic, Literal, NoReturn, Protocol, TypeVar, cast

from loushang.hosting.contracts import ChildSessionHostingPort

from ._native_profile_bridge import (
    ProductWorkerNativeProfilePort,
    _bind_posix_static_contained_product_worker_profile,
    _bind_windows_lpac_contained_product_worker_profile,
    _WindowsLpacProductWorkerProfilePlan,
    _WindowsLpacProvisioningStateStore,
)
from .capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    bind_capability_query_worker_adapter,
)
from .contracts import ManagedWorkerLaunchRequestV1, WorkerBindingError
from .gated_start import _ProductGatePort, bind_worker_gated_start_release
from .hosting_adapter import HostingManagedWorkerSessionAdapter
from .owner_selection import WorkerHostingActivationV1, WorkerSessionOwnerRouter
from .product_activation import (
    ProductWorkerActivationAuthorityPort,
    ProductWorkerActivationCoordinator,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)
from .session import ManagedWorkerSessionLaunchPort
from .supervisor import WorkerSupervisor

_WorkerReadiness = Literal[
    "current", "selected", "starting", "ready", "degraded", "unavailable", "rolled_back"
]


class _LifecycleStatus(Protocol):
    @property
    def readiness(self) -> str: ...
    @property
    def effective_owner(self) -> str: ...


_StatusT = TypeVar("_StatusT", bound=_LifecycleStatus)


class _StartGatePort(_ProductGatePort, Protocol):
    @property
    def start_gate_read_fd(self) -> int: ...


class _WorkerDomainPort(Protocol):
    """Capability-owner operations needed by the Product composition."""

    async def publish(
        self,
        *,
        adapter: CapabilityQueryWorkerAdapter,
        admission: CapabilityWorkerAdmissionV1,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
    ) -> None: ...

    async def fence_attempt(
        self, *, receipt_fingerprint: str, attempt_id: str, owner_generation: int
    ) -> None: ...

    async def revoke_and_drain(
        self, *, receipt_fingerprint: str, attempt_id: str, owner_generation: int
    ) -> None: ...

    async def settle_readiness(
        self, *, required: bool, ready: bool, code: str
    ) -> None: ...

    async def issue_current(self, *, prior_receipt_fingerprint: str) -> object: ...


class _WorkerCleanupPort(Protocol):
    """Platform owner that records settlement or durable cleanup debt."""

    async def settle(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        protocol_terminal: bool,
        domain_retired: bool,
        native_containment_witness: object | None = None,
    ) -> None: ...


class _WorkerRecoveryPort(Protocol):
    """Durable recovery drill owned by the injected lifecycle authorities."""

    async def recover(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
    ) -> tuple[str, ...]: ...


def _require_worker_machine_identity(
    value: object, *, name: str, failure: Callable[[str, str], RuntimeError]
) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 128
        or any(character.isspace() for character in value)
    ):
        raise failure(
            f"Worker {name} is invalid",
            "worker_machine_identity_invalid",
        )


def _require_worker_composition_digest(
    value: object, *, name: str, failure: Callable[[str, str], RuntimeError]
) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise failure(
            f"Worker {name} is invalid",
            "worker_composition_digest_invalid",
        )


def _bind_selected_worker_components(
    *,
    policy: ProductWorkerActivationPolicyV1,
    posix_profile_id: str,
    windows_profile_id: str,
    failure: Callable[[str, str], RuntimeError],
    error_code_prefix: str,
    receipt: ProductWorkerActivationReceiptV1,
    start_gate: _StartGatePort | None,
    require_start_gate: Callable[[ManagedWorkerLaunchRequestV1], None],
    start_gate_error: type[RuntimeError],
    authority: ProductWorkerActivationAuthorityPort | None,
    evidence_authority: object | None,
    trusted_evidence_authority_id: str | None,
    trusted_evidence_authority_fingerprint: str | None,
    activation_state_store: object | None,
    restart_budget: int,
    supervisor: WorkerSupervisor | None,
    request: ManagedWorkerLaunchRequestV1 | None,
    current_owner: ManagedWorkerSessionLaunchPort | None,
    hosting: object | None,
    containment_launcher_path: str | None,
    containment_launcher_sha256: str | None,
    containment_profile_sha256: str | None,
    windows_lpac_plan: _WindowsLpacProductWorkerProfilePlan | None,
    windows_platform_imports: tuple[str, ...] | None,
    native_provisioning_state_store: object | None,
    capability_binding: CapabilityWorkerBindingV1 | None,
    capability_authority_reader: Callable[[], CapabilityWorkerAuthorityV1] | None,
    domain: _WorkerDomainPort | None,
    cleanup: _WorkerCleanupPort | None,
    recovery: _WorkerRecoveryPort | None,
    host_identity: str | None,
    boot_identity: str | None,
) -> tuple[
    ManagedWorkerLaunchRequestV1,
    ProductWorkerNativeProfilePort,
    ProductWorkerActivationCoordinator,
    WorkerSessionOwnerRouter,
]:
    """Validate and bind the native profile, activation authority and exact route."""

    def binding_failure(message: str, reason: str) -> RuntimeError:
        return failure(message, error_code_prefix + reason)

    def reject(reason: str) -> NoReturn:
        raise binding_failure("Worker canary composition was rejected", reason)

    if policy.native_profile_id not in (posix_profile_id, windows_profile_id):
        reject("worker_native_profile_unsupported")
    _require_worker_machine_identity(host_identity, name="host identity", failure=binding_failure)
    _require_worker_machine_identity(boot_identity, name="boot identity", failure=binding_failure)
    if authority is None or any(
        not callable(getattr(authority, name, None))
        for name in (
            "serialized_admission",
            "current_witness",
            "latch_kill_switch",
        )
    ):
        reject("worker_composition_incomplete")
    if evidence_authority is None or any(
        not callable(getattr(evidence_authority, name, None))
        for name in (
            "verify_tree_settlement",
            "verify_changed_boot_absence",
            "verify_registered_lease_expired",
        )
    ):
        reject("worker_composition_incomplete")
    if (
        policy.native_profile_id == windows_profile_id
        and not callable(
            getattr(evidence_authority, "verify_native_containment_settlement", None)
        )
    ):
        reject("worker_composition_incomplete")
    _require_worker_machine_identity(
        trusted_evidence_authority_id,
        name="cleanup evidence authority identity",
        failure=binding_failure,
    )
    _require_worker_composition_digest(
        trusted_evidence_authority_fingerprint,
        name="cleanup evidence authority fingerprint",
        failure=binding_failure,
    )
    if activation_state_store is None or any(
        not callable(getattr(activation_state_store, name, None))
        for name in ("load", "compare_and_swap")
    ):
        reject("worker_composition_incomplete")
    if type(restart_budget) is not int or restart_budget < 0:
        reject("worker_composition_incomplete")
    if not isinstance(supervisor, WorkerSupervisor):
        reject("worker_composition_incomplete")
    if not isinstance(request, ManagedWorkerLaunchRequestV1):
        reject("worker_composition_incomplete")
    if supervisor.identity != request.identity:
        reject("worker_supervisor_identity_mismatch")
    if not callable(getattr(current_owner, "start", None)) or hosting is None:
        reject("worker_composition_incomplete")
    _require_worker_composition_digest(
        containment_launcher_sha256,
        name="containment launcher digest",
        failure=binding_failure,
    )
    _require_worker_composition_digest(
        containment_profile_sha256,
        name="containment profile digest",
        failure=binding_failure,
    )
    if policy.native_profile_id == posix_profile_id:
        if (
            not isinstance(containment_launcher_path, str)
            or not containment_launcher_path
            or windows_lpac_plan is not None
            or windows_platform_imports is not None
            or native_provisioning_state_store is not None
        ):
            reject("worker_composition_incomplete")
    elif (
        containment_launcher_path is not None
        or type(windows_lpac_plan) is not _WindowsLpacProductWorkerProfilePlan
        or not isinstance(windows_platform_imports, tuple)
        or not windows_platform_imports
        or any(
            not isinstance(name, str) or not name for name in windows_platform_imports
        )
        or native_provisioning_state_store is None
        or any(
            not callable(getattr(native_provisioning_state_store, name, None))
            for name in ("load", "compare_and_swap")
        )
        or native_provisioning_state_store is activation_state_store
    ):
        reject("worker_composition_incomplete")
    if (
        policy.native_profile_id == windows_profile_id
        and cast(
            _WindowsLpacProductWorkerProfilePlan,
            windows_lpac_plan,
        ).containment_profile_sha256
        != containment_profile_sha256
    ):
        reject("worker_native_provisioning_fingerprint_mismatch")
    if not isinstance(capability_binding, CapabilityWorkerBindingV1) or not callable(
        capability_authority_reader
    ):
        reject("worker_composition_incomplete")
    for owner, methods in (
        (
            domain,
            (
                "publish",
                "fence_attempt",
                "revoke_and_drain",
                "settle_readiness",
                "issue_current",
            ),
        ),
        (cleanup, ("settle",)),
        (recovery, ("recover",)),
    ):
        if owner is None or any(
            not callable(getattr(owner, method, None)) for method in methods
        ):
            reject("worker_composition_incomplete")
    identity = request.identity
    if not ProductWorkerActivationPolicyV1._matches_launch_identity(policy, identity):
        reject("worker_request_identity_mismatch")
    if (
        not CapabilityWorkerBindingV1._matches_launch_contribution(
            capability_binding, identity
        )
        or capability_binding.authority.product_policy_revision != policy.product_policy_revision
    ):
        reject("worker_capability_binding_mismatch")

    require_start_gate(request)
    assert trusted_evidence_authority_id is not None
    assert trusted_evidence_authority_fingerprint is not None
    assert containment_launcher_sha256 is not None
    assert containment_profile_sha256 is not None
    try:
        if policy.native_profile_id == posix_profile_id:
            assert containment_launcher_path is not None
            native_profile = _bind_posix_static_contained_product_worker_profile(
                receipt=receipt,
                worker_request=request,
                native_profile_catalog_revision=policy.native_profile_catalog_revision,
                launcher_path=containment_launcher_path,
                launcher_sha256=containment_launcher_sha256,
                containment_profile_sha256=containment_profile_sha256,
                start_gate_read_fd=(
                    None if start_gate is None else start_gate.start_gate_read_fd
                ),
            )
        else:
            assert windows_lpac_plan is not None
            assert windows_platform_imports is not None
            native_profile = _bind_windows_lpac_contained_product_worker_profile(
                receipt=receipt,
                worker_request=request,
                plan=windows_lpac_plan,
                platform_imports=windows_platform_imports,
                provisioning_state_store=cast(
                    _WindowsLpacProvisioningStateStore, native_provisioning_state_store
                ),
            )
    except WorkerBindingError as exc:
        raise failure("Worker native profile was rejected", exc.code) from exc
    except start_gate_error as exc:
        raise failure("Worker start gate is unavailable", getattr(exc, "code")) from exc
    except (TypeError, ValueError) as exc:
        raise binding_failure(
            "Worker native profile configuration was rejected",
            "worker_native_profile_configuration_invalid",
        ) from exc
    try:
        coordinator = ProductWorkerActivationCoordinator(
            authority=authority,
            evidence_authority=evidence_authority,
            trusted_evidence_authority_id=trusted_evidence_authority_id,
            trusted_evidence_authority_fingerprint=(
                trusted_evidence_authority_fingerprint
            ),
            state_store=activation_state_store,
            restart_budget=restart_budget,
        )
    except Exception as exc:
        raise binding_failure(
            "Worker activation composition was rejected",
            "worker_activation_composition_rejected",
        ) from exc
    session_port = WorkerSessionOwnerRouter(
        current=cast(ManagedWorkerSessionLaunchPort, current_owner),
        hosting=HostingManagedWorkerSessionAdapter(
            hosting=cast(ChildSessionHostingPort, hosting),
            preparation=native_profile,
            start_gate=(
                None
                if start_gate is None
                else bind_worker_gated_start_release(start_gate)
            ),
        ),
        activation=WorkerHostingActivationV1(owner="hosting"),
    )
    return request, native_profile, coordinator, session_port


class _ActivationAdmissionLease(Protocol):
    def __enter__(self) -> _ActivationAdmissionLease: ...

    def __exit__(self, *error: object) -> object: ...

    def begin_effect(self) -> None: ...


class _ProductWorkerAttemptLifecycle(Generic[_StatusT]):
    def __init__(
        self,
        *,
        policy: ProductWorkerActivationPolicyV1 | None,
        receipt: ProductWorkerActivationReceiptV1 | None,
        coordinator: ProductWorkerActivationCoordinator | None,
        supervisor: WorkerSupervisor | None,
        request: ManagedWorkerLaunchRequestV1 | None,
        session_port: WorkerSessionOwnerRouter | None,
        native_profile: ProductWorkerNativeProfilePort | None,
        capability_binding: CapabilityWorkerBindingV1 | None,
        capability_authority_reader: Callable[[], CapabilityWorkerAuthorityV1] | None,
        domain: _WorkerDomainPort | None,
        cleanup: _WorkerCleanupPort | None,
        recovery: _WorkerRecoveryPort | None,
        host_identity: str | None,
        boot_identity: str | None,
        status: _StatusT,
        start_gate: _StartGatePort | None = None,
    ) -> None:
        self._policy = policy
        self._receipt = receipt
        self._coordinator = coordinator
        self._supervisor = supervisor
        self._request = request
        self._session_port = session_port
        self._native_profile = native_profile
        self._capability_binding = capability_binding
        self._capability_authority_reader = capability_authority_reader
        self._domain = domain
        self._cleanup = cleanup
        self._recovery = recovery
        self._host_identity = host_identity
        self._boot_identity = boot_identity
        self._status = status
        self._start_gate = start_gate
        self._adapter: CapabilityQueryWorkerAdapter | None = None
        self._operation_lock = asyncio.Lock()
        self._closed = False

    async def start(self, *, correlation_id: str) -> _StatusT:
        """Start, handshake, admit, and publish exactly one Hosting attempt."""
        async with self._operation_lock:
            if self._closed:
                raise self._lifecycle_error(
                    "closed", code=self._lifecycle_code("worker_closed")
                )
            if self._status.readiness == "ready":
                return self._status
            if self._status.effective_owner != "hosting":
                return self._status
            if self._start_gate is not None:
                try:
                    self._start_gate.start_gate_read_fd
                except RuntimeError as exc:
                    raise self._lifecycle_error(
                        "gate_consumed",
                        code=self._lifecycle_code("worker_start_gate_consumed"),
                    ) from exc
            self._require_selected_components()
            policy = cast(ProductWorkerActivationPolicyV1, self._policy)
            receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
            coordinator = cast(ProductWorkerActivationCoordinator, self._coordinator)
            supervisor = cast(WorkerSupervisor, self._supervisor)
            request = cast(ManagedWorkerLaunchRequestV1, self._request)
            session_port = cast(WorkerSessionOwnerRouter, self._session_port)
            domain = cast(_WorkerDomainPort, self._domain)
            decision = coordinator.evaluate(policy, receipt)
            if decision.get("reason") != "admitted":
                if self._start_gate is not None:
                    self._start_gate.close()
                return await self._settle_closed_decision(
                    code=self._lifecycle_reason(decision.get("reason"))
                )
            self._status = self._attempt_status(
                code=self._lifecycle_code("worker_starting"), readiness="starting"
            )
            effect_started = False
            domain_publish_started = False
            try:
                lease = cast(
                    _ActivationAdmissionLease,
                    coordinator.admission(
                        policy=policy,
                        receipt=receipt,
                        attempt_id=request.identity.attempt_id,
                        owner_generation=request.identity.owner_generation,
                        host_identity=cast(str, self._host_identity),
                        boot_identity=cast(str, self._boot_identity),
                        cleanup_contract_version=cast(
                            ProductWorkerNativeProfilePort, self._native_profile
                        ).cleanup_contract_version,
                    ),
                )
                with lease:
                    lease.begin_effect()
                    effect_started = True
                await supervisor.start_session(
                    session_port=session_port,
                    launch_request=request,
                    correlation_id=correlation_id,
                )
                adapter = bind_capability_query_worker_adapter(
                    supervisor=supervisor,
                    binding=cast(CapabilityWorkerBindingV1, self._capability_binding),
                    authority_reader=cast(
                        Callable[[], CapabilityWorkerAuthorityV1],
                        self._capability_authority_reader,
                    ),
                    enabled=True,
                )
                admission = adapter.admit()
                coordinator.publish(
                    receipt=receipt,
                    attempt_id=request.identity.attempt_id,
                    owner_generation=request.identity.owner_generation,
                    realized_native_policy_closure_fingerprint=cast(
                        ProductWorkerNativeProfilePort, self._native_profile
                    ).realized_native_policy_closure_fingerprint,
                    native_profile_catalog_revision=policy.native_profile_catalog_revision,
                    native_profile_id=policy.native_profile_id,
                )
                domain_publish_started = True
                await domain.publish(
                    adapter=adapter,
                    admission=admission,
                    receipt_fingerprint=receipt.fingerprint,
                    attempt_id=request.identity.attempt_id,
                    owner_generation=request.identity.owner_generation,
                )
                self._adapter = adapter
                await domain.settle_readiness(
                    required=policy.effective_required,
                    ready=True,
                    code=self._lifecycle_code("worker_ready"),
                )
                self._status = self._attempt_status(
                    code=self._lifecycle_code("worker_ready"), readiness="ready"
                )
                return self._status
            except asyncio.CancelledError:
                if self._start_gate is not None:
                    self._start_gate.close()
                if effect_started:
                    await self._reclaim_failed_attempt(
                        domain_publish_started=domain_publish_started
                    )
                raise
            except BaseException as exc:
                if self._start_gate is not None:
                    self._start_gate.close()
                if effect_started:
                    await self._reclaim_failed_attempt(
                        domain_publish_started=domain_publish_started
                    )
                readiness: _WorkerReadiness = (
                    "unavailable" if policy.effective_required else "degraded"
                )
                code = (
                    self._lifecycle_code("worker_required_unavailable")
                    if policy.effective_required
                    else self._lifecycle_code("worker_optional_degraded")
                )
                self._status = self._attempt_status(code=code, readiness=readiness)
                await domain.settle_readiness(
                    required=policy.effective_required, ready=False, code=code
                )
                if policy.effective_required:
                    raise self._lifecycle_error("required_start", code=code) from exc
                return self._status

    async def rollback(self) -> _StatusT:
        """Run the fixed latch-first rollback sequence without same-attempt fallback."""
        async with self._operation_lock:
            if self._closed:
                raise self._lifecycle_error(
                    "closed", code=self._lifecycle_code("worker_closed")
                )
            if self._start_gate is not None:
                self._start_gate.close()
            self._require_selected_components()
            policy = cast(ProductWorkerActivationPolicyV1, self._policy)
            receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
            coordinator = cast(ProductWorkerActivationCoordinator, self._coordinator)
            supervisor = cast(WorkerSupervisor, self._supervisor)
            request = cast(ManagedWorkerLaunchRequestV1, self._request)
            domain = cast(_WorkerDomainPort, self._domain)
            cleanup = cast(_WorkerCleanupPort, self._cleanup)
            session_port = cast(WorkerSessionOwnerRouter, self._session_port)
            coordinator.latch_kill_switch(
                expected_generation=policy.kill_switch_generation
            )
            session_port.rollback_to_current()
            await domain.fence_attempt(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
            await domain.revoke_and_drain(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
            coordinator.retire_exact(
                receipt=receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
            await supervisor.fence(code=self._lifecycle_code("worker_rollback"))
            coordinator.record_protocol_terminal(
                receipt=receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
            await cleanup.settle(
                receipt=receipt,
                request=request,
                protocol_terminal=True,
                domain_retired=True,
                **self._native_cleanup_witness_arguments(),
            )
            await domain.settle_readiness(
                required=policy.effective_required,
                ready=False,
                code=self._lifecycle_code("worker_rollback_latched"),
            )
            await domain.issue_current(prior_receipt_fingerprint=receipt.fingerprint)
            self._status = self._attempt_status(
                code=self._lifecycle_code("worker_rollback_latched"),
                readiness="rolled_back",
                effective_owner="current",
            )
            return self._status

    async def recover(self) -> tuple[str, ...]:
        """Require the complete ordered durable recovery matrix."""
        async with self._operation_lock:
            if self._closed:
                raise self._lifecycle_error(
                    "closed", code=self._lifecycle_code("worker_closed")
                )
            if self._start_gate is not None:
                self._start_gate.close()
            self._require_selected_components()
            recovery = cast(_WorkerRecoveryPort, self._recovery)
            steps = await recovery.recover(
                receipt=cast(ProductWorkerActivationReceiptV1, self._receipt),
                request=cast(ManagedWorkerLaunchRequestV1, self._request),
            )
            if steps != self._expected_recovery_steps():
                raise self._lifecycle_error(
                    "recovery_incomplete",
                    code=self._lifecycle_code("worker_recovery_incomplete"),
                )
            return steps

    async def close(self) -> None:
        """Settle this exact Product attempt without changing Product policy."""
        async with self._operation_lock:
            if self._closed:
                return
            if self._start_gate is not None:
                self._start_gate.close()
            if self._status.effective_owner != "hosting" or self._receipt is None:
                self._closed = True
                return
            self._require_selected_components()
            policy = cast(ProductWorkerActivationPolicyV1, self._policy)
            native_profile = cast(ProductWorkerNativeProfilePort, self._native_profile)
            if self._status.readiness == "ready":
                await self._close_ready_attempt()
            else:
                await native_profile.close()
            domain = cast(_WorkerDomainPort, self._domain)
            code = self._lifecycle_code("worker_session_closed")
            await domain.settle_readiness(
                required=policy.effective_required, ready=False, code=code
            )
            self._status = self._attempt_status(
                code=code,
                readiness="unavailable" if policy.effective_required else "degraded",
            )
            self._closed = True

    async def _close_ready_attempt(self) -> None:
        receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
        request = cast(ManagedWorkerLaunchRequestV1, self._request)
        domain = cast(_WorkerDomainPort, self._domain)
        coordinator = cast(ProductWorkerActivationCoordinator, self._coordinator)
        supervisor = cast(WorkerSupervisor, self._supervisor)
        native_profile = cast(ProductWorkerNativeProfilePort, self._native_profile)
        cleanup = cast(_WorkerCleanupPort, self._cleanup)
        await domain.fence_attempt(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=request.identity.attempt_id,
            owner_generation=request.identity.owner_generation,
        )
        await domain.revoke_and_drain(
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=request.identity.attempt_id,
            owner_generation=request.identity.owner_generation,
        )
        coordinator.retire_exact(
            receipt=receipt,
            attempt_id=request.identity.attempt_id,
            owner_generation=request.identity.owner_generation,
        )
        try:
            await supervisor.shutdown(
                reason=self._lifecycle_code("product_session_close")
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            await supervisor.fence(
                code=self._lifecycle_code("worker_session_close_fenced")
            )
        coordinator.record_protocol_terminal(
            receipt=receipt,
            attempt_id=request.identity.attempt_id,
            owner_generation=request.identity.owner_generation,
        )
        await native_profile.close()
        await cleanup.settle(
            receipt=receipt,
            request=request,
            protocol_terminal=True,
            domain_retired=True,
            **self._native_cleanup_witness_arguments(),
        )

    async def _reclaim_failed_attempt(self, *, domain_publish_started: bool) -> None:
        receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
        request = cast(ManagedWorkerLaunchRequestV1, self._request)
        domain = cast(_WorkerDomainPort, self._domain)
        coordinator = cast(ProductWorkerActivationCoordinator, self._coordinator)
        supervisor = cast(WorkerSupervisor, self._supervisor)
        cleanup = cast(_WorkerCleanupPort, self._cleanup)
        with suppress(BaseException):
            await domain.fence_attempt(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
        if domain_publish_started:
            with suppress(BaseException):
                await domain.revoke_and_drain(
                    receipt_fingerprint=receipt.fingerprint,
                    attempt_id=request.identity.attempt_id,
                    owner_generation=request.identity.owner_generation,
                )
        with suppress(BaseException):
            coordinator.retire_exact(
                receipt=receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
        with suppress(BaseException):
            await supervisor.fence(code=self._lifecycle_code("worker_start_failed"))
        with suppress(BaseException):
            coordinator.record_protocol_terminal(
                receipt=receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
        with suppress(BaseException):
            await cleanup.settle(
                receipt=receipt,
                request=request,
                protocol_terminal=True,
                domain_retired=True,
                **self._native_cleanup_witness_arguments(),
            )

    def _native_cleanup_witness_arguments(self) -> dict[str, object]:
        native_profile = cast(ProductWorkerNativeProfilePort, self._native_profile)
        if native_profile.cleanup_contract_version == 1:
            return {}
        if native_profile.cleanup_contract_version != 2:
            raise self._lifecycle_error(
                "cleanup_contract",
                code=self._lifecycle_code("worker_cleanup_contract_unsupported"),
            )
        native_witness = native_profile.native_containment_settlement_witness()
        if native_witness is None:
            raise self._lifecycle_error(
                "native_settlement",
                code=self._lifecycle_code("worker_native_containment_unsettled"),
            )
        return {"native_containment_witness": native_witness}

    async def _settle_closed_decision(self, *, code: str) -> _StatusT:
        policy = cast(ProductWorkerActivationPolicyV1, self._policy)
        native_profile = cast(ProductWorkerNativeProfilePort, self._native_profile)
        readiness: _WorkerReadiness = (
            "unavailable" if policy.effective_required else "degraded"
        )
        stable_code = (
            self._lifecycle_code("worker_required_unavailable")
            if policy.effective_required
            else self._lifecycle_code("worker_optional_degraded")
        )
        domain = cast(_WorkerDomainPort, self._domain)
        await native_profile.close()
        await domain.settle_readiness(
            required=policy.effective_required, ready=False, code=code
        )
        self._status = self._attempt_status(code=stable_code, readiness=readiness)
        if policy.effective_required:
            raise self._lifecycle_error("required_rejected", code=stable_code)
        return self._status

    def _require_selected_components(self) -> None:
        components = (
            self._policy,
            self._receipt,
            self._coordinator,
            self._supervisor,
            self._request,
            self._session_port,
            self._native_profile,
            self._capability_binding,
            self._capability_authority_reader,
            self._domain,
            self._cleanup,
            self._recovery,
            self._host_identity,
            self._boot_identity,
        )
        if any((item is None for item in components)):
            raise self._lifecycle_error(
                "composition",
                code=self._lifecycle_code("worker_composition_incomplete"),
            )

    def _lifecycle_code(self, reason: str) -> str:
        raise NotImplementedError

    def _lifecycle_reason(self, value: object) -> str:
        raise NotImplementedError

    def _lifecycle_error(self, message: str, *, code: str) -> RuntimeError:
        raise NotImplementedError

    def _expected_recovery_steps(self) -> tuple[str, ...]:
        raise NotImplementedError

    def _attempt_status(
        self,
        *,
        code: str,
        readiness: _WorkerReadiness,
        effective_owner: Literal["current", "hosting"] = "hosting",
    ) -> _StatusT:
        raise NotImplementedError
