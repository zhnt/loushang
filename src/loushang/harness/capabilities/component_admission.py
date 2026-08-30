"""Exact-owner admission for inert Capability component candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Never, Protocol, TypeVar

from loushang.harness.capabilities.component_contracts import (
    CapabilityComponentBindingSpec,
    CapabilityComponentDefinition,
    _digest_document,
    _normalized_names,
    _require_exact_version,
    _require_nonempty,
    _require_nonnegative_integer,
    _require_sha256,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

CAPABILITY_COMPONENT_CANDIDATE_VERSION = 1
CAPABILITY_COMPONENT_CANDIDATE_VERSION_V2 = 2
CAPABILITY_COMPONENT_ADMISSION_VERSION = 1
CAPABILITY_COMPONENT_OWNER_SNAPSHOT_VERSION = 1


class CapabilityComponentAdmissionError(RuntimeError):
    """Stable fail-closed component admission diagnostic."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CapabilityComponentCandidate:
    """Complete inert component facts presented to one Capability owner."""

    definition: CapabilityComponentDefinition
    component_id: str
    binding_spec: CapabilityComponentBindingSpec
    product_id: str
    scope_id: str
    product_policy_revision: str
    source_trust_class: str
    source_trust_policy_revision: str
    source_trusted: bool
    package_source_identity: str | None = None
    instance_revision_ref: PluginInstanceRevisionRef | None = None
    plugin_candidate_fingerprint: str | None = None
    declaration_fingerprint: str | None = None
    declaration_evidence_fingerprint: str | None = None
    allowed_authority_ceiling: tuple[str, ...] = ()
    requested_authorities: tuple[str, ...] = ()
    candidate_version: int = CAPABILITY_COMPONENT_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.definition, CapabilityComponentDefinition):
            raise TypeError("Component candidate requires a Definition")
        if not isinstance(self.binding_spec, CapabilityComponentBindingSpec):
            raise TypeError("Component candidate requires a binding spec")
        for name, value in (
            ("component id", self.component_id),
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("Product policy revision", self.product_policy_revision),
            ("source trust class", self.source_trust_class),
            ("source trust policy revision", self.source_trust_policy_revision),
        ):
            _require_nonempty(value, name=name)
        if not isinstance(self.source_trusted, bool):
            raise TypeError("Component source trust decision must be a bool")
        if self.candidate_version not in {
            CAPABILITY_COMPONENT_CANDIDATE_VERSION,
            CAPABILITY_COMPONENT_CANDIDATE_VERSION_V2,
        }:
            raise ValueError("Unsupported Capability Component candidate version")
        if self.binding_spec.source_kind == "plugin":
            _require_nonempty(
                self.package_source_identity,
                name="component package source identity",
            )
            if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
                raise TypeError("Plugin component requires an instance revision ref")
            if self.instance_revision_ref.plugin_id != self.binding_spec.plugin_id:
                raise ValueError(
                    "Component instance revision must match its binding Plugin"
                )
            if self.candidate_version == CAPABILITY_COMPONENT_CANDIDATE_VERSION_V2:
                for fingerprint_name, fingerprint_value in (
                    (
                        "Plugin candidate fingerprint",
                        self.plugin_candidate_fingerprint,
                    ),
                    (
                        "Plugin declaration fingerprint",
                        self.declaration_fingerprint,
                    ),
                    (
                        "Plugin declaration evidence fingerprint",
                        self.declaration_evidence_fingerprint,
                    ),
                ):
                    _require_sha256(fingerprint_value, name=fingerprint_name)
            elif (
                self.plugin_candidate_fingerprint is not None
                or self.declaration_fingerprint is not None
                or self.declaration_evidence_fingerprint is not None
                or self.allowed_authority_ceiling
            ):
                raise ValueError(
                    "Capability Component candidate v1 cannot carry v2 provenance"
                )
        elif (
            self.package_source_identity is not None
            or self.instance_revision_ref is not None
            or self.plugin_candidate_fingerprint is not None
            or self.declaration_fingerprint is not None
            or self.declaration_evidence_fingerprint is not None
        ):
            raise ValueError(
                "First-party component must not carry Plugin instance provenance"
            )
        ceiling = _normalized_names(
            self.allowed_authority_ceiling,
            name="component allowed authority ceiling",
        )
        authorities = _normalized_names(
            self.requested_authorities,
            name="component requested authority",
        )
        if self.candidate_version == CAPABILITY_COMPONENT_CANDIDATE_VERSION_V2 and (
            self.binding_spec.source_kind != "plugin"
            or not set(authorities).issubset(ceiling)
        ):
            raise ValueError(
                "Component requested authorities exceed the Product ceiling"
            )
        object.__setattr__(self, "allowed_authority_ceiling", ceiling)
        object.__setattr__(self, "requested_authorities", authorities)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            f"loushang.capability-component-candidate/v{self.candidate_version}",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        document: dict[str, object] = {
            "bindingSpec": self.binding_spec.to_dict(),
            "candidateVersion": self.candidate_version,
            "componentId": self.component_id,
            "definition": self.definition.to_dict(),
            "instanceRevisionRef": (
                None
                if self.instance_revision_ref is None
                else self.instance_revision_ref.to_dict()
            ),
            "packageSourceIdentity": self.package_source_identity,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "requestedAuthorities": list(self.requested_authorities),
            "scopeId": self.scope_id,
            "sourceTrustClass": self.source_trust_class,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "sourceTrusted": self.source_trusted,
        }
        if self.candidate_version == CAPABILITY_COMPONENT_CANDIDATE_VERSION_V2:
            document.update(
                {
                    "allowedAuthorityCeiling": list(
                        self.allowed_authority_ceiling
                    ),
                    "declarationEvidenceFingerprint": (
                        self.declaration_evidence_fingerprint
                    ),
                    "declarationFingerprint": self.declaration_fingerprint,
                    "pluginCandidateFingerprint": (
                        self.plugin_candidate_fingerprint
                    ),
                }
            )
        return document


