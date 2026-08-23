"""Pure Product selection over already owner-admitted Capability Providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Never, Protocol, TypeVar

from loushang.harness.capabilities.contracts import CapabilityDefinition
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
    CapabilityProviderBindingSpec,
    CapabilityProviderOwnerSnapshot,
)
from loushang.harness.capabilities.providers import (
    CapabilityBundleProvider,
    _capability_bundle_provider_to_dict,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec

PRODUCT_CAPABILITY_PROVIDER_SELECTION_PLAN_VERSION = 1
RESOLVED_CAPABILITY_PROVIDER_SET_VERSION = 1


class ProviderSelectionError(RuntimeError):
    """Stable fail-closed Product Provider-selection diagnostic."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProductCapabilityProviderChoice:
    """One explicit Product rule selecting an exact admitted candidate."""

    capability_id: str
    provider_id: str
    candidate_fingerprint: str

    def __post_init__(self) -> None:
        _require_nonempty(self.capability_id, name="Capability id")
        _require_nonempty(self.provider_id, name="Provider id")
        _require_sha256(
            self.candidate_fingerprint,
            name="Capability Provider candidate fingerprint",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidateFingerprint": self.candidate_fingerprint,
            "capabilityId": self.capability_id,
            "providerId": self.provider_id,
        }


@dataclass(frozen=True, slots=True)
class ProductCapabilityProviderSelectionPlanV1:
    """Product-owned roots and exact choices; it grants no owner authority."""

    product_id: str
    roots: tuple[str, ...]
    choices: tuple[ProductCapabilityProviderChoice, ...]
    policy_revision: str
    plan_version: int = PRODUCT_CAPABILITY_PROVIDER_SELECTION_PLAN_VERSION

    def __post_init__(self) -> None:
        product_id = _require_nonempty(self.product_id, name="Product id")
        roots = _normalized_names(self.roots, name="Product Capability roots")
        if not roots:
            raise ValueError("Product Capability roots must not be empty")
        choices = tuple(self.choices)
        if any(not isinstance(item, ProductCapabilityProviderChoice) for item in choices):
            raise TypeError("Product Provider choices have invalid type")
        _require_nonempty(
            self.policy_revision,
            name="Product Provider-selection policy revision",
        )
        _require_exact_version(
            self.plan_version,
            supported=PRODUCT_CAPABILITY_PROVIDER_SELECTION_PLAN_VERSION,
            name="Product Capability Provider selection plan",
        )
        object.__setattr__(self, "product_id", product_id)
        object.__setattr__(self, "roots", roots)
        object.__setattr__(self, "choices", choices)

    def to_dict(self) -> dict[str, object]:
        return {
            "choices": [item.to_dict() for item in self.choices],
            "planVersion": self.plan_version,
            "policyRevision": self.policy_revision,
            "productId": self.product_id,
            "roots": list(self.roots),
        }


@dataclass(frozen=True, order=True, slots=True)
class CapabilityOptionalRequirementDecision:
    """Explicit Product decision for one selected Provider's optional edge."""

    requester_capability_id: str
    capability_id: str
    satisfied: bool
    selected_candidate_fingerprint: str | None

    def __post_init__(self) -> None:
        _require_nonempty(
            self.requester_capability_id,
            name="optional-requirement requester Capability id",
        )
        _require_nonempty(
            self.capability_id,
            name="optional-requirement Capability id",
        )
        if not isinstance(self.satisfied, bool):
            raise TypeError("Optional-requirement decision must be a bool")
        if self.satisfied:
            _require_sha256(
                self.selected_candidate_fingerprint,
                name="optional selected candidate fingerprint",
            )
        elif self.selected_candidate_fingerprint is not None:
            raise ValueError(
                "Unsatisfied optional requirement cannot name a candidate"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "requesterCapabilityId": self.requester_capability_id,
            "satisfied": self.satisfied,
            "selectedCandidateFingerprint": self.selected_candidate_fingerprint,
        }


