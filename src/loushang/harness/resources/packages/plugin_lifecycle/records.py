"""Versioned inert records for the PLC9B Package lifecycle owner."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

PACKAGE_LIFECYCLE_REQUEST_VERSION = 1
PACKAGE_LIFECYCLE_REQUEST_V2_VERSION = 2
PACKAGE_CLASSIFICATION_FACT_VERSION = 1
PACKAGE_CLASSIFICATION_FACTS_VERSION = 1
PACKAGE_CLASSIFICATION_VERSION = 1
PACKAGE_LIFECYCLE_FAILURE_VERSION = 1
PACKAGE_LIFECYCLE_STATUS_VERSION = 1
PACKAGE_LIFECYCLE_RETRY_REQUEST_VERSION = 1
PACKAGE_LIFECYCLE_CANCEL_REQUEST_VERSION = 1
PACKAGE_LIFECYCLE_JOURNAL_RECORD_VERSION = 1

PackageLifecycleAction = Literal[
    "materialize",
    "install",
    "update",
    "remove",
    "uninstall",
]
PackageClassificationDecision = Literal[
    "plugin_bound",
    "non_plugin",
    "indeterminate",
]
PackageClassificationBasisKind = Literal[
    "explicit_plugin_intent",
    "existing_plugin_binding",
    "existing_plugin_history",
    "independent_non_plugin_authority",
]
PackageLifecyclePhase = Literal[
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
PackageLifecycleDisposition = Literal[
    "active",
    "rejected",
    "cancelled",
    "retryable_failure",
    "committed",
]
PackageLifecycleRetryDomain = Literal["none", "operation", "handoff", "cleanup"]
PackageLifecycleOperatorAction = Literal[
    "none",
    "retry",
    "repair",
    "upgrade_runtime",
    "offline_restore",
    "review_policy",
]
PackageLifecycleSubjectKind = Literal["operation", "handoff", "cleanup"]
PackageLifecycleJournalRecordKind = Literal["operation", "attempt"]

_ACTIONS = {"materialize", "install", "update", "remove", "uninstall"}
_FACT_KINDS: tuple[PackageClassificationBasisKind, ...] = (
    "explicit_plugin_intent",
    "existing_plugin_binding",
    "existing_plugin_history",
    "independent_non_plugin_authority",
)
_PLUGIN_FACTS = {
    "explicit_plugin_intent",
    "existing_plugin_binding",
    "existing_plugin_history",
}
_DECISIONS = {"plugin_bound", "non_plugin", "indeterminate"}
_PHASES = {
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
_DISPOSITIONS = {
    "active",
    "rejected",
    "cancelled",
    "retryable_failure",
    "committed",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RECHECK_RULE = "before_acquisition_and_committed_set_publication"

# retryable, retry domain, operator action
_FailureRetryRule = bool | Literal["conditional:no_acquired_digest"]
_FAILURE_POLICIES: dict[
    str,
    tuple[
        _FailureRetryRule,
        PackageLifecycleRetryDomain,
        PackageLifecycleOperatorAction,
    ],
] = {
    "package_target_classification_indeterminate": (False, "none", "review_policy"),
    "package_target_classification_changed": (False, "none", "review_policy"),
    "package_source_unauthorized": (False, "none", "review_policy"),
    "package_source_provenance_changed": (False, "none", "review_policy"),
    "package_acquisition_limit_exceeded": (
        "conditional:no_acquired_digest",
        "operation",
        "retry",
    ),
    "package_operation_timed_out": (
        "conditional:no_acquired_digest",
        "operation",
        "retry",
    ),
    "package_acquisition_digest_mismatch": (False, "none", "none"),
    "package_artifact_identity_changed": (False, "none", "none"),
    "package_archive_malformed": (False, "none", "none"),
    "package_archive_path_rejected": (False, "none", "none"),
    "package_archive_name_collision": (False, "none", "none"),
    "package_archive_entry_type_rejected": (False, "none", "none"),
    "package_resource_limit_exceeded": (False, "none", "none"),
    "package_wheel_metadata_invalid": (False, "none", "none"),
    "package_wheel_record_invalid": (False, "none", "none"),
    "package_artifact_type_rejected": (False, "none", "none"),
    "package_closure_artifact_invalid": (False, "none", "none"),
    "package_closure_conflict": (False, "none", "none"),
    "package_closure_evidence_unsupported": (False, "none", "none"),
    "package_publication_root_untrusted": (False, "none", "none"),
    "package_publication_collision": (False, "none", "none"),
    "package_commit_admission_denied": (False, "none", "none"),
    "package_operation_interrupted": (True, "operation", "retry"),
    "package_attempt_stale": (False, "none", "none"),
    "package_quarantine_cleanup_retryable": (True, "cleanup", "repair"),
    "package_operation_identity_conflict": (False, "none", "none"),
    "package_operation_cancelled": (False, "none", "none"),
    "package_retention_handoff_interrupted": (True, "handoff", "retry"),
    "package_desired_revision_conflict": (False, "none", "none"),
    "package_retention_handoff_stale": (False, "none", "none"),
    "package_runtime_epoch_unsupported": (False, "none", "upgrade_runtime"),
    "package_route_unavailable": (False, "none", "none"),
}


@dataclass(frozen=True, slots=True)
class PackageClassificationBasisFactV1:
    kind: PackageClassificationBasisKind
    present: bool
    authority_id: str
    owner_revision: str
    fact_version: int = PACKAGE_CLASSIFICATION_FACT_VERSION

    def __post_init__(self) -> None:
        if self.kind not in _FACT_KINDS:
            raise ValueError("Unsupported Package classification basis fact")
        if type(self.present) is not bool:
            raise TypeError("Package classification fact presence must be boolean")
        _require_nonempty(self.authority_id, name="classification authority id")
        _require_nonempty(self.owner_revision, name="classification owner revision")
        if self.fact_version != PACKAGE_CLASSIFICATION_FACT_VERSION:
            raise ValueError("Unsupported Package classification fact")

    def to_dict(self) -> dict[str, object]:
        return {
            "authorityId": self.authority_id,
            "factVersion": self.fact_version,
            "kind": self.kind,
            "ownerRevision": self.owner_revision,
            "present": self.present,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageClassificationBasisFactV1:
        document = _exact_dict(
            value,
            fields={
                "authorityId",
                "factVersion",
                "kind",
                "ownerRevision",
                "present",
            },
            name="Package classification basis fact",
        )
        return cls(
            kind=cast(
                PackageClassificationBasisKind,
                _wire_string(document["kind"], name="classification fact kind"),
            ),
            present=_wire_bool(document["present"], name="classification fact presence"),
            authority_id=_wire_string(
                document["authorityId"], name="classification authority id"
            ),
            owner_revision=_wire_string(
                document["ownerRevision"], name="classification owner revision"
            ),
            fact_version=_wire_int(
                document["factVersion"], name="classification fact version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageClassificationFactsV1:
    facts: tuple[PackageClassificationBasisFactV1, ...]
    policy_revision: str
    classifier_epoch: int
    facts_version: int = PACKAGE_CLASSIFICATION_FACTS_VERSION

    def __post_init__(self) -> None:
        if tuple(fact.kind for fact in self.facts) != _FACT_KINDS:
            raise ValueError(
                "Package classification facts must contain every basis in canonical order"
            )
        _require_nonempty(self.policy_revision, name="classification policy revision")
        _require_positive(self.classifier_epoch, name="classifier epoch")
        if self.facts_version != PACKAGE_CLASSIFICATION_FACTS_VERSION:
            raise ValueError("Unsupported Package classification facts")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "classifierEpoch": self.classifier_epoch,
            "facts": [fact.to_dict() for fact in self.facts],
            "factsVersion": self.facts_version,
            "policyRevision": self.policy_revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageClassificationFactsV1:
        document = _exact_dict(
            value,
            fields={"classifierEpoch", "facts", "factsVersion", "policyRevision"},
            name="Package classification facts",
        )
        return cls(
            facts=tuple(
                PackageClassificationBasisFactV1.from_dict(item)
                for item in _wire_list(document["facts"], name="classification facts")
            ),
            policy_revision=_wire_string(
                document["policyRevision"], name="classification policy revision"
            ),
            classifier_epoch=_wire_positive(
                document["classifierEpoch"], name="classifier epoch"
            ),
            facts_version=_wire_int(
                document["factsVersion"], name="classification facts version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLifecycleIngressRequestV1:
    """Ephemeral caller input; the raw locator is never journalled or projected."""

    operation_id: str
    action: PackageLifecycleAction
    product_id: str
    scope_id: str
    requested_package: str
    requested_plugin_id: str | None
    source_locator: str = field(repr=False)
    policy_revision: str
    quota_profile_revision: str
    resolution_environment_fingerprint: str
    request_version: int = PACKAGE_LIFECYCLE_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, name="Package operation id")
        if self.action not in _ACTIONS:
            raise ValueError("Unsupported Package lifecycle action")
        for value, name in (
            (self.product_id, "Product id"),
            (self.scope_id, "scope id"),
            (self.requested_package, "requested Package"),
            (self.source_locator, "Source locator"),
            (self.policy_revision, "Package policy revision"),
            (self.quota_profile_revision, "quota profile revision"),
        ):
            _require_nonempty(value, name=name)
        if self.requested_plugin_id is not None:
            _require_nonempty(self.requested_plugin_id, name="requested Plugin id")
        _require_sha256(
            self.resolution_environment_fingerprint,
            name="resolution environment fingerprint",
        )
        if self.request_version != PACKAGE_LIFECYCLE_REQUEST_VERSION:
            raise ValueError("Unsupported Package lifecycle request")

    def bind_classification_facts(
        self,
        facts: PackageClassificationFactsV1,
    ) -> PackageLifecycleRequestV1:
        if not isinstance(facts, PackageClassificationFactsV1):
            raise TypeError("Package classification facts are required")
        return PackageLifecycleRequestV1(
            operation_id=self.operation_id,
            action=self.action,
            product_id=self.product_id,
            scope_id=self.scope_id,
            requested_package=self.requested_package,
            requested_plugin_id=self.requested_plugin_id,
            canonical_source_identity=canonicalize_source_identity(
                self.source_locator
            ),
            policy_revision=self.policy_revision,
            quota_profile_revision=self.quota_profile_revision,
            resolution_environment_fingerprint=(
                self.resolution_environment_fingerprint
            ),
            classification_facts=facts,
            request_version=self.request_version,
        )


@dataclass(frozen=True, slots=True)
class PackageLifecycleRequestV1:
    operation_id: str
    action: PackageLifecycleAction
    product_id: str
    scope_id: str
    requested_package: str
    requested_plugin_id: str | None
    canonical_source_identity: str
    policy_revision: str
    quota_profile_revision: str
    resolution_environment_fingerprint: str
    classification_facts: PackageClassificationFactsV1
    request_version: int = PACKAGE_LIFECYCLE_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, name="Package operation id")
        if self.action not in _ACTIONS:
            raise ValueError("Unsupported Package lifecycle action")
        for value, name in (
            (self.product_id, "Product id"),
            (self.scope_id, "scope id"),
            (self.requested_package, "requested Package"),
            (self.canonical_source_identity, "canonical Source identity"),
            (self.policy_revision, "Package policy revision"),
            (self.quota_profile_revision, "quota profile revision"),
        ):
            _require_nonempty(value, name=name)
        if canonicalize_source_identity(self.canonical_source_identity) != (
            self.canonical_source_identity
        ):
            raise ValueError("Canonical Source identity contains secret-bearing parts")
        if self.requested_plugin_id is not None:
            _require_nonempty(self.requested_plugin_id, name="requested Plugin id")
        _require_sha256(
            self.resolution_environment_fingerprint,
            name="resolution environment fingerprint",
        )
        if not isinstance(self.classification_facts, PackageClassificationFactsV1):
            raise TypeError("Package classification facts are required")
        if self.request_version != PACKAGE_LIFECYCLE_REQUEST_VERSION:
            raise ValueError("Unsupported Package lifecycle request")

    @property
    def request_fingerprint(self) -> str:
        fingerprint_fields = self.to_dict()
        del fingerprint_fields["operationId"]
        return _fingerprint(fingerprint_fields)

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "canonicalSourceIdentity": self.canonical_source_identity,
            "classificationFacts": self.classification_facts.to_dict(),
            "operationId": self.operation_id,
            "policyRevision": self.policy_revision,
            "productId": self.product_id,
            "quotaProfileRevision": self.quota_profile_revision,
            "requestVersion": self.request_version,
            "requestedPackage": self.requested_package,
            "requestedPluginId": self.requested_plugin_id,
            "resolutionEnvironmentFingerprint": (
                self.resolution_environment_fingerprint
            ),
            "scopeId": self.scope_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageLifecycleRequestV1:
        document = _exact_dict(
            value,
            fields={
                "action",
                "canonicalSourceIdentity",
                "classificationFacts",
                "operationId",
                "policyRevision",
                "productId",
                "quotaProfileRevision",
                "requestVersion",
                "requestedPackage",
                "requestedPluginId",
                "resolutionEnvironmentFingerprint",
                "scopeId",
            },
            name="Package lifecycle request",
        )
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            action=cast(
                PackageLifecycleAction,
                _wire_string(document["action"], name="Package action"),
            ),
            product_id=_wire_string(document["productId"], name="Product id"),
            scope_id=_wire_string(document["scopeId"], name="scope id"),
            requested_package=_wire_string(
                document["requestedPackage"], name="requested Package"
            ),
            requested_plugin_id=_wire_optional_string(
                document["requestedPluginId"], name="requested Plugin id"
            ),
            canonical_source_identity=_wire_string(
                document["canonicalSourceIdentity"],
                name="canonical Source identity",
            ),
            policy_revision=_wire_string(
                document["policyRevision"], name="Package policy revision"
            ),
            quota_profile_revision=_wire_string(
                document["quotaProfileRevision"], name="quota profile revision"
            ),
            resolution_environment_fingerprint=_wire_string(
                document["resolutionEnvironmentFingerprint"],
                name="resolution environment fingerprint",
            ),
            classification_facts=PackageClassificationFactsV1.from_dict(
                document["classificationFacts"]
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLifecycleIngressRequestV2(PackageLifecycleIngressRequestV1):
    """Ingress with an independently bound runtime-admission identity."""

    request_version: int = PACKAGE_LIFECYCLE_REQUEST_V2_VERSION
    runtime_admission_request_id: str = ""

    def __post_init__(self) -> None:
        PackageLifecycleIngressRequestV1(
            operation_id=self.operation_id,
            action=self.action,
            product_id=self.product_id,
            scope_id=self.scope_id,
            requested_package=self.requested_package,
            requested_plugin_id=self.requested_plugin_id,
            source_locator=self.source_locator,
            policy_revision=self.policy_revision,
            quota_profile_revision=self.quota_profile_revision,
            resolution_environment_fingerprint=(
                self.resolution_environment_fingerprint
            ),
        )
        _require_sha256(
            self.runtime_admission_request_id,
            name="runtime admission request id",
        )
        if self.request_version != PACKAGE_LIFECYCLE_REQUEST_V2_VERSION:
            raise ValueError("Unsupported Package lifecycle request v2")

    @classmethod
    def bind_runtime_admission(
        cls,
        ingress: PackageLifecycleIngressRequestV1,
        *,
        runtime_admission_request_id: str,
    ) -> PackageLifecycleIngressRequestV2:
        if not isinstance(ingress, PackageLifecycleIngressRequestV1):
            raise TypeError("Package lifecycle ingress request is required")
        if isinstance(ingress, PackageLifecycleIngressRequestV2):
            if (
                ingress.runtime_admission_request_id
                != runtime_admission_request_id
            ):
                raise ValueError("Package runtime admission identity changed")
            return ingress
        return cls(
            operation_id=ingress.operation_id,
            action=ingress.action,
            product_id=ingress.product_id,
            scope_id=ingress.scope_id,
            requested_package=ingress.requested_package,
            requested_plugin_id=ingress.requested_plugin_id,
            source_locator=ingress.source_locator,
            policy_revision=ingress.policy_revision,
            quota_profile_revision=ingress.quota_profile_revision,
            resolution_environment_fingerprint=(
                ingress.resolution_environment_fingerprint
            ),
            runtime_admission_request_id=runtime_admission_request_id,
        )

    def bind_classification_facts(
        self,
        facts: PackageClassificationFactsV1,
    ) -> PackageLifecycleRequestV2:
        if not isinstance(facts, PackageClassificationFactsV1):
            raise TypeError("Package classification facts are required")
        return PackageLifecycleRequestV2(
            operation_id=self.operation_id,
            action=self.action,
            product_id=self.product_id,
            scope_id=self.scope_id,
            requested_package=self.requested_package,
            requested_plugin_id=self.requested_plugin_id,
            canonical_source_identity=canonicalize_source_identity(
                self.source_locator
            ),
            policy_revision=self.policy_revision,
            quota_profile_revision=self.quota_profile_revision,
            resolution_environment_fingerprint=(
                self.resolution_environment_fingerprint
            ),
            classification_facts=facts,
            runtime_admission_request_id=self.runtime_admission_request_id,
        )


@dataclass(frozen=True, slots=True)
class PackageLifecycleRequestV2(PackageLifecycleRequestV1):
    """Durable request whose fingerprint includes runtime admission."""

    request_version: int = PACKAGE_LIFECYCLE_REQUEST_V2_VERSION
    runtime_admission_request_id: str = ""

    def __post_init__(self) -> None:
        PackageLifecycleRequestV1(
            operation_id=self.operation_id,
            action=self.action,
            product_id=self.product_id,
            scope_id=self.scope_id,
            requested_package=self.requested_package,
            requested_plugin_id=self.requested_plugin_id,
            canonical_source_identity=self.canonical_source_identity,
            policy_revision=self.policy_revision,
            quota_profile_revision=self.quota_profile_revision,
            resolution_environment_fingerprint=(
                self.resolution_environment_fingerprint
            ),
            classification_facts=self.classification_facts,
        )
        _require_sha256(
            self.runtime_admission_request_id,
            name="runtime admission request id",
        )
        if self.request_version != PACKAGE_LIFECYCLE_REQUEST_V2_VERSION:
            raise ValueError("Unsupported Package lifecycle request v2")

    def to_dict(self) -> dict[str, object]:
        document = PackageLifecycleRequestV1.to_dict(self)
        document["runtimeAdmissionRequestId"] = self.runtime_admission_request_id
        return document

    @classmethod
    def from_dict(cls, value: object) -> PackageLifecycleRequestV2:
        document = _exact_dict(
            value,
            fields={
                "action",
                "canonicalSourceIdentity",
                "classificationFacts",
                "operationId",
                "policyRevision",
                "productId",
                "quotaProfileRevision",
                "requestVersion",
                "requestedPackage",
                "requestedPluginId",
                "resolutionEnvironmentFingerprint",
                "runtimeAdmissionRequestId",
                "scopeId",
            },
            name="Package lifecycle request v2",
        )
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            action=cast(
                PackageLifecycleAction,
                _wire_string(document["action"], name="Package action"),
            ),
            product_id=_wire_string(document["productId"], name="Product id"),
            scope_id=_wire_string(document["scopeId"], name="scope id"),
            requested_package=_wire_string(
                document["requestedPackage"], name="requested Package"
            ),
            requested_plugin_id=_wire_optional_string(
                document["requestedPluginId"], name="requested Plugin id"
            ),
            canonical_source_identity=_wire_string(
                document["canonicalSourceIdentity"],
                name="canonical Source identity",
            ),
            policy_revision=_wire_string(
                document["policyRevision"], name="Package policy revision"
            ),
            quota_profile_revision=_wire_string(
                document["quotaProfileRevision"], name="quota profile revision"
            ),
            resolution_environment_fingerprint=_wire_string(
                document["resolutionEnvironmentFingerprint"],
                name="resolution environment fingerprint",
            ),
            classification_facts=PackageClassificationFactsV1.from_dict(
                document["classificationFacts"]
            ),
            runtime_admission_request_id=_wire_string(
                document["runtimeAdmissionRequestId"],
                name="runtime admission request id",
            ),
            request_version=_wire_int(
                document["requestVersion"], name="request version"
            ),
        )


def decode_package_lifecycle_request(value: object) -> PackageLifecycleRequestV1:
    """Decode the durable request version without changing V1 wire identity."""

    if not isinstance(value, Mapping):
        raise ValueError("Package lifecycle request must be an object")
    version = value.get("requestVersion")
    if version == PACKAGE_LIFECYCLE_REQUEST_VERSION:
        return PackageLifecycleRequestV1.from_dict(value)
    if version == PACKAGE_LIFECYCLE_REQUEST_V2_VERSION:
        return PackageLifecycleRequestV2.from_dict(value)
    raise ValueError("Unsupported Package lifecycle request")


@dataclass(frozen=True, slots=True)
class PluginBoundPackageClassificationV1:
    decision: PackageClassificationDecision
    request_fingerprint: str
    basis_facts: PackageClassificationFactsV1
    policy_revision: str
    classifier_epoch: int
    canonical_source_identity: str
    recheck_rule: str = _RECHECK_RULE
    classification_version: int = PACKAGE_CLASSIFICATION_VERSION

    def __post_init__(self) -> None:
        if self.decision not in _DECISIONS:
            raise ValueError("Unsupported Package classification decision")
        _require_sha256(self.request_fingerprint, name="request fingerprint")
        if not isinstance(self.basis_facts, PackageClassificationFactsV1):
            raise TypeError("Package classification basis facts are required")
        if self.policy_revision != self.basis_facts.policy_revision:
            raise ValueError("Classification policy revision does not match facts")
        if self.classifier_epoch != self.basis_facts.classifier_epoch:
            raise ValueError("Classifier epoch does not match facts")
        _require_nonempty(
            self.canonical_source_identity, name="canonical Source identity"
        )
        if self.recheck_rule != _RECHECK_RULE:
            raise ValueError("Unsupported Package classification recheck rule")
        if self.classification_version != PACKAGE_CLASSIFICATION_VERSION:
            raise ValueError("Unsupported Package classification evidence")

    @property
    def evidence_ref(self) -> str:
        return _fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "basisFacts": self.basis_facts.to_dict(),
            "canonicalSourceIdentity": self.canonical_source_identity,
            "classificationVersion": self.classification_version,
            "classifierEpoch": self.classifier_epoch,
            "decision": self.decision,
            "policyRevision": self.policy_revision,
            "recheckRule": self.recheck_rule,
            "requestFingerprint": self.request_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginBoundPackageClassificationV1:
        document = _exact_dict(
            value,
            fields={
                "basisFacts",
                "canonicalSourceIdentity",
                "classificationVersion",
                "classifierEpoch",
                "decision",
                "policyRevision",
                "recheckRule",
                "requestFingerprint",
            },
            name="Package classification evidence",
        )
        return cls(
            decision=cast(
                PackageClassificationDecision,
                _wire_string(document["decision"], name="classification decision"),
            ),
            request_fingerprint=_wire_string(
                document["requestFingerprint"], name="request fingerprint"
            ),
            basis_facts=PackageClassificationFactsV1.from_dict(
                document["basisFacts"]
            ),
            policy_revision=_wire_string(
                document["policyRevision"], name="classification policy revision"
            ),
            classifier_epoch=_wire_positive(
                document["classifierEpoch"], name="classifier epoch"
            ),
            canonical_source_identity=_wire_string(
                document["canonicalSourceIdentity"],
                name="canonical Source identity",
            ),
            recheck_rule=_wire_string(
                document["recheckRule"], name="classification recheck rule"
            ),
            classification_version=_wire_int(
                document["classificationVersion"],
                name="classification version",
            ),
        )


def classify_package_request(
    request: PackageLifecycleRequestV1,
) -> PluginBoundPackageClassificationV1:
    if not isinstance(request, PackageLifecycleRequestV1):
        raise TypeError("Package lifecycle request is required")
    present = {
        fact.kind for fact in request.classification_facts.facts if fact.present
    }
    if present & _PLUGIN_FACTS:
        decision: PackageClassificationDecision = "plugin_bound"
    elif "independent_non_plugin_authority" in present:
        decision = "non_plugin"
    else:
        decision = "indeterminate"
    return PluginBoundPackageClassificationV1(
        decision=decision,
        request_fingerprint=request.request_fingerprint,
        basis_facts=request.classification_facts,
        policy_revision=request.classification_facts.policy_revision,
        classifier_epoch=request.classification_facts.classifier_epoch,
        canonical_source_identity=request.canonical_source_identity,
    )


@dataclass(frozen=True, slots=True)
class PackageLifecycleFailureV1:
    code: str
    stage: PackageLifecyclePhase
    retryable: bool
    retry_domain: PackageLifecycleRetryDomain
    operator_action: PackageLifecycleOperatorAction
    subject_kind: PackageLifecycleSubjectKind
    subject_id: str
    operation_id: str
    evidence_ref: str
    details: tuple[str, ...] = ()
    failure_version: int = PACKAGE_LIFECYCLE_FAILURE_VERSION

    def __post_init__(self) -> None:
        if self.stage not in _PHASES:
            raise ValueError("Unsupported Package lifecycle failure stage")
        if self.subject_kind not in {"operation", "handoff", "cleanup"}:
            raise ValueError("Unsupported Package lifecycle failure subject")
        for value, name in (
            (self.subject_id, "failure subject id"),
            (self.operation_id, "failure operation id"),
        ):
            _require_nonempty(value, name=name)
        _require_sha256(self.evidence_ref, name="failure evidence ref")
        if len(self.details) > 8:
            raise ValueError("Package lifecycle failure details are not bounded")
        for detail in self.details:
            _require_nonempty(detail, name="failure detail code")
            if len(detail) > 96 or not re.fullmatch(r"[a-z0-9_.:-]+", detail):
                raise ValueError("Package lifecycle failure detail is not a safe code")
        policy = _resolved_failure_policy(self.code, self.details)
        if (self.retryable, self.retry_domain, self.operator_action) != policy:
            raise ValueError("Package lifecycle failure retry policy mismatch")
        if self.failure_version != PACKAGE_LIFECYCLE_FAILURE_VERSION:
            raise ValueError("Unsupported Package lifecycle failure")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "details": list(self.details),
            "evidenceRef": self.evidence_ref,
            "failureVersion": self.failure_version,
            "operationId": self.operation_id,
            "operatorAction": self.operator_action,
            "retryDomain": self.retry_domain,
            "retryable": self.retryable,
            "stage": self.stage,
            "subjectId": self.subject_id,
            "subjectKind": self.subject_kind,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageLifecycleFailureV1:
        document = _exact_dict(
            value,
            fields={
                "code",
                "details",
                "evidenceRef",
                "failureVersion",
                "operationId",
                "operatorAction",
                "retryDomain",
                "retryable",
                "stage",
                "subjectId",
                "subjectKind",
            },
            name="Package lifecycle failure",
        )
        return cls(
            code=_wire_string(document["code"], name="failure code"),
            stage=cast(
                PackageLifecyclePhase,
                _wire_string(document["stage"], name="failure stage"),
            ),
            retryable=_wire_bool(document["retryable"], name="failure retryable"),
            retry_domain=cast(
                PackageLifecycleRetryDomain,
                _wire_string(document["retryDomain"], name="failure retry domain"),
            ),
            operator_action=cast(
                PackageLifecycleOperatorAction,
                _wire_string(
                    document["operatorAction"], name="failure operator action"
                ),
            ),
            subject_kind=cast(
                PackageLifecycleSubjectKind,
                _wire_string(document["subjectKind"], name="failure subject kind"),
            ),
            subject_id=_wire_string(
                document["subjectId"], name="failure subject id"
            ),
            operation_id=_wire_string(
                document["operationId"], name="failure operation id"
            ),
            evidence_ref=_wire_string(
                document["evidenceRef"], name="failure evidence ref"
            ),
            details=tuple(
                _wire_string(item, name="failure detail")
                for item in _wire_list(document["details"], name="failure details")
            ),
            failure_version=_wire_int(
                document["failureVersion"], name="failure version"
            ),
        )

    @classmethod
    def for_operation(
        cls,
        code: str,
        *,
        stage: PackageLifecyclePhase,
        operation_id: str,
        evidence_ref: str,
        details: tuple[str, ...] = (),
    ) -> PackageLifecycleFailureV1:
        retryable, retry_domain, operator_action = _resolved_failure_policy(
            code, details
        )
        return cls(
            code=code,
            stage=stage,
            retryable=retryable,
            retry_domain=retry_domain,
            operator_action=operator_action,
            subject_kind="operation",
            subject_id=operation_id,
            operation_id=operation_id,
            evidence_ref=evidence_ref,
            details=details,
        )


@dataclass(frozen=True, slots=True)
class PackageLifecycleStatusV1:
    operation_id: str
    request_fingerprint: str
    phase: PackageLifecyclePhase
    disposition: PackageLifecycleDisposition
    attempt_epoch: int
    journal_revision: int
    attempt_revision: int
    classification: PluginBoundPackageClassificationV1 | None = None
    failure: PackageLifecycleFailureV1 | None = None
    status_version: int = PACKAGE_LIFECYCLE_STATUS_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, name="Package operation id")
        _require_sha256(self.request_fingerprint, name="request fingerprint")
        if self.phase not in _PHASES:
            raise ValueError("Unsupported Package lifecycle phase")
        if self.disposition not in _DISPOSITIONS:
            raise ValueError("Unsupported Package lifecycle disposition")
        _require_positive(self.attempt_epoch, name="attempt epoch")
        _require_nonnegative(self.journal_revision, name="journal revision")
        _require_nonnegative(self.attempt_revision, name="attempt revision")
        if self.phase == "accepted" and self.classification is not None:
            raise ValueError("Accepted Package operation cannot carry classification")
        if self.phase != "accepted" and self.classification is None:
            raise ValueError("Classified Package operation requires classification")
        if (
            self.classification is not None
            and self.classification.request_fingerprint != self.request_fingerprint
        ):
            raise ValueError("Classification request fingerprint does not match status")
        if self.disposition in {"rejected", "cancelled", "retryable_failure"}:
            if self.failure is None:
                raise ValueError("Terminal or failed Package status requires failure")
        elif self.failure is not None:
            raise ValueError("Active or committed Package status cannot carry failure")
        if self.failure is not None:
            if self.failure.operation_id != self.operation_id:
                raise ValueError("Failure operation does not match status")
            if self.failure.stage != self.phase:
                raise ValueError("Failure stage does not match status phase")
            if self.disposition == "retryable_failure" and not self.failure.retryable:
                raise ValueError("Retryable status requires retryable failure")
            if self.disposition != "retryable_failure" and self.failure.retryable:
                raise ValueError("Retryable failure requires retryable disposition")
            if (
                self.disposition == "cancelled"
                and self.failure.code != "package_operation_cancelled"
            ):
                raise ValueError("Cancelled status requires cancellation failure")
            if (
                self.disposition != "cancelled"
                and self.failure.code == "package_operation_cancelled"
            ):
                raise ValueError("Cancellation failure requires cancelled disposition")
        if self.disposition == "committed" and self.phase != "committed":
            raise ValueError("Committed disposition requires committed phase")
        if self.phase == "committed" and self.disposition != "committed":
            raise ValueError("Committed phase requires committed disposition")
        if self.status_version != PACKAGE_LIFECYCLE_STATUS_VERSION:
            raise ValueError("Unsupported Package lifecycle status")

    @property
    def terminal(self) -> bool:
        return self.disposition in {"rejected", "cancelled", "committed"}

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "attemptRevision": self.attempt_revision,
            "classification": (
                None if self.classification is None else self.classification.to_dict()
            ),
            "disposition": self.disposition,
            "failure": None if self.failure is None else self.failure.to_dict(),
            "journalRevision": self.journal_revision,
            "operationId": self.operation_id,
            "phase": self.phase,
            "requestFingerprint": self.request_fingerprint,
            "statusVersion": self.status_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageLifecycleStatusV1:
        document = _exact_dict(
            value,
            fields={
                "attemptEpoch",
                "attemptRevision",
                "classification",
                "disposition",
                "failure",
                "journalRevision",
                "operationId",
                "phase",
                "requestFingerprint",
                "statusVersion",
            },
            name="Package lifecycle status",
        )
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            request_fingerprint=_wire_string(
                document["requestFingerprint"], name="request fingerprint"
            ),
            phase=cast(
                PackageLifecyclePhase,
                _wire_string(document["phase"], name="Package lifecycle phase"),
            ),
            disposition=cast(
                PackageLifecycleDisposition,
                _wire_string(
                    document["disposition"], name="Package lifecycle disposition"
                ),
            ),
            attempt_epoch=_wire_positive(
                document["attemptEpoch"], name="attempt epoch"
            ),
            journal_revision=_wire_nonnegative(
                document["journalRevision"], name="journal revision"
            ),
            attempt_revision=_wire_nonnegative(
                document["attemptRevision"], name="attempt revision"
            ),
            classification=(
                None
                if document["classification"] is None
                else PluginBoundPackageClassificationV1.from_dict(
                    document["classification"]
                )
            ),
            failure=(
                None
                if document["failure"] is None
                else PackageLifecycleFailureV1.from_dict(document["failure"])
            ),
            status_version=_wire_int(
                document["statusVersion"], name="status version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageLifecycleRetryRequestV1:
    operation_id: str
    request_fingerprint: str
    expected_attempt_epoch: int
    request_version: int = PACKAGE_LIFECYCLE_RETRY_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, name="retry operation id")
        _require_sha256(self.request_fingerprint, name="retry request fingerprint")
        _require_positive(self.expected_attempt_epoch, name="expected attempt epoch")
        if self.request_version != PACKAGE_LIFECYCLE_RETRY_REQUEST_VERSION:
            raise ValueError("Unsupported Package lifecycle retry request")


@dataclass(frozen=True, slots=True)
class PackageLifecycleCancelRequestV1:
    operation_id: str
    request_fingerprint: str
    expected_phase: PackageLifecyclePhase
    expected_journal_revision: int
    expected_attempt_epoch: int
    request_version: int = PACKAGE_LIFECYCLE_CANCEL_REQUEST_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.operation_id, name="cancel operation id")
        _require_sha256(self.request_fingerprint, name="cancel request fingerprint")
        if self.expected_phase not in _PHASES:
            raise ValueError("Unsupported expected Package lifecycle phase")
        _require_nonnegative(
            self.expected_journal_revision, name="expected journal revision"
        )
        _require_positive(self.expected_attempt_epoch, name="expected attempt epoch")
        if self.request_version != PACKAGE_LIFECYCLE_CANCEL_REQUEST_VERSION:
            raise ValueError("Unsupported Package lifecycle cancel request")


@dataclass(frozen=True, slots=True)
class PackageLifecycleJournalRecordV1:
    record_kind: PackageLifecycleJournalRecordKind
    record_revision: int
    prior_operation_revision: int
    prior_attempt_revision: int
    request: PackageLifecycleRequestV1
    status: PackageLifecycleStatusV1
    record_version: int = PACKAGE_LIFECYCLE_JOURNAL_RECORD_VERSION

    def __post_init__(self) -> None:
        if self.record_kind not in {"operation", "attempt"}:
            raise ValueError("Unsupported Package lifecycle journal record kind")
        _require_positive(self.record_revision, name="record revision")
        _require_nonnegative(
            self.prior_operation_revision, name="prior operation revision"
        )
        _require_nonnegative(
            self.prior_attempt_revision, name="prior attempt revision"
        )
        if self.request.operation_id != self.status.operation_id:
            raise ValueError("Journal request and status operation ids differ")
        if self.request.request_fingerprint != self.status.request_fingerprint:
            raise ValueError("Journal request and status fingerprints differ")
        if self.record_kind == "operation":
            if self.status.journal_revision != self.record_revision:
                raise ValueError("Operation record revision must own status revision")
        elif self.status.attempt_revision != self.record_revision:
            raise ValueError("Attempt record revision must own attempt revision")
        if self.record_version != PACKAGE_LIFECYCLE_JOURNAL_RECORD_VERSION:
            raise ValueError("Unsupported Package lifecycle journal record")

    def to_dict(self) -> dict[str, object]:
        return {
            "priorAttemptRevision": self.prior_attempt_revision,
            "priorOperationRevision": self.prior_operation_revision,
            "recordKind": self.record_kind,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "request": self.request.to_dict(),
            "status": self.status.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageLifecycleJournalRecordV1:
        document = _exact_dict(
            value,
            fields={
                "priorAttemptRevision",
                "priorOperationRevision",
                "recordKind",
                "recordRevision",
                "recordVersion",
                "request",
                "status",
            },
            name="Package lifecycle journal record",
        )
        return cls(
            record_kind=cast(
                PackageLifecycleJournalRecordKind,
                _wire_string(document["recordKind"], name="record kind"),
            ),
            record_revision=_wire_positive(
                document["recordRevision"], name="record revision"
            ),
            prior_operation_revision=_wire_nonnegative(
                document["priorOperationRevision"],
                name="prior operation revision",
            ),
            prior_attempt_revision=_wire_nonnegative(
                document["priorAttemptRevision"], name="prior attempt revision"
            ),
            request=decode_package_lifecycle_request(document["request"]),
            status=PackageLifecycleStatusV1.from_dict(document["status"]),
            record_version=_wire_int(
                document["recordVersion"], name="record version"
            ),
        )


def canonicalize_source_identity(source_locator: str) -> str:
    """Remove credential-bearing URL components before hashing or persistence."""

    _require_nonempty(source_locator, name="Source locator")
    if source_locator != source_locator.strip():
        raise ValueError("Source locator cannot contain surrounding whitespace")
    if any(ord(character) < 0x20 for character in source_locator):
        raise ValueError("Source locator cannot contain control characters")
    if len(source_locator) > 4096:
        raise ValueError("Source locator exceeds the bounded ingress length")
    parsed = urlsplit(source_locator)
    if parsed.scheme and parsed.netloc:
        canonical = _canonical_network_source(parsed)
    else:
        canonical = source_locator.split("#", 1)[0].split("?", 1)[0]
    _require_nonempty(canonical, name="canonical Source identity")
    if len(canonical) > 2048:
        raise ValueError("Canonical Source identity exceeds the bounded length")
    return canonical


def _resolved_failure_policy(
    code: str,
    details: tuple[str, ...],
) -> tuple[
    bool,
    PackageLifecycleRetryDomain,
    PackageLifecycleOperatorAction,
]:
    try:
        retry_rule, retry_domain, operator_action = _FAILURE_POLICIES[code]
    except KeyError as exc:
        raise ValueError("Unsupported Package lifecycle failure code") from exc
    if retry_rule == "conditional:no_acquired_digest":
        if "condition:no_acquired_digest" in details:
            return True, retry_domain, operator_action
        return False, "none", "none"
    return retry_rule, retry_domain, operator_action


def _canonical_network_source(parsed: SplitResult) -> str:
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("Network Source locator requires a hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Network Source locator has an invalid port") from exc
    host = hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))


def canonical_json_bytes(value: object) -> bytes:
    _validate_canonical_json_value(value)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _validate_canonical_json_value(value: object) -> None:
    if value is None or isinstance(value, str | bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        raise TypeError("PLC9B canonical JSON does not permit floats")
    if isinstance(value, list | tuple):
        for item in value:
            _validate_canonical_json_value(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("PLC9B canonical JSON object keys must be strings")
            _validate_canonical_json_value(item)
        return
    raise TypeError("PLC9B canonical JSON accepts only inert JSON values")


def _exact_dict(
    value: object,
    *,
    fields: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    document = dict(value)
    if set(document) != fields:
        raise ValueError(f"{name} fields do not match the versioned schema")
    return cast(dict[str, object], document)


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be boolean")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_positive(value: object, *, name: str) -> int:
    result = _wire_int(value, name=name)
    _require_positive(result, name=name)
    return result


def _wire_nonnegative(value: object, *, name: str) -> int:
    result = _wire_int(value, name=name)
    _require_nonnegative(result, name=name)
    return result


def _wire_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return value


def _require_nonempty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase hexadecimal SHA-256")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_nonnegative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


__all__ = [
    "PackageClassificationBasisFactV1",
    "PackageClassificationFactsV1",
    "PackageLifecycleCancelRequestV1",
    "PackageLifecycleFailureV1",
    "PackageLifecycleIngressRequestV1",
    "PackageLifecycleIngressRequestV2",
    "PackageLifecycleJournalRecordV1",
    "PackageLifecycleRequestV1",
    "PackageLifecycleRequestV2",
    "PackageLifecycleRetryRequestV1",
    "PackageLifecycleStatusV1",
    "PluginBoundPackageClassificationV1",
    "canonical_json_bytes",
    "canonicalize_source_identity",
    "classify_package_request",
    "decode_package_lifecycle_request",
]
