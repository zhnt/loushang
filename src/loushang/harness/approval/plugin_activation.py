"""Durable Approval-owner authority for one-shot Plugin activation attempts."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from time import time_ns
from typing import Literal, cast

from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
)
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

CONTRIBUTION_ACTIVATION_APPROVAL_SUBJECT_VERSION = 1
OWNER_COMPONENT_ACTIVATION_APPROVAL_SUBJECT_VERSION = 1
PLUGIN_ACTIVATION_DECISION_VERSION = 1
PLUGIN_ACTIVATION_JOURNAL_EVENT_VERSION = 1
PLUGIN_ACTIVATION_USE_VERSION = 1

PluginActivationDisposition = Literal["approved", "denied"]
PluginActivationConsumptionState = Literal[
    "AVAILABLE",
    "DENIED",
    "CONSUMED",
    "REVOKED",
]
PluginActivationUseState = Literal[
    "CONSUMED_NOT_STARTED",
    "CANCELLED_BEFORE_START",
    "STARTING",
    "STARTED",
    "COMMITTED",
    "FAILED",
]
PluginActivationJournalEventKind = Literal[
    "decision_issued",
    "decision_revoked",
    "activation_consumed",
    "activation_use_transitioned",
    "activation_uses_recovered",
]

_USE_TRANSITIONS = frozenset(
    {
        ("CONSUMED_NOT_STARTED", "CANCELLED_BEFORE_START"),
        ("CONSUMED_NOT_STARTED", "STARTING"),
        ("STARTING", "STARTED"),
        ("STARTING", "FAILED"),
        ("STARTED", "COMMITTED"),
        ("STARTED", "FAILED"),
    }
)
_TERMINAL_USE_STATES = frozenset(
    {"CANCELLED_BEFORE_START", "COMMITTED", "FAILED"}
)


class PluginActivationJournalRecordCodecError(JournalCodecError):
    """Strict durable Plugin activation journal record failure."""


class PluginActivationJournalError(RuntimeError):
    """Fail-closed activation authority failure with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class ContributionActivationApprovalSubject:
    """Complete activation subject independent of declaration execution."""

    candidate_fingerprint: str
    admission_fingerprint: str
    binding_spec_fingerprint: str
    capability_id: str
    owner_id: str
    provider_id: str
    plugin_id: str
    contribution_id: str
    package_content_digest: str
    dependency_lock_digest: str
    product_id: str
    scope_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    source_trust_class: str
    source_trust_policy_revision: str
    product_policy_revision: str
    owner_policy_revision: str
    revocation_epoch: int
    effective_facets: tuple[str, ...]
    effective_authorities: tuple[str, ...]
    execution_model: Literal["in_process"]
    subject_version: int = CONTRIBUTION_ACTIVATION_APPROVAL_SUBJECT_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("activation candidate fingerprint", self.candidate_fingerprint),
            ("activation admission fingerprint", self.admission_fingerprint),
            ("activation binding spec fingerprint", self.binding_spec_fingerprint),
            ("activation package content digest", self.package_content_digest),
            ("activation dependency lock digest", self.dependency_lock_digest),
        ):
            _require_sha256(value, name=name)
        for name, value in (
            ("Capability id", self.capability_id),
            ("Capability owner id", self.owner_id),
            ("Provider id", self.provider_id),
            ("Plugin id", self.plugin_id),
            ("contribution id", self.contribution_id),
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("source trust class", self.source_trust_class),
            ("source trust policy revision", self.source_trust_policy_revision),
            ("Product policy revision", self.product_policy_revision),
            ("owner policy revision", self.owner_policy_revision),
        ):
            _require_nonempty(value, name=name)
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Activation Subject requires a Plugin instance ref")
        if self.instance_revision_ref.plugin_id != self.plugin_id:
            raise ValueError("Activation Subject instance must match its Plugin")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="activation revocation epoch",
        )
        facets = _sorted_unique_names(
            self.effective_facets,
            name="activation effective facet",
        )
        if not facets:
            raise ValueError("Activation Subject facets must not be empty")
        authorities = _sorted_unique_names(
            self.effective_authorities,
            name="activation effective authority",
        )
        if self.execution_model != "in_process":
            raise ValueError("Unsupported contribution activation execution model")
        _require_version(
            self.subject_version,
            expected=CONTRIBUTION_ACTIVATION_APPROVAL_SUBJECT_VERSION,
        )
        object.__setattr__(self, "effective_facets", facets)
        object.__setattr__(self, "effective_authorities", authorities)

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(b"loushang.contribution-activation-subject/v1\0" + payload).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionFingerprint": self.admission_fingerprint,
            "bindingSpecFingerprint": self.binding_spec_fingerprint,
            "candidateFingerprint": self.candidate_fingerprint,
            "capabilityId": self.capability_id,
            "contributionId": self.contribution_id,
            "dependencyLockDigest": self.dependency_lock_digest,
            "effectiveAuthorities": list(self.effective_authorities),
            "effectiveFacets": list(self.effective_facets),
            "executionModel": self.execution_model,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "ownerId": self.owner_id,
            "ownerPolicyRevision": self.owner_policy_revision,
            "packageContentDigest": self.package_content_digest,
            "pluginId": self.plugin_id,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "providerId": self.provider_id,
            "revocationEpoch": self.revocation_epoch,
            "scopeId": self.scope_id,
            "sourceTrustClass": self.source_trust_class,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "subjectVersion": self.subject_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> ContributionActivationApprovalSubject:
        document = _wire_object(value, name="Contribution activation Subject")
        _wire_exact_fields(
            document,
            keys={
                "admissionFingerprint",
                "bindingSpecFingerprint",
                "candidateFingerprint",
                "capabilityId",
                "contributionId",
                "dependencyLockDigest",
                "effectiveAuthorities",
                "effectiveFacets",
                "executionModel",
                "instanceRevisionRef",
                "ownerId",
                "ownerPolicyRevision",
                "packageContentDigest",
                "pluginId",
                "productId",
                "productPolicyRevision",
                "providerId",
                "revocationEpoch",
                "scopeId",
                "sourceTrustClass",
                "sourceTrustPolicyRevision",
                "subjectVersion",
            },
            name="Contribution activation Subject",
        )
        _wire_version(
            document["subjectVersion"],
            expected=CONTRIBUTION_ACTIVATION_APPROVAL_SUBJECT_VERSION,
        )
        try:
            return cls(
                candidate_fingerprint=_wire_string(
                    document["candidateFingerprint"],
                    name="candidate fingerprint",
                ),
                admission_fingerprint=_wire_string(
                    document["admissionFingerprint"],
                    name="admission fingerprint",
                ),
                binding_spec_fingerprint=_wire_string(
                    document["bindingSpecFingerprint"],
                    name="binding spec fingerprint",
                ),
                capability_id=_wire_string(
                    document["capabilityId"], name="Capability id"
                ),
                owner_id=_wire_string(document["ownerId"], name="owner id"),
                provider_id=_wire_string(document["providerId"], name="Provider id"),
                plugin_id=_wire_string(document["pluginId"], name="Plugin id"),
                contribution_id=_wire_string(
                    document["contributionId"], name="contribution id"
                ),
                package_content_digest=_wire_string(
                    document["packageContentDigest"],
                    name="package content digest",
                ),
                dependency_lock_digest=_wire_string(
                    document["dependencyLockDigest"],
                    name="dependency lock digest",
                ),
                product_id=_wire_string(document["productId"], name="Product id"),
                scope_id=_wire_string(document["scopeId"], name="scope id"),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                source_trust_class=_wire_string(
                    document["sourceTrustClass"], name="source trust class"
                ),
                source_trust_policy_revision=_wire_string(
                    document["sourceTrustPolicyRevision"],
                    name="source trust policy revision",
                ),
                product_policy_revision=_wire_string(
                    document["productPolicyRevision"],
                    name="Product policy revision",
                ),
                owner_policy_revision=_wire_string(
                    document["ownerPolicyRevision"],
                    name="owner policy revision",
                ),
                revocation_epoch=_wire_integer(
                    document["revocationEpoch"], name="revocation epoch"
                ),
                effective_facets=_wire_string_list(
                    document["effectiveFacets"], name="effective facets"
                ),
                effective_authorities=_wire_string_list(
                    document["effectiveAuthorities"],
                    name="effective authorities",
                ),
                execution_model=cast(
                    Literal["in_process"],
                    _wire_string(document["executionModel"], name="execution model"),
                ),
            )
        except PluginActivationJournalRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class OwnerComponentActivationApprovalSubject:
    """Approval identity for one selected component inside a Capability owner."""

    candidate_fingerprint: str
    admission_fingerprint: str
    resolved_component_fingerprint: str
    binding_spec_fingerprint: str
    definition_fingerprint: str
    owner_snapshot_fingerprint: str
    selection_plan_fingerprint: str
    capability_id: str
    owner_id: str
    component_kind: str
    component_id: str
    plugin_id: str
    contribution_id: str
    package_content_digest: str
    dependency_lock_digest: str
    product_id: str
    scope_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    package_source_identity: str
    source_trust_class: str
    source_trust_policy_revision: str
    product_policy_revision: str
    owner_policy_revision: str
    revocation_epoch: int
    effective_authorities: tuple[str, ...]
    execution_model: Literal["in_process"]
    subject_kind: Literal["capability_owner_component"] = (
        "capability_owner_component"
    )
    subject_version: int = OWNER_COMPONENT_ACTIVATION_APPROVAL_SUBJECT_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("component candidate fingerprint", self.candidate_fingerprint),
            ("component admission fingerprint", self.admission_fingerprint),
            ("resolved component fingerprint", self.resolved_component_fingerprint),
            ("component binding spec fingerprint", self.binding_spec_fingerprint),
            ("component Definition fingerprint", self.definition_fingerprint),
            ("component owner snapshot fingerprint", self.owner_snapshot_fingerprint),
            ("component selection plan fingerprint", self.selection_plan_fingerprint),
            ("component package content digest", self.package_content_digest),
            ("component dependency lock digest", self.dependency_lock_digest),
        ):
            _require_sha256(value, name=name)
        for name, value in (
            ("Capability id", self.capability_id),
            ("Capability owner id", self.owner_id),
            ("component kind", self.component_kind),
            ("component id", self.component_id),
            ("Plugin id", self.plugin_id),
            ("contribution id", self.contribution_id),
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("package source identity", self.package_source_identity),
            ("source trust class", self.source_trust_class),
            ("source trust policy revision", self.source_trust_policy_revision),
            ("Product policy revision", self.product_policy_revision),
            ("owner policy revision", self.owner_policy_revision),
        ):
            _require_nonempty(value, name=name)
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Owner-component Subject requires a Plugin instance ref")
        if self.instance_revision_ref.plugin_id != self.plugin_id:
            raise ValueError("Owner-component Subject instance must match its Plugin")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner-component revocation epoch",
        )
        authorities = _sorted_unique_names(
            self.effective_authorities,
            name="owner-component effective authority",
        )
        if self.execution_model != "in_process":
            raise ValueError("Unsupported owner-component execution model")
        if self.subject_kind != "capability_owner_component":
            raise ValueError("Unsupported owner-component Subject kind")
        _require_version(
            self.subject_version,
            expected=OWNER_COMPONENT_ACTIVATION_APPROVAL_SUBJECT_VERSION,
        )
        object.__setattr__(self, "effective_authorities", authorities)

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(
            b"loushang.owner-component-activation-subject/v1\0" + payload
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionFingerprint": self.admission_fingerprint,
            "bindingSpecFingerprint": self.binding_spec_fingerprint,
            "candidateFingerprint": self.candidate_fingerprint,
            "capabilityId": self.capability_id,
            "componentId": self.component_id,
            "componentKind": self.component_kind,
            "contributionId": self.contribution_id,
            "definitionFingerprint": self.definition_fingerprint,
            "dependencyLockDigest": self.dependency_lock_digest,
            "effectiveAuthorities": list(self.effective_authorities),
            "executionModel": self.execution_model,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "ownerId": self.owner_id,
            "ownerPolicyRevision": self.owner_policy_revision,
            "ownerSnapshotFingerprint": self.owner_snapshot_fingerprint,
            "packageContentDigest": self.package_content_digest,
            "packageSourceIdentity": self.package_source_identity,
            "pluginId": self.plugin_id,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "resolvedComponentFingerprint": self.resolved_component_fingerprint,
            "revocationEpoch": self.revocation_epoch,
            "scopeId": self.scope_id,
            "selectionPlanFingerprint": self.selection_plan_fingerprint,
            "sourceTrustClass": self.source_trust_class,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "subjectKind": self.subject_kind,
            "subjectVersion": self.subject_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> OwnerComponentActivationApprovalSubject:
        document = _wire_object(value, name="Owner-component activation Subject")
        _wire_exact_fields(
            document,
            keys={
                "admissionFingerprint",
                "bindingSpecFingerprint",
                "candidateFingerprint",
                "capabilityId",
                "componentId",
                "componentKind",
                "contributionId",
                "definitionFingerprint",
                "dependencyLockDigest",
                "effectiveAuthorities",
                "executionModel",
                "instanceRevisionRef",
                "ownerId",
                "ownerPolicyRevision",
                "ownerSnapshotFingerprint",
                "packageContentDigest",
                "packageSourceIdentity",
                "pluginId",
                "productId",
                "productPolicyRevision",
                "resolvedComponentFingerprint",
                "revocationEpoch",
                "scopeId",
                "selectionPlanFingerprint",
                "sourceTrustClass",
                "sourceTrustPolicyRevision",
                "subjectKind",
                "subjectVersion",
            },
            name="Owner-component activation Subject",
        )
        _wire_version(
            document["subjectVersion"],
            expected=OWNER_COMPONENT_ACTIVATION_APPROVAL_SUBJECT_VERSION,
        )
        try:
            return cls(
                candidate_fingerprint=_wire_string(
                    document["candidateFingerprint"], name="candidate fingerprint"
                ),
                admission_fingerprint=_wire_string(
                    document["admissionFingerprint"], name="admission fingerprint"
                ),
                resolved_component_fingerprint=_wire_string(
                    document["resolvedComponentFingerprint"],
                    name="resolved component fingerprint",
                ),
                binding_spec_fingerprint=_wire_string(
                    document["bindingSpecFingerprint"],
                    name="binding spec fingerprint",
                ),
                definition_fingerprint=_wire_string(
                    document["definitionFingerprint"],
                    name="Definition fingerprint",
                ),
                owner_snapshot_fingerprint=_wire_string(
                    document["ownerSnapshotFingerprint"],
                    name="owner snapshot fingerprint",
                ),
                selection_plan_fingerprint=_wire_string(
                    document["selectionPlanFingerprint"],
                    name="selection plan fingerprint",
                ),
                capability_id=_wire_string(
                    document["capabilityId"], name="Capability id"
                ),
                owner_id=_wire_string(document["ownerId"], name="owner id"),
                component_kind=_wire_string(
                    document["componentKind"], name="component kind"
                ),
                component_id=_wire_string(
                    document["componentId"], name="component id"
                ),
                plugin_id=_wire_string(document["pluginId"], name="Plugin id"),
                contribution_id=_wire_string(
                    document["contributionId"], name="contribution id"
                ),
                package_content_digest=_wire_string(
                    document["packageContentDigest"],
                    name="package content digest",
                ),
                dependency_lock_digest=_wire_string(
                    document["dependencyLockDigest"],
                    name="dependency lock digest",
                ),
                product_id=_wire_string(document["productId"], name="Product id"),
                scope_id=_wire_string(document["scopeId"], name="scope id"),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                package_source_identity=_wire_string(
                    document["packageSourceIdentity"],
                    name="package source identity",
                ),
                source_trust_class=_wire_string(
                    document["sourceTrustClass"], name="source trust class"
                ),
                source_trust_policy_revision=_wire_string(
                    document["sourceTrustPolicyRevision"],
                    name="source trust policy revision",
                ),
                product_policy_revision=_wire_string(
                    document["productPolicyRevision"],
                    name="Product policy revision",
                ),
                owner_policy_revision=_wire_string(
                    document["ownerPolicyRevision"], name="owner policy revision"
                ),
                revocation_epoch=_wire_integer(
                    document["revocationEpoch"], name="revocation epoch"
                ),
                effective_authorities=_wire_string_list(
                    document["effectiveAuthorities"],
                    name="effective authorities",
                ),
                execution_model=cast(
                    Literal["in_process"],
                    _wire_string(document["executionModel"], name="execution model"),
                ),
                subject_kind=cast(
                    Literal["capability_owner_component"],
                    _wire_string(document["subjectKind"], name="Subject kind"),
                ),
            )
        except PluginActivationJournalRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


PluginActivationApprovalSubject = (
    ContributionActivationApprovalSubject | OwnerComponentActivationApprovalSubject
)


@dataclass(frozen=True, slots=True)
class PluginActivationDecisionRecordV1:
    decision_id: str
    subject: PluginActivationApprovalSubject
    scope_id: str
    disposition: PluginActivationDisposition
    authorization: PluginApprovalAuthorizationV1
    issued_at_unix_ms: int
    expires_at_unix_ms: int
    consumption_state: PluginActivationConsumptionState
    consumed_activation_use_id: str | None = None
    decision_revision: int = 1
    decision_version: int = PLUGIN_ACTIVATION_DECISION_VERSION

    def __post_init__(self) -> None:
        _require_hex(self.decision_id, length=48, name="activation decision id")
        if not isinstance(
            self.subject,
            ContributionActivationApprovalSubject
            | OwnerComponentActivationApprovalSubject,
        ):
            raise TypeError("Activation decision requires a Subject")
        _require_nonempty(self.scope_id, name="activation decision scope id")
        if self.scope_id != self.subject.scope_id:
            raise ValueError("Activation decision scope does not match its Subject")
        if self.disposition not in {"approved", "denied"}:
            raise ValueError("Unsupported activation decision disposition")
        if not isinstance(self.authorization, PluginApprovalAuthorizationV1):
            raise TypeError("Activation decision requires authorization")
        _require_interval(
            self.issued_at_unix_ms,
            self.expires_at_unix_ms,
            name="activation decision",
        )
        expected_state = "AVAILABLE" if self.disposition == "approved" else "DENIED"
        if self.consumption_state not in {
            "AVAILABLE",
            "DENIED",
            "CONSUMED",
            "REVOKED",
        }:
            raise ValueError("Unsupported activation decision consumption state")
        if self.decision_revision == 1 and self.consumption_state != expected_state:
            raise ValueError("Initial activation decision state is invalid")
        if self.consumption_state == "CONSUMED":
            _require_hex(
                self.consumed_activation_use_id,
                length=48,
                name="consumed activation use id",
            )
        elif self.consumed_activation_use_id is not None:
            raise ValueError("Unconsumed activation decision has a use id")
        _require_positive_integer(self.decision_revision, name="decision revision")
        _require_version(
            self.decision_version,
            expected=PLUGIN_ACTIVATION_DECISION_VERSION,
        )

    @property
    def subject_digest(self) -> str:
        return self.subject.digest

    def to_dict(self) -> dict[str, object]:
        return {
            "authorization": self.authorization.to_dict(),
            "consumedActivationUseId": self.consumed_activation_use_id,
            "consumptionState": self.consumption_state,
            "decisionId": self.decision_id,
            "decisionRevision": self.decision_revision,
            "decisionVersion": self.decision_version,
            "disposition": self.disposition,
            "expiresAtUnixMs": self.expires_at_unix_ms,
            "issuedAtUnixMs": self.issued_at_unix_ms,
            "scopeId": self.scope_id,
            "subject": self.subject.to_dict(),
            "subjectDigest": self.subject_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginActivationDecisionRecordV1:
        document = _wire_object(value, name="Plugin activation decision")
        _wire_exact_fields(
            document,
            keys={
                "authorization",
                "consumedActivationUseId",
                "consumptionState",
                "decisionId",
                "decisionRevision",
                "decisionVersion",
                "disposition",
                "expiresAtUnixMs",
                "issuedAtUnixMs",
                "scopeId",
                "subject",
                "subjectDigest",
            },
            name="Plugin activation decision",
        )
        _wire_version(
            document["decisionVersion"],
            expected=PLUGIN_ACTIVATION_DECISION_VERSION,
        )
        try:
            subject_document = _wire_object(
                document["subject"],
                name="Plugin activation decision Subject",
            )
            subject = (
                OwnerComponentActivationApprovalSubject.from_dict(subject_document)
                if subject_document.get("subjectKind")
                == "capability_owner_component"
                else ContributionActivationApprovalSubject.from_dict(
                    subject_document
                )
            )
            if _wire_string(
                document["subjectDigest"], name="subject digest"
            ) != subject.digest:
                raise ValueError("Activation decision Subject digest does not match")
            return cls(
                decision_id=_wire_string(document["decisionId"], name="decision id"),
                subject=subject,
                scope_id=_wire_string(document["scopeId"], name="scope id"),
                disposition=cast(
                    PluginActivationDisposition,
                    _wire_string(document["disposition"], name="disposition"),
                ),
                authorization=PluginApprovalAuthorizationV1.from_dict(
                    document["authorization"]
                ),
                issued_at_unix_ms=_wire_integer(
                    document["issuedAtUnixMs"], name="issued-at time"
                ),
                expires_at_unix_ms=_wire_integer(
                    document["expiresAtUnixMs"], name="expiry time"
                ),
                consumption_state=cast(
                    PluginActivationConsumptionState,
                    _wire_string(
                        document["consumptionState"], name="consumption state"
                    ),
                ),
                consumed_activation_use_id=_wire_optional_string(
                    document["consumedActivationUseId"],
                    name="consumed activation use id",
                ),
                decision_revision=_wire_integer(
                    document["decisionRevision"], name="decision revision"
                ),
            )
        except PluginActivationJournalRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ActivationUseReservationV1:
    decision_id: str
    activation_use_id: str
    subject_digest: str
    candidate_fingerprint: str
    plugin_id: str
    contribution_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    host_boot_id: str
    import_realm_id: str
    owner_policy_revision: str
    source_trust_policy_revision: str
    revocation_epoch: int
    state: PluginActivationUseState
    use_version: int = PLUGIN_ACTIVATION_USE_VERSION

    def __post_init__(self) -> None:
        _require_hex(self.decision_id, length=48, name="activation decision id")
        _require_hex(self.activation_use_id, length=48, name="activation use id")
        for name, value in (
            ("activation Subject digest", self.subject_digest),
            ("activation candidate fingerprint", self.candidate_fingerprint),
        ):
            _require_sha256(value, name=name)
        _require_nonempty(self.plugin_id, name="activation Plugin id")
        _require_nonempty(self.contribution_id, name="activation contribution id")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Activation use requires a Plugin instance ref")
        if self.instance_revision_ref.plugin_id != self.plugin_id:
            raise ValueError("Activation use instance must match its Plugin")
        _require_hex(self.host_boot_id, length=32, name="Host boot id")
        _require_hex(self.import_realm_id, length=32, name="import realm id")
        _require_nonempty(self.owner_policy_revision, name="owner policy revision")
        _require_nonempty(
            self.source_trust_policy_revision,
            name="source trust policy revision",
        )
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="activation revocation epoch",
        )
        if self.state not in {
            "CONSUMED_NOT_STARTED",
            "CANCELLED_BEFORE_START",
            "STARTING",
            "STARTED",
            "COMMITTED",
            "FAILED",
        }:
            raise ValueError("Unsupported activation use state")
        _require_version(self.use_version, expected=PLUGIN_ACTIVATION_USE_VERSION)

    def to_dict(self) -> dict[str, object]:
        return {
            "activationUseId": self.activation_use_id,
            "candidateFingerprint": self.candidate_fingerprint,
            "contributionId": self.contribution_id,
            "decisionId": self.decision_id,
            "hostBootId": self.host_boot_id,
            "importRealmId": self.import_realm_id,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "ownerPolicyRevision": self.owner_policy_revision,
            "pluginId": self.plugin_id,
            "revocationEpoch": self.revocation_epoch,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "state": self.state,
            "subjectDigest": self.subject_digest,
            "useVersion": self.use_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> ActivationUseReservationV1:
        document = _wire_object(value, name="Activation use reservation")
        _wire_exact_fields(
            document,
            keys={
                "activationUseId",
                "candidateFingerprint",
                "contributionId",
                "decisionId",
                "hostBootId",
                "importRealmId",
                "instanceRevisionRef",
                "ownerPolicyRevision",
                "pluginId",
                "revocationEpoch",
                "sourceTrustPolicyRevision",
                "state",
                "subjectDigest",
                "useVersion",
            },
            name="Activation use reservation",
        )
        _wire_version(document["useVersion"], expected=PLUGIN_ACTIVATION_USE_VERSION)
        try:
            return cls(
                decision_id=_wire_string(document["decisionId"], name="decision id"),
                activation_use_id=_wire_string(
                    document["activationUseId"], name="activation use id"
                ),
                subject_digest=_wire_string(
                    document["subjectDigest"], name="Subject digest"
                ),
                candidate_fingerprint=_wire_string(
                    document["candidateFingerprint"], name="candidate fingerprint"
                ),
                plugin_id=_wire_string(document["pluginId"], name="Plugin id"),
                contribution_id=_wire_string(
                    document["contributionId"], name="contribution id"
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                host_boot_id=_wire_string(
                    document["hostBootId"], name="Host boot id"
                ),
                import_realm_id=_wire_string(
                    document["importRealmId"], name="import realm id"
                ),
                owner_policy_revision=_wire_string(
                    document["ownerPolicyRevision"], name="owner policy revision"
                ),
                source_trust_policy_revision=_wire_string(
                    document["sourceTrustPolicyRevision"],
                    name="source trust policy revision",
                ),
                revocation_epoch=_wire_integer(
                    document["revocationEpoch"], name="revocation epoch"
                ),
                state=cast(
                    PluginActivationUseState,
                    _wire_string(document["state"], name="activation use state"),
                ),
            )
        except PluginActivationJournalRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class _PluginActivationJournalEventV1:
    journal_revision: int
    expected_journal_revision: int
    event_kind: PluginActivationJournalEventKind
    decision: PluginActivationDecisionRecordV1 | None = None
    reservation: ActivationUseReservationV1 | None = None
    expected_state: PluginActivationUseState | None = None
    reservations: tuple[ActivationUseReservationV1, ...] = ()
    actor_id: str | None = None
    source: str | None = None
    occurred_at_unix_ms: int = 0
    event_version: int = PLUGIN_ACTIVATION_JOURNAL_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        _require_nonnegative_integer(
            self.expected_journal_revision,
            name="expected journal revision",
        )
        if self.journal_revision != self.expected_journal_revision + 1:
            raise ValueError("Activation journal CAS revision is invalid")
        _require_nonnegative_integer(self.occurred_at_unix_ms, name="event time")
        _require_version(
            self.event_version,
            expected=PLUGIN_ACTIVATION_JOURNAL_EVENT_VERSION,
        )
        if self.event_kind == "decision_issued":
            valid = (
                self.decision is not None
                and self.reservation is None
                and self.actor_id is None
                and self.source is None
            )
        elif self.event_kind == "decision_revoked":
            valid = (
                self.decision is not None
                and self.reservation is None
                and self.actor_id is not None
                and self.source is not None
            )
            if valid:
                _require_nonempty(self.actor_id, name="revocation actor id")
                _require_nonempty(self.source, name="revocation source")
        elif self.event_kind == "activation_consumed":
            valid = (
                self.decision is not None
                and self.reservation is not None
                and self.actor_id is None
                and self.source is None
            )
        elif self.event_kind == "activation_use_transitioned":
            valid = (
                self.reservation is not None
                and self.expected_state is not None
                and self.actor_id is None
                and self.source is None
            )
        elif self.event_kind == "activation_uses_recovered":
            valid = (
                bool(self.reservations)
                and self.actor_id is None
                and self.source is None
            )
        else:
            raise ValueError("Unsupported Plugin activation event kind")
        if not valid:
            raise ValueError("Plugin activation event payload does not match its kind")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object]
        if self.event_kind == "decision_issued":
            assert self.decision is not None
            payload = {"decision": self.decision.to_dict()}
        elif self.event_kind == "decision_revoked":
            assert self.decision is not None
            assert self.actor_id is not None and self.source is not None
            payload = {
                "actorId": self.actor_id,
                "decision": self.decision.to_dict(),
                "source": self.source,
            }
        elif self.event_kind == "activation_consumed":
            assert self.decision is not None and self.reservation is not None
            payload = {
                "decision": self.decision.to_dict(),
                "reservation": self.reservation.to_dict(),
            }
        elif self.event_kind == "activation_use_transitioned":
            assert self.reservation is not None and self.expected_state is not None
            payload = {
                "expectedState": self.expected_state,
                "reservation": self.reservation.to_dict(),
            }
        else:
            payload = {
                "reservations": [item.to_dict() for item in self.reservations]
            }
        return {
            "eventKind": self.event_kind,
            "eventVersion": self.event_version,
            "expectedJournalRevision": self.expected_journal_revision,
            "journalRevision": self.journal_revision,
            "occurredAtUnixMs": self.occurred_at_unix_ms,
            "payload": payload,
        }

    @classmethod
    def from_dict(cls, value: object) -> _PluginActivationJournalEventV1:
        document = _wire_object(value, name="Plugin activation journal event")
        _wire_exact_fields(
            document,
            keys={
                "eventKind",
                "eventVersion",
                "expectedJournalRevision",
                "journalRevision",
                "occurredAtUnixMs",
                "payload",
            },
            name="Plugin activation journal event",
        )
        _wire_version(
            document["eventVersion"],
            expected=PLUGIN_ACTIVATION_JOURNAL_EVENT_VERSION,
        )
        kind = _wire_string(document["eventKind"], name="event kind")
        payload = _wire_object(document["payload"], name="event payload")
        try:
            decision: PluginActivationDecisionRecordV1 | None = None
            reservation: ActivationUseReservationV1 | None = None
            expected_state: PluginActivationUseState | None = None
            reservations: tuple[ActivationUseReservationV1, ...] = ()
            actor_id: str | None = None
            source: str | None = None
            if kind == "decision_issued":
                _wire_exact_fields(payload, keys={"decision"}, name="issue payload")
                decision = PluginActivationDecisionRecordV1.from_dict(
                    payload["decision"]
                )
            elif kind == "decision_revoked":
                _wire_exact_fields(
                    payload,
                    keys={"actorId", "decision", "source"},
                    name="revocation payload",
                )
                decision = PluginActivationDecisionRecordV1.from_dict(
                    payload["decision"]
                )
                actor_id = _wire_string(payload["actorId"], name="actor id")
                source = _wire_string(payload["source"], name="revocation source")
            elif kind == "activation_consumed":
                _wire_exact_fields(
                    payload,
                    keys={"decision", "reservation"},
                    name="consumption payload",
                )
                decision = PluginActivationDecisionRecordV1.from_dict(
                    payload["decision"]
                )
                reservation = ActivationUseReservationV1.from_dict(
                    payload["reservation"]
                )
            elif kind == "activation_use_transitioned":
                _wire_exact_fields(
                    payload,
                    keys={"expectedState", "reservation"},
                    name="transition payload",
                )
                expected_state = cast(
                    PluginActivationUseState,
                    _wire_string(payload["expectedState"], name="expected state"),
                )
                reservation = ActivationUseReservationV1.from_dict(
                    payload["reservation"]
                )
            elif kind == "activation_uses_recovered":
                _wire_exact_fields(
                    payload,
                    keys={"reservations"},
                    name="recovery payload",
                )
                values = payload["reservations"]
                if not isinstance(values, list):
                    raise ValueError("Recovered activation uses must be an array")
                reservations = tuple(
                    ActivationUseReservationV1.from_dict(item) for item in values
                )
            else:
                raise ValueError("Unsupported Plugin activation event kind")
            return cls(
                journal_revision=_wire_integer(
                    document["journalRevision"], name="journal revision"
                ),
                expected_journal_revision=_wire_integer(
                    document["expectedJournalRevision"],
                    name="expected journal revision",
                ),
                event_kind=cast(PluginActivationJournalEventKind, kind),
                decision=decision,
                reservation=reservation,
                expected_state=expected_state,
                reservations=reservations,
                actor_id=actor_id,
                source=source,
                occurred_at_unix_ms=_wire_integer(
                    document["occurredAtUnixMs"], name="event time"
                ),
            )
        except PluginActivationJournalRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


_ACTIVATION_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=_PluginActivationJournalEventV1.to_dict,
    decoder=_PluginActivationJournalEventV1.from_dict,
)


@dataclass(frozen=True, slots=True)
class PluginActivationDecisionSnapshotV1:
    journal_revision: int
    decisions: tuple[PluginActivationDecisionRecordV1, ...]
    activation_uses: tuple[ActivationUseReservationV1, ...]


@dataclass(slots=True)
class _ReplayedActivationJournal:
    events: tuple[_PluginActivationJournalEventV1, ...]
    decisions: dict[str, PluginActivationDecisionRecordV1]
    subject_decisions: dict[str, list[str]]
    activation_uses: dict[str, ActivationUseReservationV1]


class PluginActivationDecisionJournal:
    """Workspace-scoped durable activation decision and attempt authority."""

    def __init__(
        self,
        path: str | Path,
        *,
        scope_id: str,
        identity_factory: Callable[[], str] = lambda: secrets.token_hex(24),
        clock: Callable[[], int] = lambda: time_ns() // 1_000_000,
        retained_authority_validator: Callable[
            [PluginApprovalAuthorizationV1], bool
        ] = lambda _authorization: False,
    ) -> None:
        _require_nonempty(scope_id, name="Plugin activation journal scope id")
        self._path = Path(path)
        self._scope_id = scope_id
        self._identity_factory = identity_factory
        self._clock = clock
        self._retained_authority_validator = retained_authority_validator
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def issue_activation_decision(
        self,
        subject: PluginActivationApprovalSubject,
        *,
        disposition: PluginActivationDisposition,
        authorization: PluginApprovalAuthorizationV1,
        issued_at_unix_ms: int,
        expires_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> PluginActivationDecisionRecordV1:
        self._require_subject_scope(subject)
        if disposition not in {"approved", "denied"}:
            raise ValueError("Unsupported Plugin activation disposition")
        if not isinstance(authorization, PluginApprovalAuthorizationV1):
            raise TypeError("Plugin activation authorization is required")
        _require_expected_revision(expected_journal_revision)
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            now = self._now()
            if issued_at_unix_ms > now:
                raise self._error(
                    "Activation decision issue time is in the future",
                    code="invalid_plugin_activation_decision",
                )
            latest = _latest_subject_decision(replayed, subject.digest)
            if (
                latest is not None
                and latest.consumption_state == "AVAILABLE"
                and now < latest.expires_at_unix_ms
            ):
                raise self._error(
                    "Activation Subject already has an active decision",
                    code="plugin_activation_subject_decision_active",
                )
            decision_id = self._new_identity(replayed)
            try:
                decision = PluginActivationDecisionRecordV1(
                    decision_id=decision_id,
                    subject=subject,
                    scope_id=self._scope_id,
                    disposition=disposition,
                    authorization=authorization,
                    issued_at_unix_ms=issued_at_unix_ms,
                    expires_at_unix_ms=expires_at_unix_ms,
                    consumption_state=(
                        "AVAILABLE" if disposition == "approved" else "DENIED"
                    ),
                )
            except (TypeError, ValueError) as exc:
                raise self._error(
                    "Invalid Plugin activation decision",
                    code="invalid_plugin_activation_decision",
                ) from exc
            self._append_unlocked(
                replayed,
                event_kind="decision_issued",
                decision=decision,
                occurred_at=now,
            )
            return decision

    def consume_activation_decision(
        self,
        subject: PluginActivationApprovalSubject,
        *,
        decision_id: str,
        host_boot_id: str,
        import_realm_id: str,
        expected_journal_revision: int,
    ) -> ActivationUseReservationV1:
        self._require_subject_scope(subject)
        _require_hex(decision_id, length=48, name="activation decision id")
        _require_hex(host_boot_id, length=32, name="Host boot id")
        _require_hex(import_realm_id, length=32, name="import realm id")
        _require_expected_revision(expected_journal_revision)
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            decision = replayed.decisions.get(decision_id)
            if decision is None:
                raise self._error(
                    "Plugin activation decision does not exist",
                    code="plugin_activation_decision_missing",
                )
            if decision.subject_digest != subject.digest:
                raise self._error(
                    "Plugin activation decision belongs to another Subject",
                    code="plugin_activation_decision_subject_mismatch",
                )
            if decision.consumption_state == "DENIED":
                raise self._error(
                    "Plugin activation decision is denied",
                    code="plugin_activation_decision_denied",
                )
            if decision.consumption_state == "CONSUMED":
                raise self._error(
                    "Plugin activation decision was already consumed",
                    code="plugin_activation_decision_consumed",
                )
            if decision.consumption_state == "REVOKED":
                raise self._error(
                    "Plugin activation decision was revoked",
                    code="plugin_activation_decision_revoked",
                )
            now = self._now()
            if now < decision.issued_at_unix_ms:
                raise self._error(
                    "Plugin activation decision is not current",
                    code="invalid_plugin_activation_decision",
                )
            if now >= decision.expires_at_unix_ms:
                raise self._error(
                    "Plugin activation decision expired",
                    code="plugin_activation_decision_expired",
                )
            if (
                decision.authorization.authorization_kind != "direct"
                and not self._retained_authority_validator(decision.authorization)
            ):
                raise self._error(
                    "Retained activation authorization is no longer live",
                    code="plugin_activation_authorization_stale",
                )
            activation_use_id = self._new_identity(replayed)
            reservation = ActivationUseReservationV1(
                decision_id=decision.decision_id,
                activation_use_id=activation_use_id,
                subject_digest=subject.digest,
                candidate_fingerprint=subject.candidate_fingerprint,
                plugin_id=subject.plugin_id,
                contribution_id=subject.contribution_id,
                instance_revision_ref=subject.instance_revision_ref,
                host_boot_id=host_boot_id,
                import_realm_id=import_realm_id,
                owner_policy_revision=subject.owner_policy_revision,
                source_trust_policy_revision=(
                    subject.source_trust_policy_revision
                ),
                revocation_epoch=subject.revocation_epoch,
                state="CONSUMED_NOT_STARTED",
            )
            consumed = replace(
                decision,
                consumption_state="CONSUMED",
                consumed_activation_use_id=activation_use_id,
                decision_revision=decision.decision_revision + 1,
            )
            self._append_unlocked(
                replayed,
                event_kind="activation_consumed",
                decision=consumed,
                reservation=reservation,
                occurred_at=now,
            )
            return reservation

    def revoke_activation_decision(
        self,
        decision_id: str,
        *,
        actor_id: str,
        source: str,
        revoked_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> PluginActivationDecisionRecordV1:
        _require_hex(decision_id, length=48, name="activation decision id")
        _require_nonempty(actor_id, name="revocation actor id")
        _require_nonempty(source, name="revocation source")
        _require_expected_revision(expected_journal_revision)
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            decision = replayed.decisions.get(decision_id)
            if decision is None:
                raise self._error(
                    "Plugin activation decision does not exist",
                    code="plugin_activation_decision_missing",
                )
            if decision.consumption_state != "AVAILABLE":
                raise self._error(
                    "Plugin activation decision is not available for revocation",
                    code="plugin_activation_decision_not_available",
                )
            now = self._now()
            if (
                revoked_at_unix_ms < decision.issued_at_unix_ms
                or revoked_at_unix_ms > now
            ):
                raise self._error(
                    "Plugin activation revocation time is outside the durable clock",
                    code="invalid_plugin_activation_revocation",
                )
            revoked = replace(
                decision,
                consumption_state="REVOKED",
                decision_revision=decision.decision_revision + 1,
            )
            self._append_unlocked(
                replayed,
                event_kind="decision_revoked",
                decision=revoked,
                actor_id=actor_id,
                source=source,
                occurred_at=revoked_at_unix_ms,
            )
            return revoked

    def validate_activation_use_current(
        self,
        reservation: ActivationUseReservationV1,
        *,
        expected_state: PluginActivationUseState,
    ) -> None:
        if not isinstance(reservation, ActivationUseReservationV1):
            raise TypeError("Activation use validation requires an exact reservation")
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            current = replayed.activation_uses.get(reservation.activation_use_id)
            decision = replayed.decisions.get(reservation.decision_id)
            if current != reservation or current.state != expected_state:
                raise self._error(
                    "Plugin activation use is no longer current",
                    code="plugin_activation_use_state_conflict",
                )
            if (
                decision is None
                or decision.consumption_state != "CONSUMED"
                or decision.consumed_activation_use_id
                != reservation.activation_use_id
            ):
                raise self._error(
                    "Plugin activation use has no exact consumed decision",
                    code="plugin_activation_use_authority_mismatch",
                )
            now = self._now()
            if now < decision.issued_at_unix_ms or now >= decision.expires_at_unix_ms:
                raise self._error(
                    "Plugin activation decision expired before execution start",
                    code="plugin_activation_decision_expired",
                )
            if (
                decision.authorization.authorization_kind != "direct"
                and not self._retained_authority_validator(decision.authorization)
            ):
                raise self._error(
                    "Retained activation authorization is no longer live",
                    code="plugin_activation_authorization_stale",
                )

    def transition_activation_use(
        self,
        activation_use_id: str,
        *,
        expected_state: PluginActivationUseState,
        target_state: PluginActivationUseState,
        host_boot_id: str,
        import_realm_id: str,
        transitioned_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> ActivationUseReservationV1:
        _require_hex(activation_use_id, length=48, name="activation use id")
        _require_hex(host_boot_id, length=32, name="Host boot id")
        _require_hex(import_realm_id, length=32, name="import realm id")
        _require_expected_revision(expected_journal_revision)
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            current = replayed.activation_uses.get(activation_use_id)
            if current is None:
                raise self._error(
                    "Plugin activation use does not exist",
                    code="plugin_activation_use_missing",
                )
            if current.state != expected_state:
                raise self._error(
                    "Plugin activation use state changed",
                    code="plugin_activation_use_state_conflict",
                )
            if (expected_state, target_state) not in _USE_TRANSITIONS:
                raise self._error(
                    "Plugin activation use transition is invalid",
                    code="plugin_activation_use_transition_invalid",
                )
            if (
                current.host_boot_id != host_boot_id
                or current.import_realm_id != import_realm_id
            ):
                raise self._error(
                    "Plugin activation use belongs to another Host realm",
                    code="plugin_activation_use_host_mismatch",
                )
            transitioned = replace(current, state=target_state)
            self._append_unlocked(
                replayed,
                event_kind="activation_use_transitioned",
                reservation=transitioned,
                expected_state=expected_state,
                occurred_at=transitioned_at_unix_ms,
            )
            return transitioned

    def recover_activation_uses(
        self,
        *,
        current_host_boot_id: str,
        recovered_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> tuple[ActivationUseReservationV1, ...]:
        _require_hex(current_host_boot_id, length=32, name="current Host boot id")
        _require_expected_revision(expected_journal_revision)
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            recovered: list[ActivationUseReservationV1] = []
            for current in sorted(
                replayed.activation_uses.values(),
                key=lambda item: item.activation_use_id,
            ):
                if current.state in _TERMINAL_USE_STATES:
                    continue
                if current.host_boot_id == current_host_boot_id:
                    continue
                if current.state == "CONSUMED_NOT_STARTED":
                    recovered.append(
                        replace(current, state="CANCELLED_BEFORE_START")
                    )
                    continue
                recovered.append(replace(current, state="FAILED"))
            if not recovered:
                return ()
            self._append_unlocked(
                replayed,
                event_kind="activation_uses_recovered",
                reservations=tuple(recovered),
                occurred_at=recovered_at_unix_ms,
            )
            return tuple(recovered)

    def snapshot(self) -> PluginActivationDecisionSnapshotV1:
        with self._lock():
            replayed = self._load_and_replay_unlocked()
        return PluginActivationDecisionSnapshotV1(
            journal_revision=len(replayed.events),
            decisions=tuple(
                replayed.decisions[item] for item in sorted(replayed.decisions)
            ),
            activation_uses=tuple(
                replayed.activation_uses[item]
                for item in sorted(replayed.activation_uses)
            ),
        )

    def _new_identity(self, replayed: _ReplayedActivationJournal) -> str:
        identity = self._identity_factory()
        _require_hex(identity, length=48, name="activation identity")
        if identity in replayed.decisions or identity in replayed.activation_uses:
            raise self._error(
                "Plugin activation identity was already used",
                code="plugin_activation_identity_conflict",
            )
        return identity

    def _require_subject_scope(
        self,
        subject: PluginActivationApprovalSubject,
    ) -> None:
        if not isinstance(
            subject,
            ContributionActivationApprovalSubject
            | OwnerComponentActivationApprovalSubject,
        ):
            raise TypeError("Plugin activation journal requires an exact Subject")
        if subject.scope_id != self._scope_id:
            raise self._error(
                "Plugin activation Subject belongs to another scope",
                code="plugin_activation_decision_scope_mismatch",
            )

    def _now(self) -> int:
        value = self._clock()
        return _require_nonnegative_integer(value, name="activation clock")

    def _lock(self):
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _require_journal_revision(
        self,
        replayed: _ReplayedActivationJournal,
        expected: int,
    ) -> None:
        if len(replayed.events) != expected:
            raise self._error(
                "Expected Plugin activation journal revision does not match",
                code="plugin_activation_journal_revision_conflict",
            )

    def _append_unlocked(
        self,
        replayed: _ReplayedActivationJournal,
        *,
        event_kind: PluginActivationJournalEventKind,
        occurred_at: int,
        decision: PluginActivationDecisionRecordV1 | None = None,
        reservation: ActivationUseReservationV1 | None = None,
        expected_state: PluginActivationUseState | None = None,
        reservations: tuple[ActivationUseReservationV1, ...] = (),
        actor_id: str | None = None,
        source: str | None = None,
    ) -> None:
        event = _PluginActivationJournalEventV1(
            journal_revision=len(replayed.events) + 1,
            expected_journal_revision=len(replayed.events),
            event_kind=event_kind,
            decision=decision,
            reservation=reservation,
            expected_state=expected_state,
            reservations=reservations,
            actor_id=actor_id,
            source=source,
            occurred_at_unix_ms=occurred_at,
        )
        append_jsonl_record(
            self._path,
            event,
            record_codec=_ACTIVATION_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_and_replay_unlocked(self) -> _ReplayedActivationJournal:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, _PluginActivationJournalEventV1] = (
                load_jsonl(
                    self._path,
                    record_codec=_ACTIVATION_EVENT_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=self._load_policy,
                )
            )
        except JournalFileError as exc:
            raise self._error(
                "Plugin activation journal cannot be decoded",
                code="plugin_activation_journal_corrupt",
            ) from exc
        replayed = _replay(snapshot.records, path=self._path)
        if any(
            decision.scope_id != self._scope_id
            for decision in replayed.decisions.values()
        ):
            raise self._error(
                "Plugin activation journal contains another durable scope",
                code="plugin_activation_journal_corrupt",
            )
        return replayed

    def _error(self, message: str, *, code: str) -> PluginActivationJournalError:
        return PluginActivationJournalError(message, code=code, path=self._path)


def _empty_replay() -> _ReplayedActivationJournal:
    return _ReplayedActivationJournal(
        events=(),
        decisions={},
        subject_decisions={},
        activation_uses={},
    )


def _replay(
    events: tuple[_PluginActivationJournalEventV1, ...],
    *,
    path: Path,
) -> _ReplayedActivationJournal:
    replayed = _empty_replay()
    replayed.events = events
    for index, event in enumerate(events, start=1):
        if (
            event.journal_revision != index
            or event.expected_journal_revision != index - 1
        ):
            raise _corrupt(path, "Activation journal revision sequence is invalid")
        if event.event_kind == "decision_issued":
            assert event.decision is not None
            decision = event.decision
            if decision.decision_id in replayed.decisions:
                raise _corrupt(path, "Activation decision identity is duplicated")
            replayed.decisions[decision.decision_id] = decision
            replayed.subject_decisions.setdefault(decision.subject_digest, []).append(
                decision.decision_id
            )
        elif event.event_kind == "decision_revoked":
            assert event.decision is not None
            previous_decision = replayed.decisions.get(event.decision.decision_id)
            expected_decision = (
                None
                if previous_decision is None
                else replace(
                    previous_decision,
                    consumption_state="REVOKED",
                    decision_revision=previous_decision.decision_revision + 1,
                )
            )
            if (
                previous_decision is None
                or previous_decision.consumption_state != "AVAILABLE"
                or event.decision != expected_decision
            ):
                raise _corrupt(path, "Activation revocation event is invalid")
            replayed.decisions[event.decision.decision_id] = event.decision
        elif event.event_kind == "activation_consumed":
            assert event.decision is not None and event.reservation is not None
            previous_decision = replayed.decisions.get(event.decision.decision_id)
            subject = event.decision.subject
            expected_decision = (
                None
                if previous_decision is None
                else replace(
                    previous_decision,
                    consumption_state="CONSUMED",
                    consumed_activation_use_id=(
                        event.reservation.activation_use_id
                    ),
                    decision_revision=previous_decision.decision_revision + 1,
                )
            )
            expected_reservation = ActivationUseReservationV1(
                decision_id=event.decision.decision_id,
                activation_use_id=event.reservation.activation_use_id,
                subject_digest=subject.digest,
                candidate_fingerprint=subject.candidate_fingerprint,
                plugin_id=subject.plugin_id,
                contribution_id=subject.contribution_id,
                instance_revision_ref=subject.instance_revision_ref,
                host_boot_id=event.reservation.host_boot_id,
                import_realm_id=event.reservation.import_realm_id,
                owner_policy_revision=subject.owner_policy_revision,
                source_trust_policy_revision=(
                    subject.source_trust_policy_revision
                ),
                revocation_epoch=subject.revocation_epoch,
                state="CONSUMED_NOT_STARTED",
            )
            if (
                previous_decision is None
                or previous_decision.consumption_state != "AVAILABLE"
                or event.decision != expected_decision
                or event.reservation != expected_reservation
                or event.reservation.activation_use_id in replayed.activation_uses
            ):
                raise _corrupt(path, "Activation consumption event is invalid")
            replayed.decisions[event.decision.decision_id] = event.decision
            replayed.activation_uses[event.reservation.activation_use_id] = (
                event.reservation
            )
        elif event.event_kind == "activation_use_transitioned":
            assert event.reservation is not None and event.expected_state is not None
            previous_reservation = replayed.activation_uses.get(
                event.reservation.activation_use_id
            )
            expected_transition = (
                None
                if previous_reservation is None
                else replace(previous_reservation, state=event.reservation.state)
            )
            if (
                previous_reservation is None
                or previous_reservation.state != event.expected_state
                or (previous_reservation.state, event.reservation.state)
                not in _USE_TRANSITIONS
                or event.reservation != expected_transition
            ):
                raise _corrupt(path, "Activation transition event is invalid")
            replayed.activation_uses[event.reservation.activation_use_id] = (
                event.reservation
            )
        else:
            for reservation in event.reservations:
                previous_reservation = replayed.activation_uses.get(
                    reservation.activation_use_id
                )
                valid = previous_reservation is not None and (
                    (
                        previous_reservation.state == "CONSUMED_NOT_STARTED"
                        and reservation.state == "CANCELLED_BEFORE_START"
                    )
                    or (
                        previous_reservation.state in {"STARTING", "STARTED"}
                        and reservation.state == "FAILED"
                    )
                ) and reservation == replace(
                    previous_reservation,
                    state=reservation.state,
                )
                if not valid:
                    raise _corrupt(path, "Activation recovery event is invalid")
                replayed.activation_uses[reservation.activation_use_id] = reservation
    return replayed


def _latest_subject_decision(
    replayed: _ReplayedActivationJournal,
    subject_digest: str,
) -> PluginActivationDecisionRecordV1 | None:
    identities = replayed.subject_decisions.get(subject_digest, ())
    if not identities:
        return None
    return replayed.decisions[identities[-1]]


def _corrupt(path: Path, message: str) -> PluginActivationJournalError:
    return PluginActivationJournalError(
        message,
        code="plugin_activation_journal_corrupt",
        path=path,
    )


def _invalid_record(message: str) -> PluginActivationJournalRecordCodecError:
    return PluginActivationJournalRecordCodecError(
        message,
        code="invalid_plugin_activation_journal_record",
    )


def _wire_object(value: object, *, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid_record(f"{name} must be an object")
    return value


def _wire_exact_fields(
    value: Mapping[str, object],
    *,
    keys: set[str],
    name: str,
) -> None:
    if set(value) != keys:
        raise _invalid_record(f"{name} fields do not match")


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise _invalid_record(f"{name} must be a string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid_record(f"{name} must be an integer")
    return value


def _wire_string_list(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _invalid_record(f"{name} must be a string list")
    return tuple(value)


def _wire_version(value: object, *, expected: int) -> None:
    try:
        _require_version(value, expected=expected)
    except (TypeError, ValueError) as exc:
        raise _invalid_record(str(exc)) from exc


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_sha256(value: object, *, name: str) -> None:
    _require_hex(value, length=64, name=name)


def _require_hex(value: object, *, length: int, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _require_positive_integer(value: object, *, name: str) -> int:
    result = _require_nonnegative_integer(value, name=name)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


def _require_interval(issued_at: object, expires_at: object, *, name: str) -> None:
    issued = _require_nonnegative_integer(issued_at, name=f"{name} issue time")
    expires = _require_nonnegative_integer(expires_at, name=f"{name} expiry time")
    if expires <= issued:
        raise ValueError(f"{name} expiry must be after issue time")


def _require_expected_revision(value: object) -> None:
    _require_nonnegative_integer(value, name="expected journal revision")


def _require_version(value: object, *, expected: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("record version must be an integer")
    if value != expected:
        raise ValueError("Unsupported Plugin activation record version")


def _sorted_unique_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_require_nonempty(item, name=name) for item in values))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} values must be unique")
    return normalized


__all__ = [
    "ActivationUseReservationV1",
    "ContributionActivationApprovalSubject",
    "OwnerComponentActivationApprovalSubject",
    "PluginActivationApprovalSubject",
    "PluginActivationDecisionJournal",
    "PluginActivationDecisionRecordV1",
    "PluginActivationDecisionSnapshotV1",
    "PluginActivationJournalError",
    "PluginActivationUseState",
]