@dataclass(frozen=True, slots=True, init=False)
class ResolvedCapabilityProvider:
    """One Product-selected exact metadata/spec/admission tuple."""

    definition: CapabilityDefinition
    provider: CapabilityBundleProvider
    binding_spec: CapabilityProviderBindingSpec
    admission: CapabilityProviderAdmissionRecord = field(repr=False)
    choice: ProductCapabilityProviderChoice

    def __init__(self) -> None:
        raise TypeError("Resolved Capability Provider is Resolver-constructed")

    def __post_init__(self) -> None:
        if not isinstance(self.definition, CapabilityDefinition):
            raise TypeError("Resolved Provider requires a Capability Definition")
        if not isinstance(self.provider, CapabilityBundleProvider):
            raise TypeError("Resolved Provider requires Provider metadata")
        if not isinstance(self.binding_spec, CapabilityProviderBindingSpec):
            raise TypeError("Resolved Provider requires a binding spec")
        if not isinstance(self.admission, CapabilityProviderAdmissionRecord):
            raise TypeError("Resolved Provider requires owner admission")
        if not isinstance(self.choice, ProductCapabilityProviderChoice):
            raise TypeError("Resolved Provider requires a Product choice")
        if (
            self.definition != self.admission.candidate.definition
            or self.provider != self.admission.provider
            or self.binding_spec != self.admission.binding_spec
            or self.choice.capability_id != self.provider.capability_id
            or self.choice.provider_id != self.provider.provider_id
            or self.choice.candidate_fingerprint
            != self.admission.candidate_fingerprint
        ):
            raise ValueError("Resolved Capability Provider facts do not exact-match")

    @property
    def capability_id(self) -> str:
        return self.provider.capability_id

    def to_dict(self) -> dict[str, object]:
        return {
            "admission": self.admission.to_dict(),
            "bindingSpec": self.binding_spec.to_dict(),
            "choice": self.choice.to_dict(),
            "definition": {
                "authorityCeiling": sorted(self.definition.authority_ceiling),
                "capabilityId": self.definition.capability_id,
                "contractVersion": self.definition.contract_version,
                "facets": list(self.definition.facets),
                "ownerId": self.definition.owner_id,
                "phase": self.definition.phase,
                "refreshBoundary": self.definition.refresh_boundary,
                "scope": self.definition.scope,
            },
            "provider": _capability_bundle_provider_to_dict(self.provider),
        }


@dataclass(frozen=True, slots=True, init=False)
class ResolvedCapabilityProviderSet:
    """Complete Product closure ready for the existing metadata-only Planner."""

    product_id: str
    roots: tuple[str, ...]
    product_policy_revision: str
    evaluated_at: int
    entries: tuple[ResolvedCapabilityProvider, ...]
    prebound_providers: tuple[CapabilityBundleProvider, ...]
    optional_decisions: tuple[CapabilityOptionalRequirementDecision, ...]
    set_version: int

    def __init__(self) -> None:
        raise TypeError("Resolved Capability Provider set is Resolver-constructed")

    def __post_init__(self) -> None:
        _require_nonempty(self.product_id, name="Product id")
        roots = _normalized_names(self.roots, name="Product Capability roots")
        if not roots:
            raise ValueError("Resolved Provider roots must not be empty")
        _require_nonempty(
            self.product_policy_revision,
            name="Product Provider-selection policy revision",
        )
        _require_nonnegative_integer(
            self.evaluated_at,
            name="Provider selection evaluation time",
        )
        entries = tuple(self.entries)
        if any(not isinstance(item, ResolvedCapabilityProvider) for item in entries):
            raise TypeError("Resolved Provider entries have invalid type")
        entry_ids = tuple(item.capability_id for item in entries)
        if entry_ids != tuple(sorted(entry_ids)) or len(entry_ids) != len(
            set(entry_ids)
        ):
            raise ValueError("Resolved Provider entries must be sorted and unique")
        prebound = tuple(self.prebound_providers)
        if any(not isinstance(item, CapabilityBundleProvider) for item in prebound):
            raise TypeError("Resolved prebound Providers have invalid type")
        prebound_ids = tuple(item.capability_id for item in prebound)
        if prebound_ids != tuple(sorted(prebound_ids)) or len(prebound_ids) != len(
            set(prebound_ids)
        ):
            raise ValueError("Resolved prebound Providers must be sorted and unique")
        if set(entry_ids).intersection(prebound_ids):
            raise ValueError("Resolved external and prebound Providers overlap")
        if not set(roots).issubset(set(entry_ids).union(prebound_ids)):
            raise ValueError("Resolved Provider entries must cover Product roots")
        optional = tuple(self.optional_decisions)
        if any(
            not isinstance(item, CapabilityOptionalRequirementDecision)
            for item in optional
        ):
            raise TypeError("Optional Provider decisions have invalid type")
        if optional != tuple(sorted(optional)):
            raise ValueError("Optional Provider decisions must be sorted")
        _require_exact_version(
            self.set_version,
            supported=RESOLVED_CAPABILITY_PROVIDER_SET_VERSION,
            name="Resolved Capability Provider set",
        )
        object.__setattr__(self, "roots", roots)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "prebound_providers", prebound)
        object.__setattr__(self, "optional_decisions", optional)

    @property
    def providers(self) -> tuple[CapabilityBundleProvider, ...]:
        return tuple(item.provider for item in self.entries)

    @property
    def binding_specs(self) -> tuple[CapabilityProviderBindingSpec, ...]:
        return tuple(item.binding_spec for item in self.entries)

    @property
    def closure_fingerprint(self) -> str:
        return _digest_document(
            "loushang.resolved-capability-provider-set/v1",
            self._record_document(),
        )

    def _record_document(self) -> dict[str, object]:
        return {
            "entries": [item.to_dict() for item in self.entries],
            "evaluatedAt": self.evaluated_at,
            "optionalDecisions": [
                item.to_dict() for item in self.optional_decisions
            ],
            "preboundProviders": [
                _capability_bundle_provider_to_dict(item)
                for item in self.prebound_providers
            ],
            "productId": self.product_id,
            "productPolicyRevision": self.product_policy_revision,
            "roots": list(self.roots),
            "setVersion": self.set_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._record_document(),
            "closureFingerprint": self.closure_fingerprint,
        }


