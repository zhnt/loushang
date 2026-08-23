"""Exact-owner admission for inert Resource, Tool, and Command contributions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal, Never, Protocol, TypeVar, cast

from loushang.harness.capabilities.contracts import (
    CapabilityRequirement,
    CapabilityRequirementBinding,
    _capability_requirement_to_dict,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.runtime import RuntimeCapabilityScope, RuntimeRefreshBoundary

OWNER_CONTRIBUTION_ADMISSION_VERSION = 1
OWNER_CONTRIBUTION_CANDIDATE_VERSION = 1

OwnerContributionKind = Literal["resource_item", "tool_pack", "command_pack"]
ResourceContributionKind = Literal[
    "asset",
    "method",
    "prompt",
    "skill",
    "source",
    "theme",
]
ResourceLocatorKind = Literal["directory", "file"]

_OWNER_CONTRIBUTION_KINDS = frozenset(
    {"resource_item", "tool_pack", "command_pack"}
)
_RESOURCE_KINDS = frozenset(
    {"asset", "method", "prompt", "skill", "source", "theme"}
)
_LOCATOR_KINDS = frozenset({"directory", "file"})
_SCOPES = frozenset({"process", "tenant", "workspace", "session", "turn", "channel"})
_REFRESH_BOUNDARIES = frozenset({"sealed", "turn"})
_REQUIREMENT_BINDINGS = frozenset({"direct", "stable_reference"})


class OwnerContributionAdmissionError(RuntimeError):
    """Stable fail-closed diagnostic from one exact contribution owner."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResourceContributionSpec:
    """Normalized Resource-owner input over one verified package locator."""

    resource_kind: ResourceContributionKind
    locator: str
    locator_kind: ResourceLocatorKind
    media_type: str
    schema_id: str
    schema_version: int

    def __post_init__(self) -> None:
        if self.resource_kind not in _RESOURCE_KINDS:
            raise ValueError("Unsupported Resource contribution kind")
        if self.locator_kind not in _LOCATOR_KINDS:
            raise ValueError("Unsupported Resource locator kind")
        for name, value in (
            ("Resource locator", self.locator),
            ("Resource media type", self.media_type),
            ("Resource schema id", self.schema_id),
        ):
            _require_nonempty(value, name=name)
        _require_positive_integer(self.schema_version, name="Resource schema version")

    @property
    def contribution_kind(self) -> Literal["resource_item"]:
        return "resource_item"

    @property
    def collection_id(self) -> str:
        return self.schema_id

    @property
    def admitted_identities(self) -> tuple[str, ...]:
        return (f"{self.schema_id}:{self.locator}",)

    @property
    def requirements(self) -> tuple[CapabilityRequirement, ...]:
        return ()

    def to_dict(self) -> dict[str, object]:
        return {
            "contributionKind": self.contribution_kind,
            "locator": self.locator,
            "locatorKind": self.locator_kind,
            "mediaType": self.media_type,
            "resourceKind": self.resource_kind,
            "schemaId": self.schema_id,
            "schemaVersion": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CatalogConsumerContributionSpec:
    """Normalized Tool/Command owner input with typed Capability requirements."""

    contribution_kind: Literal["tool_pack", "command_pack"]
    catalog_id: str
    catalog_revision: int
    item_ids: tuple[str, ...]
    requirements: tuple[CapabilityRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.contribution_kind not in {"tool_pack", "command_pack"}:
            raise ValueError("Unsupported Catalog Consumer contribution kind")
        _require_nonempty(self.catalog_id, name="Catalog id")
        _require_positive_integer(self.catalog_revision, name="Catalog revision")
        item_ids = _normalized_names(self.item_ids, name="Catalog item identity")
        if not item_ids:
            raise ValueError("Catalog Consumer items must not be empty")
        if item_ids != tuple(sorted(item_ids)):
            raise ValueError("Catalog Consumer items must be sorted")
        requirements = tuple(self.requirements)
        if any(not isinstance(item, CapabilityRequirement) for item in requirements):
            raise TypeError("Catalog Consumer requirements have invalid type")
        capability_ids = tuple(item.capability for item in requirements)
        if capability_ids != tuple(sorted(capability_ids)) or len(
            capability_ids
        ) != len(set(capability_ids)):
            raise ValueError(
                "Catalog Consumer requirements must be Capability-sorted and unique"
            )
        object.__setattr__(self, "item_ids", item_ids)
        object.__setattr__(self, "requirements", requirements)

    @property
    def collection_id(self) -> str:
        return self.catalog_id

    @property
    def admitted_identities(self) -> tuple[str, ...]:
        return tuple(f"{self.catalog_id}:{item_id}" for item_id in self.item_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "catalogId": self.catalog_id,
            "catalogRevision": self.catalog_revision,
            "contributionKind": self.contribution_kind,
            "itemIds": list(self.item_ids),
            "requirements": [
                _capability_requirement_to_dict(item) for item in self.requirements
            ],
        }


OwnerContributionSpec = ResourceContributionSpec | CatalogConsumerContributionSpec


@dataclass(frozen=True, slots=True)
class OwnerContributionCandidateEnvelope:
    """Complete inert candidate presented to one exact contribution owner."""

    owner_id: str
    plugin_id: str
    contribution_id: str
    contribution: OwnerContributionSpec
    plugin_candidate_fingerprint: str
    declaration_fingerprint: str
    declaration_evidence_fingerprint: str
    package_content_digest: str
    dependency_lock_digest: str
    product_id: str
    scope_id: str
    product_policy_revision: str
    instance_revision_ref: PluginInstanceRevisionRef
    package_source_identity: str
    source_trust_class: str
    source_trust_policy_revision: str
    source_trusted: bool
    candidate_version: int = OWNER_CONTRIBUTION_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Contribution owner id", self.owner_id),
            ("Plugin id", self.plugin_id),
            ("Contribution id", self.contribution_id),
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("Product policy revision", self.product_policy_revision),
            ("package source identity", self.package_source_identity),
            ("source trust class", self.source_trust_class),
            ("source trust policy revision", self.source_trust_policy_revision),
        ):
            _require_nonempty(value, name=name)
        if not isinstance(
            self.contribution,
            ResourceContributionSpec | CatalogConsumerContributionSpec,
        ):
            raise TypeError("Owner contribution candidate has an invalid payload")
        for name, value in (
            ("Plugin candidate fingerprint", self.plugin_candidate_fingerprint),
            ("declaration fingerprint", self.declaration_fingerprint),
            (
                "declaration evidence fingerprint",
                self.declaration_evidence_fingerprint,
            ),
            ("package content digest", self.package_content_digest),
            ("dependency lock digest", self.dependency_lock_digest),
        ):
            _require_sha256(value, name=name)
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Owner contribution candidate requires an instance ref")
        if self.instance_revision_ref.plugin_id != self.plugin_id:
            raise ValueError("Owner contribution instance must match its Plugin")
        if type(self.source_trusted) is not bool:
            raise TypeError("Owner contribution source trust must be a bool")
        _require_exact_version(
            self.candidate_version,
            supported=OWNER_CONTRIBUTION_CANDIDATE_VERSION,
            name="Owner contribution candidate",
        )

    @property
    def contribution_kind(self) -> OwnerContributionKind:
        return cast(OwnerContributionKind, self.contribution.contribution_kind)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.owner-contribution-candidate/v1",
            self._record_document(),
        )

    def _record_document(self) -> dict[str, object]:
        return {
            "candidateVersion": self.candidate_version,
            "contribution": self.contribution.to_dict(),
            "contributionId": self.contribution_id,
            "declarationEvidenceFingerprint": (
                self.declaration_evidence_fingerprint
            ),
            "declarationFingerprint": self.declaration_fingerprint,
            "dependencyLockDigest": self.dependency_lock_digest,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "ownerId": self.owner_id,
            "packageContentDigest": self.package_content_digest,
            "packageSourceIdentity": self.package_source_identity,
            "pluginCandidateFingerprint": self.plugin_candidate_fingerprint,
            "pluginId": self.plugin_id,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "scopeId": self.scope_id,
            "sourceTrustClass": self.source_trust_class,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "sourceTrusted": self.source_trusted,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._record_document(), "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class OwnerContributionPolicy:
    """Explicit immutable authority for one owner/kind/Product combination."""

    owner_id: str
    contribution_kind: OwnerContributionKind
    product_id: str
    policy_revision: str
    revocation_epoch: int
    allowed_source_trust_classes: tuple[str, ...]
    allowed_collection_ids: tuple[str, ...]
    allowed_requirement_bindings: tuple[CapabilityRequirementBinding, ...]
    consumer_scope: RuntimeCapabilityScope
    consumer_refresh_boundary: RuntimeRefreshBoundary

    def __post_init__(self) -> None:
        _require_nonempty(self.owner_id, name="Contribution owner id")
        if self.contribution_kind not in _OWNER_CONTRIBUTION_KINDS:
            raise ValueError("Unsupported owner contribution kind")
        _require_nonempty(self.product_id, name="Contribution Product id")
        _require_nonempty(self.policy_revision, name="owner policy revision")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        trust_classes = _normalized_names(
            self.allowed_source_trust_classes,
            name="allowed source trust class",
        )
        collection_ids = _normalized_names(
            self.allowed_collection_ids,
            name="allowed collection id",
        )
        bindings = _normalized_names(
            self.allowed_requirement_bindings,
            name="allowed requirement binding",
        )
        if not trust_classes or not collection_ids or not bindings:
            raise ValueError("Owner policy allowlists must not be empty")
        if set(bindings) - _REQUIREMENT_BINDINGS:
            raise ValueError("Owner policy contains an unsupported requirement binding")
        if self.consumer_scope not in _SCOPES:
            raise ValueError("Owner policy contains an unsupported Consumer scope")
        if self.consumer_refresh_boundary not in _REFRESH_BOUNDARIES:
            raise ValueError("Owner policy contains an unsupported refresh boundary")
        object.__setattr__(self, "allowed_source_trust_classes", trust_classes)
        object.__setattr__(self, "allowed_collection_ids", collection_ids)
        object.__setattr__(
            self,
            "allowed_requirement_bindings",
            cast(tuple[CapabilityRequirementBinding, ...], bindings),
        )


@dataclass(frozen=True, slots=True, init=False)
class OwnerContributionAdmissionRecord:
    """Exact-owner immutable decision over one complete inert candidate."""

    candidate: OwnerContributionCandidateEnvelope = field(repr=False)
    owner_policy_revision: str
    revocation_epoch: int
    admitted_identities: tuple[str, ...]
    requirements: tuple[CapabilityRequirement, ...]
    consumer_scope: RuntimeCapabilityScope
    consumer_refresh_boundary: RuntimeRefreshBoundary
    issued_at: int
    expires_at: int
    admission_version: int

    def __init__(self) -> None:
        raise TypeError("Owner contribution admission is owner-constructed")

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, OwnerContributionCandidateEnvelope):
            raise TypeError("Owner contribution admission requires a candidate")
        _require_nonempty(self.owner_policy_revision, name="owner policy revision")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        identities = _normalized_names(
            self.admitted_identities,
            name="admitted contribution identity",
        )
        if identities != self.candidate.contribution.admitted_identities:
            raise ValueError("Owner admission identities do not match the candidate")
        requirements = tuple(self.requirements)
        if requirements != self.candidate.contribution.requirements:
            raise ValueError("Owner admission requirements do not match the candidate")
        if self.consumer_scope not in _SCOPES:
            raise ValueError("Owner admission Consumer scope is invalid")
        if self.consumer_refresh_boundary not in _REFRESH_BOUNDARIES:
            raise ValueError("Owner admission refresh boundary is invalid")
        _require_interval(self.issued_at, self.expires_at, name="owner admission")
        _require_exact_version(
            self.admission_version,
            supported=OWNER_CONTRIBUTION_ADMISSION_VERSION,
            name="Owner contribution admission",
        )
        object.__setattr__(self, "admitted_identities", identities)
        object.__setattr__(self, "requirements", requirements)

    @property
    def owner_id(self) -> str:
        return self.candidate.owner_id

    @property
    def contribution_kind(self) -> OwnerContributionKind:
        return self.candidate.contribution_kind

    @property
    def plugin_id(self) -> str:
        return self.candidate.plugin_id

    @property
    def contribution_id(self) -> str:
        return self.candidate.contribution_id

    @property
    def product_id(self) -> str:
        return self.candidate.product_id

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.owner-contribution-admission/v1",
            self._record_document(),
        )

    def _record_document(self) -> dict[str, object]:
        return {
            "admissionVersion": self.admission_version,
            "admittedIdentities": list(self.admitted_identities),
            "candidate": self.candidate.to_dict(),
            "consumerRefreshBoundary": self.consumer_refresh_boundary,
            "consumerScope": self.consumer_scope,
            "expiresAt": self.expires_at,
            "issuedAt": self.issued_at,
            "ownerPolicyRevision": self.owner_policy_revision,
            "requirements": [
                _capability_requirement_to_dict(item) for item in self.requirements
            ],
            "revocationEpoch": self.revocation_epoch,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._record_document(), "fingerprint": self.fingerprint}


