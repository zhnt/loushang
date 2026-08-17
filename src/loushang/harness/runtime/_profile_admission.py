"""Product authorization policy for externally supplied runtime profile layers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from loushang.foundation.json import JSONValue
from loushang.harness.runtime._profile_types import (
    _SOURCES,
    ProductRuntimePlan,
    RuntimeProfileDiagnostic,
    RuntimeProfileLayer,
    RuntimeProfileResolutionError,
    RuntimeProfileSource,
    _require_choice,
    _require_nonempty_string,
)


@dataclass(frozen=True)
class RuntimeProfileLayerGrant:
    """Product authorization for one externally supplied runtime profile layer."""

    source: RuntimeProfileSource
    layer_id: str
    allowed_slots: frozenset[str] | None = None
    granted_permissions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_choice(self.source, name="layer grant source", choices=_SOURCES)
        if self.source == "product":
            raise ValueError("Product defaults must be declared on the Product plan")
        _require_nonempty_string(self.layer_id, name="layer grant id")
        if self.allowed_slots is not None:
            slots = frozenset(self.allowed_slots)
            if any(not isinstance(slot, str) or not slot for slot in slots):
                raise ValueError("layer grant allowed slots must be non-empty strings")
            object.__setattr__(self, "allowed_slots", slots)
        permissions = frozenset(self.granted_permissions)
        if any(
            not isinstance(permission, str) or not permission
            for permission in permissions
        ):
            raise ValueError("layer grant permissions must be non-empty strings")
        object.__setattr__(self, "granted_permissions", permissions)


@dataclass(frozen=True)
class RuntimeProfileAdmission:
    """Result of Product policy admitting external runtime profile layers."""

    layers: tuple[RuntimeProfileLayer, ...]
    diagnostics: tuple[RuntimeProfileDiagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    def require_valid(self) -> tuple[RuntimeProfileLayer, ...]:
        if self.diagnostics:
            raise RuntimeProfileResolutionError(self.diagnostics)
        return self.layers


@dataclass(frozen=True)
class RuntimeProfileAdmissionPolicy:
    """Admit trusted OEM, extension, and session layers before resolution.

    This is intentionally an allow-list, not a plugin discovery mechanism.
    Product bootstrap is responsible for authenticating an OEM or extension
    and deriving the grants it supplies here.  The policy only verifies that a
    declared layer is entitled to select the requested runtime slots.
    """

    grants: tuple[RuntimeProfileLayerGrant, ...] = ()
    slot_permissions: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        grants = tuple(self.grants)
        if any(not isinstance(grant, RuntimeProfileLayerGrant) for grant in grants):
            raise TypeError(
                "admission grants must contain RuntimeProfileLayerGrant values"
            )
        identities = [(grant.source, grant.layer_id) for grant in grants]
        if len(identities) != len(set(identities)):
            raise ValueError("admission grants must have unique source and layer ids")
        object.__setattr__(self, "grants", grants)

        permissions: dict[str, frozenset[str]] = {}
        for slot, required in self.slot_permissions.items():
            _require_nonempty_string(slot, name="slot permission key")
            values = frozenset(required)
            if any(
                not isinstance(permission, str) or not permission
                for permission in values
            ):
                raise ValueError("slot permissions must be non-empty strings")
            permissions[slot] = values
        object.__setattr__(self, "slot_permissions", permissions)

    def admit(
        self,
        plan: ProductRuntimePlan,
        layers: Iterable[RuntimeProfileLayer],
    ) -> RuntimeProfileAdmission:
        """Return only authorized layers and diagnostics for rejected input."""

        supplied = tuple(layers)
        if any(not isinstance(layer, RuntimeProfileLayer) for layer in supplied):
            raise TypeError(
                "runtime profile layers must contain RuntimeProfileLayer values"
            )
        known_slots = {slot.key for slot in plan.slots}
        grants = {(grant.source, grant.layer_id): grant for grant in self.grants}
        admitted: list[RuntimeProfileLayer] = []
        diagnostics: list[RuntimeProfileDiagnostic] = []
        for layer in supplied:
            grant = grants.get((layer.source, layer.layer_id))
            if grant is None:
                diagnostics.append(
                    RuntimeProfileDiagnostic(
                        code="untrusted_runtime_layer",
                        message="no Product grant admits this runtime profile layer",
                        source=layer.source,
                        layer_id=layer.layer_id,
                    )
                )
                continue
            rejected = False
            for selection in layer.selections:
                if selection.slot not in known_slots:
                    # Preserve this diagnostic shape for the resolver, which
                    # remains the authority on Product plan validity.
                    continue
                if (
                    grant.allowed_slots is not None
                    and selection.slot not in grant.allowed_slots
                ):
                    diagnostics.append(
                        RuntimeProfileDiagnostic(
                            code="runtime_slot_not_granted",
                            message="runtime layer is not granted access to this slot",
                            slot=selection.slot,
                            source=layer.source,
                            layer_id=layer.layer_id,
                        )
                    )
                    rejected = True
                    continue
                required_permissions = self.slot_permissions.get(
                    selection.slot, frozenset()
                )
                missing_permissions = sorted(
                    required_permissions - grant.granted_permissions
                )
                if missing_permissions:
                    missing_permissions_json: list[JSONValue] = [
                        permission for permission in missing_permissions
                    ]
                    diagnostics.append(
                        RuntimeProfileDiagnostic(
                            code="runtime_slot_permission_denied",
                            message="runtime layer lacks a required slot permission",
                            slot=selection.slot,
                            source=layer.source,
                            layer_id=layer.layer_id,
                            details={"missingPermissions": missing_permissions_json},
                        )
                    )
                    rejected = True
            if not rejected:
                admitted.append(layer)
        return RuntimeProfileAdmission(
            layers=tuple(admitted), diagnostics=tuple(diagnostics)
        )