class ProductCapabilityProviderResolver:
    """Select a complete closure without importing, constructing, or planning."""

    def resolve(
        self,
        plan: ProductCapabilityProviderSelectionPlanV1,
        *,
        definitions: tuple[CapabilityDefinition, ...],
        admissions: tuple[CapabilityProviderAdmissionRecord, ...],
        owner_snapshots: tuple[CapabilityProviderOwnerSnapshot, ...],
        evaluated_at: int,
        prebound_providers: tuple[CapabilityBundleProvider, ...] = (),
    ) -> ResolvedCapabilityProviderSet:
        if not isinstance(plan, ProductCapabilityProviderSelectionPlanV1):
            raise TypeError("Product Provider Resolver requires an exact Plan v1")
        _require_nonnegative_integer(
            evaluated_at,
            name="Provider selection evaluation time",
        )
        definitions_by_id = _index_definitions(definitions)
        admission_values = tuple(admissions)
        if any(
            not isinstance(item, CapabilityProviderAdmissionRecord)
            for item in admission_values
        ):
            raise TypeError("Provider admissions have invalid type")
        snapshots_by_capability = _index_snapshots(owner_snapshots)
        prebound_by_capability = _index_prebound_providers(
            prebound_providers,
            definitions_by_id=definitions_by_id,
        )
        choices_by_capability: dict[
            str, list[ProductCapabilityProviderChoice]
        ] = {}
        for choice in plan.choices:
            choices_by_capability.setdefault(choice.capability_id, []).append(choice)

        selected: dict[str, ResolvedCapabilityProvider] = {}
        visiting: set[str] = set()
        optional_decisions: list[CapabilityOptionalRequirementDecision] = []
        used_prebound: set[str] = set()

        def visit(capability_id: str) -> None:
            if capability_id in selected or capability_id in visiting:
                return
            if capability_id in prebound_by_capability:
                used_prebound.add(capability_id)
                return
            choices = choices_by_capability.get(capability_id, [])
            if not choices:
                _raise_selection(
                    "missing_provider_selection",
                    f"Product did not select a Provider for {capability_id}.",
                )
            if len(choices) != 1:
                _raise_selection(
                    "multiple_provider_selections",
                    f"Product selected multiple Providers for {capability_id}.",
                )
            choice = choices[0]
            definition = definitions_by_id.get(capability_id)
            if definition is None:
                _raise_selection(
                    "missing_capability_definition",
                    f"Capability Definition is missing for {capability_id}.",
                )
            matches = tuple(
                admission
                for admission in admission_values
                if admission.capability_id == capability_id
                and admission.provider.provider_id == choice.provider_id
                and admission.candidate_fingerprint
                == choice.candidate_fingerprint
            )
            if not matches:
                _raise_selection(
                    "selected_provider_not_admitted",
                    f"Selected Provider is not owner-admitted for {capability_id}.",
                )
            if len(matches) != 1:
                _raise_selection(
                    "multiple_admitted_provider_matches",
                    f"Selected Provider admission is ambiguous for {capability_id}.",
                )
            admission = matches[0]
            _validate_current_admission(
                plan,
                definition,
                admission,
                snapshots_by_capability,
                evaluated_at=evaluated_at,
            )
            entry = _resolver_construct(
                ResolvedCapabilityProvider,
                definition=definition,
                provider=admission.provider,
                binding_spec=admission.binding_spec,
                admission=admission,
                choice=choice,
            )
            selected[capability_id] = entry
            visiting.add(capability_id)
            try:
                for requirement in admission.provider.requirements:
                    if requirement.optional:
                        if requirement.capability in prebound_by_capability:
                            visit(requirement.capability)
                            optional_decisions.append(
                                CapabilityOptionalRequirementDecision(
                                    requester_capability_id=capability_id,
                                    capability_id=requirement.capability,
                                    satisfied=True,
                                    selected_candidate_fingerprint=(
                                        _prebound_provider_fingerprint(
                                            prebound_by_capability[
                                                requirement.capability
                                            ]
                                        )
                                    ),
                                )
                            )
                            continue
                        dependency_choices = choices_by_capability.get(
                            requirement.capability,
                            [],
                        )
                        if not dependency_choices:
                            optional_decisions.append(
                                CapabilityOptionalRequirementDecision(
                                    requester_capability_id=capability_id,
                                    capability_id=requirement.capability,
                                    satisfied=False,
                                    selected_candidate_fingerprint=None,
                                )
                            )
                            continue
                        visit(requirement.capability)
                        dependency = selected[requirement.capability]
                        optional_decisions.append(
                            CapabilityOptionalRequirementDecision(
                                requester_capability_id=capability_id,
                                capability_id=requirement.capability,
                                satisfied=True,
                                selected_candidate_fingerprint=(
                                    dependency.choice.candidate_fingerprint
                                ),
                            )
                        )
                        continue
                    visit(requirement.capability)
            finally:
                visiting.remove(capability_id)

        for root in plan.roots:
            visit(root)

        extra_choices = set(choices_by_capability) - set(selected)
        if extra_choices:
            _raise_selection(
                "extra_provider_selection",
                "Product selected Providers outside the root dependency closure: "
                + ", ".join(sorted(extra_choices)),
            )
        entries = tuple(sorted(selected.values(), key=lambda item: item.capability_id))
        optional = tuple(sorted(optional_decisions))
        return _resolver_construct(
            ResolvedCapabilityProviderSet,
            product_id=plan.product_id,
            roots=plan.roots,
            product_policy_revision=plan.policy_revision,
            evaluated_at=evaluated_at,
            entries=entries,
            prebound_providers=tuple(
                prebound_by_capability[item] for item in sorted(used_prebound)
            ),
            optional_decisions=optional,
            set_version=RESOLVED_CAPABILITY_PROVIDER_SET_VERSION,
        )