@dataclass(frozen=True, slots=True)
class CapabilityComponentOwnerPolicy:
    """Immutable allowlist for exactly one owner/component-kind seam."""

    capability_id: str
    owner_id: str
    component_kind: str
    policy_revision: str
    revocation_epoch: int
    allowed_component_ids: tuple[str, ...]
    allowed_source_trust_classes: tuple[str, ...]
    authority_ceiling: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        capability_id = _require_nonempty(self.capability_id, name="Capability id")
        owner_id = _require_nonempty(self.owner_id, name="Capability owner id")
        if not capability_id.startswith(f"{owner_id}."):
            raise ValueError("Component owner policy does not own its Capability")
        _require_nonempty(self.component_kind, name="component kind")
        _require_nonempty(self.policy_revision, name="owner policy revision")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        component_ids = _normalized_names(
            self.allowed_component_ids,
            name="allowed component id",
        )
        trust_classes = _normalized_names(
            self.allowed_source_trust_classes,
            name="allowed source trust class",
        )
        if not component_ids:
            raise ValueError("Component owner policy must allow at least one component")
        if not trust_classes:
            raise ValueError("Component owner policy must allow a source trust class")
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "allowed_component_ids", component_ids)
        object.__setattr__(self, "allowed_source_trust_classes", trust_classes)
        object.__setattr__(
            self,
            "authority_ceiling",
            _normalized_names(
                self.authority_ceiling,
                name="component authority ceiling",
            ),
        )


@dataclass(frozen=True, slots=True, init=False)
class CapabilityComponentOwnerSnapshot:
    capability_id: str
    owner_id: str
    component_kind: str
    definition_fingerprint: str
    policy_revision: str
    revocation_epoch: int
    snapshot_version: int

    def __init__(self) -> None:
        raise TypeError("Component owner snapshot is owner-constructed")

    def __post_init__(self) -> None:
        for name, value in (
            ("Capability id", self.capability_id),
            ("Capability owner id", self.owner_id),
            ("component kind", self.component_kind),
            ("owner policy revision", self.policy_revision),
        ):
            _require_nonempty(value, name=name)
        _require_sha256(
            self.definition_fingerprint,
            name="component Definition fingerprint",
        )
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        _require_exact_version(
            self.snapshot_version,
            supported=CAPABILITY_COMPONENT_OWNER_SNAPSHOT_VERSION,
            name="Capability Component owner snapshot",
        )

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-component-owner-snapshot/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "componentKind": self.component_kind,
            "definitionFingerprint": self.definition_fingerprint,
            "ownerId": self.owner_id,
            "policyRevision": self.policy_revision,
            "revocationEpoch": self.revocation_epoch,
            "snapshotVersion": self.snapshot_version,
        }


@dataclass(frozen=True, slots=True, init=False)
class CapabilityComponentAdmission:
    candidate: CapabilityComponentCandidate = field(repr=False)
    owner_snapshot_fingerprint: str
    owner_policy_revision: str
    revocation_epoch: int
    effective_authorities: tuple[str, ...]
    issued_at: int
    expires_at: int
    admission_version: int

    def __init__(self) -> None:
        raise TypeError("Component admission is owner-constructed")

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CapabilityComponentCandidate):
            raise TypeError("Component admission requires a candidate")
        _require_sha256(
            self.owner_snapshot_fingerprint,
            name="component owner snapshot fingerprint",
        )
        _require_nonempty(self.owner_policy_revision, name="owner policy revision")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        authorities = _normalized_names(
            self.effective_authorities,
            name="effective component authority",
        )
        if authorities != self.candidate.requested_authorities:
            raise ValueError("Admission authorities do not match the candidate")
        _require_interval(self.issued_at, self.expires_at, name="component admission")
        _require_exact_version(
            self.admission_version,
            supported=CAPABILITY_COMPONENT_ADMISSION_VERSION,
            name="Capability Component admission",
        )
        object.__setattr__(self, "effective_authorities", authorities)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-component-admission/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionVersion": self.admission_version,
            "candidate": self.candidate.to_dict(),
            "effectiveAuthorities": list(self.effective_authorities),
            "expiresAt": self.expires_at,
            "issuedAt": self.issued_at,
            "ownerPolicyRevision": self.owner_policy_revision,
            "ownerSnapshotFingerprint": self.owner_snapshot_fingerprint,
            "revocationEpoch": self.revocation_epoch,
        }


