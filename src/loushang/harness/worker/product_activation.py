"""Default-dark Product authorization and lifecycle for hosted Workers.

This module deliberately owns no Product selection, native preparation, process,
or domain implementation.  It joins authority-free Product evidence to a
serialized freshness fence and maintains a deterministic lifecycle aggregate
over an injected compare-and-swap state store.
"""

from __future__ import annotations

import inspect
import json
import re
import threading
import weakref
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import TracebackType
from typing import Literal, Protocol, Self, cast

PRODUCT_WORKER_ACTIVATION_POLICY_VERSION = 1
PRODUCT_WORKER_ACTIVATION_RECEIPT_VERSION = 1
PRODUCT_WORKER_ACTIVATION_STATE_VERSION = 1
WORKER_CLEANUP_SETTLEMENT_VERSION = 1
WORKER_CLEANUP_DEBT_VERSION = 1

_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_HEX32 = re.compile(r"[0-9a-f]{32}")
_MAX_TEXT = 128
_POLICY_CLOSURE_DOMAIN = "loushang.worker.native-policy-closure.v1"
_POLICY_DOMAIN = "loushang.product-worker-activation-policy/v1"
_RECEIPT_DOMAIN = "loushang.product-worker-activation-receipt/v1"
_DOMAIN_SLOT_DOMAIN = "loushang.product-worker-domain-slot/v1"
_MAX_DURABLE_ATTEMPTS = 4096

WorkerSessionRoute = Literal["new", "selected"]
WorkerRequestedOwner = Literal["current", "hosting"]
ActivationWitness = tuple[str, str, str, int, int]


class _ActivationReason(str, Enum):
    ADMITTED = "admitted"
    CLEANUP_DEBT = "cleanup_debt"
    CLEANUP_SETTLED = "cleanup_settled"
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    DISABLED_BY_POLICY = "disabled_by_policy"
    FOREIGN_RECEIPT = "foreign_receipt"
    INVALID_RECEIPT = "invalid_receipt"
    KILL_SWITCH_LATCHED = "kill_switch_latched"
    OPTIONAL_DEGRADED = "optional_degraded"
    POLICY_REQUIRED_UNAVAILABLE = "policy_required_unavailable"
    PUBLISHED = "published"
    PUBLICATION_FENCED = "publication_fenced"
    RESTART_EXHAUSTED = "restart_exhausted"
    RESTART_READY = "restart_ready"
    RETIRED = "retired"
    REENTRANT_CALL = "reentrant_call"
    STALE_AUTHORITY = "stale_authority"


class _CleanupDebtReason(str, Enum):
    SAME_BOOT_UNKNOWN_TREE = "same_boot_unknown_tree"
    SETTLEMENT_INCOMPLETE = "settlement_incomplete"


