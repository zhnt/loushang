"""Capability-owner admission records for inert complete-Bundle Providers.

This module does not import a Provider factory, construct a live value, select a
Product graph, or publish a Capability. It holds only the inert facts consumed
by one owner-controlled eligibility and admission path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal, Never, Protocol, TypeVar

from loushang.harness.capabilities.contracts import CapabilityDefinition
from loushang.harness.capabilities.providers import (
    CapabilityBundleProvider,
    _capability_bundle_provider_to_dict,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    _freeze_json_mapping,
    _thaw_json,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_python_path,
    canonical_plugin_symbol,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

CAPABILITY_PROVIDER_ADMISSION_VERSION = 1
CAPABILITY_PROVIDER_BINDING_SPEC_VERSION = 1
CAPABILITY_PROVIDER_CANDIDATE_FINGERPRINT_VERSION = 1
CAPABILITY_PROVIDER_CANDIDATE_VERSION = 1
CAPABILITY_PROVIDER_ELIGIBILITY_VERSION = 1
CAPABILITY_PROVIDER_OWNER_SNAPSHOT_VERSION = 1
CAPABILITY_PROVIDER_SYMBOL_LOCATOR_VERSION = 1


class CapabilityProviderAdmissionError(RuntimeError):
    """Stable fail-closed diagnostic from candidate preparation/admission."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CapabilityProviderSymbolLocator:
    """Normalized data-only locator projected from a declaration reference."""

    path: str
    symbol: str
    execution_model: Literal["in_process"]
    locator_version: int = CAPABILITY_PROVIDER_SYMBOL_LOCATOR_VERSION

    def __post_init__(self) -> None:
        path = canonical_plugin_python_path(self.path)
        symbol = canonical_plugin_symbol(self.symbol)
        if self.execution_model != "in_process":
            raise ValueError("Unsupported Provider symbol execution model")
        _require_exact_version(
            self.locator_version,
            supported=CAPABILITY_PROVIDER_SYMBOL_LOCATOR_VERSION,
            name="Capability Provider symbol locator",
        )
        object.__setattr__(self, "path", path.as_posix())
        object.__setattr__(self, "symbol", symbol)

    def to_dict(self) -> dict[str, object]:
        return {
            "executionModel": self.execution_model,
            "locatorVersion": self.locator_version,
            "path": self.path,
            "symbol": self.symbol,
        }


@dataclass(frozen=True, slots=True)
class CapabilityProviderBindingSpec:
    """Verified package-local locators and inert inputs for a future Host."""

    plugin_id: str
    contribution_id: str
    package_content_digest: str
    dependency_lock_digest: str
    factory: CapabilityProviderSymbolLocator
    disposer: CapabilityProviderSymbolLocator | None
    binding_inputs: Mapping[str, object] = field(default_factory=dict)
    binding_spec_version: int = CAPABILITY_PROVIDER_BINDING_SPEC_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Plugin id")
        _require_nonempty(self.contribution_id, name="contribution id")
        _require_sha256(
            self.package_content_digest,
            name="package content digest",
        )
        _require_sha256(
            self.dependency_lock_digest,
            name="dependency lock digest",
        )
        if not isinstance(self.factory, CapabilityProviderSymbolLocator):
            raise TypeError("Capability Provider binding requires a factory reference")
        if self.disposer is not None and not isinstance(
            self.disposer, CapabilityProviderSymbolLocator
        ):
            raise TypeError(
                "Capability Provider binding disposer must be a symbol reference"
            )
        if self.disposer is not None and (
            self.disposer.execution_model != self.factory.execution_model
        ):
            raise ValueError(
                "Capability Provider binding references must share an execution model"
            )
        try:
            binding_inputs = _freeze_json_mapping(self.binding_inputs)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Capability Provider binding inputs must be strict JSON data"
            ) from exc
        _require_exact_version(
            self.binding_spec_version,
            supported=CAPABILITY_PROVIDER_BINDING_SPEC_VERSION,
            name="Capability Provider binding spec",
        )
        object.__setattr__(self, "binding_inputs", binding_inputs)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-provider-binding-spec/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingInputs": _thaw_json(self.binding_inputs),
            "bindingSpecVersion": self.binding_spec_version,
            "contributionId": self.contribution_id,
            "dependencyLockDigest": self.dependency_lock_digest,
            "disposer": None if self.disposer is None else self.disposer.to_dict(),
            "factory": self.factory.to_dict(),
            "packageContentDigest": self.package_content_digest,
            "pluginId": self.plugin_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilityProviderCandidateFingerprint:
    """Canonical adjacent identity for a normalized complete-Bundle candidate."""

    digest: str
    fingerprint_version: int = CAPABILITY_PROVIDER_CANDIDATE_FINGERPRINT_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.digest, name="Capability Provider candidate fingerprint")
        _require_exact_version(
            self.fingerprint_version,
            supported=CAPABILITY_PROVIDER_CANDIDATE_FINGERPRINT_VERSION,
            name="Capability Provider candidate fingerprint",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "fingerprintVersion": self.fingerprint_version,
        }


