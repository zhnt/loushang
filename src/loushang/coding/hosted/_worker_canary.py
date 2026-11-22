"""Explicit Coding Product composition for one contained local Plugin Worker.

The Product owns selection and readiness.  Harness owns Worker lifecycle and
native-profile capabilities, while Hosting owns every process, endpoint, and
platform resource.  This module joins those already-authorized capabilities;
it never imports Hosting or manufactures native material.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol, cast

from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker import (
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
)
from loushang.harness.worker._native_profile_bridge import (
    _bind_posix_static_contained_product_worker_profile,
    _bind_windows_lpac_contained_product_worker_profile,
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker._product_attempt_lifecycle import (
    _ProductWorkerAttemptLifecycle,
    _validate_selected_worker_components,
    _WorkerCleanupPort,
    _WorkerDomainPort,
    _WorkerReadiness,
    _WorkerRecoveryPort,
)
from loushang.harness.worker.gated_start import bind_worker_gated_start_release
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationCoordinator,
    _fingerprint,
)

if TYPE_CHECKING:
    from loushang.coding.package.product_worker_start_gate import (
        CodingProductWorkerStartGate,
    )

CODING_PRODUCT_WORKER_CANARY_VERSION = 1
CODING_PRODUCT_WORKER_CANARY_ENTRYPOINTS = ("cli", "product", "tui")
CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID = "posix-static-query-contained-elf-v1"
CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID = "windows-lpac-contained-pe-v1"
CODING_PRODUCT_WORKER_NATIVE_PROFILE_IDS = (
    CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID,
    CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
)

CodingWorkerCanaryReadiness = _WorkerReadiness

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


class CodingProductWorkerCanaryDomainPort(_WorkerDomainPort, Protocol):
    "Capability-owner operations needed by the Product composition."


class CodingProductWorkerCleanupPort(_WorkerCleanupPort, Protocol):
    "Platform owner that records settlement or durable cleanup debt."


class CodingProductWorkerRecoveryPort(_WorkerRecoveryPort, Protocol):
    "Durable recovery drill owned by the injected lifecycle authorities."


class CodingProductWorkerCanary(
    _ProductWorkerAttemptLifecycle[CodingProductWorkerCanaryStatusV1]
):
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
        start_gate: CodingProductWorkerStartGate | None = None,
    ) -> None:
        super().__init__(
            policy=policy,
            receipt=receipt,
            coordinator=coordinator,
            supervisor=supervisor,
            request=request,
            session_port=session_port,
            native_profile=native_profile,
            capability_binding=capability_binding,
            capability_authority_reader=capability_authority_reader,
            domain=domain,
            cleanup=cleanup,
            recovery=recovery,
            host_identity=host_identity,
            boot_identity=boot_identity,
            status=status,
            start_gate=start_gate,
        )

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
        self, entrypoint: str
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
        return await super().start(correlation_id=correlation_id)

    async def rollback(self) -> CodingProductWorkerCanaryStatusV1:
        """Run the fixed latch-first rollback sequence without same-attempt fallback."""
        return await super().rollback()

    async def recover(self) -> tuple[str, ...]:
        """Require the complete ordered durable recovery matrix."""
        return await super().recover()

    async def close(self) -> None:
        """Settle this exact Product attempt without changing Product policy."""
        return await super().close()

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

    @staticmethod
    def _lifecycle_code(reason: str) -> str:
        return "coding_" + reason

    @staticmethod
    def _lifecycle_reason(value: object) -> str:
        return _stable_reason(value)

    @staticmethod
    def _lifecycle_error(message: str, *, code: str) -> CodingProductWorkerCanaryError:
        messages = {
            "closed": "Coding Worker canary is closed",
            "gate_consumed": "Coding Worker gated attempt is no longer available",
            "required_start": "Required Coding Worker canary is unavailable",
            "cleanup_contract": "Coding Worker cleanup contract is unsupported",
            "native_settlement": "Coding Worker native containment is unsettled",
            "required_rejected": "Required Coding Worker canary was rejected",
            "composition": "Coding Worker canary composition is incomplete",
            "recovery_incomplete": "Coding Worker recovery evidence is incomplete",
        }
        return CodingProductWorkerCanaryError(messages[message], code=code)

    @staticmethod
    def _expected_recovery_steps() -> tuple[str, ...]:
        return _RECOVERY_STEPS


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
    start_gate: CodingProductWorkerStartGate | None = None,
    windows_lpac_plan: _WindowsLpacProductWorkerProfilePlan | None = None,
    windows_platform_imports: tuple[str, ...] | None = None,
    native_provisioning_state_store: object | None = None,
    capability_binding: CapabilityWorkerBindingV1 | None = None,
    capability_authority_reader: Callable[[], CapabilityWorkerAuthorityV1]
    | None = None,
    domain: CodingProductWorkerCanaryDomainPort | None = None,
    cleanup: CodingProductWorkerCleanupPort | None = None,
    recovery: CodingProductWorkerRecoveryPort | None = None,
    host_identity: str | None = None,
    boot_identity: str | None = None,
) -> CodingProductWorkerCanary:
    """Bind the sole explicit Coding Product canary; omission remains Current."""

    if policy is None:
        if receipt is not None or start_gate is not None:
            _raise("coding_worker_product_missing")
        return _current_canary(code="coding_worker_product_missing")
    if not isinstance(policy, ProductWorkerActivationPolicyV1):
        raise TypeError("Coding Worker canary requires typed Product policy")
    if policy.product_id != CODING_PRODUCT_ID:
        _raise("coding_worker_product_mismatch")
    if not policy.enabled or policy.requested_owner == "current":
        if receipt is not None or start_gate is not None:
            _raise("coding_worker_disabled_receipt_present")
        return _current_canary(
            code="coding_worker_disabled_by_policy",
            policy=policy,
        )
    if receipt is None:
        if start_gate is not None:
            _raise("coding_worker_start_gate_receipt_missing")
        code = (
            "coding_worker_required_unavailable"
            if policy.effective_required
            else "coding_worker_optional_degraded"
        )
        readiness: CodingWorkerCanaryReadiness = (
            "unavailable" if policy.effective_required else "degraded"
        )
        return _current_canary(code=code, policy=policy, readiness=readiness)
    if not isinstance(receipt, ProductWorkerActivationReceiptV1) or (
        receipt.policy != policy
    ):
        _raise("coding_worker_receipt_mismatch")
    _validate_session(
        policy,
        session_discovery=session_discovery,
        validate_product_session=validate_product_session,
    )
    _validate_selected_worker_components(
        policy=policy,
        posix_profile_id=CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID,
        windows_profile_id=CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
        failure=_canary_binding_failure,
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
        windows_lpac_plan=windows_lpac_plan,
        windows_platform_imports=windows_platform_imports,
        native_provisioning_state_store=native_provisioning_state_store,
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
    assert containment_launcher_sha256 is not None
    assert containment_profile_sha256 is not None
    from loushang.coding.package.product_worker_start_gate import (
        CodingProductWorkerStartGate,
        CodingWorkerStartGateError,
    )

    if start_gate is not None and (
        type(start_gate) is not CodingProductWorkerStartGate
        or policy.native_profile_id != CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID
        or start_gate.receipt_owner is not authority
        or start_gate.receipt_fingerprint != receipt.fingerprint
        or start_gate.attempt_id != worker_request.identity.attempt_id
        or start_gate.worker_identity_fingerprint != worker_request.identity.fingerprint
    ):
        _raise("coding_worker_start_gate_binding_mismatch")
    try:
        if policy.native_profile_id == CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID:
            assert containment_launcher_path is not None
            native_profile = _bind_posix_static_contained_product_worker_profile(
                receipt=receipt,
                worker_request=worker_request,
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
            assert native_provisioning_state_store is not None
            native_profile = _bind_windows_lpac_contained_product_worker_profile(
                receipt=receipt,
                worker_request=worker_request,
                plan=windows_lpac_plan,
                platform_imports=windows_platform_imports,
                provisioning_state_store=native_provisioning_state_store,  # type: ignore[arg-type]
            )
    except WorkerBindingError as exc:
        raise CodingProductWorkerCanaryError(
            "Coding Worker native profile was rejected",
            code=exc.code,
        ) from exc
    except CodingWorkerStartGateError as exc:
        raise CodingProductWorkerCanaryError(
            "Coding Worker start gate is unavailable",
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
            start_gate=(
                None
                if start_gate is None
                else bind_worker_gated_start_release(start_gate)
            ),
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
        start_gate=start_gate,
    )


def coding_product_worker_session_fingerprint(
    discovery: SessionDiscoveryMetadata,
) -> str:
    """Hash exact locator provenance without exposing a machine-local path."""

    if not isinstance(discovery, SessionDiscoveryMetadata):
        raise TypeError("Coding Worker canary requires Session discovery metadata")
    return _fingerprint(
        "loushang.coding-product-worker-session/v1", discovery.to_dict()
    )


def _current_canary(
    *,
    code: str,
    policy: ProductWorkerActivationPolicyV1 | None = None,
    readiness: CodingWorkerCanaryReadiness = "current",
) -> CodingProductWorkerCanary:
    required = False if policy is None else policy.effective_required
    requested_owner: Literal["current", "hosting"] = (
        "current" if policy is None else policy.requested_owner
    )
    if readiness != "current":
        requested_owner = "hosting"
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


def _stable_reason(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "coding_worker_activation_rejected"
    return f"coding_worker_{value}"


def _canary_binding_failure(message: str, reason: str) -> CodingProductWorkerCanaryError:
    return CodingProductWorkerCanaryError(f"Coding {message}", code=f"coding_{reason}")


def _raise(code: str) -> NoReturn:
    raise CodingProductWorkerCanaryError(
        "Coding Worker canary composition was rejected",
        code=code,
    )


__all__ = [
    "CODING_PRODUCT_WORKER_CANARY_ENTRYPOINTS",
    "CODING_PRODUCT_WORKER_CANARY_VERSION",
    "CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID",
    "CODING_PRODUCT_WORKER_NATIVE_PROFILE_IDS",
    "CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID",
    "CodingProductWorkerCanary",
    "CodingProductWorkerCanaryDomainPort",
    "CodingProductWorkerCanaryError",
    "CodingProductWorkerCanaryStatusV1",
    "CodingProductWorkerCleanupPort",
    "CodingProductWorkerRecoveryPort",
    "bind_coding_product_worker_canary",
    "coding_product_worker_session_fingerprint",
]