class _ActivationRejected(RuntimeError):
    """Stable internal failure; arbitrary exception text never reaches status."""

    def __init__(self, reason: _ActivationReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ProductWorkerActivationPolicyV1:
    """Authority-free explicit Product decision for one Worker contribution."""

    product_id: str
    product_runtime_id: str
    product_scope_id: str
    session_id: str
    session_route: WorkerSessionRoute
    selected_locator_fingerprint: str | None
    selected_locator_revision: str
    plugin_id: str
    plugin_revision_digest: str
    contribution_id: str
    reservation_fingerprint: str
    declaration_fingerprint: str
    worker_configuration_fingerprint: str
    declared_required: bool
    effective_required: bool
    enabled: bool
    allowed_product_ids: tuple[str, ...]
    allowed_contribution_ids: tuple[str, ...]
    requested_owner: WorkerRequestedOwner
    owner_selection_generation: int
    no_fallback: bool
    native_profile_id: str
    native_profile_catalog_revision: str
    allowed_native_profile_ids: tuple[str, ...]
    expected_native_policy_closure_fingerprint: str
    product_policy_revision: str
    kill_switch_generation: int
    policy_version: int = PRODUCT_WORKER_ACTIVATION_POLICY_VERSION

    def __post_init__(self) -> None:
        for name, identifier_value in (
            ("Product id", self.product_id),
            ("Plugin id", self.plugin_id),
            ("contribution id", self.contribution_id),
            ("native profile id", self.native_profile_id),
        ):
            _require_identifier(identifier_value, name=name)
        for name, opaque_value in (
            ("Product runtime id", self.product_runtime_id),
            ("Product scope id", self.product_scope_id),
            ("Session id", self.session_id),
            ("selected locator revision", self.selected_locator_revision),
            ("native profile catalog revision", self.native_profile_catalog_revision),
            ("Product policy revision", self.product_policy_revision),
        ):
            _require_opaque(opaque_value, name=name)
        for name, fingerprint_value in (
            ("Plugin revision digest", self.plugin_revision_digest),
            ("reservation fingerprint", self.reservation_fingerprint),
            ("declaration fingerprint", self.declaration_fingerprint),
            (
                "Worker configuration fingerprint",
                self.worker_configuration_fingerprint,
            ),
            (
                "expected native policy closure fingerprint",
                self.expected_native_policy_closure_fingerprint,
            ),
        ):
            _require_sha256(fingerprint_value, name=name)
        if self.session_route not in {"new", "selected"}:
            raise ValueError("Worker Session route is unsupported")
        if self.session_route == "new":
            if self.selected_locator_fingerprint is not None:
                raise ValueError("A new Worker Session cannot carry a locator")
        elif self.selected_locator_fingerprint is None:
            raise ValueError("A selected Worker Session requires a locator fingerprint")
        if self.selected_locator_fingerprint is not None:
            _require_sha256(
                self.selected_locator_fingerprint,
                name="selected locator fingerprint",
            )
        for name, bool_value in (
            ("declared requiredness", self.declared_required),
            ("effective requiredness", self.effective_required),
            ("enabled decision", self.enabled),
            ("no-fallback decision", self.no_fallback),
        ):
            _require_bool(bool_value, name=name)
        if self.declared_required and not self.effective_required:
            raise ValueError("Effective Worker policy cannot weaken requiredness")
        _require_allowlist(self.allowed_product_ids, name="Product allowlist")
        _require_allowlist(
            self.allowed_contribution_ids,
            name="contribution allowlist",
        )
        _require_allowlist(
            self.allowed_native_profile_ids,
            name="native profile allowlist",
        )
        if self.requested_owner not in {"current", "hosting"}:
            raise ValueError("Requested Worker owner is unsupported")
        _require_positive_integer(
            self.owner_selection_generation,
            name="owner-selection generation",
        )
        _require_nonnegative_integer(
            self.kill_switch_generation,
            name="kill-switch generation",
        )
        if self.policy_version != PRODUCT_WORKER_ACTIVATION_POLICY_VERSION:
            raise ValueError("Unsupported Product Worker activation policy version")
        if self.enabled:
            if self.requested_owner != "hosting":
                raise ValueError("Enabled Worker activation must request Hosting")
            if not self.no_fallback:
                raise ValueError("Enabled Worker activation must forbid fallback")
            if self.product_id not in self.allowed_product_ids:
                raise ValueError("Product is absent from the explicit allowlist")
            if self.contribution_id not in self.allowed_contribution_ids:
                raise ValueError("Contribution is absent from the explicit allowlist")
            if self.native_profile_id not in self.allowed_native_profile_ids:
                raise ValueError("Native profile is absent from the explicit allowlist")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(_POLICY_DOMAIN, self.to_dict())

    @staticmethod
    def native_policy_closure_fingerprint(
        *,
        native_profile_catalog_revision: str,
        native_profile_id: str,
        payload_sha256: str | None,
        containment_launcher_sha256: str | None,
        containment_profile_sha256: str | None,
    ) -> str:
        """Encode expected and realized native policy in one canonical domain."""

        _require_opaque(
            native_profile_catalog_revision,
            name="native profile catalog revision",
        )
        _require_identifier(native_profile_id, name="native profile id")
        values = (
            native_profile_catalog_revision,
            native_profile_id,
            _optional_sha256(payload_sha256, name="payload digest"),
            _optional_sha256(
                containment_launcher_sha256,
                name="containment launcher digest",
            ),
            _optional_sha256(
                containment_profile_sha256,
                name="containment profile digest",
            ),
        )
        digest = sha256()
        digest.update(_POLICY_CLOSURE_DOMAIN.encode("ascii"))
        for value in values:
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "allowedContributionIds": list(self.allowed_contribution_ids),
            "allowedNativeProfileIds": list(self.allowed_native_profile_ids),
            "allowedProductIds": list(self.allowed_product_ids),
            "contributionId": self.contribution_id,
            "declarationFingerprint": self.declaration_fingerprint,
            "declaredRequired": self.declared_required,
            "effectiveRequired": self.effective_required,
            "enabled": self.enabled,
            "expectedNativePolicyClosureFingerprint": (
                self.expected_native_policy_closure_fingerprint
            ),
            "killSwitchGeneration": self.kill_switch_generation,
            "nativeProfileCatalogRevision": self.native_profile_catalog_revision,
            "nativeProfileId": self.native_profile_id,
            "noFallback": self.no_fallback,
            "ownerSelectionGeneration": self.owner_selection_generation,
            "pluginId": self.plugin_id,
            "pluginRevisionDigest": self.plugin_revision_digest,
            "policyVersion": self.policy_version,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "productRuntimeId": self.product_runtime_id,
            "productScopeId": self.product_scope_id,
            "requestedOwner": self.requested_owner,
            "reservationFingerprint": self.reservation_fingerprint,
            "selectedLocatorFingerprint": self.selected_locator_fingerprint,
            "selectedLocatorRevision": self.selected_locator_revision,
            "sessionId": self.session_id,
            "sessionRoute": self.session_route,
            "workerConfigurationFingerprint": (
                self.worker_configuration_fingerprint
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        document = _strict_document(value, _POLICY_FIELDS, name="activation policy")
        return cls(
            product_id=_string(document, "productId"),
            product_runtime_id=_string(document, "productRuntimeId"),
            product_scope_id=_string(document, "productScopeId"),
            session_id=_string(document, "sessionId"),
            session_route=cast(WorkerSessionRoute, _string(document, "sessionRoute")),
            selected_locator_fingerprint=_optional_string(
                document,
                "selectedLocatorFingerprint",
            ),
            selected_locator_revision=_string(document, "selectedLocatorRevision"),
            plugin_id=_string(document, "pluginId"),
            plugin_revision_digest=_string(document, "pluginRevisionDigest"),
            contribution_id=_string(document, "contributionId"),
            reservation_fingerprint=_string(document, "reservationFingerprint"),
            declaration_fingerprint=_string(document, "declarationFingerprint"),
            worker_configuration_fingerprint=_string(
                document,
                "workerConfigurationFingerprint",
            ),
            declared_required=_bool(document, "declaredRequired"),
            effective_required=_bool(document, "effectiveRequired"),
            enabled=_bool(document, "enabled"),
            allowed_product_ids=_string_tuple(document, "allowedProductIds"),
            allowed_contribution_ids=_string_tuple(
                document,
                "allowedContributionIds",
            ),
            requested_owner=cast(
                WorkerRequestedOwner,
                _string(document, "requestedOwner"),
            ),
            owner_selection_generation=_integer(
                document,
                "ownerSelectionGeneration",
            ),
            no_fallback=_bool(document, "noFallback"),
            native_profile_id=_string(document, "nativeProfileId"),
            native_profile_catalog_revision=_string(
                document,
                "nativeProfileCatalogRevision",
            ),
            allowed_native_profile_ids=_string_tuple(
                document,
                "allowedNativeProfileIds",
            ),
            expected_native_policy_closure_fingerprint=_string(
                document,
                "expectedNativePolicyClosureFingerprint",
            ),
            product_policy_revision=_string(document, "productPolicyRevision"),
            kill_switch_generation=_integer(document, "killSwitchGeneration"),
            policy_version=_integer(document, "policyVersion"),
        )


@dataclass(frozen=True, slots=True)
class ProductWorkerActivationReceiptV1:
    """Strict, pathless receipt joining policy to one issuance event."""

    policy: ProductWorkerActivationPolicyV1
    issue_sequence: int
    issue_nonce: str
    receipt_version: int = PRODUCT_WORKER_ACTIVATION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.policy, ProductWorkerActivationPolicyV1):
            raise TypeError("Worker activation receipt requires typed policy")
        if not self.policy.enabled or self.policy.requested_owner != "hosting":
            raise ValueError("A Worker activation receipt requires enabled Hosting policy")
        _require_positive_integer(self.issue_sequence, name="receipt issue sequence")
        _require_opaque(self.issue_nonce, name="receipt issue nonce")
        if self.receipt_version != PRODUCT_WORKER_ACTIVATION_RECEIPT_VERSION:
            raise ValueError("Unsupported Product Worker activation receipt version")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(_RECEIPT_DOMAIN, self._unsigned_dict())

    @property
    def authority_witness(self) -> ActivationWitness:
        return (
            self.fingerprint,
            self.policy.product_policy_revision,
            self.policy.selected_locator_revision,
            self.policy.owner_selection_generation,
            self.policy.kill_switch_generation,
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "issueNonce": self.issue_nonce,
            "issueSequence": self.issue_sequence,
            "policy": self.policy.to_dict(),
            "receiptVersion": self.receipt_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "receiptFingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        document = _strict_document(value, _RECEIPT_FIELDS, name="activation receipt")
        receipt = cls(
            policy=ProductWorkerActivationPolicyV1.from_dict(document["policy"]),
            issue_sequence=_integer(document, "issueSequence"),
            issue_nonce=_string(document, "issueNonce"),
            receipt_version=_integer(document, "receiptVersion"),
        )
        if _string(document, "receiptFingerprint") != receipt.fingerprint:
            raise ValueError("Worker activation receipt fingerprint mismatch")
        return receipt


class ProductWorkerActivationAuthorityPort(Protocol):
    """Product-owned freshness gate; changes share this serialized lease.

    The returned context's ``__exit__`` is an idempotent release operation: a
    caller may invoke it after an ambiguous ``__enter__`` failure and retry it
    after either a pre-release or ambiguous post-release exception.
    ``__enter__`` is a callback-free acquisition primitive and may block while
    another holder completes its critical section.
    """

    def serialized_admission(self) -> AbstractContextManager[None]: ...

    def current_witness(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> ActivationWitness: ...

    def latch_kill_switch(self, *, expected_generation: int) -> int: ...


@dataclass(frozen=True, slots=True)
class WorkerCleanupSettlementV1:
    """Durable proof that all three exact-attempt exit edges have joined."""

    receipt_fingerprint: str
    attempt_id: str
    owner_generation: int
    host_identity: str
    boot_identity: str
    protocol_terminal: bool
    domain_retired: bool
    tree_settled: bool
    settlement_version: int = WORKER_CLEANUP_SETTLEMENT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_fingerprint, name="receipt fingerprint")
        _require_attempt_id(self.attempt_id)
        _require_positive_integer(self.owner_generation, name="owner generation")
        _require_opaque(self.host_identity, name="host identity")
        _require_opaque(self.boot_identity, name="boot identity")
        for name, value in (
            ("protocol terminal", self.protocol_terminal),
            ("domain retired", self.domain_retired),
            ("tree settled", self.tree_settled),
        ):
            _require_bool(value, name=name)
        if not (self.protocol_terminal and self.domain_retired and self.tree_settled):
            raise ValueError("Cleanup settlement requires all exact-attempt exit edges")
        if self.settlement_version != WORKER_CLEANUP_SETTLEMENT_VERSION:
            raise ValueError("Unsupported Worker cleanup settlement version")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "bootIdentity": self.boot_identity,
            "domainRetired": self.domain_retired,
            "hostIdentity": self.host_identity,
            "ownerGeneration": self.owner_generation,
            "protocolTerminal": self.protocol_terminal,
            "receiptFingerprint": self.receipt_fingerprint,
            "settlementVersion": self.settlement_version,
            "treeSettled": self.tree_settled,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        document = _strict_document(
            value,
            _SETTLEMENT_FIELDS,
            name="cleanup settlement",
        )
        return cls(
            receipt_fingerprint=_string(document, "receiptFingerprint"),
            attempt_id=_string(document, "attemptId"),
            owner_generation=_integer(document, "ownerGeneration"),
            host_identity=_string(document, "hostIdentity"),
            boot_identity=_string(document, "bootIdentity"),
            protocol_terminal=_bool(document, "protocolTerminal"),
            domain_retired=_bool(document, "domainRetired"),
            tree_settled=_bool(document, "treeSettled"),
            settlement_version=_integer(document, "settlementVersion"),
        )


@dataclass(frozen=True, slots=True)
class WorkerCleanupDebtV1:
    """Durable, pathless fence for an exact attempt with unknown tree state."""

    receipt_fingerprint: str
    attempt_id: str
    owner_generation: int
    host_identity: str
    boot_identity: str
    reason: _CleanupDebtReason
    debt_version: int = WORKER_CLEANUP_DEBT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_fingerprint, name="receipt fingerprint")
        _require_attempt_id(self.attempt_id)
        _require_positive_integer(self.owner_generation, name="owner generation")
        _require_opaque(self.host_identity, name="host identity")
        _require_opaque(self.boot_identity, name="boot identity")
        if not isinstance(self.reason, _CleanupDebtReason):
            raise TypeError("Worker cleanup debt requires a closed reason")
        if self.debt_version != WORKER_CLEANUP_DEBT_VERSION:
            raise ValueError("Unsupported Worker cleanup debt version")

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "bootIdentity": self.boot_identity,
            "debtVersion": self.debt_version,
            "hostIdentity": self.host_identity,
            "ownerGeneration": self.owner_generation,
            "reason": self.reason.value,
            "receiptFingerprint": self.receipt_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        document = _strict_document(value, _DEBT_FIELDS, name="cleanup debt")
        try:
            reason = _CleanupDebtReason(_string(document, "reason"))
        except ValueError as error:
            raise ValueError("Unsupported Worker cleanup debt reason") from error
        return cls(
            receipt_fingerprint=_string(document, "receiptFingerprint"),
            attempt_id=_string(document, "attemptId"),
            owner_generation=_integer(document, "ownerGeneration"),
            host_identity=_string(document, "hostIdentity"),
            boot_identity=_string(document, "bootIdentity"),
            reason=reason,
            debt_version=_integer(document, "debtVersion"),
        )


class _ActivationStateStore(Protocol):
    def load(self) -> Mapping[str, object] | None: ...

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: Mapping[str, object],
    ) -> bool: ...


class _ExternalCallbackDomain:
    """Weak-token callback domain and shared authority-release owner."""

    def __init__(self, *, identity: int) -> None:
        self.identity = identity
        self.lock = threading.Lock()
        self.active = False
        self.release_condition = threading.Condition(threading.Lock())
        self.pending_releases: dict[int, _PendingAuthorityRelease] = {}
        self.next_release_id = 1


_CALLBACK_DOMAINS_LOCK = threading.RLock()
_CALLBACK_DOMAINS: dict[
    int,
    tuple[weakref.ReferenceType[object], _ExternalCallbackDomain],
] = {}


@dataclass(frozen=True, slots=True)
class _CallbackDomainFinalizer:
    identity: int

    def __call__(self, observed: weakref.ReferenceType[object]) -> None:
        _discard_callback_domain(self.identity, observed)


