"""Explicit Linux-only Coding Product composition for a local Plugin Worker.

The Product owns selection and readiness.  Harness owns Worker lifecycle and
native-profile capabilities, while Hosting owns every process, endpoint, and
platform resource.  This module joins those already-authorized capabilities;
it never imports Hosting or manufactures native material.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, NoReturn, Protocol, cast

from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    HostingManagedWorkerSessionAdapter,
    ManagedWorkerLaunchRequestV1,
    ManagedWorkerSessionLaunchPort,
    ProductWorkerActivationAuthorityPort,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
    ProductWorkerNativeProfilePort,
    WorkerBindingError,
    WorkerHostingActivationV1,
    WorkerSessionOwnerRouter,
    WorkerSupervisor,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker._native_profile_bridge import (
    _bind_posix_static_contained_product_worker_profile,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
)

CODING_PRODUCT_WORKER_CANARY_VERSION = 1
CODING_PRODUCT_WORKER_CANARY_ENTRYPOINTS = ("cli", "product", "tui")
CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID = "posix-static-contained-elf-v1"

CodingWorkerCanaryReadiness = Literal[
    "current",
    "selected",
    "starting",
    "ready",
    "degraded",
    "unavailable",
    "rolled_back",
]

_ROLLBACK_STEPS = (
    "R1-LATCH-FUTURE",
    "R2-FENCE-ATTEMPTS",
    "R3-REVOKE-DRAIN",
    "R4-TERMINATE-TREE",
    "R5-SETTLE-OR-DEBT",
    "R6-SETTLE-READINESS",
    "R7-ISSUE-CURRENT",
)
_RECOVERY_STEPS = (
    "V1-PRIOR-ABSENT",
    "V2-EXACT-REAPED",
    "V3-SAMEBOOT-UNKNOWN",
    "V4-CHANGEDBOOT-ABSENT",
    "V5-BUDGET-EXHAUSTED",
    "V6-HOST-RESTART",
)


class CodingProductWorkerCanaryError(RuntimeError):
    """Stable, redacted Product-composition failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingProductWorkerCanaryStatusV1:
    """Bounded pathless readiness projection for the Coding canary."""

    code: str
    readiness: CodingWorkerCanaryReadiness
    required: bool
    requested_owner: Literal["current", "hosting"]
    effective_owner: Literal["current", "hosting"]
    receipt_fingerprint: str | None = None
    attempt_id: str | None = None
    owner_generation: int | None = None
    status_version: int = CODING_PRODUCT_WORKER_CANARY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("Coding Worker canary status code is invalid")
        if self.readiness not in {
            "current",
            "selected",
            "starting",
            "ready",
            "degraded",
            "unavailable",
            "rolled_back",
        }:
            raise ValueError("Coding Worker canary readiness is invalid")
        if type(self.required) is not bool:
            raise TypeError("Coding Worker canary requiredness must be boolean")
        if self.requested_owner not in {"current", "hosting"} or (
            self.effective_owner not in {"current", "hosting"}
        ):
            raise ValueError("Coding Worker canary owner is invalid")
        if (self.receipt_fingerprint is None) != (self.attempt_id is None):
            raise ValueError("Coding Worker canary attempt identity is incomplete")
        if (self.attempt_id is None) != (self.owner_generation is None):
            raise ValueError("Coding Worker canary generation identity is incomplete")
        if self.status_version != CODING_PRODUCT_WORKER_CANARY_VERSION:
            raise ValueError("Coding Worker canary status version is unsupported")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "code": self.code,
            "effectiveOwner": self.effective_owner,
            "ownerGeneration": self.owner_generation,
            "readiness": self.readiness,
            "receiptFingerprint": self.receipt_fingerprint,
            "requestedOwner": self.requested_owner,
            "required": self.required,
            "statusVersion": self.status_version,
        }


class CodingProductWorkerCanaryDomainPort(Protocol):
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
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
    ) -> None: ...

    async def revoke_and_drain(
        self,
        *,
        receipt_fingerprint: str,
        attempt_id: str,
        owner_generation: int,
    ) -> None: ...

    async def settle_readiness(
        self,
        *,
        required: bool,
        ready: bool,
        code: str,
    ) -> None: ...

    async def issue_current(self, *, prior_receipt_fingerprint: str) -> object: ...


