"""Inert owner-component contracts for Capability-owned aggregation seams.

These records describe components *inside* one Capability.  They neither replace
complete-Bundle Providers nor create another Capability graph or live registry.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal

from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.resources.plugins.declarations import (
    _freeze_json_mapping,
    _thaw_json,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_python_path,
    canonical_plugin_symbol,
)

CAPABILITY_COMPONENT_DEFINITION_VERSION = 1
CAPABILITY_COMPONENT_BINDING_SPEC_VERSION = 1

ComponentMultiplicity = Literal["exclusive", "aggregate"]
ComponentSelectionPolicy = Literal["exactly_one", "ordered_unique"]
ComponentDisposerContract = Literal["required", "optional"]
ComponentSourceKind = Literal["first_party", "plugin"]


@dataclass(frozen=True, slots=True)
class CapabilityComponentDefinition:
    """Versioned schema published by one exact Capability owner."""

    capability_id: str
    owner_id: str
    component_kind: str
    payload_schema_id: str
    payload_schema_version: int
    compatible_bundle_contract: CapabilityContractRange
    multiplicity: ComponentMultiplicity
    selection_policy: ComponentSelectionPolicy
    minimum_count: int
    maximum_count: int | None
    requested_facets: tuple[str, ...] = ()
    service_references: tuple[str, ...] = ()
    refresh_boundary: Literal["owner_generation"] = "owner_generation"
    disposer_contract: ComponentDisposerContract = "optional"
    definition_version: int = CAPABILITY_COMPONENT_DEFINITION_VERSION

    def __post_init__(self) -> None:
        capability_id = _require_nonempty(self.capability_id, name="Capability id")
        owner_id = _require_nonempty(self.owner_id, name="Capability owner id")
        if not capability_id.startswith(f"{owner_id}."):
            raise ValueError("Component Definition owner does not own its Capability")
        _require_nonempty(self.component_kind, name="component kind")
        _require_nonempty(self.payload_schema_id, name="component payload schema id")
        _require_positive_integer(
            self.payload_schema_version,
            name="component payload schema version",
        )
        if not isinstance(self.compatible_bundle_contract, CapabilityContractRange):
            raise TypeError("Component Definition requires a Bundle contract range")
        if self.multiplicity not in {"exclusive", "aggregate"}:
            raise ValueError("Unsupported component multiplicity")
        if self.selection_policy not in {"exactly_one", "ordered_unique"}:
            raise ValueError("Unsupported component selection policy")
        if self.multiplicity == "exclusive" and self.selection_policy != "exactly_one":
            raise ValueError("Exclusive components require exactly-one selection")
        if self.multiplicity == "aggregate" and self.selection_policy != "ordered_unique":
            raise ValueError("Aggregate components require ordered-unique selection")
        minimum = _require_nonnegative_integer(
            self.minimum_count,
            name="component minimum count",
        )
        maximum = self.maximum_count
        if maximum is not None:
            maximum = _require_positive_integer(
                maximum,
                name="component maximum count",
            )
            if maximum < minimum:
                raise ValueError("Component maximum count cannot be below its minimum")
        if self.multiplicity == "exclusive" and (minimum != 1 or maximum != 1):
            raise ValueError("Exclusive components require minimum and maximum count 1")
        facets = _normalized_names(self.requested_facets, name="requested facet")
        services = _normalized_names(
            self.service_references,
            name="component service reference",
        )
        if self.refresh_boundary != "owner_generation":
            raise ValueError("Unsupported component refresh boundary")
        if self.disposer_contract not in {"required", "optional"}:
            raise ValueError("Unsupported component disposer contract")
        _require_exact_version(
            self.definition_version,
            supported=CAPABILITY_COMPONENT_DEFINITION_VERSION,
            name="Capability Component Definition",
        )
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "requested_facets", facets)
        object.__setattr__(self, "service_references", services)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-component-definition/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilityId": self.capability_id,
            "compatibleBundleContract": {
                "maximumVersion": self.compatible_bundle_contract.maximum,
                "minimumVersion": self.compatible_bundle_contract.minimum,
            },
            "componentKind": self.component_kind,
            "definitionVersion": self.definition_version,
            "disposerContract": self.disposer_contract,
            "maximumCount": self.maximum_count,
            "minimumCount": self.minimum_count,
            "multiplicity": self.multiplicity,
            "ownerId": self.owner_id,
            "payloadSchemaId": self.payload_schema_id,
            "payloadSchemaVersion": self.payload_schema_version,
            "refreshBoundary": self.refresh_boundary,
            "requestedFacets": list(self.requested_facets),
            "selectionPolicy": self.selection_policy,
            "serviceReferences": list(self.service_references),
        }


@dataclass(frozen=True, slots=True)
class CapabilityComponentBindingSpec:
    """Inert construction identity; executable callables are Host bindings."""

    source_kind: ComponentSourceKind
    source_id: str
    contribution_id: str
    source_revision_ref: str
    content_digest: str
    plugin_id: str | None = None
    dependency_lock_digest: str | None = None
    factory_path: str | None = None
    factory_symbol: str | None = None
    disposer_path: str | None = None
    disposer_symbol: str | None = None
    binding_inputs: Mapping[str, object] = field(default_factory=dict)
    binding_spec_version: int = CAPABILITY_COMPONENT_BINDING_SPEC_VERSION

    def __post_init__(self) -> None:
        if self.source_kind not in {"first_party", "plugin"}:
            raise ValueError("Unsupported component source kind")
        for name, value in (
            ("component source id", self.source_id),
            ("component contribution id", self.contribution_id),
            ("component source revision ref", self.source_revision_ref),
        ):
            _require_nonempty(value, name=name)
        _require_sha256(self.content_digest, name="component content digest")
        plugin_fields = (
            self.plugin_id,
            self.dependency_lock_digest,
            self.factory_path,
            self.factory_symbol,
            self.disposer_path,
            self.disposer_symbol,
        )
        if self.source_kind == "first_party":
            if any(value is not None for value in plugin_fields):
                raise ValueError(
                    "First-party component binding must not carry Plugin locators"
                )
        else:
            plugin_id = _require_nonempty(self.plugin_id, name="component Plugin id")
            if plugin_id != self.source_id:
                raise ValueError("Component Plugin id must match its source id")
            _require_sha256(
                self.dependency_lock_digest,
                name="component dependency lock digest",
            )
            factory_path = canonical_plugin_python_path(self.factory_path)
            factory_symbol = canonical_plugin_symbol(self.factory_symbol)
            if (self.disposer_path is None) != (self.disposer_symbol is None):
                raise ValueError(
                    "Component disposer path and symbol must appear together"
                )
            disposer_path = (
                None
                if self.disposer_path is None
                else canonical_plugin_python_path(self.disposer_path).as_posix()
            )
            disposer_symbol = (
                None
                if self.disposer_symbol is None
                else canonical_plugin_symbol(self.disposer_symbol)
            )
            object.__setattr__(self, "plugin_id", plugin_id)
            object.__setattr__(self, "factory_path", factory_path.as_posix())
            object.__setattr__(self, "factory_symbol", factory_symbol)
            object.__setattr__(self, "disposer_path", disposer_path)
            object.__setattr__(self, "disposer_symbol", disposer_symbol)
        try:
            inputs = _freeze_json_mapping(self.binding_inputs)
        except (TypeError, ValueError) as exc:
            raise ValueError("Component binding inputs must be strict JSON data") from exc
        _require_exact_version(
            self.binding_spec_version,
            supported=CAPABILITY_COMPONENT_BINDING_SPEC_VERSION,
            name="Capability Component binding spec",
        )
        object.__setattr__(self, "binding_inputs", inputs)

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            "loushang.capability-component-binding-spec/v1",
            self.to_dict(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingInputs": _thaw_json(self.binding_inputs),
            "bindingSpecVersion": self.binding_spec_version,
            "contentDigest": self.content_digest,
            "contributionId": self.contribution_id,
            "dependencyLockDigest": self.dependency_lock_digest,
            "disposerPath": self.disposer_path,
            "disposerSymbol": self.disposer_symbol,
            "factoryPath": self.factory_path,
            "factorySymbol": self.factory_symbol,
            "pluginId": self.plugin_id,
            "sourceId": self.source_id,
            "sourceKind": self.source_kind,
            "sourceRevisionRef": self.source_revision_ref,
        }


def _digest_document(domain: str, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(domain.encode("utf-8") + b"\0" + payload).hexdigest()


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_nonnegative_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _require_positive_integer(value: object, *, name: str) -> int:
    result = _require_nonnegative_integer(value, name=name)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


def _require_sha256(value: object, *, name: str) -> str:
    result = _require_nonempty(value, name=name)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{name} must be lowercase SHA-256 hex")
    return result


def _require_exact_version(value: object, *, supported: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} version must be an integer")
    if value != supported:
        raise ValueError(f"Unsupported {name} version")


def _normalized_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(_require_nonempty(value, name=name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} values must not repeat")
    return tuple(sorted(normalized))


__all__ = [
    "CapabilityComponentBindingSpec",
    "CapabilityComponentDefinition",
    "ComponentDisposerContract",
    "ComponentMultiplicity",
    "ComponentSelectionPolicy",
    "ComponentSourceKind",
]