def _callback_domain_for(token: object) -> _ExternalCallbackDomain:
    """Return a reclaimable identity domain for one weak-referenceable token."""

    try:
        candidate = weakref.ref(token)
    except TypeError as error:
        raise TypeError("Worker activation domain token must be weak-referenceable") from error
    identity = id(token)
    with _CALLBACK_DOMAINS_LOCK:
        existing = _CALLBACK_DOMAINS.get(identity)
        if existing is not None:
            reference, domain = existing
            if reference() is token:
                return domain
        domain = _ExternalCallbackDomain(identity=identity)
        reference = weakref.ref(token, _CallbackDomainFinalizer(identity))
        assert candidate() is token
        _CALLBACK_DOMAINS[identity] = (reference, domain)
        return domain


def _discard_callback_domain(
    identity: int,
    observed: weakref.ReferenceType[object],
) -> None:
    with _CALLBACK_DOMAINS_LOCK:
        current = _CALLBACK_DOMAINS.get(identity)
        if current is not None and current[0] is observed:
            del _CALLBACK_DOMAINS[identity]


@dataclass(frozen=True, slots=True)
class _AuthorityBinding:
    callback_domain: _ExternalCallbackDomain
    serialized_admission: Callable[..., object]
    current_witness: Callable[..., object]
    latch_kill_switch: Callable[..., object]


@dataclass(frozen=True, slots=True)
class _StoreBinding:
    callback_domain: _ExternalCallbackDomain
    load: Callable[..., object]
    compare_and_swap: Callable[..., object]


@dataclass(frozen=True, slots=True)
class _EvidenceAuthorityBinding:
    callback_domain: _ExternalCallbackDomain
    authority_id: str
    authority_fingerprint: str
    verify_tree_settlement: Callable[..., object]
    verify_changed_boot_absence: Callable[..., object]
    verify_registered_lease_expired: Callable[..., object]


def _bind_authority(value: object, *, domain_token: object) -> _AuthorityBinding:
    return _AuthorityBinding(
        callback_domain=_callback_domain_for(domain_token),
        serialized_admission=_bind_static_method(value, "serialized_admission"),
        current_witness=_bind_static_method(value, "current_witness"),
        latch_kill_switch=_bind_static_method(value, "latch_kill_switch"),
    )


def _bind_store(value: object, *, domain_token: object) -> _StoreBinding:
    return _StoreBinding(
        callback_domain=_callback_domain_for(domain_token),
        load=_bind_static_method(value, "load"),
        compare_and_swap=_bind_static_method(value, "compare_and_swap"),
    )


def _bind_evidence_authority(
    value: object,
    *,
    domain_token: object,
) -> _EvidenceAuthorityBinding:
    authority_id = _bind_static_string(value, "authority_id")
    authority_fingerprint = _bind_static_string(value, "authority_fingerprint")
    _require_opaque(authority_id, name="cleanup evidence authority id")
    _require_sha256(
        authority_fingerprint,
        name="cleanup evidence authority fingerprint",
    )
    return _EvidenceAuthorityBinding(
        callback_domain=_callback_domain_for(domain_token),
        authority_id=authority_id,
        authority_fingerprint=authority_fingerprint,
        verify_tree_settlement=_bind_static_method(value, "verify_tree_settlement"),
        verify_changed_boot_absence=_bind_static_method(
            value,
            "verify_changed_boot_absence",
        ),
        verify_registered_lease_expired=_bind_static_method(
            value,
            "verify_registered_lease_expired",
        ),
    )


def _bind_static_string(value: object, name: str) -> str:
    descriptor = inspect.getattr_static(type(value), name, None)
    visible = inspect.getattr_static(value, name, None)
    instance_values = inspect.getattr_static(value, "__dict__", None)
    shadowed = isinstance(instance_values, dict) and name in instance_values
    if type(descriptor) is not str or visible is not descriptor or shadowed:
        raise TypeError(f"Worker activation port requires static string {name}")
    return descriptor


def _bind_static_method(value: object, name: str) -> Callable[..., object]:
    """Bind a plain class method without dynamic lookup or instance shadowing."""

    descriptor = inspect.getattr_static(type(value), name, None)
    visible = inspect.getattr_static(value, name, None)
    instance_values = inspect.getattr_static(value, "__dict__", None)
    shadowed = isinstance(instance_values, dict) and name in instance_values
    if (
        descriptor is None
        or visible is not descriptor
        or shadowed
        or not inspect.isfunction(descriptor)
    ):
        raise TypeError(f"Worker activation port requires static method {name}")
    bound = descriptor.__get__(value, type(value))
    if not callable(bound):  # pragma: no cover - defensive descriptor closure
        raise TypeError(f"Worker activation port method {name} is not callable")
    return cast(Callable[..., object], bound)


class _MemoryActivationStateStore:
    """Thread-safe deterministic fake of the durable CAS owner."""

    def __init__(self) -> None:
        self._document: dict[str, object] | None = None
        self._lock = threading.Lock()

    def load(self) -> Mapping[str, object] | None:
        with self._lock:
            return _json_clone(self._document) if self._document is not None else None

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: Mapping[str, object],
    ) -> bool:
        with self._lock:
            current_revision = 0
            if self._document is not None:
                current_revision = _integer(self._document, "stateRevision")
            if current_revision != expected_revision:
                return False
            self._document = _json_clone(document)
            return True


@dataclass(frozen=True, slots=True)
class _AttemptKey:
    receipt_fingerprint: str
    attempt_id: str
    owner_generation: int

    @property
    def encoded(self) -> str:
        return f"{self.receipt_fingerprint}:{self.attempt_id}:{self.owner_generation}"


@dataclass(frozen=True, slots=True)
class _ActivationStatusV1:
    reason: _ActivationReason
    required: bool
    receipt_fingerprint: str | None = None
    attempt_id: str | None = None
    owner_generation: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "ownerGeneration": self.owner_generation,
            "reason": self.reason.value,
            "receiptFingerprint": self.receipt_fingerprint,
            "required": self.required,
            "statusVersion": 1,
        }


@dataclass(slots=True)
class _PendingAuthorityRelease:
    exit_method: Callable[..., object]
    exc_type: type[BaseException] | None = None
    exc_value: BaseException | None = None
    traceback: TracebackType | None = None
    phase: Literal["reserved", "held", "release_due", "releasing", "settled"] = (
        "reserved"
    )