class OwnerContributionAuthority:
    """One non-global exact owner admission authority."""

    def __init__(self, policy: OwnerContributionPolicy) -> None:
        if not isinstance(policy, OwnerContributionPolicy):
            raise TypeError("Owner contribution authority requires a policy")
        self._policy = policy

    @property
    def policy(self) -> OwnerContributionPolicy:
        return self._policy

    def admit(
        self,
        candidate: OwnerContributionCandidateEnvelope,
        *,
        issued_at: int,
        expires_at: int,
    ) -> OwnerContributionAdmissionRecord:
        if not isinstance(candidate, OwnerContributionCandidateEnvelope):
            raise TypeError("Owner contribution admission requires a candidate")
        policy = self._policy
        if candidate.owner_id != policy.owner_id:
            _raise_admission(
                "contribution_owner_mismatch",
                "Candidate belongs to another contribution owner.",
            )
        if candidate.contribution_kind != policy.contribution_kind:
            _raise_admission(
                "contribution_kind_mismatch",
                "Candidate belongs to another contribution kind.",
            )
        if candidate.product_id != policy.product_id:
            _raise_admission(
                "contribution_product_mismatch",
                "Candidate belongs to another Product.",
            )
        if not candidate.source_trusted:
            _raise_admission(
                "contribution_source_untrusted",
                "Candidate source is not trusted.",
            )
        if candidate.source_trust_class not in policy.allowed_source_trust_classes:
            _raise_admission(
                "contribution_source_class_denied",
                "Candidate source trust class is not allowed.",
            )
        if candidate.contribution.collection_id not in policy.allowed_collection_ids:
            _raise_admission(
                "contribution_collection_denied",
                "Candidate collection is not allowed by its owner.",
            )
        for requirement in candidate.contribution.requirements:
            if requirement.binding not in policy.allowed_requirement_bindings:
                _raise_admission(
                    "contribution_requirement_binding_denied",
                    "Candidate requirement binding is not allowed by its owner.",
                )
        try:
            _require_interval(issued_at, expires_at, name="owner admission")
        except (TypeError, ValueError) as exc:
            raise OwnerContributionAdmissionError(
                "Owner contribution admission interval is invalid.",
                code="invalid_contribution_admission_interval",
            ) from exc
        return _owner_construct(
            OwnerContributionAdmissionRecord,
            candidate=candidate,
            owner_policy_revision=policy.policy_revision,
            revocation_epoch=policy.revocation_epoch,
            admitted_identities=candidate.contribution.admitted_identities,
            requirements=candidate.contribution.requirements,
            consumer_scope=policy.consumer_scope,
            consumer_refresh_boundary=policy.consumer_refresh_boundary,
            issued_at=issued_at,
            expires_at=expires_at,
            admission_version=OWNER_CONTRIBUTION_ADMISSION_VERSION,
        )