class CapabilityComponentOwnerAuthority:
    """Exact owner issuer; deliberately not a global owner registry."""

    def __init__(
        self,
        definition: CapabilityComponentDefinition,
        policy: CapabilityComponentOwnerPolicy,
    ) -> None:
        if not isinstance(definition, CapabilityComponentDefinition):
            raise TypeError("Component owner requires one Definition")
        if not isinstance(policy, CapabilityComponentOwnerPolicy):
            raise TypeError("Component owner requires one exact policy")
        if (
            definition.capability_id != policy.capability_id
            or definition.owner_id != policy.owner_id
            or definition.component_kind != policy.component_kind
        ):
            raise ValueError("Component owner policy does not match its Definition")
        self._definition = definition
        self._policy = policy

    @property
    def definition(self) -> CapabilityComponentDefinition:
        return self._definition

    @property
    def policy(self) -> CapabilityComponentOwnerPolicy:
        return self._policy

    def snapshot(self) -> CapabilityComponentOwnerSnapshot:
        return _owner_construct(
            CapabilityComponentOwnerSnapshot,
            capability_id=self._definition.capability_id,
            owner_id=self._definition.owner_id,
            component_kind=self._definition.component_kind,
            definition_fingerprint=self._definition.fingerprint,
            policy_revision=self._policy.policy_revision,
            revocation_epoch=self._policy.revocation_epoch,
            snapshot_version=CAPABILITY_COMPONENT_OWNER_SNAPSHOT_VERSION,
        )

    def admit(
        self,
        candidate: CapabilityComponentCandidate,
        *,
        issued_at: int,
        expires_at: int,
    ) -> CapabilityComponentAdmission:
        if not isinstance(candidate, CapabilityComponentCandidate):
            raise TypeError("Component owner requires a candidate")
        _require_interval(issued_at, expires_at, name="component admission")
        self._validate_candidate(candidate)
        snapshot = self.snapshot()
        return _owner_construct(
            CapabilityComponentAdmission,
            candidate=candidate,
            owner_snapshot_fingerprint=snapshot.fingerprint,
            owner_policy_revision=self._policy.policy_revision,
            revocation_epoch=self._policy.revocation_epoch,
            effective_authorities=candidate.requested_authorities,
            issued_at=issued_at,
            expires_at=expires_at,
            admission_version=CAPABILITY_COMPONENT_ADMISSION_VERSION,
        )

    def _validate_candidate(self, candidate: CapabilityComponentCandidate) -> None:
        policy = self._policy
        if candidate.definition != self._definition:
            _raise_admission(
                "component_definition_mismatch",
                "Component candidate does not target the current owner Definition.",
            )
        if candidate.component_id not in policy.allowed_component_ids:
            _raise_admission(
                "component_not_allowed",
                "Component identity is not allowed by the owner policy.",
            )
        if not candidate.source_trusted:
            _raise_admission(
                "component_source_untrusted",
                "Component source is not trusted.",
            )
        if candidate.source_trust_class not in policy.allowed_source_trust_classes:
            _raise_admission(
                "component_source_class_not_allowed",
                "Component source trust class is not allowed by the owner.",
            )
        if not set(candidate.requested_authorities).issubset(policy.authority_ceiling):
            _raise_admission(
                "component_authority_ceiling_exceeded",
                "Component authorities exceed the owner ceiling.",
            )


class _PostInitValue(Protocol):
    def __post_init__(self) -> None: ...


_T = TypeVar("_T", bound=_PostInitValue)


def _owner_construct(record_type: type[_T], **values: object) -> _T:
    value = object.__new__(record_type)
    for name, item in values.items():
        object.__setattr__(value, name, item)
    value.__post_init__()
    return value


def _require_interval(start: object, end: object, *, name: str) -> None:
    start_value = _require_nonnegative_integer(start, name=f"{name} start")
    end_value = _require_nonnegative_integer(end, name=f"{name} end")
    if end_value <= start_value:
        raise ValueError(f"{name} end must be after its start")


def _raise_admission(code: str, message: str) -> Never:
    raise CapabilityComponentAdmissionError(message, code=code)


__all__ = [
    "CapabilityComponentAdmission",
    "CapabilityComponentAdmissionError",
    "CapabilityComponentCandidate",
    "CapabilityComponentOwnerAuthority",
    "CapabilityComponentOwnerPolicy",
    "CapabilityComponentOwnerSnapshot",
]