def _index_definitions(
    definitions: tuple[CapabilityDefinition, ...],
) -> dict[str, CapabilityDefinition]:
    values = tuple(definitions)
    if any(not isinstance(item, CapabilityDefinition) for item in values):
        raise TypeError("Capability Definitions have invalid type")
    indexed: dict[str, CapabilityDefinition] = {}
    for definition in values:
        if definition.capability_id in indexed:
            _raise_selection(
                "duplicate_capability_definition",
                f"Capability Definition is duplicated for {definition.capability_id}.",
            )
        indexed[definition.capability_id] = definition
    return indexed


def _index_snapshots(
    snapshots: tuple[CapabilityProviderOwnerSnapshot, ...],
) -> dict[str, CapabilityProviderOwnerSnapshot]:
    values = tuple(snapshots)
    if any(not isinstance(item, CapabilityProviderOwnerSnapshot) for item in values):
        raise TypeError("Capability owner snapshots have invalid type")
    indexed: dict[str, CapabilityProviderOwnerSnapshot] = {}
    for snapshot in values:
        if snapshot.capability_id in indexed:
            _raise_selection(
                "duplicate_provider_owner_snapshot",
                f"Capability owner snapshot is duplicated for {snapshot.capability_id}.",
            )
        indexed[snapshot.capability_id] = snapshot
    return indexed