@dataclass(frozen=True, slots=True)
class CapabilityProviderCandidateEnvelope:
    """Untrusted inert candidate whose complete facts receive owner review."""

    definition: CapabilityDefinition
    provider: CapabilityBundleProvider
    binding_spec: CapabilityProviderBindingSpec
    plugin_candidate_fingerprint: str
    declaration_fingerprint: str
    declaration_evidence_fingerprint: str
    product_id: str
    scope_id: str
    product_policy_revision: str
    instance_revision_ref: PluginInstanceRevisionRef
    package_source_identity: str
    source_trust_class: str
    source_trust_policy_revision: str
    source_trusted: bool
    allowed_authority_ceiling: tuple[str, ...]
    candidate_version: int = CAPABILITY_PROVIDER_CANDIDATE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.definition, CapabilityDefinition):
            raise TypeError("Capability Provider candidate requires a Definition")
        if not isinstance(self.provider, CapabilityBundleProvider):
            raise TypeError("Capability Provider candidate requires Provider metadata")
        if not isinstance(self.binding_spec, CapabilityProviderBindingSpec):
            raise TypeError("Capability Provider candidate requires a binding spec")
        if self.provider.capability_id != self.definition.capability_id:
            raise ValueError(
                "Capability Provider candidate metadata must target its Definition"
            )
        for name, value in (
            ("Plugin candidate fingerprint", self.plugin_candidate_fingerprint),
            ("Plugin declaration fingerprint", self.declaration_fingerprint),
            (
                "Plugin declaration evidence fingerprint",
                self.declaration_evidence_fingerprint,
            ),
        ):
            _require_sha256(value, name=name)
        for name, value in (
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("Product policy revision", self.product_policy_revision),
            ("package source identity", self.package_source_identity),
            ("source trust class", self.source_trust_class),
            ("source trust policy revision", self.source_trust_policy_revision),
        ):
            _require_nonempty(value, name=name)
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Capability Provider candidate requires an instance ref")
        if self.instance_revision_ref.plugin_id != self.binding_spec.plugin_id:
            raise ValueError(
                "Capability Provider candidate instance must match its binding Plugin"
            )
        if self.provider.source_id != f"plugin:{self.binding_spec.plugin_id}":
            raise ValueError(
                "Capability Provider candidate source must match its binding Plugin"
            )
        if not isinstance(self.source_trusted, bool):
            raise TypeError("Capability Provider source trust decision must be a bool")
        ceiling = _normalized_names(
            self.allowed_authority_ceiling,
            name="allowed authority ceiling",
        )
        if not self.provider.required_authorities.issubset(ceiling):
            raise ValueError(
                "Capability Provider candidate exceeds the Product authority ceiling"
            )
        _require_exact_version(
            self.candidate_version,
            supported=CAPABILITY_PROVIDER_CANDIDATE_VERSION,
            name="Capability Provider candidate",
        )
        object.__setattr__(self, "allowed_authority_ceiling", ceiling)

    @property
    def fingerprint(self) -> CapabilityProviderCandidateFingerprint:
        return CapabilityProviderCandidateFingerprint(
            digest=_digest_document(
                "loushang.capability-provider-candidate/v1",
                self._fingerprint_document(),
            )
        )

    def _fingerprint_document(self) -> dict[str, object]:
        return {
            "allowedAuthorityCeiling": list(self.allowed_authority_ceiling),
            "bindingSpec": self.binding_spec.to_dict(),
            "candidateVersion": self.candidate_version,
            "declarationEvidenceFingerprint": (
                self.declaration_evidence_fingerprint
            ),
            "declarationFingerprint": self.declaration_fingerprint,
            "definition": _capability_definition_to_dict(self.definition),
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "packageSourceIdentity": self.package_source_identity,
            "pluginCandidateFingerprint": self.plugin_candidate_fingerprint,
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "provider": _capability_bundle_provider_to_dict(self.provider),
            "scopeId": self.scope_id,
            "sourceTrustClass": self.source_trust_class,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "sourceTrusted": self.source_trusted,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._fingerprint_document(),
            "fingerprint": self.fingerprint.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CapabilityProviderOwnerPolicy:
    """Immutable explicit allowlist for exactly one Capability owner seam."""

    capability_id: str
    owner_id: str
    policy_revision: str
    revocation_epoch: int
    allowed_provider_ids: tuple[str, ...]
    allowed_source_trust_classes: tuple[str, ...]
    authority_ceiling: tuple[str, ...]

    def __post_init__(self) -> None:
        capability_id = _require_nonempty(
            self.capability_id,
            name="Capability id",
        )
        owner_id = _require_nonempty(self.owner_id, name="Capability owner id")
        if not capability_id.startswith(f"{owner_id}."):
            raise ValueError("Capability owner policy does not own its Capability")
        _require_nonempty(self.policy_revision, name="owner policy revision")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        providers = _normalized_names(
            self.allowed_provider_ids,
            name="allowed Provider ids",
        )
        if not providers:
            raise ValueError("Capability owner policy must allow at least one Provider")
        trust_classes = _normalized_names(
            self.allowed_source_trust_classes,
            name="allowed source trust classes",
        )
        if not trust_classes:
            raise ValueError(
                "Capability owner policy must allow at least one source trust class"
            )
        authority_ceiling = _normalized_names(
            self.authority_ceiling,
            name="owner authority ceiling",
        )
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "allowed_provider_ids", providers)
        object.__setattr__(
            self,
            "allowed_source_trust_classes",
            trust_classes,
        )
        object.__setattr__(self, "authority_ceiling", authority_ceiling)