class _PostInitValue(Protocol):
    def __post_init__(self) -> None: ...


_ConstructedT = TypeVar("_ConstructedT", bound=_PostInitValue)


def _owner_construct(
    value_type: type[_ConstructedT],
    **values: object,
) -> _ConstructedT:
    value = object.__new__(value_type)
    for name, item in values.items():
        object.__setattr__(value, name, item)
    value.__post_init__()
    return value


def _digest_document(domain: str, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(domain.encode("ascii") + b"\0" + payload).hexdigest()


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be lowercase SHA-256 hex")


def _require_positive_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _require_interval(issued_at: object, expires_at: object, *, name: str) -> None:
    issued = _require_nonnegative_integer(issued_at, name=f"{name} issue time")
    expires = _require_nonnegative_integer(expires_at, name=f"{name} expiry time")
    if expires <= issued:
        raise ValueError(f"{name} expiry must be after issue time")


def _require_exact_version(value: object, *, supported: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} version must be an integer")
    if value != supported:
        raise ValueError(f"Unsupported {name} version")


def _normalized_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(_require_nonempty(item, name=name) for item in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} values must be unique")
    return normalized


def _raise_admission(code: str, message: str) -> Never:
    raise OwnerContributionAdmissionError(message, code=code)


__all__ = [
    "CatalogConsumerContributionSpec",
    "OwnerContributionAdmissionError",
    "OwnerContributionAdmissionRecord",
    "OwnerContributionAuthority",
    "OwnerContributionCandidateEnvelope",
    "OwnerContributionKind",
    "OwnerContributionPolicy",
    "OwnerContributionSpec",
    "ResourceContributionSpec",
]
