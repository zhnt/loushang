"""Product-owned compilation of admitted external Capability Consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Never, Protocol, TypeVar

from loushang.harness.capabilities.contracts import (
    CapabilityDefinition,
    CapabilityRequirement,
    _capability_requirement_to_dict,
    _direct_requirement_scope_is_valid,
    _requirement_refresh_is_valid,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider

PRODUCT_CAPABILITY_CONSUMER_REQUIREMENT_SET_VERSION = 1


class ProductCompositionError(RuntimeError):
    """Stable Product compilation failure preserving owner provenance."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        admission_fingerprints: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.admission_fingerprints = tuple(sorted(admission_fingerprints))


@dataclass(frozen=True, slots=True)
class ProductCapabilityOptionalRequirementChoice:
    requirement_fingerprint: str
    satisfied: bool

    def __post_init__(self) -> None:
        _require_sha256(
            self.requirement_fingerprint,
            name="optional requirement fingerprint",
        )
        if type(self.satisfied) is not bool:
            raise TypeError("Optional requirement choice must be a bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "requirementFingerprint": self.requirement_fingerprint,
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True, slots=True)
class ProductCapabilityConsumerRequirementEntry:
    """One unmerged owner-admitted external Consumer requirement."""

    owner_id: str
    contribution_kind: str
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str
    consumer_scope: str
    consumer_refresh_boundary: str
    requirement: CapabilityRequirement

    def __post_init__(self) -> None:
        for name, value in (
            ("Consumer owner id", self.owner_id),
            ("Consumer contribution kind", self.contribution_kind),
            ("Consumer Plugin id", self.plugin_id),
            ("Consumer contribution id", self.contribution_id),
            ("Consumer scope", self.consumer_scope),
            ("Consumer refresh boundary", self.consumer_refresh_boundary),
        ):
            _require_nonempty(value, name=name)
        _require_sha256(
            self.admission_fingerprint,
            name="Consumer admission fingerprint",
        )
        if not isinstance(self.requirement, CapabilityRequirement):
            raise TypeError("Consumer entry requires a CapabilityRequirement")

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.product-capability-consumer-requirement/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionFingerprint": self.admission_fingerprint,
            "consumerRefreshBoundary": self.consumer_refresh_boundary,
            "consumerScope": self.consumer_scope,
            "contributionId": self.contribution_id,
            "contributionKind": self.contribution_kind,
            "ownerId": self.owner_id,
            "pluginId": self.plugin_id,
            "requirement": _capability_requirement_to_dict(self.requirement),
        }


@dataclass(frozen=True, slots=True)
class ProductCapabilityConsumerRequirementPreview:
    optional_entries: tuple[ProductCapabilityConsumerRequirementEntry, ...]