class CodingProductWorkerCleanupPort(Protocol):
    """Platform owner that records settlement or durable cleanup debt."""

    async def settle(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
        protocol_terminal: bool,
        domain_retired: bool,
    ) -> None: ...


class CodingProductWorkerRecoveryPort(Protocol):
    """Durable recovery drill owned by the injected lifecycle authorities."""

    async def recover(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        request: ManagedWorkerLaunchRequestV1,
    ) -> tuple[str, ...]: ...


class _ActivationAdmissionLease(Protocol):
    def __enter__(self) -> _ActivationAdmissionLease: ...

    def __exit__(self, *error: object) -> object: ...

    def begin_effect(self) -> None: ...


class CodingProductWorkerCanary:
    """One selected attempt shared by every canary-capable Coding entrypoint."""

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
        domain: CodingProductWorkerCanaryDomainPort | None,
        cleanup: CodingProductWorkerCleanupPort | None,
        recovery: CodingProductWorkerRecoveryPort | None,
        host_identity: str | None,
        boot_identity: str | None,
        status: CodingProductWorkerCanaryStatusV1,
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
        self._adapter: CapabilityQueryWorkerAdapter | None = None
        self._operation_lock = asyncio.Lock()

    @property
    def status(self) -> CodingProductWorkerCanaryStatusV1:
        return self._status

    @property
    def rollback_steps(self) -> tuple[str, ...]:
        return _ROLLBACK_STEPS

    @property
    def recovery_steps(self) -> tuple[str, ...]:
        return _RECOVERY_STEPS

    def receipt_for_entrypoint(
        self,
        entrypoint: str,
    ) -> ProductWorkerActivationReceiptV1 | None:
        """Return the one immutable receipt; early-dispatch routes stay dark."""

        if entrypoint not in CODING_PRODUCT_WORKER_CANARY_ENTRYPOINTS:
            raise CodingProductWorkerCanaryError(
                "Coding entrypoint cannot activate the Worker canary",
                code="coding_worker_entrypoint_unsupported",
            )
        return self._receipt

    async def start(self, *, correlation_id: str) -> CodingProductWorkerCanaryStatusV1:
        """Start, handshake, admit, and publish exactly one Hosting attempt."""

        async with self._operation_lock:
            if self._status.readiness == "ready":
                return self._status
            if self._status.effective_owner != "hosting":
                return self._status
            self._require_selected_components()
            policy = cast(ProductWorkerActivationPolicyV1, self._policy)
            receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
            coordinator = cast(ProductWorkerActivationCoordinator, self._coordinator)
            supervisor = cast(WorkerSupervisor, self._supervisor)
            request = cast(ManagedWorkerLaunchRequestV1, self._request)
            session_port = cast(WorkerSessionOwnerRouter, self._session_port)
            domain = cast(CodingProductWorkerCanaryDomainPort, self._domain)
            decision = coordinator.evaluate(policy, receipt)
            if decision.get("reason") != "admitted":
                return await self._settle_closed_decision(
                    code=_stable_reason(decision.get("reason")),
                )
            self._status = self._attempt_status(
                code="coding_worker_starting",
                readiness="starting",
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
                    realized_native_policy_closure_fingerprint=(
                        cast(
                            ProductWorkerNativeProfilePort,
                            self._native_profile,
                        ).realized_native_policy_closure_fingerprint
                    ),
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
                    code="coding_worker_ready",
                )
                self._status = self._attempt_status(
                    code="coding_worker_ready",
                    readiness="ready",
                )
                return self._status
            except asyncio.CancelledError:
                if effect_started:
                    await self._reclaim_failed_attempt(
                        domain_publish_started=domain_publish_started,
                    )
                raise
            except BaseException as exc:
                if effect_started:
                    await self._reclaim_failed_attempt(
                        domain_publish_started=domain_publish_started,
                    )
                readiness: CodingWorkerCanaryReadiness = (
                    "unavailable" if policy.effective_required else "degraded"
                )
                code = (
                    "coding_worker_required_unavailable"
                    if policy.effective_required
                    else "coding_worker_optional_degraded"
                )
                self._status = self._attempt_status(code=code, readiness=readiness)
                await domain.settle_readiness(
                    required=policy.effective_required,
                    ready=False,
                    code=code,
                )
                if policy.effective_required:
                    raise CodingProductWorkerCanaryError(
                        "Required Coding Worker canary is unavailable",
                        code=code,
                    ) from exc
                return self._status

    async def rollback(self) -> CodingProductWorkerCanaryStatusV1:
        """Run the fixed latch-first rollback sequence without same-attempt fallback."""

        async with self._operation_lock:
            self._require_selected_components()
            policy = cast(ProductWorkerActivationPolicyV1, self._policy)
            receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
            coordinator = cast(ProductWorkerActivationCoordinator, self._coordinator)
            supervisor = cast(WorkerSupervisor, self._supervisor)
            request = cast(ManagedWorkerLaunchRequestV1, self._request)
            domain = cast(CodingProductWorkerCanaryDomainPort, self._domain)
            cleanup = cast(CodingProductWorkerCleanupPort, self._cleanup)
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
            await supervisor.fence(code="coding_worker_rollback")
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
            )
            await domain.settle_readiness(
                required=policy.effective_required,
                ready=False,
                code="coding_worker_rollback_latched",
            )
            await domain.issue_current(prior_receipt_fingerprint=receipt.fingerprint)
            self._status = self._attempt_status(
                code="coding_worker_rollback_latched",
                readiness="rolled_back",
                effective_owner="current",
            )
            return self._status

    async def recover(self) -> tuple[str, ...]:
        """Require the complete ordered durable recovery matrix."""

        async with self._operation_lock:
            self._require_selected_components()
            recovery = cast(CodingProductWorkerRecoveryPort, self._recovery)
            steps = await recovery.recover(
                receipt=cast(ProductWorkerActivationReceiptV1, self._receipt),
                request=cast(ManagedWorkerLaunchRequestV1, self._request),
            )
            if steps != _RECOVERY_STEPS:
                raise CodingProductWorkerCanaryError(
                    "Coding Worker recovery evidence is incomplete",
                    code="coding_worker_recovery_incomplete",
                )
            return steps

    async def _reclaim_failed_attempt(
        self,
        *,
        domain_publish_started: bool,
    ) -> None:
        receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
        request = cast(ManagedWorkerLaunchRequestV1, self._request)
        domain = cast(CodingProductWorkerCanaryDomainPort, self._domain)
        coordinator = cast(ProductWorkerActivationCoordinator, self._coordinator)
        supervisor = cast(WorkerSupervisor, self._supervisor)
        cleanup = cast(CodingProductWorkerCleanupPort, self._cleanup)
        with _suppress_failures():
            await domain.fence_attempt(
                receipt_fingerprint=receipt.fingerprint,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
        if domain_publish_started:
            with _suppress_failures():
                await domain.revoke_and_drain(
                    receipt_fingerprint=receipt.fingerprint,
                    attempt_id=request.identity.attempt_id,
                    owner_generation=request.identity.owner_generation,
                )
        with _suppress_failures():
            coordinator.retire_exact(
                receipt=receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
        with _suppress_failures():
            await supervisor.fence(code="coding_worker_start_failed")
        with _suppress_failures():
            coordinator.record_protocol_terminal(
                receipt=receipt,
                attempt_id=request.identity.attempt_id,
                owner_generation=request.identity.owner_generation,
            )
        with _suppress_failures():
            await cleanup.settle(
                receipt=receipt,
                request=request,
                protocol_terminal=True,
                domain_retired=True,
            )

    async def _settle_closed_decision(
        self,
        *,
        code: str,
    ) -> CodingProductWorkerCanaryStatusV1:
        policy = cast(ProductWorkerActivationPolicyV1, self._policy)
        readiness: CodingWorkerCanaryReadiness = (
            "unavailable" if policy.effective_required else "degraded"
        )
        stable_code = (
            "coding_worker_required_unavailable"
            if policy.effective_required
            else "coding_worker_optional_degraded"
        )
        domain = cast(CodingProductWorkerCanaryDomainPort, self._domain)
        await domain.settle_readiness(
            required=policy.effective_required,
            ready=False,
            code=code,
        )
        self._status = self._attempt_status(
            code=stable_code,
            readiness=readiness,
        )
        if policy.effective_required:
            raise CodingProductWorkerCanaryError(
                "Required Coding Worker canary was rejected",
                code=stable_code,
            )
        return self._status

    def _attempt_status(
        self,
        *,
        code: str,
        readiness: CodingWorkerCanaryReadiness,
        effective_owner: Literal["current", "hosting"] = "hosting",
    ) -> CodingProductWorkerCanaryStatusV1:
        policy = cast(ProductWorkerActivationPolicyV1, self._policy)
        receipt = cast(ProductWorkerActivationReceiptV1, self._receipt)
        request = cast(ManagedWorkerLaunchRequestV1, self._request)
        return CodingProductWorkerCanaryStatusV1(
            code=code,
            readiness=readiness,
            required=policy.effective_required,
            requested_owner=policy.requested_owner,
            effective_owner=effective_owner,
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=request.identity.attempt_id,
            owner_generation=request.identity.owner_generation,
        )

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
        if any(item is None for item in components):
            raise CodingProductWorkerCanaryError(
                "Coding Worker canary composition is incomplete",
                code="coding_worker_composition_incomplete",
            )


def bind_coding_product_worker_canary(
    *,
    policy: ProductWorkerActivationPolicyV1 | None = None,
    receipt: ProductWorkerActivationReceiptV1 | None = None,
    session_discovery: SessionDiscoveryMetadata | None = None,
    validate_product_session: Callable[[], None] | None = None,
    authority: ProductWorkerActivationAuthorityPort | None = None,
    evidence_authority: object | None = None,
    trusted_evidence_authority_id: str | None = None,
    trusted_evidence_authority_fingerprint: str | None = None,
    activation_state_store: object | None = None,
    restart_budget: int = 3,
    supervisor: WorkerSupervisor | None = None,
    worker_request: ManagedWorkerLaunchRequestV1 | None = None,
    current_owner: ManagedWorkerSessionLaunchPort | None = None,
    hosting: object | None = None,
    containment_launcher_path: str | None = None,
    containment_launcher_sha256: str | None = None,
    containment_profile_sha256: str | None = None,
    capability_binding: CapabilityWorkerBindingV1 | None = None,
    capability_authority_reader: Callable[[], CapabilityWorkerAuthorityV1]
    | None = None,
    domain: CodingProductWorkerCanaryDomainPort | None = None,
    cleanup: CodingProductWorkerCleanupPort | None = None,
    recovery: CodingProductWorkerRecoveryPort | None = None,
    host_identity: str | None = None,
    boot_identity: str | None = None,
) -> CodingProductWorkerCanary:
    """Bind the sole Linux Coding Product canary; omission remains Current."""

    if policy is None:
        if receipt is not None:
            _raise("coding_worker_product_missing")
        return _current_canary(code="coding_worker_product_missing")
    if not isinstance(policy, ProductWorkerActivationPolicyV1):
        raise TypeError("Coding Worker canary requires typed Product policy")
    if policy.product_id != CODING_PRODUCT_ID:
        _raise("coding_worker_product_mismatch")
    if not policy.enabled or policy.requested_owner == "current":
        if receipt is not None:
            _raise("coding_worker_disabled_receipt_present")
        return _current_canary(
            code="coding_worker_disabled_by_policy",
            policy=policy,
        )
    if receipt is None:
        code = (
            "coding_worker_required_unavailable"
            if policy.effective_required
            else "coding_worker_optional_degraded"
        )
        readiness: CodingWorkerCanaryReadiness = (
            "unavailable" if policy.effective_required else "degraded"
        )
        return CodingProductWorkerCanary(
            policy=policy,
            receipt=None,
            coordinator=None,
            supervisor=None,
            request=None,
            session_port=None,
            native_profile=None,
            capability_binding=None,
            capability_authority_reader=None,
            domain=None,
            cleanup=None,
            recovery=None,
            host_identity=None,
            boot_identity=None,
            status=CodingProductWorkerCanaryStatusV1(
                code=code,
                readiness=readiness,
                required=policy.effective_required,
                requested_owner="hosting",
                effective_owner="current",
            ),
        )
    if not isinstance(receipt, ProductWorkerActivationReceiptV1) or (
        receipt.policy != policy
    ):
        _raise("coding_worker_receipt_mismatch")
    _validate_session(
        policy,
        session_discovery=session_discovery,
        validate_product_session=validate_product_session,
    )
    _validate_selected_components(
        policy=policy,
        receipt=receipt,
        authority=authority,
        evidence_authority=evidence_authority,
        trusted_evidence_authority_id=trusted_evidence_authority_id,
        trusted_evidence_authority_fingerprint=(trusted_evidence_authority_fingerprint),
        activation_state_store=activation_state_store,
        restart_budget=restart_budget,
        supervisor=supervisor,
        request=worker_request,
        current_owner=current_owner,
        hosting=hosting,
        containment_launcher_path=containment_launcher_path,
        containment_launcher_sha256=containment_launcher_sha256,
        containment_profile_sha256=containment_profile_sha256,
        capability_binding=capability_binding,
        capability_authority_reader=capability_authority_reader,
        domain=domain,
        cleanup=cleanup,
        recovery=recovery,
        host_identity=host_identity,
        boot_identity=boot_identity,
    )
    assert worker_request is not None
    assert authority is not None
    assert evidence_authority is not None
    assert trusted_evidence_authority_id is not None
    assert trusted_evidence_authority_fingerprint is not None
    assert activation_state_store is not None
    assert containment_launcher_path is not None
    assert containment_launcher_sha256 is not None
    assert containment_profile_sha256 is not None
    try:
        native_profile = _bind_posix_static_contained_product_worker_profile(
            receipt=receipt,
            worker_request=worker_request,
            native_profile_catalog_revision=policy.native_profile_catalog_revision,
            launcher_path=containment_launcher_path,
            launcher_sha256=containment_launcher_sha256,
            containment_profile_sha256=containment_profile_sha256,
        )
    except WorkerBindingError as exc:
        raise CodingProductWorkerCanaryError(
            "Coding Worker native profile was rejected",
            code=exc.code,
        ) from exc
    except (TypeError, ValueError) as exc:
        raise CodingProductWorkerCanaryError(
            "Coding Worker native profile configuration was rejected",
            code="coding_worker_native_profile_configuration_invalid",
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
        raise CodingProductWorkerCanaryError(
            "Coding Worker activation composition was rejected",
            code="coding_worker_activation_composition_rejected",
        ) from exc
    session_port = WorkerSessionOwnerRouter(
        current=cast(ManagedWorkerSessionLaunchPort, current_owner),
        hosting=HostingManagedWorkerSessionAdapter(
            hosting=hosting,  # type: ignore[arg-type]
            preparation=native_profile,
        ),
        activation=WorkerHostingActivationV1(owner="hosting"),
    )
    return CodingProductWorkerCanary(
        policy=policy,
        receipt=receipt,
        coordinator=coordinator,
        supervisor=supervisor,
        request=worker_request,
        session_port=session_port,
        native_profile=native_profile,
        capability_binding=capability_binding,
        capability_authority_reader=capability_authority_reader,
        domain=domain,
        cleanup=cleanup,
        recovery=recovery,
        host_identity=host_identity,
        boot_identity=boot_identity,
        status=CodingProductWorkerCanaryStatusV1(
            code="coding_worker_selected",
            readiness="selected",
            required=policy.effective_required,
            requested_owner="hosting",
            effective_owner="hosting",
            receipt_fingerprint=receipt.fingerprint,
            attempt_id=worker_request.identity.attempt_id,
            owner_generation=worker_request.identity.owner_generation,
        ),
    )


def coding_product_worker_session_fingerprint(
    discovery: SessionDiscoveryMetadata,
) -> str:
    """Hash exact locator provenance without exposing a machine-local path."""

    if not isinstance(discovery, SessionDiscoveryMetadata):
        raise TypeError("Coding Worker canary requires Session discovery metadata")
    encoded = json.dumps(
        discovery.to_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = sha256()
    digest.update(b"loushang.coding-product-worker-session/v1")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    return digest.hexdigest()


def _current_canary(
    *,
    code: str,
    policy: ProductWorkerActivationPolicyV1 | None = None,
) -> CodingProductWorkerCanary:
    required = False if policy is None else policy.effective_required
    requested_owner: Literal["current", "hosting"] = (
        "current" if policy is None else policy.requested_owner
    )
    return CodingProductWorkerCanary(
        policy=policy,
        receipt=None,
        coordinator=None,
        supervisor=None,
        request=None,
        session_port=None,
        native_profile=None,
        capability_binding=None,
        capability_authority_reader=None,
        domain=None,
        cleanup=None,
        recovery=None,
        host_identity=None,
        boot_identity=None,
        status=CodingProductWorkerCanaryStatusV1(
            code=code,
            readiness="current",
            required=required,
            requested_owner=requested_owner,
            effective_owner="current",
        ),
    )


def _validate_session(
    policy: ProductWorkerActivationPolicyV1,
    *,
    session_discovery: SessionDiscoveryMetadata | None,
    validate_product_session: Callable[[], None] | None,
) -> None:
    if policy.session_route == "selected" and not callable(validate_product_session):
        _raise("coding_worker_session_product_evidence_missing")
    if validate_product_session is not None:
        if not callable(validate_product_session):
            raise TypeError("Coding Worker Session validator is invalid")
        try:
            validate_product_session()
        except BaseException as exc:
            raise CodingProductWorkerCanaryError(
                "Coding Worker Session Product profile was rejected",
                code="coding_worker_session_product_mismatch",
            ) from exc
    if policy.session_route == "new":
        if session_discovery is not None:
            _raise("coding_worker_new_session_has_locator")
        return
    if not isinstance(session_discovery, SessionDiscoveryMetadata):
        _raise("coding_worker_session_locator_missing")
    if not session_discovery.resumable or session_discovery.conflicts:
        _raise("coding_worker_session_locator_conflict")
    locator = session_discovery.locator
    if locator.conversation_id != policy.session_id:
        _raise("coding_worker_session_identity_mismatch")
    if locator.revision != policy.selected_locator_revision:
        _raise("coding_worker_session_locator_changed")
    if coding_product_worker_session_fingerprint(session_discovery) != (
        policy.selected_locator_fingerprint
    ):
        _raise("coding_worker_session_locator_changed")


def _validate_selected_components(
    *,
    policy: ProductWorkerActivationPolicyV1,
    receipt: ProductWorkerActivationReceiptV1,
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
    capability_binding: CapabilityWorkerBindingV1 | None,
    capability_authority_reader: Callable[[], CapabilityWorkerAuthorityV1] | None,
    domain: CodingProductWorkerCanaryDomainPort | None,
    cleanup: CodingProductWorkerCleanupPort | None,
    recovery: CodingProductWorkerRecoveryPort | None,
    host_identity: str | None,
    boot_identity: str | None,
) -> None:
    if policy.native_profile_id != CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID:
        _raise("coding_worker_native_profile_unsupported")
    _require_opaque(host_identity, name="host identity")
    _require_opaque(boot_identity, name="boot identity")
    if authority is None or any(
        not callable(getattr(authority, name, None))
        for name in (
            "serialized_admission",
            "current_witness",
            "latch_kill_switch",
        )
    ):
        _raise("coding_worker_composition_incomplete")
    if evidence_authority is None or any(
        not callable(getattr(evidence_authority, name, None))
        for name in (
            "verify_tree_settlement",
            "verify_changed_boot_absence",
            "verify_registered_lease_expired",
        )
    ):
        _raise("coding_worker_composition_incomplete")
    _require_opaque(
        trusted_evidence_authority_id,
        name="cleanup evidence authority identity",
    )
    _require_sha256(
        trusted_evidence_authority_fingerprint,
        name="cleanup evidence authority fingerprint",
    )
    if activation_state_store is None or any(
        not callable(getattr(activation_state_store, name, None))
        for name in ("load", "compare_and_swap")
    ):
        _raise("coding_worker_composition_incomplete")
    if type(restart_budget) is not int or restart_budget < 0:
        _raise("coding_worker_composition_incomplete")
    if not isinstance(supervisor, WorkerSupervisor):
        _raise("coding_worker_composition_incomplete")
    if not isinstance(request, ManagedWorkerLaunchRequestV1):
        _raise("coding_worker_composition_incomplete")
    if supervisor.identity != request.identity:
        _raise("coding_worker_supervisor_identity_mismatch")
    if not callable(getattr(current_owner, "start", None)) or hosting is None:
        _raise("coding_worker_composition_incomplete")
    if not isinstance(containment_launcher_path, str) or not containment_launcher_path:
        _raise("coding_worker_composition_incomplete")
    _require_sha256(
        containment_launcher_sha256,
        name="containment launcher digest",
    )
    _require_sha256(
        containment_profile_sha256,
        name="containment profile digest",
    )
    if not isinstance(capability_binding, CapabilityWorkerBindingV1) or not callable(
        capability_authority_reader
    ):
        _raise("coding_worker_composition_incomplete")
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
            _raise("coding_worker_composition_incomplete")
    identity = request.identity
    expected = (
        policy.product_id,
        policy.product_scope_id,
        policy.plugin_id,
        policy.plugin_revision_digest,
        policy.contribution_id,
        policy.declaration_fingerprint,
        policy.worker_configuration_fingerprint,
        policy.owner_selection_generation,
    )
    actual = (
        identity.product_id,
        identity.scope_id,
        identity.plugin_id,
        identity.plugin_revision_digest,
        identity.contribution_id,
        identity.declaration_fingerprint,
        identity.worker_configuration_fingerprint,
        identity.owner_generation,
    )
    if expected != actual:
        _raise("coding_worker_request_identity_mismatch")
    binding_authority = capability_binding.authority
    if (
        capability_binding.plugin_id != identity.plugin_id
        or capability_binding.contribution_id != identity.contribution_id
        or capability_binding.product_id != identity.product_id
        or capability_binding.scope_id != identity.scope_id
        or binding_authority.plugin_revision_digest != identity.plugin_revision_digest
        or binding_authority.declaration_fingerprint != identity.declaration_fingerprint
        or binding_authority.owner_generation != identity.owner_generation
        or binding_authority.product_policy_revision != policy.product_policy_revision
    ):
        _raise("coding_worker_capability_binding_mismatch")


def _stable_reason(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "coding_worker_activation_rejected"
    return f"coding_worker_{value}"


def _require_opaque(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 128
        or any(character.isspace() for character in value)
    ):
        raise CodingProductWorkerCanaryError(
            f"Coding Worker {name} is invalid",
            code="coding_worker_machine_identity_invalid",
        )


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CodingProductWorkerCanaryError(
            f"Coding Worker {name} is invalid",
            code="coding_worker_composition_digest_invalid",
        )


class _suppress_failures:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_error: object) -> bool:
        return True


def _raise(code: str) -> NoReturn:
    raise CodingProductWorkerCanaryError(
        "Coding Worker canary composition was rejected",
        code=code,
    )


__all__ = [
    "CODING_PRODUCT_WORKER_CANARY_ENTRYPOINTS",
    "CODING_PRODUCT_WORKER_CANARY_VERSION",
    "CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID",
    "CodingProductWorkerCanary",
    "CodingProductWorkerCanaryDomainPort",
    "CodingProductWorkerCanaryError",
    "CodingProductWorkerCanaryStatusV1",
    "CodingProductWorkerCleanupPort",
    "CodingProductWorkerRecoveryPort",
    "bind_coding_product_worker_canary",
    "coding_product_worker_session_fingerprint",
]