@dataclass(frozen=True, slots=True, init=False)
class CapabilityProviderOwnerSnapshot:
    capability_id: str
    owner_id: str
    policy_revision: str
    revocation_epoch: int
    snapshot_version: int

    def __init__(self) -> None:
        raise TypeError("Capability Provider owner snapshot is owner-constructed")

    def __post_init__(self) -> None:
        _require_nonempty(self.capability_id, name="Capability id")
        _require_nonempty(self.owner_id, name="Capability owner id")
        _require_nonempty(self.policy_revision, name="owner policy revision")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        _require_exact_version(
            self.snapshot_version,
            supported=CAPABILITY_PROVIDER_OWNER_SNAPSHOT_VERSION,
            name="Capability Provider owner snapshot",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "ownerId": self.owner_id,
            "policyRevision": self.policy_revision,
            "revocationEpoch": self.revocation_epoch,
            "snapshotVersion": self.snapshot_version,
        }


@dataclass(frozen=True, slots=True, init=False)
class CapabilityProviderEligibilityGrant:
    capability_id: str
    owner_id: str
    candidate_fingerprint: str
    owner_policy_revision: str
    revocation_epoch: int
    allowed_facets: tuple[str, ...]
    allowed_authorities: tuple[str, ...]
    source_trust_policy_revision: str
    issued_at: int
    expires_at: int
    eligibility_version: int

    def __init__(self) -> None:
        raise TypeError("Capability Provider eligibility is owner-constructed")

    def __post_init__(self) -> None:
        for name, value in (
            ("Capability id", self.capability_id),
            ("Capability owner id", self.owner_id),
            ("owner policy revision", self.owner_policy_revision),
            ("source trust policy revision", self.source_trust_policy_revision),
        ):
            _require_nonempty(value, name=name)
        _require_sha256(
            self.candidate_fingerprint,
            name="Capability Provider candidate fingerprint",
        )
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        _normalized_names(self.allowed_facets, name="eligible Provider facets")
        _normalized_names(
            self.allowed_authorities,
            name="eligible Provider authorities",
        )
        _require_interval(self.issued_at, self.expires_at, name="eligibility")
        _require_exact_version(
            self.eligibility_version,
            supported=CAPABILITY_PROVIDER_ELIGIBILITY_VERSION,
            name="Capability Provider eligibility",
        )

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-provider-eligibility/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "allowedAuthorities": list(self.allowed_authorities),
            "allowedFacets": list(self.allowed_facets),
            "candidateFingerprint": self.candidate_fingerprint,
            "capabilityId": self.capability_id,
            "eligibilityVersion": self.eligibility_version,
            "expiresAt": self.expires_at,
            "issuedAt": self.issued_at,
            "ownerId": self.owner_id,
            "ownerPolicyRevision": self.owner_policy_revision,
            "revocationEpoch": self.revocation_epoch,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
        }


