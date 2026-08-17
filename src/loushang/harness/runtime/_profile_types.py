"""Value objects for Product runtime profile declarations and snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeVar, cast

from loushang.foundation.json import JSONValue, require_json_mapping

RuntimeProfileSource = Literal["product", "oem", "extension", "session"]
RuntimeCapabilityShape = Literal["single", "ordered", "exclusive", "append_only"]
RuntimeCapabilityVariationSemantic = Literal[
    "aggregate_contribution",
    "ordered_interception",
    "exclusive_replacement",
]
RuntimeCapabilityScope = Literal[
    "process", "tenant", "workspace", "session", "turn", "channel"
]
RuntimeRefreshBoundary = Literal["sealed", "turn"]

_SOURCES: frozenset[RuntimeProfileSource] = frozenset(
    {"product", "oem", "extension", "session"}
)
_SHAPES: frozenset[RuntimeCapabilityShape] = frozenset(
    {"single", "ordered", "exclusive", "append_only"}
)
_VARIATION_SEMANTICS: frozenset[RuntimeCapabilityVariationSemantic] = frozenset(
    {
        "aggregate_contribution",
        "ordered_interception",
        "exclusive_replacement",
    }
)
_SCOPES: frozenset[RuntimeCapabilityScope] = frozenset(
    {"process", "tenant", "workspace", "session", "turn", "channel"}
)
_REFRESH_BOUNDARIES: frozenset[RuntimeRefreshBoundary] = frozenset({"sealed", "turn"})


def _require_nonempty_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_integer(value: object, *, name: str, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


ChoiceT = TypeVar("ChoiceT", bound=str)


def _require_choice(
    value: object,
    *,
    name: str,
    choices: frozenset[ChoiceT],
) -> ChoiceT:
    value = _require_nonempty_string(value, name=name)
    if value not in choices:
        options = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {options}")
    return cast(ChoiceT, value)


@dataclass(frozen=True)
class RuntimeCapabilitySlot:
    """A Product-declared position at which runtime behavior may bind."""

    key: str
    shape: RuntimeCapabilityShape
    scope: RuntimeCapabilityScope
    refresh_boundary: RuntimeRefreshBoundary
    allowed_sources: frozenset[RuntimeProfileSource]
    required: bool = True
    variation_semantic: RuntimeCapabilityVariationSemantic | None = None

    def __post_init__(self) -> None:
        _require_nonempty_string(self.key, name="slot key")
        _require_choice(self.shape, name="slot shape", choices=_SHAPES)
        _require_choice(self.scope, name="slot scope", choices=_SCOPES)
        _require_choice(
            self.refresh_boundary,
            name="slot refresh boundary",
            choices=_REFRESH_BOUNDARIES,
        )
        if type(self.required) is not bool:
            raise TypeError("slot required must be a bool")
        sources = frozenset(self.allowed_sources)
        if not sources:
            raise ValueError("slot allowed_sources must not be empty")
        for source in sources:
            _require_choice(source, name="slot allowed source", choices=_SOURCES)
        if self.shape == "exclusive" and self.refresh_boundary != "sealed":
            raise ValueError("exclusive slots must use the sealed refresh boundary")
        if self.variation_semantic is not None:
            _require_choice(
                self.variation_semantic,
                name="slot variation semantic",
                choices=_VARIATION_SEMANTICS,
            )
        if (
            sources != frozenset({"product"})
            or self.shape in {"ordered", "append_only"}
        ) and self.variation_semantic is None:
            raise ValueError(
                "externally variable or multi-value slots must declare a variation "
                "semantic"
            )
        if (
            self.variation_semantic == "exclusive_replacement"
            and self.shape not in {"single", "exclusive"}
        ):
            raise ValueError(
                "exclusive replacement requires a single or exclusive slot shape"
            )
        if (
            self.variation_semantic
            in {"aggregate_contribution", "ordered_interception"}
            and self.shape not in {"ordered", "append_only"}
        ):
            raise ValueError(
                "aggregate contribution and ordered interception require an "
                "ordered or append_only slot shape"
            )
        object.__setattr__(self, "allowed_sources", sources)


@dataclass(frozen=True)
class RuntimeCapabilitySelection:
    """One implementation selection and its strictly JSON configuration."""

    slot: str
    implementation: str
    implementation_version: int
    config: Mapping[str, JSONValue] = field(default_factory=dict)
    priority: int = 0

    def __post_init__(self) -> None:
        _require_nonempty_string(self.slot, name="selection slot")
        _require_nonempty_string(self.implementation, name="selection implementation")
        _require_integer(
            self.implementation_version,
            name="selection implementation_version",
            minimum=1,
        )
        _require_integer(self.priority, name="selection priority")
        object.__setattr__(
            self,
            "config",
            require_json_mapping(dict(self.config), name="selection config"),
        )


@dataclass(frozen=True)
class RuntimeProfileLayer:
    """A source-owned group of selections applied after Product authorization."""

    source: RuntimeProfileSource
    layer_id: str
    selections: tuple[RuntimeCapabilitySelection, ...]
    priority: int = 0

    def __post_init__(self) -> None:
        _require_choice(self.source, name="layer source", choices=_SOURCES)
        _require_nonempty_string(self.layer_id, name="layer id")
        _require_integer(self.priority, name="layer priority")
        selections = tuple(self.selections)
        if any(not isinstance(item, RuntimeCapabilitySelection) for item in selections):
            raise TypeError(
                "layer selections must contain RuntimeCapabilitySelection values"
            )
        object.__setattr__(self, "selections", selections)


@dataclass(frozen=True)
class ProductRuntimePlan:
    """Product-owned declared slots and baseline selections.

    The plan is intentionally data-only.  It does not carry factories, plugin
    discovery, credentials, or configuration precedence code.
    """

    product_id: str
    slots: tuple[RuntimeCapabilitySlot, ...]
    defaults: tuple[RuntimeCapabilitySelection, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty_string(self.product_id, name="product id")
        _require_integer(self.schema_version, name="plan schema_version", minimum=1)
        slots = tuple(self.slots)
        defaults = tuple(self.defaults)
        if any(not isinstance(slot, RuntimeCapabilitySlot) for slot in slots):
            raise TypeError("plan slots must contain RuntimeCapabilitySlot values")
        if any(
            not isinstance(selection, RuntimeCapabilitySelection)
            for selection in defaults
        ):
            raise TypeError(
                "plan defaults must contain RuntimeCapabilitySelection values"
            )
        slot_keys = [slot.key for slot in slots]
        duplicate_slots = sorted(
            key for key in set(slot_keys) if slot_keys.count(key) > 1
        )
        if duplicate_slots:
            raise ValueError(
                "plan slot keys must be unique: " + ", ".join(duplicate_slots)
            )
        unknown_defaults = sorted(
            {selection.slot for selection in defaults} - set(slot_keys)
        )
        if unknown_defaults:
            raise ValueError(
                "plan defaults select undeclared slots: " + ", ".join(unknown_defaults)
            )
        object.__setattr__(self, "slots", slots)
        object.__setattr__(self, "defaults", defaults)

    def slot(self, key: str) -> RuntimeCapabilitySlot:
        for slot in self.slots:
            if slot.key == key:
                return slot
        raise KeyError(f"unknown runtime capability slot: {key}")


@dataclass(frozen=True)
class RuntimeProfileDiagnostic:
    """Structured explanation for a rejected declaration or binding."""

    code: str
    message: str
    slot: str | None = None
    source: RuntimeProfileSource | None = None
    layer_id: str | None = None
    details: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_nonempty_string(self.code, name="diagnostic code")
        _require_nonempty_string(self.message, name="diagnostic message")
        if self.slot is not None:
            _require_nonempty_string(self.slot, name="diagnostic slot")
        if self.source is not None:
            _require_choice(self.source, name="diagnostic source", choices=_SOURCES)
        if self.layer_id is not None:
            _require_nonempty_string(self.layer_id, name="diagnostic layer id")
        object.__setattr__(
            self,
            "details",
            require_json_mapping(dict(self.details), name="diagnostic details"),
        )


class RuntimeProfileResolutionError(ValueError):
    """Raised when supplied profile layers cannot form one valid profile."""

    def __init__(self, diagnostics: Iterable[RuntimeProfileDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        if not self.diagnostics:
            raise ValueError("resolution errors must include at least one diagnostic")
        super().__init__(
            "runtime profile resolution failed: "
            + "; ".join(
                f"{diagnostic.code}: {diagnostic.message}"
                for diagnostic in self.diagnostics
            )
        )


@dataclass(frozen=True)
class ResolvedRuntimeSelection:
    """A selection with source provenance retained for diagnostics and replay."""

    selection: RuntimeCapabilitySelection
    source: RuntimeProfileSource
    layer_id: str
    layer_priority: int


@dataclass(frozen=True)
class ResolvedRuntimeCapability:
    slot: RuntimeCapabilitySlot
    selections: tuple[ResolvedRuntimeSelection, ...]


@dataclass(frozen=True)
class RuntimeProfileSnapshotSelection:
    implementation: str
    implementation_version: int
    config: Mapping[str, JSONValue]
    source: RuntimeProfileSource
    layer_id: str
    layer_priority: int
    selection_priority: int

    def __post_init__(self) -> None:
        _require_nonempty_string(self.implementation, name="snapshot implementation")
        _require_integer(
            self.implementation_version,
            name="snapshot implementation_version",
            minimum=1,
        )
        _require_choice(self.source, name="snapshot source", choices=_SOURCES)
        _require_nonempty_string(self.layer_id, name="snapshot layer id")
        _require_integer(self.layer_priority, name="snapshot layer priority")
        _require_integer(self.selection_priority, name="snapshot selection priority")
        object.__setattr__(
            self,
            "config",
            require_json_mapping(dict(self.config), name="snapshot config"),
        )

    @classmethod
    def from_json(cls, value: object, *, name: str) -> RuntimeProfileSnapshotSelection:
        mapping = require_json_mapping(value, name=name)
        return cls(
            implementation=_require_nonempty_string(
                mapping.get("implementation"), name=f"{name}.implementation"
            ),
            implementation_version=_require_integer(
                mapping.get("implementationVersion"),
                name=f"{name}.implementationVersion",
                minimum=1,
            ),
            config=require_json_mapping(mapping.get("config"), name=f"{name}.config"),
            source=_require_choice(
                mapping.get("source"), name=f"{name}.source", choices=_SOURCES
            ),
            layer_id=_require_nonempty_string(
                mapping.get("layerId"), name=f"{name}.layerId"
            ),
            layer_priority=_require_integer(
                mapping.get("layerPriority"), name=f"{name}.layerPriority"
            ),
            selection_priority=_require_integer(
                mapping.get("selectionPriority"),
                name=f"{name}.selectionPriority",
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "implementation": self.implementation,
            "implementationVersion": self.implementation_version,
            "config": dict(self.config),
            "source": self.source,
            "layerId": self.layer_id,
            "layerPriority": self.layer_priority,
            "selectionPriority": self.selection_priority,
        }


@dataclass(frozen=True)
class RuntimeProfileSnapshotCapability:
    slot: str
    shape: RuntimeCapabilityShape
    scope: RuntimeCapabilityScope
    refresh_boundary: RuntimeRefreshBoundary
    selections: tuple[RuntimeProfileSnapshotSelection, ...]
    variation_semantic: RuntimeCapabilityVariationSemantic | None = None

    def __post_init__(self) -> None:
        _require_nonempty_string(self.slot, name="snapshot slot")
        _require_choice(self.shape, name="snapshot shape", choices=_SHAPES)
        _require_choice(self.scope, name="snapshot scope", choices=_SCOPES)
        _require_choice(
            self.refresh_boundary,
            name="snapshot refresh boundary",
            choices=_REFRESH_BOUNDARIES,
        )
        if self.variation_semantic is not None:
            _require_choice(
                self.variation_semantic,
                name="snapshot variation semantic",
                choices=_VARIATION_SEMANTICS,
            )
        selections = tuple(self.selections)
        if any(
            not isinstance(selection, RuntimeProfileSnapshotSelection)
            for selection in selections
        ):
            raise TypeError(
                "snapshot selections must contain RuntimeProfileSnapshotSelection values"
            )
        object.__setattr__(self, "selections", selections)

    @classmethod
    def from_json(cls, value: object, *, name: str) -> RuntimeProfileSnapshotCapability:
        mapping = require_json_mapping(value, name=name)
        raw_selections = mapping.get("selections")
        if not isinstance(raw_selections, list):
            raise TypeError(f"{name}.selections must be a JSON array")
        return cls(
            slot=_require_nonempty_string(mapping.get("slot"), name=f"{name}.slot"),
            shape=_require_choice(
                mapping.get("shape"), name=f"{name}.shape", choices=_SHAPES
            ),
            scope=_require_choice(
                mapping.get("scope"), name=f"{name}.scope", choices=_SCOPES
            ),
            refresh_boundary=_require_choice(
                mapping.get("refreshBoundary"),
                name=f"{name}.refreshBoundary",
                choices=_REFRESH_BOUNDARIES,
            ),
            variation_semantic=(
                _require_choice(
                    mapping.get("variationSemantic"),
                    name=f"{name}.variationSemantic",
                    choices=_VARIATION_SEMANTICS,
                )
                if mapping.get("variationSemantic") is not None
                else None
            ),
            selections=tuple(
                RuntimeProfileSnapshotSelection.from_json(
                    selection, name=f"{name}.selections[{index}]"
                )
                for index, selection in enumerate(raw_selections)
            ),
        )

    def to_json(self) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "slot": self.slot,
            "shape": self.shape,
            "scope": self.scope,
            "refreshBoundary": self.refresh_boundary,
            "selections": [selection.to_json() for selection in self.selections],
        }
        if self.variation_semantic is not None:
            result["variationSemantic"] = self.variation_semantic
        return result


@dataclass(frozen=True)
class RuntimeProfileSnapshot:
    """Durable, JSON-only description of a resolved runtime profile."""

    product_id: str
    capabilities: tuple[RuntimeProfileSnapshotCapability, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty_string(self.product_id, name="snapshot product id")
        _require_integer(self.schema_version, name="snapshot schema_version", minimum=1)
        capabilities = tuple(self.capabilities)
        if any(
            not isinstance(capability, RuntimeProfileSnapshotCapability)
            for capability in capabilities
        ):
            raise TypeError(
                "snapshot capabilities must contain RuntimeProfileSnapshotCapability values"
            )
        keys = [capability.slot for capability in capabilities]
        duplicates = sorted(key for key in set(keys) if keys.count(key) > 1)
        if duplicates:
            raise ValueError(
                "snapshot capability slots must be unique: " + ", ".join(duplicates)
            )
        object.__setattr__(self, "capabilities", capabilities)

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "schemaVersion": self.schema_version,
            "productId": self.product_id,
            "capabilities": [capability.to_json() for capability in self.capabilities],
        }

    @classmethod
    def from_json(cls, value: object) -> RuntimeProfileSnapshot:
        mapping = require_json_mapping(value, name="runtime profile snapshot")
        schema_version = _require_integer(
            mapping.get("schemaVersion"),
            name="runtime profile snapshot.schemaVersion",
            minimum=1,
        )
        if schema_version != 1:
            raise ValueError(
                f"unsupported runtime profile snapshot schema version: {schema_version}"
            )
        raw_capabilities = mapping.get("capabilities")
        if not isinstance(raw_capabilities, list):
            raise TypeError(
                "runtime profile snapshot.capabilities must be a JSON array"
            )
        return cls(
            product_id=_require_nonempty_string(
                mapping.get("productId"), name="runtime profile snapshot.productId"
            ),
            capabilities=tuple(
                RuntimeProfileSnapshotCapability.from_json(
                    capability,
                    name=f"runtime profile snapshot.capabilities[{index}]",
                )
                for index, capability in enumerate(raw_capabilities)
            ),
            schema_version=schema_version,
        )


@dataclass(frozen=True)
class ResolvedRuntimeProfile:
    product_id: str
    capabilities: tuple[ResolvedRuntimeCapability, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty_string(self.product_id, name="resolved product id")
        _require_integer(self.schema_version, name="resolved schema_version", minimum=1)
        capabilities = tuple(self.capabilities)
        if any(
            not isinstance(capability, ResolvedRuntimeCapability)
            for capability in capabilities
        ):
            raise TypeError(
                "resolved capabilities must contain ResolvedRuntimeCapability values"
            )
        keys = [capability.slot.key for capability in capabilities]
        duplicates = sorted(key for key in set(keys) if keys.count(key) > 1)
        if duplicates:
            raise ValueError(
                "resolved capability slots must be unique: " + ", ".join(duplicates)
            )
        object.__setattr__(self, "capabilities", capabilities)

    def capability(self, key: str) -> ResolvedRuntimeCapability:
        for capability in self.capabilities:
            if capability.slot.key == key:
                return capability
        raise KeyError(f"unknown resolved runtime capability slot: {key}")

    def snapshot(self) -> RuntimeProfileSnapshot:
        return RuntimeProfileSnapshot(
            product_id=self.product_id,
            schema_version=self.schema_version,
            capabilities=tuple(
                RuntimeProfileSnapshotCapability(
                    slot=capability.slot.key,
                    shape=capability.slot.shape,
                    scope=capability.slot.scope,
                    refresh_boundary=capability.slot.refresh_boundary,
                    variation_semantic=capability.slot.variation_semantic,
                    selections=tuple(
                        RuntimeProfileSnapshotSelection(
                            implementation=resolved.selection.implementation,
                            implementation_version=resolved.selection.implementation_version,
                            config=resolved.selection.config,
                            source=resolved.source,
                            layer_id=resolved.layer_id,
                            layer_priority=resolved.layer_priority,
                            selection_priority=resolved.selection.priority,
                        )
                        for resolved in capability.selections
                    ),
                )
                for capability in self.capabilities
            ),
        )
