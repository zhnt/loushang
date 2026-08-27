"""Product-neutral runtime provenance composition.

The collector in :mod:`loushang.foundation.observability.identity` describes
the host process and imported package.  This module adds independently owned
component facts without importing a Product, plugin, or terminal UI package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, runtime_checkable

from loushang.foundation.json import JSONValue, require_json_mapping

RuntimeProvenanceScope = Literal["installation", "runtime"]
RUNTIME_PROVENANCE_SCHEMA_VERSION = 1


class RuntimeProvenanceError(ValueError):
    """Raised when independently contributed provenance cannot be composed."""


@dataclass(frozen=True, slots=True)
class RuntimeProvenanceComponent:
    """One immutable, JSON-safe component description."""

    component_id: str
    kind: str
    details: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        component_id = self.component_id.strip()
        kind = self.kind.strip()
        if not component_id:
            raise RuntimeProvenanceError("provenance component id must be non-empty")
        if not kind:
            raise RuntimeProvenanceError(
                f"provenance component {component_id!r} kind must be non-empty"
            )
        details = require_json_mapping(
            dict(self.details),
            name=f"provenance component {component_id!r} details",
        )
        if "kind" in details:
            raise RuntimeProvenanceError(
                f"provenance component {component_id!r} details reserve 'kind'"
            )
        object.__setattr__(self, "component_id", component_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "details", MappingProxyType(details))

    def to_json(self) -> dict[str, JSONValue]:
        return {"kind": self.kind, **dict(self.details)}


@runtime_checkable
class RuntimeProvenanceContributor(Protocol):
    """Contribute installation or effective-runtime component facts."""

    def provenance_component(
        self,
        scope: RuntimeProvenanceScope,
    ) -> RuntimeProvenanceComponent | None: ...


@dataclass(frozen=True, slots=True)
class StaticRuntimeProvenanceContributor:
    """Describe a bundled component and, optionally, its active runtime state."""

    component_id: str
    kind: str
    installation_details: Mapping[str, JSONValue] = field(default_factory=dict)
    runtime_details: Mapping[str, JSONValue] | None = None

    def provenance_component(
        self,
        scope: RuntimeProvenanceScope,
    ) -> RuntimeProvenanceComponent | None:
        details = (
            self.installation_details
            if scope == "installation"
            else self.runtime_details
        )
        if details is None:
            return None
        return RuntimeProvenanceComponent(
            component_id=self.component_id,
            kind=self.kind,
            details=details,
        )


def compose_runtime_provenance(
    host_identity: Mapping[str, object],
    *,
    contributors: Sequence[RuntimeProvenanceContributor] = (),
    scope: RuntimeProvenanceScope = "installation",
) -> dict[str, object]:
    """Return a transportable host identity plus deterministic component facts."""

    if scope not in {"installation", "runtime"}:
        raise RuntimeProvenanceError(f"unsupported provenance scope: {scope!r}")
    components: dict[str, dict[str, JSONValue]] = {}
    for contributor in contributors:
        component = contributor.provenance_component(scope)
        if component is None:
            continue
        if component.component_id in components:
            raise RuntimeProvenanceError(
                f"duplicate provenance component id: {component.component_id!r}"
            )
        components[component.component_id] = component.to_json()

    identity = dict(host_identity)
    identity.update(
        {
            "provenance_schema_version": RUNTIME_PROVENANCE_SCHEMA_VERSION,
            "provenance_scope": scope,
            "components": {
                component_id: components[component_id]
                for component_id in sorted(components)
            },
        }
    )
    return identity


__all__ = [
    "RUNTIME_PROVENANCE_SCHEMA_VERSION",
    "RuntimeProvenanceComponent",
    "RuntimeProvenanceContributor",
    "RuntimeProvenanceError",
    "RuntimeProvenanceScope",
    "StaticRuntimeProvenanceContributor",
    "compose_runtime_provenance",
]