@dataclass(frozen=True, slots=True, init=False)
class CapabilityProviderAdmissionRecord:
    candidate: CapabilityProviderCandidateEnvelope = field(repr=False)
    eligibility_fingerprint: str
    owner_policy_revision: str
    revocation_epoch: int
    effective_facets: tuple[str, ...]
    effective_authorities: tuple[str, ...]
    issued_at: int
    expires_at: int
    admission_version: int

    def __init__(self) -> None:
        raise TypeError("Capability Provider admission is owner-constructed")

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CapabilityProviderCandidateEnvelope):
            raise TypeError("Capability Provider admission requires a candidate")
        _require_sha256(
            self.eligibility_fingerprint,
            name="eligibility fingerprint",
        )
        _require_nonempty(self.owner_policy_revision, name="owner policy revision")
        _require_nonnegative_integer(
            self.revocation_epoch,
            name="owner revocation epoch",
        )
        facets = _normalized_names(
            self.effective_facets,
            name="effective Provider facets",
        )
        authorities = _normalized_names(
            self.effective_authorities,
            name="effective Provider authorities",
        )
        if facets != tuple(sorted(self.candidate.provider.facets)):
            raise ValueError("Admission facets do not match Provider metadata")
        if authorities != tuple(
            sorted(self.candidate.provider.required_authorities)
        ):
            raise ValueError("Admission authorities do not match Provider metadata")
        _require_interval(self.issued_at, self.expires_at, name="admission")
        _require_exact_version(
            self.admission_version,
            supported=CAPABILITY_PROVIDER_ADMISSION_VERSION,
            name="Capability Provider admission",
        )
        object.__setattr__(self, "effective_facets", facets)
        object.__setattr__(self, "effective_authorities", authorities)

    @property
    def capability_id(self) -> str:
        return self.candidate.provider.capability_id

    @property
    def owner_id(self) -> str:
        return self.candidate.definition.owner_id

    @property
    def provider(self) -> CapabilityBundleProvider:
        return self.candidate.provider

    @property
    def binding_spec(self) -> CapabilityProviderBindingSpec:
        return self.candidate.binding_spec

    @property
    def candidate_fingerprint(self) -> str:
        return self.candidate.fingerprint.digest

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-provider-admission/v1",
            self._record_document(),
        )

    def _record_document(self) -> dict[str, object]:
        return {
            "admissionVersion": self.admission_version,
            "candidate": self.candidate.to_dict(),
            "effectiveAuthorities": list(self.effective_authorities),
            "effectiveFacets": list(self.effective_facets),
            "eligibilityFingerprint": self.eligibility_fingerprint,
            "expiresAt": self.expires_at,
            "issuedAt": self.issued_at,
            "ownerPolicyRevision": self.owner_policy_revision,
            "revocationEpoch": self.revocation_epoch,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._record_document(), "fingerprint": self.fingerprint}