class ProductWorkerActivationCoordinator:
    """Serialized, Product-neutral C5.1 lifecycle aggregate.

    The default state store is an inert deterministic fake.  A caller that
    needs restart durability injects one CAS store and gives the same store to
    the reconstructed coordinator.  This slice intentionally has no production
    composition root.
    """

    def __init__(
        self,
        *,
        authority: ProductWorkerActivationAuthorityPort,
        evidence_authority: object,
        trusted_evidence_authority_id: str,
        trusted_evidence_authority_fingerprint: str,
        state_store: object | None = None,
        restart_budget: int = 3,
        _authority_domain_token: object | None = None,
        _store_domain_token: object | None = None,
        _evidence_domain_token: object | None = None,
    ) -> None:
        _require_nonnegative_integer(restart_budget, name="restart budget")
        authority_domain_token = (
            authority if _authority_domain_token is None else _authority_domain_token
        )
        evidence_domain_token = (
            evidence_authority
            if _evidence_domain_token is None
            else _evidence_domain_token
        )
        self._authority = _bind_authority(
            authority,
            domain_token=authority_domain_token,
        )
        self._evidence_authority = _bind_evidence_authority(
            evidence_authority,
            domain_token=evidence_domain_token,
        )
        _require_opaque(
            trusted_evidence_authority_id,
            name="trusted cleanup evidence authority id",
        )
        _require_sha256(
            trusted_evidence_authority_fingerprint,
            name="trusted cleanup evidence authority fingerprint",
        )
        if (
            self._evidence_authority.authority_id
            != trusted_evidence_authority_id
            or self._evidence_authority.authority_fingerprint
            != trusted_evidence_authority_fingerprint
        ):
            raise ValueError("Worker cleanup evidence authority is not trusted")
        store_owner = (
            _MemoryActivationStateStore() if state_store is None else state_store
        )
        store_domain_token = (
            store_owner if _store_domain_token is None else _store_domain_token
        )
        self._store = _bind_store(
            store_owner,
            domain_token=store_domain_token,
        )
        self._domain_tokens = (
            authority_domain_token,
            store_domain_token,
            evidence_domain_token,
        )
        self._callback_domains = tuple(
            sorted(
                {
                    id(binding.callback_domain): binding.callback_domain
                    for binding in (
                        self._authority,
                        self._store,
                        self._evidence_authority,
                    )
                }.values(),
                key=lambda domain: domain.identity,
            )
        )
        self._lock = threading.RLock()
        loaded_value = self._call_external(
            self._store.load,
        )
        if loaded_value is not None and not isinstance(loaded_value, Mapping):
            raise ValueError("Worker activation store returned invalid state")
        loaded = cast(Mapping[str, object] | None, loaded_value)
        if loaded is None:
            self._state = _validate_state(_initial_state(restart_budget=restart_budget))
            initialized = self._call_external(
                self._store.compare_and_swap,
                expected_revision=0,
                document=self._state,
            )
            if initialized is not True:
                loaded_value = self._call_external(
                    self._store.load,
                )
                if loaded_value is not None and not isinstance(loaded_value, Mapping):
                    raise ValueError("Worker activation store returned invalid state")
                loaded = cast(Mapping[str, object] | None, loaded_value)
                if loaded is None:
                    raise RuntimeError("Worker activation state initialization raced")
                self._state = _validate_state(loaded)
        else:
            self._state = _validate_state(loaded)
        if self._state["restartBudget"] != restart_budget:
            raise ValueError("Worker activation restart budget differs from durable state")
        self._require_evidence_binding_locked()

    def _require_not_reentrant(self) -> None:
        for domain in self._callback_domains:
            domain.lock.acquire()
        try:
            for domain in self._callback_domains:
                if domain.active:
                    raise _ActivationRejected(_ActivationReason.REENTRANT_CALL)
        finally:
            for domain in reversed(self._callback_domains):
                domain.lock.release()

    def _call_external(
        self,
        function: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        for domain in self._callback_domains:
            domain.lock.acquire()
        try:
            if any(domain.active for domain in self._callback_domains):
                raise _ActivationRejected(_ActivationReason.REENTRANT_CALL)
            for domain in self._callback_domains:
                domain.active = True
        finally:
            for domain in reversed(self._callback_domains):
                domain.lock.release()
        try:
            return function(*args, **kwargs)
        finally:
            for domain in self._callback_domains:
                domain.lock.acquire()
            try:
                for domain in self._callback_domains:
                    domain.active = False
            finally:
                for domain in reversed(self._callback_domains):
                    domain.lock.release()

    def _authority_release_domain(self) -> _ExternalCallbackDomain:
        return self._authority.callback_domain

    def _open_serialized_gate(self) -> int:
        self._require_not_reentrant()
        self.retry_pending_releases()
        context = self._call_external(self._authority.serialized_admission)
        enter = _bind_static_method(context, "__enter__")
        exit_method = _bind_static_method(context, "__exit__")
        release_id = self._register_pending_release(exit_method)
        try:
            # Gate acquisition is the one external operation allowed to block.
            # Its contract forbids callbacks; marking owner domains active while
            # queued here would prevent the current holder from releasing.
            self._require_not_reentrant()
            enter()
            self._mark_release_held(release_id)
        except BaseException:
            self._mark_release_due(release_id, allow_reserved=True)
            with suppress(BaseException):
                self._drain_release_due(release_id)
            raise
        return release_id

    def _register_pending_release(self, exit_method: Callable[..., object]) -> int:
        domain = self._authority_release_domain()
        with domain.release_condition:
            release_id = domain.next_release_id
            domain.next_release_id += 1
            domain.pending_releases[release_id] = _PendingAuthorityRelease(exit_method)
            return release_id

    def _mark_release_held(self, release_id: int) -> None:
        domain = self._authority_release_domain()
        with domain.release_condition:
            pending = domain.pending_releases.get(release_id)
            if pending is None or pending.phase != "reserved":
                raise RuntimeError("Worker authority release reservation is invalid")
            pending.phase = "held"
            domain.release_condition.notify_all()

    def _mark_release_due(
        self,
        release_id: int,
        *,
        allow_reserved: bool = False,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        domain = self._authority_release_domain()
        with domain.release_condition:
            pending = domain.pending_releases.get(release_id)
            if pending is None:
                return
            allowed = {"held", "release_due", "releasing"}
            if allow_reserved:
                allowed.add("reserved")
            if pending.phase not in allowed:
                raise RuntimeError("Worker authority release phase is invalid")
            if pending.exc_type is None and exc_type is not None:
                pending.exc_type = exc_type
                pending.exc_value = exc_value
                pending.traceback = traceback
            if pending.phase in {"reserved", "held"}:
                pending.phase = "release_due"
            domain.release_condition.notify_all()

    def _release_registered(
        self,
        release_id: int,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        self._require_not_reentrant()
        self._mark_release_due(
            release_id,
            exc_type=exc_type,
            exc_value=exc_value,
            traceback=traceback,
        )
        self._drain_release_due(release_id)

    def _drain_release_due(self, release_id: int) -> None:
        domain = self._authority_release_domain()
        while True:
            with domain.release_condition:
                pending = domain.pending_releases.get(release_id)
                if pending is None:
                    return
                if pending.phase in {"reserved", "held"}:
                    return
                if pending.phase == "settled":
                    del domain.pending_releases[release_id]
                    domain.release_condition.notify_all()
                    return
                if pending.phase == "releasing":
                    raise _ActivationRejected(_ActivationReason.REENTRANT_CALL)
                if pending.phase != "release_due":
                    raise RuntimeError("Worker authority release phase is invalid")
                pending.phase = "releasing"
                break
        try:
            self._call_external(
                pending.exit_method,
                pending.exc_type,
                pending.exc_value,
                pending.traceback,
            )
        except BaseException:
            with domain.release_condition:
                pending.phase = "release_due"
                domain.release_condition.notify_all()
            raise
        with domain.release_condition:
            observed = domain.pending_releases.get(release_id)
            if observed is pending:
                pending.phase = "settled"
                del domain.pending_releases[release_id]
            domain.release_condition.notify_all()

    def retry_pending_releases(self) -> None:
        """Drain shared serialized authority-release debt or fail closed."""

        self._require_not_reentrant()
        domain = self._authority_release_domain()
        while True:
            with domain.release_condition:
                release_ids = tuple(
                    sorted(
                        release_id
                        for release_id, pending in domain.pending_releases.items()
                        if pending.phase in {"release_due", "releasing"}
                    )
                )
            if not release_ids:
                return
            for release_id in release_ids:
                self._drain_release_due(release_id)


    @contextmanager
    def _serialized_gate(self) -> Iterator[None]:
        release_id = self._open_serialized_gate()
        try:
            yield
        finally:
            self._release_registered(release_id)

    def evaluate(
        self,
        policy: ProductWorkerActivationPolicyV1,
        receipt: ProductWorkerActivationReceiptV1 | None,
    ) -> Mapping[str, object]:
        """Return a closed decision before any acquisition side effect."""

        self._require_not_reentrant()
        if not isinstance(policy, ProductWorkerActivationPolicyV1):
            raise TypeError("Worker activation evaluation requires typed policy")
        if not policy.enabled or policy.requested_owner == "current" or receipt is None:
            reason = (
                _ActivationReason.POLICY_REQUIRED_UNAVAILABLE
                if policy.effective_required and policy.enabled
                else _ActivationReason.DISABLED_BY_POLICY
            )
            return _ActivationStatusV1(reason, policy.effective_required).to_dict()
        try:
            _validate_receipt_for_policy(policy, receipt)
        except _ActivationRejected as error:
            reason = (
                error.reason
                if policy.effective_required
                else _ActivationReason.OPTIONAL_DEGRADED
            )
            return _ActivationStatusV1(
                reason,
                policy.effective_required,
                receipt.fingerprint,
            ).to_dict()
        return _ActivationStatusV1(
            _ActivationReason.ADMITTED,
            policy.effective_required,
            receipt.fingerprint,
        ).to_dict()

    def admission(
        self,
        *,
        policy: ProductWorkerActivationPolicyV1,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
    ) -> _AttemptAdmissionLease:
        """Acquire the freshness lease spanning registration and first effect."""

        self._require_not_reentrant()
        return _AttemptAdmissionLease(
            coordinator=self,
            policy=policy,
            receipt=receipt,
            attempt_id=attempt_id,
            owner_generation=owner_generation,
            host_identity=host_identity,
            boot_identity=boot_identity,
        )

    def publish(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
        realized_native_policy_closure_fingerprint: str,
        native_profile_catalog_revision: str,
        native_profile_id: str,
    ) -> Mapping[str, object]:
        """Recheck freshness and atomically publish the exact fake generation."""

        _require_sha256(
            realized_native_policy_closure_fingerprint,
            name="realized native policy closure fingerprint",
        )
        _require_opaque(
            native_profile_catalog_revision,
            name="native profile catalog revision",
        )
        _require_identifier(native_profile_id, name="native profile id")
        key = _attempt_key(receipt, attempt_id, owner_generation)
        self._require_not_reentrant()
        with self._serialized_gate():
            with self._lock:
                self._reload_locked()
                attempt = self._attempt_locked(key, receipt=receipt)
                if self._state["killSwitchState"] != "open":
                    raise _ActivationRejected(_ActivationReason.KILL_SWITCH_LATCHED)
                self._require_current_locked(receipt)
                policy = receipt.policy
                if (
                    realized_native_policy_closure_fingerprint
                    != policy.expected_native_policy_closure_fingerprint
                    or native_profile_catalog_revision
                    != policy.native_profile_catalog_revision
                    or native_profile_id != policy.native_profile_id
                ):
                    raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
                slot = _domain_slot(policy)
                publications = _mapping(self._state, "publications")
                prior = publications.get(slot)
                if attempt["phase"] == "published" and prior == key.encoded:
                    return _status_for_attempt(
                        _ActivationReason.PUBLISHED,
                        key,
                        required=receipt.policy.effective_required,
                    )
                if attempt["phase"] != "effect_started":
                    raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
                if prior is not None and prior != key.encoded:
                    raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
                new_state = _json_clone(self._state)
                _mapping(new_state, "publications")[slot] = key.encoded
                new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
                _transition_attempt(new_attempt, "published")
                new_attempt["readiness"] = "ready"
                self._commit_locked(new_state)
                return _status_for_attempt(
                    _ActivationReason.PUBLISHED,
                    key,
                    required=receipt.policy.effective_required,
                )

    def record_protocol_terminal(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
    ) -> None:
        self._require_not_reentrant()
        key = _attempt_key(receipt, attempt_id, owner_generation)
        with self._lock:
            self._reload_locked()
            attempt = self._attempt_locked(key, receipt=receipt)
            if attempt["protocolTerminal"] is True:
                return
            new_state = _json_clone(self._state)
            _mapping(_mapping(new_state, "attempts"), key.encoded)[
                "protocolTerminal"
            ] = True
            self._commit_locked(new_state)

    def retire_exact(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
    ) -> Mapping[str, object]:
        """Retire only the exact generation; stale attempts cannot touch successors."""

        key = _attempt_key(receipt, attempt_id, owner_generation)
        self._require_not_reentrant()
        with self._serialized_gate():
            with self._lock:
                self._reload_locked()
                attempt = self._attempt_locked(key, receipt=receipt)
                slot = _domain_slot(receipt.policy)
                publications = _mapping(self._state, "publications")
                if attempt["domainRetired"] is True:
                    if publications.get(slot) == key.encoded:
                        raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
                    return _status_for_attempt(
                        _ActivationReason.RETIRED,
                        key,
                        required=receipt.policy.effective_required,
                    )
                if attempt["phase"] == "registered":
                    raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
                if attempt["phase"] == "published":
                    if publications.get(slot) != key.encoded:
                        raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
                elif publications.get(slot) not in {None, key.encoded}:
                    raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
                new_state = _json_clone(self._state)
                new_publications = _mapping(new_state, "publications")
                if new_publications.get(slot) == key.encoded:
                    del new_publications[slot]
                new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
                new_attempt["domainRetired"] = True
                if new_attempt["phase"] != "cleanup_debt":
                    _transition_attempt(new_attempt, "retired")
                self._commit_locked(new_state)
                return _status_for_attempt(
                    _ActivationReason.RETIRED,
                    key,
                    required=receipt.policy.effective_required,
                )

    def record_cleanup_settlement(
        self,
        settlement: WorkerCleanupSettlementV1,
        *,
        witness: object,
    ) -> Mapping[str, object]:
        self._require_not_reentrant()
        if not isinstance(settlement, WorkerCleanupSettlementV1):
            raise TypeError("Worker cleanup settlement must be typed")
        key = _AttemptKey(
            settlement.receipt_fingerprint,
            settlement.attempt_id,
            settlement.owner_generation,
        )
        with self._lock:
            self._reload_locked()
            attempt = self._attempt_locked(key)
            _require_cleanup_identity(
                attempt,
                settlement.host_identity,
                settlement.boot_identity,
            )
            if attempt["phase"] == "settled":
                if attempt["cleanupSettlement"] != settlement.to_dict():
                    raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
                return _status_for_attempt(
                    _ActivationReason.CLEANUP_SETTLED,
                    key,
                    required=bool(attempt["required"]),
                )
            if not attempt["protocolTerminal"] or not attempt["domainRetired"]:
                raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
            self._verify_cleanup_witness(
                method_name="verify_tree_settlement",
                witness=witness,
                key=key,
                attempt=attempt,
            )
            new_state = _json_clone(self._state)
            new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
            new_attempt["cleanupSettlement"] = settlement.to_dict()
            new_attempt["cleanupDebt"] = None
            _transition_attempt(new_attempt, "settled")
            self._commit_locked(new_state)
            return _status_for_attempt(
                _ActivationReason.CLEANUP_SETTLED,
                key,
                required=bool(attempt["required"]),
            )

    def record_cleanup_debt(
        self,
        debt: WorkerCleanupDebtV1,
    ) -> Mapping[str, object]:
        self._require_not_reentrant()
        if not isinstance(debt, WorkerCleanupDebtV1):
            raise TypeError("Worker cleanup debt must be typed")
        key = _AttemptKey(
            debt.receipt_fingerprint,
            debt.attempt_id,
            debt.owner_generation,
        )
        with self._lock:
            self._reload_locked()
            attempt = self._attempt_locked(key)
            _require_cleanup_identity(attempt, debt.host_identity, debt.boot_identity)
            if attempt["phase"] == "settled":
                raise _ActivationRejected(_ActivationReason.CLEANUP_SETTLED)
            if attempt["cleanupDebt"] is not None:
                if attempt["cleanupDebt"] != debt.to_dict():
                    raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
                return _status_for_attempt(
                    _ActivationReason.CLEANUP_DEBT,
                    key,
                    required=bool(attempt["required"]),
                )
            if attempt["phase"] == "registered":
                raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
            new_state = _json_clone(self._state)
            new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
            new_attempt["cleanupDebt"] = debt.to_dict()
            new_attempt["cleanupSettlement"] = None
            _transition_attempt(new_attempt, "cleanup_debt")
            new_attempt["readiness"] = (
                "unavailable" if bool(attempt["required"]) else "degraded"
            )
            self._commit_locked(new_state)
            return _status_for_attempt(
                _ActivationReason.CLEANUP_DEBT,
                key,
                required=bool(attempt["required"]),
            )

    def settle_changed_boot_absence(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
        current_boot_identity: str,
        witness: object,
    ) -> Mapping[str, object]:
        """Turn debt into settlement only for a trusted different boot identity."""

        self._require_not_reentrant()
        _require_opaque(current_boot_identity, name="current boot identity")
        key = _attempt_key(receipt, attempt_id, owner_generation)
        with self._lock:
            self._reload_locked()
            attempt = self._attempt_locked(key, receipt=receipt)
            if attempt["cleanupDebt"] is None:
                raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
            if attempt["bootIdentity"] == current_boot_identity:
                raise _ActivationRejected(_ActivationReason.CLEANUP_DEBT)
            if not attempt["protocolTerminal"] or not attempt["domainRetired"]:
                raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
            self._verify_cleanup_witness(
                method_name="verify_changed_boot_absence",
                witness=witness,
                key=key,
                attempt=attempt,
                current_boot_identity=current_boot_identity,
            )
            settlement = WorkerCleanupSettlementV1(
                receipt_fingerprint=key.receipt_fingerprint,
                attempt_id=key.attempt_id,
                owner_generation=key.owner_generation,
                host_identity=cast(str, attempt["hostIdentity"]),
                boot_identity=cast(str, attempt["bootIdentity"]),
                protocol_terminal=True,
                domain_retired=True,
                tree_settled=True,
            )
            new_state = _json_clone(self._state)
            new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
            new_attempt["cleanupDebt"] = None
            new_attempt["cleanupSettlement"] = settlement.to_dict()
            _transition_attempt(new_attempt, "settled")
            self._commit_locked(new_state)
            return _status_for_attempt(
                _ActivationReason.CLEANUP_SETTLED,
                key,
                required=bool(attempt["required"]),
            )

    def claim_restart(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
    ) -> Mapping[str, object]:
        """Consume restart budget only after terminal+retired+settled CAS closure."""

        self._require_not_reentrant()
        key = _attempt_key(receipt, attempt_id, owner_generation)
        with self._lock:
            self._reload_locked()
            attempt = self._attempt_locked(key, receipt=receipt)
            if (
                not attempt["protocolTerminal"]
                or not attempt["domainRetired"]
                or attempt["cleanupSettlement"] is None
                or attempt["cleanupDebt"] is not None
            ):
                raise _ActivationRejected(_ActivationReason.CLEANUP_DEBT)
            restart_ordinal = cast(int, attempt["restartOrdinal"])
            if restart_ordinal >= cast(int, self._state["restartBudget"]):
                raise _ActivationRejected(_ActivationReason.RESTART_EXHAUSTED)
            new_state = _json_clone(self._state)
            new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
            new_attempt["restartOrdinal"] = restart_ordinal + 1
            self._commit_locked(new_state)
            return _status_for_attempt(
                _ActivationReason.RESTART_READY,
                key,
                required=bool(attempt["required"]),
            )

    def recover_registered_no_effect(
        self,
        *,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
        current_boot_identity: str,
        witness: object,
    ) -> Mapping[str, object]:
        """Settle only an exact registered lease proven dead after host restart."""

        self._require_not_reentrant()
        _require_opaque(current_boot_identity, name="current boot identity")
        key = _attempt_key(receipt, attempt_id, owner_generation)
        with self._lock:
            self._reload_locked()
            attempt = self._attempt_locked(key, receipt=receipt)
            if attempt["phase"] == "settled":
                return _status_for_attempt(
                    _ActivationReason.CLEANUP_SETTLED,
                    key,
                    required=bool(attempt["required"]),
                )
            if attempt["phase"] != "registered":
                raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
            if attempt["bootIdentity"] == current_boot_identity:
                raise _ActivationRejected(_ActivationReason.CLEANUP_DEBT)
            self._verify_cleanup_witness(
                method_name="verify_registered_lease_expired",
                witness=witness,
                key=key,
                attempt=attempt,
                current_boot_identity=current_boot_identity,
            )
            self._settle_without_effect_locked(key)
            return _status_for_attempt(
                _ActivationReason.CLEANUP_SETTLED,
                key,
                required=bool(attempt["required"]),
            )

    def latch_kill_switch(self, *, expected_generation: int) -> tuple[Mapping[str, object], ...]:
        """Durably close, idempotently stale authority, then enumerate active keys."""

        _require_nonnegative_integer(expected_generation, name="kill-switch generation")
        self._require_not_reentrant()
        with self._serialized_gate():
            with self._lock:
                self._reload_locked()
                state = cast(str, self._state["killSwitchState"])
                current = cast(int, self._state["killSwitchGeneration"])
                prior = cast(int, self._state["killSwitchPriorGeneration"])
                if state == "completed":
                    if expected_generation not in {prior, current}:
                        raise _ActivationRejected(_ActivationReason.STALE_AUTHORITY)
                    return self.active_attempts()
                if state == "open":
                    if current not in {0, expected_generation}:
                        raise _ActivationRejected(_ActivationReason.STALE_AUTHORITY)
                    next_generation = expected_generation + 1
                    new_state = _json_clone(self._state)
                    new_state["killSwitchPriorGeneration"] = expected_generation
                    new_state["killSwitchGeneration"] = next_generation
                    new_state["killSwitchState"] = "pending"
                    self._commit_locked(new_state)
                else:
                    if state != "pending" or expected_generation != prior:
                        raise _ActivationRejected(_ActivationReason.STALE_AUTHORITY)
                    next_generation = current
                observed_generation = self._call_external(
                    self._authority.latch_kill_switch,
                    expected_generation=expected_generation,
                )
                if observed_generation != next_generation:
                    raise _ActivationRejected(_ActivationReason.STALE_AUTHORITY)
                completed_state = _json_clone(self._state)
                completed_state["killSwitchState"] = "completed"
                self._commit_locked(completed_state)
                return self.active_attempts()

    def active_attempts(self) -> tuple[Mapping[str, object], ...]:
        self._require_not_reentrant()
        with self._lock:
            self._reload_locked()
            attempts = _mapping(self._state, "attempts")
            active = []
            for key in sorted(attempts):
                attempt = _mapping(attempts, key)
                if attempt["phase"] not in {"settled"}:
                    active.append(_public_attempt(attempt))
            return tuple(active)

    def snapshot(self) -> Mapping[str, object]:
        """Return the strict durable state document without material authority."""

        self._require_not_reentrant()
        with self._lock:
            self._reload_locked()
            return _json_clone(self._state)

    def _enter_admission(
        self,
        lease: _AttemptAdmissionLease,
    ) -> None:
        self._require_not_reentrant()
        lease._authority_release_id = self._open_serialized_gate()
        self._lock.acquire()
        lease._lock_held = True
        try:
            self._reload_locked()
            if self._state["killSwitchState"] != "open":
                raise _ActivationRejected(_ActivationReason.KILL_SWITCH_LATCHED)
            _validate_receipt_for_policy(lease.policy, lease.receipt)
            self._require_current_locked(lease.receipt)
            key = _attempt_key(
                lease.receipt,
                lease.attempt_id,
                lease.owner_generation,
            )
            attempts = _mapping(self._state, "attempts")
            if key.encoded in attempts:
                raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
            new_state = _json_clone(self._state)
            _compact_settled_attempts(new_state)
            if len(_mapping(new_state, "attempts")) >= _MAX_DURABLE_ATTEMPTS:
                raise _ActivationRejected(_ActivationReason.CAPACITY_EXHAUSTED)
            if cast(int, new_state["killSwitchGeneration"]) == 0:
                new_state["killSwitchGeneration"] = (
                    lease.receipt.policy.kill_switch_generation
                )
                new_state["killSwitchPriorGeneration"] = (
                    lease.receipt.policy.kill_switch_generation
                )
            _mapping(new_state, "attempts")[key.encoded] = {
                "attemptId": key.attempt_id,
                "bootIdentity": lease.boot_identity,
                "cleanupDebt": None,
                "cleanupSettlement": None,
                "domainRetired": False,
                "evidenceAuthorityFingerprint": (
                    self._evidence_authority.authority_fingerprint
                ),
                "evidenceAuthorityId": self._evidence_authority.authority_id,
                "hostIdentity": lease.host_identity,
                "owner": "hosting",
                "ownerGeneration": key.owner_generation,
                "phase": "registered",
                "policyFingerprint": lease.policy.fingerprint,
                "protocolTerminal": False,
                "readiness": "pending",
                "receiptFingerprint": key.receipt_fingerprint,
                "required": lease.policy.effective_required,
                "restartOrdinal": 0,
            }
            lease._key = key
            self._commit_locked(new_state)
        except BaseException as error:
            if lease._key is not None and not isinstance(error, _ActivationRejected):
                with suppress(BaseException):
                    attempt = self._attempt_locked(lease._key)
                    if (
                        attempt["phase"] == "registered"
                        and attempt["hostIdentity"] == lease.host_identity
                        and attempt["bootIdentity"] == lease.boot_identity
                        and attempt["policyFingerprint"] == lease.policy.fingerprint
                    ):
                        self._settle_without_effect_locked(lease._key)
                        lease._completed = True
            self._release_admission(lease, None, None, None)
            raise

    def _leave_admission(
        self,
        lease: _AttemptAdmissionLease,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._require_not_reentrant()
        try:
            if lease._key is not None and not lease._completed:
                self._settle_without_effect_locked(lease._key)
                lease._completed = True
        finally:
            self._release_admission(lease, exc_type, exc_value, traceback)

    def _release_admission(
        self,
        lease: _AttemptAdmissionLease,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._require_not_reentrant()
        if lease._lock_held:
            lease._lock_held = False
            self._lock.release()
        release_id = lease._authority_release_id
        if release_id is not None:
            self._release_registered(
                release_id,
                exc_type,
                exc_value,
                traceback,
            )
            lease._authority_release_id = None

    def _mark_effect_started(self, lease: _AttemptAdmissionLease) -> None:
        self._require_not_reentrant()
        key = lease._required_key()
        attempt = self._attempt_locked(key)
        if attempt["phase"] != "registered":
            raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
        new_state = _json_clone(self._state)
        new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
        _transition_attempt(new_attempt, "effect_started")
        try:
            self._commit_locked(new_state)
        except BaseException:
            observed = self._state.get("attempts")
            if isinstance(observed, dict):
                current = observed.get(key.encoded)
                if isinstance(current, dict) and current.get("phase") == "effect_started":
                    lease._completed = True
                    self._release_admission(lease, None, None, None)
            raise
        lease._completed = True
        self._release_admission(lease, None, None, None)

    def _settle_without_effect(self, lease: _AttemptAdmissionLease) -> None:
        self._require_not_reentrant()
        key = lease._required_key()
        try:
            self._settle_without_effect_locked(key)
        except BaseException:
            observed = self._state.get("attempts")
            if isinstance(observed, dict):
                current = observed.get(key.encoded)
                if isinstance(current, dict) and current.get("phase") == "settled":
                    lease._completed = True
                    self._release_admission(lease, None, None, None)
            raise
        lease._completed = True
        self._release_admission(lease, None, None, None)

    def _settle_without_effect_locked(self, key: _AttemptKey) -> None:
        attempt = self._attempt_locked(key)
        if attempt["phase"] != "registered":
            raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
        settlement = WorkerCleanupSettlementV1(
            receipt_fingerprint=key.receipt_fingerprint,
            attempt_id=key.attempt_id,
            owner_generation=key.owner_generation,
            host_identity=cast(str, attempt["hostIdentity"]),
            boot_identity=cast(str, attempt["bootIdentity"]),
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
        )
        new_state = _json_clone(self._state)
        new_attempt = _mapping(_mapping(new_state, "attempts"), key.encoded)
        new_attempt["protocolTerminal"] = True
        new_attempt["domainRetired"] = True
        new_attempt["cleanupSettlement"] = settlement.to_dict()
        _transition_attempt(new_attempt, "settled")
        self._commit_locked(new_state)

    def _require_current_locked(
        self,
        receipt: ProductWorkerActivationReceiptV1,
    ) -> None:
        witness = self._call_external(
            self._authority.current_witness,
            receipt,
        )
        if witness != receipt.authority_witness:
            raise _ActivationRejected(_ActivationReason.STALE_AUTHORITY)
        state_generation = cast(int, self._state["killSwitchGeneration"])
        if state_generation not in {0, receipt.policy.kill_switch_generation}:
            raise _ActivationRejected(_ActivationReason.STALE_AUTHORITY)

    def _verify_cleanup_witness(
        self,
        *,
        method_name: str,
        witness: object,
        key: _AttemptKey,
        attempt: Mapping[str, object],
        current_boot_identity: str | None = None,
    ) -> None:
        verifiers = {
            "verify_changed_boot_absence": (
                self._evidence_authority.verify_changed_boot_absence
            ),
            "verify_registered_lease_expired": (
                self._evidence_authority.verify_registered_lease_expired
            ),
            "verify_tree_settlement": self._evidence_authority.verify_tree_settlement,
        }
        verifier = verifiers[method_name]
        arguments: dict[str, object] = {
            "attempt_id": key.attempt_id,
            "boot_identity": attempt["bootIdentity"],
            "host_identity": attempt["hostIdentity"],
            "owner_generation": key.owner_generation,
            "receipt_fingerprint": key.receipt_fingerprint,
            "witness": witness,
            "evidence_authority_id": attempt["evidenceAuthorityId"],
            "evidence_authority_fingerprint": attempt[
                "evidenceAuthorityFingerprint"
            ],
        }
        if current_boot_identity is not None:
            arguments["current_boot_identity"] = current_boot_identity
        if (
            self._call_external(
                verifier,
                **arguments,
            )
            is not True
        ):
            raise _ActivationRejected(_ActivationReason.CLEANUP_DEBT)

    def _require_evidence_binding_locked(self) -> None:
        attempts = _mapping(self._state, "attempts")
        for encoded_key in attempts:
            attempt = _mapping(attempts, encoded_key)
            if (
                attempt["evidenceAuthorityId"]
                != self._evidence_authority.authority_id
                or attempt["evidenceAuthorityFingerprint"]
                != self._evidence_authority.authority_fingerprint
            ):
                raise ValueError("Worker cleanup evidence authority differs from durable state")

    def _attempt_locked(
        self,
        key: _AttemptKey,
        *,
        receipt: ProductWorkerActivationReceiptV1 | None = None,
    ) -> dict[str, object]:
        attempts = _mapping(self._state, "attempts")
        attempt = attempts.get(key.encoded)
        if not isinstance(attempt, dict):
            raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
        if (
            attempt["evidenceAuthorityId"] != self._evidence_authority.authority_id
            or attempt["evidenceAuthorityFingerprint"]
            != self._evidence_authority.authority_fingerprint
        ):
            raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
        if receipt is not None and attempt["policyFingerprint"] != receipt.policy.fingerprint:
            raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
        return attempt

    def _update_attempt_flag(self, key: _AttemptKey, name: str, value: bool) -> None:
        with self._lock:
            self._reload_locked()
            self._attempt_locked(key)
            new_state = _json_clone(self._state)
            _mapping(_mapping(new_state, "attempts"), key.encoded)[name] = value
            self._commit_locked(new_state)

    def _reload_locked(self) -> None:
        loaded_value = self._call_external(
            self._store.load,
        )
        if loaded_value is None:
            raise RuntimeError("Worker activation durable state disappeared")
        if not isinstance(loaded_value, Mapping):
            raise ValueError("Worker activation store returned invalid state")
        self._state = _validate_state(loaded_value)

    def _commit_locked(self, new_state: dict[str, object]) -> None:
        expected = cast(int, self._state["stateRevision"])
        new_state["stateRevision"] = expected + 1
        validated = _validate_state(new_state)
        try:
            committed = self._call_external(
                self._store.compare_and_swap,
                expected_revision=expected,
                document=validated,
            )
        except BaseException:
            # A durable owner may commit and fail before returning.  Reloading
            # preserves the conservative active/debt witness for the caller.
            with suppress(BaseException):
                self._reload_locked()
            raise
        if committed is not True:
            self._reload_locked()
            raise _ActivationRejected(_ActivationReason.STALE_AUTHORITY)
        self._state = validated


class _AttemptAdmissionLease(AbstractContextManager["_AttemptAdmissionLease"]):
    """Non-transferable lease held through registration and first effect."""

    def __init__(
        self,
        *,
        coordinator: ProductWorkerActivationCoordinator,
        policy: ProductWorkerActivationPolicyV1,
        receipt: ProductWorkerActivationReceiptV1,
        attempt_id: str,
        owner_generation: int,
        host_identity: str,
        boot_identity: str,
    ) -> None:
        if not isinstance(policy, ProductWorkerActivationPolicyV1):
            raise TypeError("Worker admission requires typed policy")
        if not isinstance(receipt, ProductWorkerActivationReceiptV1):
            raise TypeError("Worker admission requires typed receipt")
        _require_attempt_id(attempt_id)
        _require_positive_integer(owner_generation, name="owner generation")
        _require_opaque(host_identity, name="host identity")
        _require_opaque(boot_identity, name="boot identity")
        self.coordinator = coordinator
        self.policy = policy
        self.receipt = receipt
        self.attempt_id = attempt_id
        self.owner_generation = owner_generation
        self.host_identity = host_identity
        self.boot_identity = boot_identity
        self._key: _AttemptKey | None = None
        self._authority_release_id: int | None = None
        self._lock_held = False
        self._entered = False
        self._completed = False

    def __enter__(self) -> Self:
        if self._entered:
            raise RuntimeError("Worker admission lease is one-use")
        self._entered = True
        self.coordinator._enter_admission(self)
        return self

    def begin_effect(self) -> None:
        self._require_open()
        self.coordinator._mark_effect_started(self)

    def settle_without_effect(self) -> None:
        self._require_open()
        self.coordinator._settle_without_effect(self)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._authority_release_id is None:
            return None
        if self._key is not None and not self._completed:
            self.coordinator._leave_admission(self, exc_type, exc_value, traceback)
        else:
            self.coordinator._release_admission(
                self,
                exc_type,
                exc_value,
                traceback,
            )
        return None

    def retry_release(self) -> None:
        """Retry the idempotent Product gate release after an ambiguous fault."""

        if self._authority_release_id is not None:
            self.coordinator._release_admission(self, None, None, None)

    def _required_key(self) -> _AttemptKey:
        self._require_open()
        assert self._key is not None
        return self._key

    def _require_open(self) -> None:
        if self._key is None or self._authority_release_id is None or self._completed:
            raise RuntimeError("Worker admission lease is not open")


_POLICY_FIELDS = frozenset(
    {
        "allowedContributionIds",
        "allowedNativeProfileIds",
        "allowedProductIds",
        "contributionId",
        "declarationFingerprint",
        "declaredRequired",
        "effectiveRequired",
        "enabled",
        "expectedNativePolicyClosureFingerprint",
        "killSwitchGeneration",
        "nativeProfileCatalogRevision",
        "nativeProfileId",
        "noFallback",
        "ownerSelectionGeneration",
        "pluginId",
        "pluginRevisionDigest",
        "policyVersion",
        "productId",
        "productPolicyRevision",
        "productRuntimeId",
        "productScopeId",
        "requestedOwner",
        "reservationFingerprint",
        "selectedLocatorFingerprint",
        "selectedLocatorRevision",
        "sessionId",
        "sessionRoute",
        "workerConfigurationFingerprint",
    }
)
_RECEIPT_FIELDS = frozenset(
    {"issueNonce", "issueSequence", "policy", "receiptFingerprint", "receiptVersion"}
)
_SETTLEMENT_FIELDS = frozenset(
    {
        "attemptId",
        "bootIdentity",
        "domainRetired",
        "hostIdentity",
        "ownerGeneration",
        "protocolTerminal",
        "receiptFingerprint",
        "settlementVersion",
        "treeSettled",
    }
)
_DEBT_FIELDS = frozenset(
    {
        "attemptId",
        "bootIdentity",
        "debtVersion",
        "hostIdentity",
        "ownerGeneration",
        "reason",
        "receiptFingerprint",
    }
)
_STATE_FIELDS = frozenset(
    {
        "attempts",
        "killSwitchGeneration",
        "killSwitchPriorGeneration",
        "killSwitchState",
        "publications",
        "restartBudget",
        "stateRevision",
        "stateVersion",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {
        "attemptId",
        "bootIdentity",
        "cleanupDebt",
        "cleanupSettlement",
        "domainRetired",
        "evidenceAuthorityFingerprint",
        "evidenceAuthorityId",
        "hostIdentity",
        "owner",
        "ownerGeneration",
        "phase",
        "policyFingerprint",
        "protocolTerminal",
        "readiness",
        "receiptFingerprint",
        "required",
        "restartOrdinal",
    }
)

_ATTEMPT_TRANSITIONS = {
    "registered": frozenset({"effect_started", "settled"}),
    "effect_started": frozenset({"published", "retired", "cleanup_debt"}),
    "published": frozenset({"retired", "cleanup_debt"}),
    "retired": frozenset({"cleanup_debt", "settled"}),
    "cleanup_debt": frozenset({"settled"}),
    "settled": frozenset(),
}


def _transition_attempt(attempt: dict[str, object], target: str) -> None:
    """Apply the single closed, monotonic lifecycle transition table."""

    current = attempt.get("phase")
    if not isinstance(current, str) or current not in _ATTEMPT_TRANSITIONS:
        raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
    if current == target:
        return
    if target not in _ATTEMPT_TRANSITIONS[current]:
        raise _ActivationRejected(_ActivationReason.PUBLICATION_FENCED)
    attempt["phase"] = target


def _compact_settled_attempts(state: dict[str, object]) -> None:
    """Deterministically free one admission slot using absorbing records only."""

    attempts = _mapping(state, "attempts")
    required = max(0, len(attempts) - _MAX_DURABLE_ATTEMPTS + 1)
    settled = sorted(
        key
        for key, value in attempts.items()
        if isinstance(value, dict) and value.get("phase") == "settled"
    )
    for key in settled[:required]:
        del attempts[key]


def _initial_state(*, restart_budget: int) -> dict[str, object]:
    return {
        "attempts": {},
        "killSwitchGeneration": 0,
        "killSwitchPriorGeneration": 0,
        "killSwitchState": "open",
        "publications": {},
        "restartBudget": restart_budget,
        "stateRevision": 1,
        "stateVersion": PRODUCT_WORKER_ACTIVATION_STATE_VERSION,
    }


def _validate_state(value: object) -> dict[str, object]:
    document = _strict_document(value, _STATE_FIELDS, name="activation state")
    if _integer(document, "stateVersion") != PRODUCT_WORKER_ACTIVATION_STATE_VERSION:
        raise ValueError("Unsupported Product Worker activation state version")
    _require_positive_integer(_integer(document, "stateRevision"), name="state revision")
    _require_nonnegative_integer(
        _integer(document, "killSwitchGeneration"),
        name="kill-switch generation",
    )
    prior_generation = _integer(document, "killSwitchPriorGeneration")
    generation = _integer(document, "killSwitchGeneration")
    _require_nonnegative_integer(prior_generation, name="prior kill-switch generation")
    kill_switch_state = _string(document, "killSwitchState")
    if kill_switch_state not in {"open", "pending", "completed"}:
        raise ValueError("Worker activation kill-switch state is unsupported")
    if kill_switch_state == "open" and prior_generation != generation:
        raise ValueError("Open Worker kill switch has inconsistent generations")
    if kill_switch_state != "open" and generation != prior_generation + 1:
        raise ValueError("Latched Worker kill switch has inconsistent generations")
    _require_nonnegative_integer(
        _integer(document, "restartBudget"),
        name="restart budget",
    )
    attempts = _mapping(document, "attempts")
    if len(attempts) > _MAX_DURABLE_ATTEMPTS:
        raise ValueError("Worker activation state has too many attempts")
    for encoded_key, raw_attempt in attempts.items():
        attempt = _strict_document(
            raw_attempt,
            _ATTEMPT_FIELDS,
            name="activation attempt",
        )
        receipt_fingerprint = _string(attempt, "receiptFingerprint")
        attempt_id = _string(attempt, "attemptId")
        owner_generation = _integer(attempt, "ownerGeneration")
        _require_sha256(receipt_fingerprint, name="receipt fingerprint")
        _require_attempt_id(attempt_id)
        _require_positive_integer(owner_generation, name="owner generation")
        expected_key = _AttemptKey(
            receipt_fingerprint,
            attempt_id,
            owner_generation,
        ).encoded
        if encoded_key != expected_key:
            raise ValueError("Worker activation attempt key mismatch")
        _require_opaque(_string(attempt, "hostIdentity"), name="host identity")
        _require_opaque(_string(attempt, "bootIdentity"), name="boot identity")
        _require_opaque(
            _string(attempt, "evidenceAuthorityId"),
            name="cleanup evidence authority id",
        )
        _require_sha256(
            _string(attempt, "evidenceAuthorityFingerprint"),
            name="cleanup evidence authority fingerprint",
        )
        _require_sha256(
            _string(attempt, "policyFingerprint"),
            name="policy fingerprint",
        )
        if _string(attempt, "owner") != "hosting":
            raise ValueError("Worker activation attempt owner must remain Hosting")
        phase = _string(attempt, "phase")
        if phase not in _ATTEMPT_TRANSITIONS:
            raise ValueError("Worker activation attempt phase is unsupported")
        readiness = _string(attempt, "readiness")
        if readiness not in {"pending", "ready", "degraded", "unavailable"}:
            raise ValueError("Worker activation readiness is unsupported")
        _bool(attempt, "protocolTerminal")
        _bool(attempt, "domainRetired")
        _bool(attempt, "required")
        _require_nonnegative_integer(
            _integer(attempt, "restartOrdinal"),
            name="restart ordinal",
        )
        if _integer(attempt, "restartOrdinal") > _integer(document, "restartBudget"):
            raise ValueError("Worker activation restart ordinal exceeds durable budget")
        settlement_value = attempt["cleanupSettlement"]
        debt_value = attempt["cleanupDebt"]
        settlement = (
            None
            if settlement_value is None
            else WorkerCleanupSettlementV1.from_dict(settlement_value)
        )
        debt = (
            None if debt_value is None else WorkerCleanupDebtV1.from_dict(debt_value)
        )
        if settlement is not None and debt is not None:
            raise ValueError("Worker activation attempt cannot be settled and debt")
        if settlement is not None and (
            settlement.receipt_fingerprint != receipt_fingerprint
            or settlement.attempt_id != attempt_id
            or settlement.owner_generation != owner_generation
            or settlement.host_identity != attempt["hostIdentity"]
            or settlement.boot_identity != attempt["bootIdentity"]
        ):
            raise ValueError("Worker cleanup settlement identity mismatch")
        if debt is not None and (
            debt.receipt_fingerprint != receipt_fingerprint
            or debt.attempt_id != attempt_id
            or debt.owner_generation != owner_generation
            or debt.host_identity != attempt["hostIdentity"]
            or debt.boot_identity != attempt["bootIdentity"]
        ):
            raise ValueError("Worker cleanup debt identity mismatch")
        if phase == "settled" and settlement is None:
            raise ValueError("Settled Worker activation attempt lacks settlement")
        if phase == "cleanup_debt" and debt is None:
            raise ValueError("Worker cleanup-debt phase lacks debt")
        if phase != "cleanup_debt" and debt is not None:
            raise ValueError("Worker cleanup debt has inconsistent attempt phase")
        if phase != "settled" and settlement is not None:
            raise ValueError("Worker cleanup settlement has inconsistent attempt phase")
        if phase in {"retired", "settled"} and attempt["domainRetired"] is not True:
            raise ValueError("Retired Worker activation attempt lacks domain retirement")
        if phase == "settled" and attempt["protocolTerminal"] is not True:
            raise ValueError("Settled Worker activation attempt lacks protocol terminal")
        if phase in {"registered", "effect_started", "published"} and attempt[
            "domainRetired"
        ] is True:
            raise ValueError("Live Worker activation attempt claims domain retirement")
    publications = _mapping(document, "publications")
    publication_targets: set[str] = set()
    for slot, encoded_value in publications.items():
        _require_sha256(slot, name="domain slot fingerprint")
        if not isinstance(encoded_value, str) or encoded_value not in attempts:
            raise ValueError("Worker activation publication target is invalid")
        attempt = _mapping(attempts, encoded_value)
        if attempt["phase"] not in {"published", "cleanup_debt"}:
            raise ValueError("Worker activation publication is not live")
        if attempt["domainRetired"] is True:
            raise ValueError("Retired Worker activation publication remains visible")
        if encoded_value in publication_targets:
            raise ValueError("Worker activation attempt occupies multiple publications")
        publication_targets.add(encoded_value)
    for encoded_key in attempts:
        attempt = _mapping(attempts, encoded_key)
        if attempt["phase"] == "published" and encoded_key not in publication_targets:
            raise ValueError("Published Worker activation attempt has no publication")
    return _json_clone(document)


def _validate_receipt_for_policy(
    policy: ProductWorkerActivationPolicyV1,
    receipt: ProductWorkerActivationReceiptV1,
) -> None:
    if not isinstance(receipt, ProductWorkerActivationReceiptV1):
        raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)
    if not policy.enabled or policy.requested_owner != "hosting":
        raise _ActivationRejected(_ActivationReason.DISABLED_BY_POLICY)
    if receipt.policy.product_id != policy.product_id:
        raise _ActivationRejected(_ActivationReason.FOREIGN_RECEIPT)
    if receipt.policy.fingerprint != policy.fingerprint:
        raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)


def _attempt_key(
    receipt: ProductWorkerActivationReceiptV1,
    attempt_id: str,
    owner_generation: int,
) -> _AttemptKey:
    if not isinstance(receipt, ProductWorkerActivationReceiptV1):
        raise TypeError("Worker attempt requires typed receipt")
    _require_attempt_id(attempt_id)
    _require_positive_integer(owner_generation, name="owner generation")
    return _AttemptKey(receipt.fingerprint, attempt_id, owner_generation)


def _domain_slot(policy: ProductWorkerActivationPolicyV1) -> str:
    return _fingerprint(
        _DOMAIN_SLOT_DOMAIN,
        {
            "contributionId": policy.contribution_id,
            "productId": policy.product_id,
            "productRuntimeId": policy.product_runtime_id,
            "productScopeId": policy.product_scope_id,
            "sessionId": policy.session_id,
        },
    )


def _status_for_attempt(
    reason: _ActivationReason,
    key: _AttemptKey,
    *,
    required: bool,
) -> Mapping[str, object]:
    return _ActivationStatusV1(
        reason,
        required,
        key.receipt_fingerprint,
        key.attempt_id,
        key.owner_generation,
    ).to_dict()


def _public_attempt(attempt: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "attemptId": attempt["attemptId"],
        "owner": attempt["owner"],
        "ownerGeneration": attempt["ownerGeneration"],
        "phase": attempt["phase"],
        "readiness": attempt["readiness"],
        "receiptFingerprint": attempt["receiptFingerprint"],
        "required": attempt["required"],
    }


def _require_cleanup_identity(
    attempt: Mapping[str, object],
    host_identity: str,
    boot_identity: str,
) -> None:
    if (
        attempt["hostIdentity"] != host_identity
        or attempt["bootIdentity"] != boot_identity
    ):
        raise _ActivationRejected(_ActivationReason.INVALID_RECEIPT)


def _strict_document(
    value: object,
    fields: frozenset[str],
    *,
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"Worker {name} has invalid fields")
    return cast(dict[str, object], value)


def _mapping(value: Mapping[str, object], name: str) -> dict[str, object]:
    item = value.get(name)
    if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
        raise ValueError(f"Worker activation {name} must be an object")
    return cast(dict[str, object], item)


def _string(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str):
        raise ValueError(f"Worker activation {name} must be a string")
    return item


def _optional_string(value: Mapping[str, object], name: str) -> str | None:
    item = value.get(name)
    if item is not None and not isinstance(item, str):
        raise ValueError(f"Worker activation {name} must be a string or null")
    return item


def _integer(value: Mapping[str, object], name: str) -> int:
    item = value.get(name)
    if type(item) is not int:
        raise ValueError(f"Worker activation {name} must be an integer")
    return cast(int, item)


def _bool(value: Mapping[str, object], name: str) -> bool:
    item = value.get(name)
    if type(item) is not bool:
        raise ValueError(f"Worker activation {name} must be a boolean")
    return cast(bool, item)


def _string_tuple(value: Mapping[str, object], name: str) -> tuple[str, ...]:
    item = value.get(name)
    if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
        raise ValueError(f"Worker activation {name} must be a string array")
    return tuple(item)


def _require_identifier(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_TEXT
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise ValueError(f"{name} must be a bounded canonical identifier")


def _require_opaque(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_TEXT
        or _OPAQUE.fullmatch(value) is None
    ):
        raise ValueError(f"{name} must be a bounded opaque token")


def _require_sha256(value: object, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 fingerprint")


def _optional_sha256(value: str | None, *, name: str) -> str:
    if value is None:
        return ""
    _require_sha256(value, name=name)
    return value


def _require_allowlist(value: object, *, name: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{name} must be a nonempty tuple")
    if tuple(sorted(set(value))) != value:
        raise ValueError(f"{name} must be sorted and unique")
    for item in value:
        _require_identifier(item, name=name)


def _require_bool(value: object, *, name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")


def _require_positive_integer(value: object, *, name: str) -> None:
    if type(value) is not int or cast(int, value) < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_nonnegative_integer(value: object, *, name: str) -> None:
    if type(value) is not int or cast(int, value) < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _require_attempt_id(value: object) -> None:
    if not isinstance(value, str) or _HEX32.fullmatch(value) is None:
        raise ValueError("Worker attempt id must be 32 lowercase hex characters")


def _fingerprint(domain: str, document: Mapping[str, object]) -> str:
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = sha256()
    digest.update(domain.encode("ascii"))
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    return digest.hexdigest()


def _json_clone(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    clone = json.loads(json.dumps(value, ensure_ascii=True, sort_keys=True))
    if not isinstance(clone, dict):
        raise TypeError("Worker activation state must be a JSON object")
    return cast(dict[str, object], clone)


__all__ = [
    "ProductWorkerActivationAuthorityPort",
    "ProductWorkerActivationPolicyV1",
    "ProductWorkerActivationReceiptV1",
]