@dataclass(frozen=True, slots=True, init=False)
class ProductCapabilityConsumerRequirementSet:
    """Sole immutable external-Consumer bridge into Provider root selection."""

    product_id: str
    mandatory_roots: tuple[str, ...]
    roots: tuple[str, ...]
    entries: tuple[ProductCapabilityConsumerRequirementEntry, ...]
    optional_choices: tuple[ProductCapabilityOptionalRequirementChoice, ...]
    set_version: int

    def __init__(self) -> None:
        raise TypeError("Product Consumer requirement set is compiler-constructed")

    def __post_init__(self) -> None:
        _require_nonempty(self.product_id, name="Product id")
        mandatory_roots = _sorted_unique_names(
            self.mandatory_roots,
            name="mandatory Capability root",
        )
        roots = _sorted_unique_names(self.roots, name="Capability root")
        if not mandatory_roots or not set(mandatory_roots).issubset(roots):
            raise ValueError("Consumer roots must contain every mandatory root")
        entries = tuple(self.entries)
        if any(
            not isinstance(item, ProductCapabilityConsumerRequirementEntry)
            for item in entries
        ):
            raise TypeError("Consumer requirement set entries have invalid type")
        if entries != tuple(sorted(entries, key=_entry_sort_key)):
            raise ValueError("Consumer requirement entries must be canonical")
        fingerprints = tuple(item.fingerprint for item in entries)
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("Consumer requirement entries must be unique")
        choices = tuple(self.optional_choices)
        if any(
            not isinstance(item, ProductCapabilityOptionalRequirementChoice)
            for item in choices
        ):
            raise TypeError("Optional Consumer choices have invalid type")
        if choices != tuple(
            sorted(choices, key=lambda item: item.requirement_fingerprint)
        ):
            raise ValueError("Optional Consumer choices must be canonical")
        _require_exact_version(
            self.set_version,
            supported=PRODUCT_CAPABILITY_CONSUMER_REQUIREMENT_SET_VERSION,
            name="Product Consumer requirement set",
        )
        object.__setattr__(self, "mandatory_roots", mandatory_roots)
        object.__setattr__(self, "roots", roots)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "optional_choices", choices)

    @property
    def satisfied_entries(self) -> tuple[ProductCapabilityConsumerRequirementEntry, ...]:
        choices = {
            item.requirement_fingerprint: item.satisfied
            for item in self.optional_choices
        }
        return tuple(
            entry
            for entry in self.entries
            if not entry.requirement.optional or choices[entry.fingerprint]
        )

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.product-capability-consumer-requirement-set/v1",
            self._record_document(),
        )

    def validate_provider_metadata(
        self,
        providers: tuple[CapabilityBundleProvider, ...],
    ) -> None:
        indexed = {item.capability_id: item for item in providers}
        if len(indexed) != len(providers):
            _raise_composition(
                "duplicate_selected_provider",
                "Selected Provider metadata contains a duplicate Capability.",
            )
        for entry in self.satisfied_entries:
            provider = indexed.get(entry.requirement.capability)
            if provider is None:
                _raise_composition(
                    "consumer_provider_missing",
                    "Satisfied Consumer requirement has no selected Provider.",
                    admission_fingerprints=(entry.admission_fingerprint,),
                )
            if not provider.compatible_contract.accepts(
                entry.requirement.compatible_contract.minimum
            ) and not entry.requirement.compatible_contract.accepts(
                provider.compatible_contract.minimum
            ):
                _raise_composition(
                    "consumer_selected_provider_contract_mismatch",
                    "Selected Provider does not overlap the Consumer contract.",
                    admission_fingerprints=(entry.admission_fingerprint,),
                )
            if set(entry.requirement.facets) - set(provider.facets):
                _raise_composition(
                    "consumer_selected_provider_facet_mismatch",
                    "Selected Provider is missing a Consumer facet.",
                    admission_fingerprints=(entry.admission_fingerprint,),
                )

    def _record_document(self) -> dict[str, object]:
        return {
            "entries": [item.to_dict() for item in self.entries],
            "mandatoryRoots": list(self.mandatory_roots),
            "optionalChoices": [item.to_dict() for item in self.optional_choices],
            "productId": self.product_id,
            "roots": list(self.roots),
            "setVersion": self.set_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._record_document(), "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class ProductCompositionCompilation:
    resource_admissions: tuple[OwnerContributionAdmissionRecord, ...]
    catalog_admissions: tuple[OwnerContributionAdmissionRecord, ...]
    consumer_requirements: ProductCapabilityConsumerRequirementSet


class ProductCompositionCompiler:
    """Compile owner-admitted contributions exactly once without live effects."""

    def preview_optional_choices(
        self,
        *,
        product_id: str,
        mandatory_roots: tuple[str, ...],
        admissions: tuple[OwnerContributionAdmissionRecord, ...],
        definitions: tuple[CapabilityDefinition, ...],
        evaluated_at: int | None = None,
    ) -> ProductCapabilityConsumerRequirementPreview:
        entries, _resources, _catalog = self._prepare(
            product_id=product_id,
            admissions=admissions,
            definitions=definitions,
            evaluated_at=evaluated_at,
        )
        _sorted_unique_names(mandatory_roots, name="mandatory Capability root")
        return ProductCapabilityConsumerRequirementPreview(
            optional_entries=tuple(
                item for item in entries if item.requirement.optional
            )
        )

    def compile(
        self,
        *,
        product_id: str,
        mandatory_roots: tuple[str, ...],
        admissions: tuple[OwnerContributionAdmissionRecord, ...],
        definitions: tuple[CapabilityDefinition, ...],
        optional_choices: tuple[ProductCapabilityOptionalRequirementChoice, ...],
        evaluated_at: int | None = None,
    ) -> ProductCompositionCompilation:
        mandatory = _sorted_unique_names(
            mandatory_roots,
            name="mandatory Capability root",
        )
        if not mandatory:
            raise ValueError("Product composition requires mandatory roots")
        entries, resources, catalog = self._prepare(
            product_id=product_id,
            admissions=admissions,
            definitions=definitions,
            evaluated_at=evaluated_at,
        )
        optional_entries = {
            item.fingerprint: item
            for item in entries
            if item.requirement.optional
        }
        choices = tuple(optional_choices)
        if any(
            not isinstance(item, ProductCapabilityOptionalRequirementChoice)
            for item in choices
        ):
            raise TypeError("Optional Consumer choices have invalid type")
        choice_map: dict[str, ProductCapabilityOptionalRequirementChoice] = {}
        for choice in choices:
            if choice.requirement_fingerprint in choice_map:
                _raise_composition(
                    "multiple_optional_consumer_decisions",
                    "An optional Consumer requirement has multiple decisions.",
                )
            choice_map[choice.requirement_fingerprint] = choice
        missing = set(optional_entries) - set(choice_map)
        if missing:
            _raise_composition(
                "missing_optional_consumer_decision",
                "An optional Consumer requirement has no explicit decision.",
                admission_fingerprints=tuple(
                    optional_entries[item].admission_fingerprint for item in missing
                ),
            )
        extra = set(choice_map) - set(optional_entries)
        if extra:
            _raise_composition(
                "extra_optional_consumer_decision",
                "Product supplied a decision for an unknown optional requirement.",
            )
        roots = set(mandatory)
        for entry in entries:
            if not entry.requirement.optional or choice_map[entry.fingerprint].satisfied:
                roots.add(entry.requirement.capability)
        requirement_set = _compiler_construct(
            ProductCapabilityConsumerRequirementSet,
            product_id=product_id,
            mandatory_roots=mandatory,
            roots=tuple(sorted(roots)),
            entries=entries,
            optional_choices=tuple(
                sorted(choices, key=lambda item: item.requirement_fingerprint)
            ),
            set_version=PRODUCT_CAPABILITY_CONSUMER_REQUIREMENT_SET_VERSION,
        )
        return ProductCompositionCompilation(
            resource_admissions=resources,
            catalog_admissions=catalog,
            consumer_requirements=requirement_set,
        )

    @staticmethod
    def _prepare(
        *,
        product_id: str,
        admissions: tuple[OwnerContributionAdmissionRecord, ...],
        definitions: tuple[CapabilityDefinition, ...],
        evaluated_at: int | None,
    ) -> tuple[
        tuple[ProductCapabilityConsumerRequirementEntry, ...],
        tuple[OwnerContributionAdmissionRecord, ...],
        tuple[OwnerContributionAdmissionRecord, ...],
    ]:
        _require_nonempty(product_id, name="Product id")
        values = tuple(admissions)
        if any(not isinstance(item, OwnerContributionAdmissionRecord) for item in values):
            raise TypeError("Product composition admissions have invalid type")
        if evaluated_at is not None:
            _require_nonnegative_integer(evaluated_at, name="composition evaluation time")
        definitions_by_id = _index_definitions(definitions)
        identity_owners: dict[
            tuple[str, str, str], list[OwnerContributionAdmissionRecord]
        ] = {}
        entries: list[ProductCapabilityConsumerRequirementEntry] = []
        resources: list[OwnerContributionAdmissionRecord] = []
        catalog: list[OwnerContributionAdmissionRecord] = []
        for admission in values:
            if admission.product_id != product_id:
                _raise_composition(
                    "contribution_admission_product_mismatch",
                    "Owner contribution admission belongs to another Product.",
                    admission_fingerprints=(admission.fingerprint,),
                )
            if evaluated_at is not None and not (
                admission.issued_at <= evaluated_at < admission.expires_at
            ):
                _raise_composition(
                    "contribution_admission_not_current",
                    "Owner contribution admission is not current.",
                    admission_fingerprints=(admission.fingerprint,),
                )
            for identity in admission.admitted_identities:
                identity_owners.setdefault(
                    (admission.contribution_kind, admission.owner_id, identity),
                    [],
                ).append(admission)
            if admission.contribution_kind == "resource_item":
                resources.append(admission)
                continue
            catalog.append(admission)
            for requirement in admission.requirements:
                definition = definitions_by_id.get(requirement.capability)
                if definition is None:
                    _raise_composition(
                        "consumer_requirement_definition_missing",
                        "Consumer requirement targets an unknown Capability.",
                        admission_fingerprints=(admission.fingerprint,),
                    )
                _validate_requirement(
                    admission,
                    requirement=requirement,
                    definition=definition,
                )
                entries.append(
                    ProductCapabilityConsumerRequirementEntry(
                        owner_id=admission.owner_id,
                        contribution_kind=admission.contribution_kind,
                        plugin_id=admission.plugin_id,
                        contribution_id=admission.contribution_id,
                        admission_fingerprint=admission.fingerprint,
                        consumer_scope=admission.consumer_scope,
                        consumer_refresh_boundary=(
                            admission.consumer_refresh_boundary
                        ),
                        requirement=requirement,
                    )
                )
        duplicates = tuple(
            item
            for item in identity_owners.values()
            if len(item) > 1
        )
        if duplicates:
            fingerprints = tuple(
                admission.fingerprint
                for group in duplicates
                for admission in group
            )
            _raise_composition(
                "duplicate_owner_contribution_identity",
                "Multiple admissions claim the same exact owner identity.",
                admission_fingerprints=fingerprints,
            )
        return (
            tuple(sorted(entries, key=_entry_sort_key)),
            tuple(sorted(resources, key=_admission_sort_key)),
            tuple(sorted(catalog, key=_admission_sort_key)),
        )


def _validate_requirement(
    admission: OwnerContributionAdmissionRecord,
    *,
    requirement: CapabilityRequirement,
    definition: CapabilityDefinition,
) -> None:
    provenance = (admission.fingerprint,)
    if not requirement.compatible_contract.accepts(definition.contract_version):
        _raise_composition(
            "consumer_requirement_contract_mismatch",
            "Consumer requirement is incompatible with its Definition.",
            admission_fingerprints=provenance,
        )
    if set(requirement.facets) - set(definition.facets):
        _raise_composition(
            "consumer_requirement_facet_mismatch",
            "Consumer requirement requests a facet outside its Definition.",
            admission_fingerprints=provenance,
        )
    if requirement.binding == "stable_reference":
        return
    if not _direct_requirement_scope_is_valid(
        admission.consumer_scope,
        definition.scope,
    ):
        _raise_composition(
            "consumer_requirement_scope_inversion",
            "Consumer requirement captures a shorter-lived Capability.",
            admission_fingerprints=provenance,
        )
    if not _requirement_refresh_is_valid(
        admission.consumer_refresh_boundary,
        definition.refresh_boundary,
    ):
        _raise_composition(
            "consumer_requirement_refresh_inversion",
            "Sealed Consumer captures a turn-refreshable Capability.",
            admission_fingerprints=provenance,
        )


def _index_definitions(
    definitions: tuple[CapabilityDefinition, ...],
) -> dict[str, CapabilityDefinition]:
    values = tuple(definitions)
    if any(not isinstance(item, CapabilityDefinition) for item in values):
        raise TypeError("Product composition Definitions have invalid type")
    indexed: dict[str, CapabilityDefinition] = {}
    for definition in values:
        if definition.capability_id in indexed:
            _raise_composition(
                "duplicate_capability_definition",
                "Product composition contains duplicate Capability Definitions.",
            )
        indexed[definition.capability_id] = definition
    return indexed


def _entry_sort_key(
    entry: ProductCapabilityConsumerRequirementEntry,
) -> tuple[object, ...]:
    requirement = entry.requirement
    return (
        requirement.capability,
        requirement.optional,
        requirement.binding,
        requirement.compatible_contract.minimum,
        requirement.compatible_contract.maximum,
        requirement.facets,
        entry.admission_fingerprint,
        entry.owner_id,
        entry.contribution_id,
    )


def _admission_sort_key(
    admission: OwnerContributionAdmissionRecord,
) -> tuple[str, str, str, str]:
    return (
        admission.contribution_kind,
        admission.owner_id,
        admission.contribution_id,
        admission.fingerprint,
    )


class _PostInitValue(Protocol):
    def __post_init__(self) -> None: ...


_ConstructedT = TypeVar("_ConstructedT", bound=_PostInitValue)


def _compiler_construct(
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


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _require_exact_version(value: object, *, supported: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} version must be an integer")
    if value != supported:
        raise ValueError(f"Unsupported {name} version")


def _sorted_unique_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_require_nonempty(item, name=name) for item in values))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} values must be unique")
    return normalized


def _raise_composition(
    code: str,
    message: str,
    *,
    admission_fingerprints: tuple[str, ...] = (),
) -> Never:
    raise ProductCompositionError(
        message,
        code=code,
        admission_fingerprints=admission_fingerprints,
    )


__all__ = [
    "ProductCapabilityConsumerRequirementEntry",
    "ProductCapabilityConsumerRequirementPreview",
    "ProductCapabilityConsumerRequirementSet",
    "ProductCapabilityOptionalRequirementChoice",
    "ProductCompositionCompilation",
    "ProductCompositionCompiler",
    "ProductCompositionError",
]