def _index_prebound_providers(
    providers: tuple[CapabilityBundleProvider, ...],
    *,
    definitions_by_id: dict[str, CapabilityDefinition],
) -> dict[str, CapabilityBundleProvider]:
    values = tuple(providers)
    if any(not isinstance(item, CapabilityBundleProvider) for item in values):
        raise TypeError("Prebound Providers have invalid type")
    indexed: dict[str, CapabilityBundleProvider] = {}
    for provider in values:
        if provider.capability_id in indexed:
            _raise_selection(
                "duplicate_prebound_provider",
                "Product supplied duplicate prebound Providers.",
            )
        definition = definitions_by_id.get(provider.capability_id)
        if definition is None:
            _raise_selection(
                "missing_capability_definition",
                "Prebound Provider has no Capability Definition.",
            )
        if (
            not provider.compatible_contract.accepts(definition.contract_version)
            or set(provider.facets) - set(definition.facets)
            or set(provider.required_authorities) - set(definition.authority_ceiling)
        ):
            _raise_selection(
                "invalid_prebound_provider",
                "Prebound Provider metadata violates its Capability Definition.",
            )
        indexed[provider.capability_id] = provider
    return indexed


def _prebound_provider_fingerprint(provider: CapabilityBundleProvider) -> str:
    return _digest_document(
        "loushang.prebound-capability-provider/v1",
        _capability_bundle_provider_to_dict(provider),
    )


def _validate_current_admission(
    plan: ProductCapabilityProviderSelectionPlanV1,
    definition: CapabilityDefinition,
    admission: CapabilityProviderAdmissionRecord,
    snapshots: dict[str, CapabilityProviderOwnerSnapshot],
    *,
    evaluated_at: int,
) -> None:
    if admission.candidate.definition != definition:
        _raise_selection(
            "provider_admission_definition_skew",
            "Provider admission does not match the current Definition.",
        )
    if admission.candidate.product_id != plan.product_id:
        _raise_selection(
            "provider_admission_product_mismatch",
            "Provider admission belongs to a different Product.",
        )
    snapshot = snapshots.get(definition.capability_id)
    if snapshot is None:
        _raise_selection(
            "provider_owner_snapshot_missing",
            "Current Capability owner policy snapshot is missing.",
        )
    if snapshot.owner_id != definition.owner_id:
        _raise_selection(
            "provider_owner_snapshot_mismatch",
            "Capability owner snapshot belongs to a different owner.",
        )
    if (
        admission.owner_policy_revision != snapshot.policy_revision
        or admission.revocation_epoch != snapshot.revocation_epoch
    ):
        _raise_selection(
            "provider_admission_policy_stale",
            "Provider admission is stale under current owner policy.",
        )
    if evaluated_at < admission.issued_at:
        _raise_selection(
            "provider_admission_not_current",
            "Provider admission has not reached its issued time.",
        )
    if evaluated_at >= admission.expires_at:
        _raise_selection(
            "provider_admission_expired",
            "Provider admission has expired.",
        )


class _PostInitValue(Protocol):
    def __post_init__(self) -> None: ...


_PostInitT = TypeVar("_PostInitT", bound=_PostInitValue)


def _resolver_construct(
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


def _raise_selection(code: str, message: str) -> Never:
    raise ProviderSelectionError(message, code=code)


__all__ = [
    "PRODUCT_CAPABILITY_PROVIDER_SELECTION_PLAN_VERSION",
    "RESOLVED_CAPABILITY_PROVIDER_SET_VERSION",
    "CapabilityOptionalRequirementDecision",
    "ProductCapabilityProviderChoice",
    "ProductCapabilityProviderResolver",
    "ProductCapabilityProviderSelectionPlanV1",
    "ProviderSelectionError",
    "ResolvedCapabilityProvider",
    "ResolvedCapabilityProviderSet",
]