class CapabilityProviderOwnerAuthority:
    """One immutable exact-owner issuer; it is not a global owner registry."""

    def __init__(self, policy: CapabilityProviderOwnerPolicy) -> None:
        if not isinstance(policy, CapabilityProviderOwnerPolicy):
            raise TypeError("Capability Provider owner requires an exact policy")
        self._policy = policy

    @property
    def policy(self) -> CapabilityProviderOwnerPolicy:
        return self._policy

    def snapshot(self) -> CapabilityProviderOwnerSnapshot:
        return _owner_construct(
            CapabilityProviderOwnerSnapshot,
            capability_id=self._policy.capability_id,
            owner_id=self._policy.owner_id,
            policy_revision=self._policy.policy_revision,
            revocation_epoch=self._policy.revocation_epoch,
            snapshot_version=CAPABILITY_PROVIDER_OWNER_SNAPSHOT_VERSION,
        )

    def grant_eligibility(
        self,
        candidate: CapabilityProviderCandidateEnvelope,
        *,
        issued_at: int,
        expires_at: int,
    ) -> CapabilityProviderEligibilityGrant:
        if not isinstance(candidate, CapabilityProviderCandidateEnvelope):
            raise TypeError("Capability Provider owner requires a candidate")
        _require_interval(issued_at, expires_at, name="eligibility")
        self._validate_candidate(candidate)
        return _owner_construct(
            CapabilityProviderEligibilityGrant,
            capability_id=candidate.provider.capability_id,
            owner_id=candidate.definition.owner_id,
            candidate_fingerprint=candidate.fingerprint.digest,
            owner_policy_revision=self._policy.policy_revision,
            revocation_epoch=self._policy.revocation_epoch,
            allowed_facets=tuple(sorted(candidate.provider.facets)),
            allowed_authorities=tuple(
                sorted(candidate.provider.required_authorities)
            ),
            source_trust_policy_revision=(
                candidate.source_trust_policy_revision
            ),
            issued_at=issued_at,
            expires_at=expires_at,
            eligibility_version=CAPABILITY_PROVIDER_ELIGIBILITY_VERSION,
        )

    def admit(
        self,
        candidate: CapabilityProviderCandidateEnvelope,
        *,
        eligibility: CapabilityProviderEligibilityGrant,
        issued_at: int,
        expires_at: int,
    ) -> CapabilityProviderAdmissionRecord:
        if not isinstance(candidate, CapabilityProviderCandidateEnvelope):
            raise TypeError("Capability Provider owner requires a candidate")
        if not isinstance(eligibility, CapabilityProviderEligibilityGrant):
            raise TypeError("Capability Provider owner requires eligibility")
        _require_interval(issued_at, expires_at, name="admission")
        self._validate_candidate(candidate)
        policy = self._policy
        if (
            eligibility.owner_policy_revision != policy.policy_revision
            or eligibility.revocation_epoch != policy.revocation_epoch
        ):
            _raise_admission(
                "provider_owner_policy_stale",
                "Capability Provider eligibility does not match current owner policy.",
            )
        if (
            eligibility.capability_id != candidate.provider.capability_id
            or eligibility.owner_id != candidate.definition.owner_id
            or eligibility.candidate_fingerprint != candidate.fingerprint.digest
            or eligibility.source_trust_policy_revision
            != candidate.source_trust_policy_revision
        ):
            _raise_admission(
                "provider_eligibility_mismatch",
                "Capability Provider eligibility does not match the candidate.",
            )
        if issued_at >= eligibility.expires_at:
            _raise_admission(
                "provider_eligibility_expired",
                "Capability Provider eligibility has expired.",
            )
        if issued_at < eligibility.issued_at or expires_at > eligibility.expires_at:
            _raise_admission(
                "provider_admission_exceeds_eligibility",
                "Capability Provider admission exceeds its eligibility interval.",
            )
        provider_facets = set(candidate.provider.facets)
        provider_authorities = set(candidate.provider.required_authorities)
        if not provider_facets.issubset(eligibility.allowed_facets) or not (
            provider_authorities.issubset(eligibility.allowed_authorities)
        ):
            _raise_admission(
                "provider_admission_widens_eligibility",
                "Capability Provider admission would widen owner eligibility.",
            )
        return _owner_construct(
            CapabilityProviderAdmissionRecord,
            candidate=candidate,
            eligibility_fingerprint=eligibility.fingerprint,
            owner_policy_revision=policy.policy_revision,
            revocation_epoch=policy.revocation_epoch,
            effective_facets=tuple(sorted(candidate.provider.facets)),
            effective_authorities=tuple(
                sorted(candidate.provider.required_authorities)
            ),
            issued_at=issued_at,
            expires_at=expires_at,
            admission_version=CAPABILITY_PROVIDER_ADMISSION_VERSION,
        )

    def _validate_candidate(
        self,
        candidate: CapabilityProviderCandidateEnvelope,
    ) -> None:
        policy = self._policy
        definition = candidate.definition
        provider = candidate.provider
        if (
            definition.capability_id != policy.capability_id
            or definition.owner_id != policy.owner_id
        ):
            _raise_admission(
                "provider_owner_mismatch",
                "Capability Provider candidate targets a different owner.",
            )
        if provider.provider_id not in policy.allowed_provider_ids:
            _raise_admission(
                "provider_not_allowed_by_owner",
                "Capability Provider is not present in the owner allowlist.",
            )
        if (
            not candidate.source_trusted
            or candidate.source_trust_class
            not in policy.allowed_source_trust_classes
        ):
            _raise_admission(
                "provider_source_not_eligible",
                "Capability Provider source trust is not owner-eligible.",
            )
        if not provider.compatible_contract.accepts(definition.contract_version):
            _raise_admission(
                "provider_contract_incompatible",
                "Capability Provider does not accept the owner contract.",
            )
        if not set(provider.facets).issubset(definition.facets):
            _raise_admission(
                "provider_facets_exceed_definition",
                "Capability Provider facets exceed its Definition.",
            )
        authorities = set(provider.required_authorities)
        if not authorities.issubset(definition.authority_ceiling) or not (
            authorities.issubset(policy.authority_ceiling)
        ):
            _raise_admission(
                "provider_authorities_exceed_owner_ceiling",
                "Capability Provider authorities exceed owner ceilings.",
            )


