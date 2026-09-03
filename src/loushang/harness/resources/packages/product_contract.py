"""Transport-neutral PLC9A2 Product package lifecycle contract.

This module deliberately owns its wire-facing vocabulary. Plugin-lifecycle
kernel records are mapped at the activation adapter and never escape through a
Product transport contract.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal, Protocol, TypeVar

PACKAGE_PRODUCT_INTENT_VERSION = 1
PACKAGE_PRODUCT_EVIDENCE_VERSION = 1
PACKAGE_PRODUCT_OUTCOME_VERSION = 1
PACKAGE_PRODUCT_RECORD_VERSION = 1
PACKAGE_PRODUCT_UPDATE_CHECK_VERSION = 1
PACKAGE_PRODUCT_UPDATE_CHECK_REQUEST_VERSION = 1
PACKAGE_PRODUCT_UPDATE_MANIFEST_RECEIPT_VERSION = 1
PACKAGE_PRODUCT_UPDATE_TARGET_VERSION = 1

PackageProductLifecycleAction = Literal[
    "materialize", "install", "update", "remove", "uninstall"
]
PackageProductLifecycleMode = Literal["legacy", "dark", "enforced"]
PackageProductLifecyclePhase = Literal[
    "accepted",
    "classified",
    "acquiring",
    "acquired",
    "inspecting",
    "extracted",
    "resolving_closure",
    "closure_verified",
    "transaction_pinned",
    "staging",
    "set_published",
    "committed",
]
PackageProductLifecycleDisposition = Literal[
    "active", "committed", "rejected", "retryable_failure", "cancelled"
]
PackageProductClassificationDecision = Literal[
    "plugin_bound", "non_plugin", "indeterminate"
]
PackageProductEntrypoint = Literal[
    "cli", "rpc", "session", "startup", "operations", "direct_materializer"
]
PackageProductRoutingDisposition = Literal["plugin_handled", "non_plugin"]
PackageProductScope = Literal["user", "project", "session"]
T = TypeVar("T")

_SHA256_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ACTIONS = frozenset({"materialize", "install", "update", "remove", "uninstall"})
_PHASES = frozenset(
    {
        "accepted",
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
        "transaction_pinned",
        "staging",
        "set_published",
        "committed",
    }
)
_DISPOSITIONS = frozenset(
    {"active", "committed", "rejected", "retryable_failure", "cancelled"}
)
# Product exposes only the stable, classified failure vocabulary mapped from the
# private lifecycle owner.  Treating an arbitrary identifier-shaped string as a
# code would turn every transport record into a covert detail channel.
PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES = frozenset(
    {
        "package_acquisition_digest_mismatch",
        "package_acquisition_limit_exceeded",
        "package_archive_entry_type_rejected",
        "package_archive_malformed",
        "package_archive_name_collision",
        "package_archive_path_rejected",
        "package_artifact_identity_changed",
        "package_artifact_type_rejected",
        "package_attempt_stale",
        "package_closure_artifact_invalid",
        "package_closure_conflict",
        "package_closure_evidence_unsupported",
        "package_commit_admission_denied",
        "package_desired_revision_conflict",
        "package_operation_cancelled",
        "package_operation_identity_conflict",
        "package_operation_interrupted",
        "package_operation_timed_out",
        "package_publication_collision",
        "package_publication_root_untrusted",
        "package_quarantine_cleanup_retryable",
        "package_resource_limit_exceeded",
        "package_retention_handoff_interrupted",
        "package_retention_handoff_stale",
        "package_route_unavailable",
        "package_runtime_epoch_unsupported",
        "package_source_provenance_changed",
        "package_source_unauthorized",
        "package_target_classification_changed",
        "package_target_classification_indeterminate",
        "package_wheel_metadata_invalid",
        "package_wheel_record_invalid",
    }
)


def canonicalize_package_product_scope(scope: str) -> PackageProductScope:
    """Map the compatibility spelling ``global`` to canonical Product ``user``."""

    canonical = "user" if scope == "global" else scope
    if canonical not in {"user", "project", "session"}:
        raise ValueError("Unsupported Package Product scope")
    return canonical  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleIntentV1:
    """One transport-neutral package intent; provenance is carried separately."""

    operation_id: str
    action: PackageProductLifecycleAction
    source: str
    scope: str
    intent_version: int = PACKAGE_PRODUCT_INTENT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "Package Product operation id"),
            (self.source, "Package Product source"),
            (self.scope, "Package Product scope"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if self.action not in _ACTIONS:
            raise ValueError("Unsupported Package Product action")
        object.__setattr__(
            self,
            "scope",
            canonicalize_package_product_scope(self.scope),
        )
        if self.intent_version != PACKAGE_PRODUCT_INTENT_VERSION:
            raise ValueError("Unsupported Package Product intent")


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleEvidenceV1:
    """Pathless Product-owned evidence copied from the private owner journal."""

    operation_id: str
    request_ref: str
    source_ref: str
    display_name: str
    classification: PackageProductClassificationDecision
    phase: PackageProductLifecyclePhase
    disposition: PackageProductLifecycleDisposition
    failure_code: str | None
    evidence_version: int = PACKAGE_PRODUCT_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "Package Product operation id"),
            (self.display_name, "Package Product display name"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        for value, name in (
            (self.request_ref, "Package Product request reference"),
            (self.source_ref, "Package Product source reference"),
        ):
            if not isinstance(value, str) or _SHA256_REF.fullmatch(value) is None:
                raise ValueError(f"{name} must be an opaque SHA-256 reference")
        if self.classification not in {
            "plugin_bound",
            "non_plugin",
            "indeterminate",
        }:
            raise ValueError("Unsupported Package Product classification")
        if self.phase not in _PHASES:
            raise ValueError("Unsupported Package Product lifecycle phase")
        if self.disposition not in _DISPOSITIONS:
            raise ValueError("Unsupported Package Product lifecycle disposition")
        if self.disposition == "committed" and self.phase != "committed":
            raise ValueError("Committed Package Product evidence changed phase")
        if self.disposition != "committed" and self.phase == "committed":
            raise ValueError("Non-committed Package Product evidence changed phase")
        if self.disposition == "committed":
            if self.failure_code is not None:
                raise ValueError(
                    "Committed Package Product evidence cannot carry a code"
                )
        elif self.disposition == "active":
            if self.failure_code is not None:
                raise ValueError("Active Package Product evidence cannot carry a code")
        elif self.failure_code is None:
            raise ValueError("Failed Package Product evidence requires a code")
        elif self.failure_code not in PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES:
            raise ValueError("Unsupported Package Product failure code")
        if self.evidence_version != PACKAGE_PRODUCT_EVIDENCE_VERSION:
            raise ValueError("Unsupported Package Product evidence")


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleRecordV1:
    """Compatibility projection derived only from Product-owned evidence."""

    operation_id: str
    action: PackageProductLifecycleAction
    source_identity: str
    name: str
    lifecycle: Literal["installed", "remote_registered", "failed"]
    phase: PackageProductLifecyclePhase
    disposition: PackageProductLifecycleDisposition
    failure_code: str | None
    record_version: int = PACKAGE_PRODUCT_RECORD_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "Package Product operation id"),
            (self.source_identity, "Package Product source identity"),
            (self.name, "Package Product name"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if _SHA256_REF.fullmatch(self.source_identity) is None:
            raise ValueError("Package Product source identity must be opaque")
        if self.name != (
            f"plugin-{self.source_identity.removeprefix('sha256:')[:12]}"
        ):
            raise ValueError("Package Product name changed source identity")
        if self.action not in _ACTIONS:
            raise ValueError("Unsupported Package Product record action")
        if self.phase not in _PHASES:
            raise ValueError("Unsupported Package Product record phase")
        if self.disposition not in _DISPOSITIONS:
            raise ValueError("Unsupported Package Product record disposition")
        if self.disposition == "active":
            raise ValueError("Active Package Product evidence cannot be a record")
        if self.disposition == "committed" and self.phase != "committed":
            raise ValueError("Committed Package Product record changed phase")
        if self.disposition != "committed" and self.phase == "committed":
            raise ValueError("Non-committed Package Product record changed phase")
        if self.lifecycle not in {"installed", "remote_registered", "failed"}:
            raise ValueError("Unsupported Package Product record lifecycle")
        if self.lifecycle == "failed":
            if self.failure_code is None:
                raise ValueError("Failed Package Product record requires a code")
            if self.failure_code not in PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES:
                raise ValueError("Unsupported Package Product failure code")
        elif self.failure_code is not None:
            raise ValueError("Successful Package Product record cannot carry a code")
        if self.lifecycle == "failed" and self.disposition == "committed":
            raise ValueError("Committed Package Product record cannot be failed")
        if self.lifecycle != "failed" and self.disposition != "committed":
            raise ValueError("Successful Package Product record must be committed")
        if self.record_version != PACKAGE_PRODUCT_RECORD_VERSION:
            raise ValueError("Unsupported Package Product record")

    @property
    def source(self) -> str:
        return self.source_identity

    @property
    def error_message(self) -> str | None:
        return self.failure_code

    @property
    def security(self) -> Literal["allowed", "denied"]:
        return "denied" if self.lifecycle == "failed" else "allowed"

    @property
    def source_type(self) -> Literal["plugin"]:
        return "plugin"

    @classmethod
    def from_evidence(
        cls,
        intent: PackageProductLifecycleIntentV1,
        evidence: PackageProductLifecycleEvidenceV1,
    ) -> PackageProductLifecycleRecordV1:
        if evidence.classification == "non_plugin":
            raise ValueError("Plugin Product record requires Plugin classification")
        if evidence.disposition == "active":
            raise ValueError("Active Package Product evidence cannot be projected")
        succeeded = evidence.disposition == "committed"
        lifecycle: Literal["installed", "remote_registered", "failed"]
        if not succeeded:
            lifecycle = "failed"
        elif intent.action in {"remove", "uninstall"}:
            lifecycle = "remote_registered"
        else:
            lifecycle = "installed"
        return cls(
            operation_id=evidence.operation_id,
            action=intent.action,
            source_identity=evidence.source_ref,
            name=evidence.display_name,
            lifecycle=lifecycle,
            phase=evidence.phase,
            disposition=evidence.disposition,
            failure_code=evidence.failure_code,
        )

    def to_dict(self) -> dict[str, object]:
        """Project without a filesystem path, live handle, or raw source locator."""

        return {
            "action": self.action,
            "errorCode": self.failure_code or "",
            "errorMessage": self.failure_code or "",
            "kind": "plugin_package",
            "lifecycle": self.lifecycle,
            "name": self.name,
            "operationId": self.operation_id,
            "packageLifecycleDisposition": self.disposition,
            "packageLifecyclePhase": self.phase,
            "path": "",
            "recordVersion": self.record_version,
            "source": self.source_identity,
        }


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleOutcomeV1:
    """Exact split between handled Plugin work and explicit non-Plugin work."""

    routing_disposition: PackageProductRoutingDisposition
    evidence: PackageProductLifecycleEvidenceV1
    record: PackageProductLifecycleRecordV1 | None
    outcome_version: int = PACKAGE_PRODUCT_OUTCOME_VERSION

    def __post_init__(self) -> None:
        if self.routing_disposition == "non_plugin":
            if self.evidence.classification != "non_plugin" or self.record is not None:
                raise ValueError("Non-Plugin outcome is inconsistent")
            if (
                self.evidence.phase != "classified"
                or self.evidence.disposition != "active"
            ):
                raise ValueError("Non-Plugin outcome must retain classified evidence")
        elif self.routing_disposition == "plugin_handled":
            if self.evidence.classification == "non_plugin" or self.record is None:
                raise ValueError("Plugin outcome is inconsistent")
            if (
                self.record.operation_id != self.evidence.operation_id
                or self.record.source_identity != self.evidence.source_ref
                or self.record.phase != self.evidence.phase
                or self.record.disposition != self.evidence.disposition
            ):
                raise ValueError("Plugin Product record changed lifecycle evidence")
        else:
            raise ValueError("Unsupported Package Product routing disposition")
        if self.outcome_version != PACKAGE_PRODUCT_OUTCOME_VERSION:
            raise ValueError("Unsupported Package Product outcome")

    @property
    def handled(self) -> bool:
        return self.routing_disposition == "plugin_handled"


class PackageProductLifecycleOperationPort(Protocol):
    """The sole Product-facing operation port used by every transport."""

    @property
    def active(self) -> bool: ...

    @property
    def binding_id(self) -> str: ...

    def activate(self) -> object: ...

    def route(
        self,
        intent: PackageProductLifecycleIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
    ) -> PackageProductLifecycleOutcomeV1: ...

    async def execute_guarded_query(self, query: Callable[[], Awaitable[T]]) -> T: ...


@dataclass(frozen=True, slots=True)
class PackageProductUpdateTargetV1:
    """Capability-poor inventory row for one correlated Product update."""

    target_ref: str
    scope: str
    source: str = field(repr=False)
    target_version: int = PACKAGE_PRODUCT_UPDATE_TARGET_VERSION

    def __post_init__(self) -> None:
        if _SHA256_REF.fullmatch(self.target_ref) is None:
            raise ValueError("Package Product update target must be opaque")
        if not isinstance(self.scope, str) or not self.scope:
            raise ValueError("Package Product update target scope is required")
        object.__setattr__(
            self,
            "scope",
            canonicalize_package_product_scope(self.scope),
        )
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("Package Product update target source is required")
        if self.target_ref != f"sha256:{sha256(self.source.encode()).hexdigest()}":
            raise ValueError("Package Product update target changed source identity")
        if self.target_version != PACKAGE_PRODUCT_UPDATE_TARGET_VERSION:
            raise ValueError("Unsupported Package Product update target")


@dataclass(frozen=True, slots=True)
class PackageProductUpdateCheckV1:
    """Pathless Product-owned result for one update availability check."""

    target_ref: str
    scope: str
    update_available: bool
    failure_code: str | None = field(default=None, repr=False)
    check_version: int = PACKAGE_PRODUCT_UPDATE_CHECK_VERSION

    def __post_init__(self) -> None:
        if _SHA256_REF.fullmatch(self.target_ref) is None:
            raise ValueError("Package Product update check target must be opaque")
        object.__setattr__(
            self,
            "scope",
            canonicalize_package_product_scope(self.scope),
        )
        if not isinstance(self.update_available, bool):
            raise TypeError("Package Product update availability must be a bool")
        if self.failure_code is not None and (
            not isinstance(self.failure_code, str) or not self.failure_code
        ):
            raise ValueError("Package Product update check code is invalid")
        if self.check_version != PACKAGE_PRODUCT_UPDATE_CHECK_VERSION:
            raise ValueError("Unsupported Package Product update check")

    def to_dict(self) -> dict[str, object]:
        display_name = f"plugin-{self.target_ref.removeprefix('sha256:')[:12]}"
        return {
            "checkVersion": self.check_version,
            "errorCode": (
                "" if self.failure_code is None else "package_update_check_failed"
            ),
            "name": display_name,
            "scope": self.scope,
            "source": self.target_ref,
            "updateAvailable": self.update_available,
        }


@dataclass(frozen=True, slots=True)
class PackageProductUpdateCheckRequestV1:
    """Correlated, transport-neutral request for one guarded inventory check."""

    operation_id: str
    entrypoint: PackageProductEntrypoint
    scope: str
    request_version: int = PACKAGE_PRODUCT_UPDATE_CHECK_REQUEST_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ValueError("Package Product update check operation id is required")
        if self.entrypoint not in {
            "cli",
            "rpc",
            "session",
            "startup",
            "operations",
            "direct_materializer",
        }:
            raise ValueError("Package Product update check entrypoint is invalid")
        object.__setattr__(
            self,
            "scope",
            canonicalize_package_product_scope(self.scope),
        )
        if self.request_version != PACKAGE_PRODUCT_UPDATE_CHECK_REQUEST_VERSION:
            raise ValueError("Unsupported Package Product update check request")


@dataclass(frozen=True, slots=True)
class PackageProductUpdateManifestReceiptV1:
    """Pathless proof that one owner durably froze an exact update target set."""

    binding_id: str
    operation_id: str
    scope: str
    target_refs: tuple[str, ...]
    manifest_ref: str
    receipt_version: int = PACKAGE_PRODUCT_UPDATE_MANIFEST_RECEIPT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.binding_id, str) or not self.binding_id:
            raise ValueError("Package Product update manifest owner is required")
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ValueError("Package Product update operation id is required")
        object.__setattr__(
            self,
            "scope",
            canonicalize_package_product_scope(self.scope),
        )
        if (
            not isinstance(self.target_refs, tuple)
            or tuple(sorted(self.target_refs)) != self.target_refs
            or len(set(self.target_refs)) != len(self.target_refs)
            or any(_SHA256_REF.fullmatch(item) is None for item in self.target_refs)
        ):
            raise ValueError("Package Product update manifest targets are invalid")
        if self.receipt_version != PACKAGE_PRODUCT_UPDATE_MANIFEST_RECEIPT_VERSION:
            raise ValueError("Unsupported Package Product update manifest receipt")
        if self.manifest_ref != _update_manifest_ref(
            binding_id=self.binding_id,
            operation_id=self.operation_id,
            scope=self.scope,
            target_refs=self.target_refs,
        ):
            raise ValueError("Package Product update manifest receipt changed")

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        operation_id: str,
        scope: str,
        target_refs: tuple[str, ...],
    ) -> PackageProductUpdateManifestReceiptV1:
        canonical_scope = canonicalize_package_product_scope(scope)
        return cls(
            binding_id=binding_id,
            operation_id=operation_id,
            scope=canonical_scope,
            target_refs=target_refs,
            manifest_ref=_update_manifest_ref(
                binding_id=binding_id,
                operation_id=operation_id,
                scope=canonical_scope,
                target_refs=target_refs,
            ),
        )


def _update_manifest_ref(
    *,
    binding_id: str,
    operation_id: str,
    scope: str,
    target_refs: tuple[str, ...],
) -> str:
    identity = "\0".join(
        (
            str(PACKAGE_PRODUCT_UPDATE_MANIFEST_RECEIPT_VERSION),
            binding_id,
            operation_id,
            scope,
            *target_refs,
        )
    )
    return f"sha256:{sha256(identity.encode('utf-8')).hexdigest()}"


class PackageProductLifecycleInventoryPort(Protocol):
    """Product-owned inventory; it exposes no materializer or filesystem handle."""

    @property
    def binding_id(self) -> str: ...

    def list_update_targets(
        self,
        *,
        scope: str,
    ) -> tuple[PackageProductUpdateTargetV1, ...]: ...

    def bind_update_targets(
        self,
        *,
        operation_id: str,
        scope: str,
        targets: tuple[PackageProductUpdateTargetV1, ...],
    ) -> PackageProductUpdateManifestReceiptV1: ...

    async def check_updates(
        self,
        *,
        request: PackageProductUpdateCheckRequestV1,
    ) -> tuple[PackageProductUpdateCheckV1, ...]: ...


__all__ = [
    "PACKAGE_PRODUCT_EVIDENCE_VERSION",
    "PACKAGE_PRODUCT_INTENT_VERSION",
    "PACKAGE_PRODUCT_OUTCOME_VERSION",
    "PACKAGE_PRODUCT_RECORD_VERSION",
    "PACKAGE_PRODUCT_UPDATE_CHECK_VERSION",
    "PACKAGE_PRODUCT_UPDATE_CHECK_REQUEST_VERSION",
    "PACKAGE_PRODUCT_UPDATE_MANIFEST_RECEIPT_VERSION",
    "PACKAGE_PRODUCT_UPDATE_TARGET_VERSION",
    "PackageProductClassificationDecision",
    "PackageProductEntrypoint",
    "PackageProductLifecycleAction",
    "PackageProductLifecycleDisposition",
    "PackageProductLifecycleEvidenceV1",
    "PackageProductLifecycleIntentV1",
    "PackageProductLifecycleInventoryPort",
    "PackageProductLifecycleMode",
    "PackageProductLifecycleOperationPort",
    "PackageProductLifecycleOutcomeV1",
    "PackageProductLifecyclePhase",
    "PackageProductLifecycleRecordV1",
    "PackageProductRoutingDisposition",
    "PackageProductScope",
    "PackageProductUpdateCheckV1",
    "PackageProductUpdateCheckRequestV1",
    "PackageProductUpdateManifestReceiptV1",
    "PackageProductUpdateTargetV1",
    "canonicalize_package_product_scope",
]