def _capability_definition_to_dict(
    definition: CapabilityDefinition,
) -> dict[str, object]:
    return {
        "authorityCeiling": sorted(definition.authority_ceiling),
        "capabilityId": definition.capability_id,
        "contractVersion": definition.contract_version,
        "facets": list(definition.facets),
        "ownerId": definition.owner_id,
        "phase": definition.phase,
        "refreshBoundary": definition.refresh_boundary,
        "scope": definition.scope,
    }


class _PostInitValue(Protocol):
    def __post_init__(self) -> None: ...


_PostInitT = TypeVar("_PostInitT", bound=_PostInitValue)


def _owner_construct(
    cls: type[_PostInitT],
    **values: object,
) -> _PostInitT:
    value = object.__new__(cls)
    for name, item in values.items():
        object.__setattr__(value, name, item)
    value.__post_init__()
    return value


def _digest_document(domain: str, value: object) -> str:
    encoded = StrictPluginJsonCodec.encode({"domain": domain, "value": value})
    return sha256(encoded).hexdigest()


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
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_interval(issued_at: object, expires_at: object, *, name: str) -> None:
    issued = _require_nonnegative_integer(issued_at, name=f"{name} issued time")
    expires = _require_nonnegative_integer(expires_at, name=f"{name} expiry time")
    if expires <= issued:
        raise ValueError(f"{name} expiry must be after its issued time")


def _require_exact_version(value: object, *, supported: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} version must be an integer")
    if value != supported:
        raise ValueError(f"Unsupported {name} version")


def _normalized_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_require_nonempty(item, name=name) for item in values))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


def _raise_admission(code: str, message: str) -> Never:
    raise CapabilityProviderAdmissionError(message, code=code)


__all__ = [
    "CAPABILITY_PROVIDER_ADMISSION_VERSION",
    "CAPABILITY_PROVIDER_BINDING_SPEC_VERSION",
    "CAPABILITY_PROVIDER_CANDIDATE_FINGERPRINT_VERSION",
    "CAPABILITY_PROVIDER_CANDIDATE_VERSION",
    "CAPABILITY_PROVIDER_ELIGIBILITY_VERSION",
    "CAPABILITY_PROVIDER_OWNER_SNAPSHOT_VERSION",
    "CAPABILITY_PROVIDER_SYMBOL_LOCATOR_VERSION",
    "CapabilityProviderAdmissionError",
    "CapabilityProviderAdmissionRecord",
    "CapabilityProviderBindingSpec",
    "CapabilityProviderCandidateEnvelope",
    "CapabilityProviderCandidateFingerprint",
    "CapabilityProviderEligibilityGrant",
    "CapabilityProviderOwnerAuthority",
    "CapabilityProviderOwnerPolicy",
    "CapabilityProviderOwnerSnapshot",
    "CapabilityProviderSymbolLocator",
]
