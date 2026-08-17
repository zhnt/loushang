"""JSON-only values and pure operations for effective runtime diagnostics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from typing import Literal, cast

from loushang.foundation.json import JSONValue
from loushang.harness.capabilities.graph_runtime import (
    MountGraphSnapshot,
    MountNodeSnapshot,
    RegistrationInventoryEntry,
    RegistrationInventorySnapshot,
)
from loushang.harness.runtime import RuntimeProfileSnapshot

EFFECTIVE_RUNTIME_SCHEMA_VERSION = 1
EffectiveRuntimeSkewCode = Literal[
    "profile_mount_reference_skew",
    "registration_mount_reference_skew",
    "model_profile_reference_skew",
    "model_runtime_reference_skew",
    "model_mount_reference_skew",
    "model_registration_reference_skew",
]


@dataclass(frozen=True)
class RuntimeProfileSelectionReference:
    implementation: str
    implementation_version: int
    source: str
    layer_id: str
    layer_priority: int
    selection_priority: int


@dataclass(frozen=True)
class RuntimeProfileSlotReference:
    slot: str
    shape: str
    scope: str
    refresh_boundary: str
    variation_semantic: str | None
    selections: tuple[RuntimeProfileSelectionReference, ...]


@dataclass(frozen=True)
class RuntimeProfileClock:
    schema_version: int | None
    fingerprint: str


@dataclass(frozen=True)
class MountGraphClock:
    schema_version: int
    graph_id: str
    runtime_id: str
    generation: int
    profile_fingerprint: str
    assembly_fingerprint: str


@dataclass(frozen=True)
class RegistrationInventoryClock:
    schema_version: int
    graph_id: str
    mount_generation: int
    revision: str


@dataclass(frozen=True)
class ModelSurfaceReference:
    schema_version: int
    snapshot_id: str
    product_id: str
    runtime_id: str
    profile_fingerprint: str
    mount_generation: int
    registration_revision: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Model Surface reference schema version")
        for value, name in (
            (self.snapshot_id, "Model Surface snapshot id"),
            (self.product_id, "Model Surface Product id"),
            (self.runtime_id, "Model Surface runtime id"),
        ):
            _require_text(value, name=name)
        _require_fingerprint(
            self.profile_fingerprint,
            name="Model Surface Profile fingerprint",
        )
        _require_non_negative_int(
            self.mount_generation,
            name="Model Surface Mount generation",
        )
        _require_fingerprint(
            self.registration_revision,
            name="Model Surface registration revision",
        )


@dataclass(frozen=True)
class EffectiveRuntimeClocks:
    profile: RuntimeProfileClock
    mount: MountGraphClock
    registration: RegistrationInventoryClock
    model_surface: ModelSurfaceReference | None


@dataclass(frozen=True)
class EffectiveRuntimeSkew:
    code: EffectiveRuntimeSkewCode
    left_clock: str
    left_value: str
    right_clock: str
    right_value: str
    classification: Literal["clock_skew"] = "clock_skew"


@dataclass(frozen=True)
class EffectiveRuntimeView:
    schema_version: int
    product_id: str
    runtime_id: str
    clocks: EffectiveRuntimeClocks
    profile_slots: tuple[RuntimeProfileSlotReference, ...]
    capabilities: tuple[MountNodeSnapshot, ...]
    registrations: tuple[RegistrationInventoryEntry, ...]
    skew: tuple[EffectiveRuntimeSkew, ...]
    assembly_fingerprint: str


@dataclass(frozen=True)
class EffectiveRuntimeDiff:
    schema_version: int
    product_id: str
    runtime_id: str
    before_clocks: EffectiveRuntimeClocks
    after_clocks: EffectiveRuntimeClocks
    before_skew: tuple[EffectiveRuntimeSkew, ...]
    after_skew: tuple[EffectiveRuntimeSkew, ...]
    profile_changed: bool
    mount_graph_changed: bool
    mount_generation_changed: bool
    registration_revision_changed: bool
    model_surface_changed: bool
    added_profile_slots: tuple[str, ...]
    removed_profile_slots: tuple[str, ...]
    replaced_profile_slots: tuple[str, ...]
    added_capability_ids: tuple[str, ...]
    removed_capability_ids: tuple[str, ...]
    replaced_capability_ids: tuple[str, ...]
    added_registration_ids: tuple[str, ...]
    removed_registration_ids: tuple[str, ...]
    replaced_registration_ids: tuple[str, ...]


def compose_effective_runtime_view(
    graph: MountGraphSnapshot,
    registrations: RegistrationInventorySnapshot,
    profile: RuntimeProfileSnapshot,
    *,
    model_surface: ModelSurfaceReference | None = None,
) -> EffectiveRuntimeView:
    if not isinstance(profile, RuntimeProfileSnapshot):
        raise TypeError("effective runtime view requires RuntimeProfileSnapshot")
    if profile.schema_version != 1:
        raise ValueError("unsupported Runtime Profile snapshot schema version")
    if graph.schema_version != 1 or registrations.schema_version != 1:
        raise ValueError("unsupported effective runtime source schema version")
    if profile.product_id != graph.product_id:
        raise ValueError("Runtime Profile and Mount graph Product ids differ")
    if (
        registrations.graph_id != graph.graph_id
        or registrations.runtime_id != graph.runtime_id
    ):
        raise ValueError("registration inventory and Mount graph ids differ")
    _require_model_surface_identity(graph, model_surface)
    clocks = effective_runtime_clocks(
        graph,
        registrations,
        profile=profile,
        model_surface=model_surface,
    )
    profile_slots = _profile_slots(profile)
    skew = _clock_skew(clocks)
    payload = {
        "schema_version": EFFECTIVE_RUNTIME_SCHEMA_VERSION,
        "product_id": graph.product_id,
        "runtime_id": graph.runtime_id,
        "clocks": clocks,
        "profile_slots": profile_slots,
        "capabilities": graph.nodes,
        "registrations": registrations.entries,
        "skew": skew,
    }
    return EffectiveRuntimeView(
        schema_version=EFFECTIVE_RUNTIME_SCHEMA_VERSION,
        product_id=graph.product_id,
        runtime_id=graph.runtime_id,
        clocks=clocks,
        profile_slots=profile_slots,
        capabilities=graph.nodes,
        registrations=registrations.entries,
        skew=skew,
        assembly_fingerprint=_fingerprint(payload),
    )


def compose_registration_inventory(
    base: RegistrationInventorySnapshot,
    supplemental: tuple[RegistrationInventoryEntry, ...],
) -> RegistrationInventorySnapshot:
    if not isinstance(base, RegistrationInventorySnapshot):
        raise TypeError("registration composition requires an inventory snapshot")
    by_id = {entry.registration_id: entry for entry in base.entries}
    for entry in supplemental:
        if not isinstance(entry, RegistrationInventoryEntry):
            raise TypeError(
                "supplemental registrations must be RegistrationInventoryEntry values"
            )
        existing = by_id.get(entry.registration_id)
        if existing is not None and existing != entry:
            raise ValueError("registration id maps to conflicting inventory entries")
        by_id[entry.registration_id] = entry
    entries = tuple(
        sorted(
            by_id.values(),
            key=lambda entry: (
                entry.owner_id,
                entry.surface,
                entry.public_key or "",
                entry.registration_id,
            ),
        )
    )
    revision = _fingerprint(
        {
            "entries": entries,
            "graph_id": base.graph_id,
            "mount_generation": base.mount_generation,
            "schema_version": base.schema_version,
        }
    )
    return RegistrationInventorySnapshot(
        schema_version=base.schema_version,
        graph_id=base.graph_id,
        runtime_id=base.runtime_id,
        mount_generation=base.mount_generation,
        revision=revision,
        entries=entries,
    )


def effective_runtime_clocks(
    graph: MountGraphSnapshot,
    registrations: RegistrationInventorySnapshot,
    *,
    profile: RuntimeProfileSnapshot | None,
    model_surface: ModelSurfaceReference | None,
) -> EffectiveRuntimeClocks:
    if profile is not None:
        if not isinstance(profile, RuntimeProfileSnapshot):
            raise TypeError("runtime clocks require RuntimeProfileSnapshot")
        if profile.product_id != graph.product_id:
            raise ValueError("Runtime Profile and Mount graph Product ids differ")
    _require_model_surface_identity(graph, model_surface)
    return EffectiveRuntimeClocks(
        profile=RuntimeProfileClock(
            schema_version=profile.schema_version if profile is not None else None,
            fingerprint=(
                runtime_profile_fingerprint(profile)
                if profile is not None
                else graph.profile_fingerprint
            ),
        ),
        mount=MountGraphClock(
            schema_version=graph.schema_version,
            graph_id=graph.graph_id,
            runtime_id=graph.runtime_id,
            generation=graph.generation,
            profile_fingerprint=graph.profile_fingerprint,
            assembly_fingerprint=graph.assembly_fingerprint,
        ),
        registration=RegistrationInventoryClock(
            schema_version=registrations.schema_version,
            graph_id=registrations.graph_id,
            mount_generation=registrations.mount_generation,
            revision=registrations.revision,
        ),
        model_surface=model_surface,
    )


def runtime_profile_fingerprint(profile: RuntimeProfileSnapshot) -> str:
    """Return the canonical fingerprint for one immutable Profile fact."""

    if not isinstance(profile, RuntimeProfileSnapshot):
        raise TypeError("Profile fingerprint requires RuntimeProfileSnapshot")
    if profile.schema_version != 1:
        raise ValueError("unsupported Runtime Profile snapshot schema version")
    return _fingerprint(profile.to_json())


def diff_effective_runtime_views(
    before: EffectiveRuntimeView,
    after: EffectiveRuntimeView,
) -> EffectiveRuntimeDiff:
    if not isinstance(before, EffectiveRuntimeView) or not isinstance(
        after,
        EffectiveRuntimeView,
    ):
        raise TypeError("effective runtime diff requires two EffectiveRuntimeViews")
    if (
        before.schema_version != EFFECTIVE_RUNTIME_SCHEMA_VERSION
        or after.schema_version != EFFECTIVE_RUNTIME_SCHEMA_VERSION
    ):
        raise ValueError("unsupported effective runtime view schema version")
    if before.product_id != after.product_id or before.runtime_id != after.runtime_id:
        raise ValueError("effective runtime diff requires one Product/runtime")
    before_slots = {item.slot: item for item in before.profile_slots}
    after_slots = {item.slot: item for item in after.profile_slots}
    before_nodes = {item.capability_id: item for item in before.capabilities}
    after_nodes = {item.capability_id: item for item in after.capabilities}
    before_registrations = {
        item.registration_id: item for item in before.registrations
    }
    after_registrations = {
        item.registration_id: item for item in after.registrations
    }
    return EffectiveRuntimeDiff(
        schema_version=EFFECTIVE_RUNTIME_SCHEMA_VERSION,
        product_id=before.product_id,
        runtime_id=before.runtime_id,
        before_clocks=before.clocks,
        after_clocks=after.clocks,
        before_skew=before.skew,
        after_skew=after.skew,
        profile_changed=(
            before.clocks.profile.fingerprint != after.clocks.profile.fingerprint
        ),
        mount_graph_changed=(
            before.clocks.mount.graph_id != after.clocks.mount.graph_id
        ),
        mount_generation_changed=(
            before.clocks.mount.generation != after.clocks.mount.generation
        ),
        registration_revision_changed=(
            before.clocks.registration.revision
            != after.clocks.registration.revision
        ),
        model_surface_changed=(
            before.clocks.model_surface != after.clocks.model_surface
        ),
        added_profile_slots=_added(before_slots, after_slots),
        removed_profile_slots=_removed(before_slots, after_slots),
        replaced_profile_slots=_replaced(before_slots, after_slots),
        added_capability_ids=_added(before_nodes, after_nodes),
        removed_capability_ids=_removed(before_nodes, after_nodes),
        replaced_capability_ids=_replaced(before_nodes, after_nodes),
        added_registration_ids=_added(before_registrations, after_registrations),
        removed_registration_ids=_removed(before_registrations, after_registrations),
        replaced_registration_ids=_replaced(
            before_registrations,
            after_registrations,
        ),
    )


def runtime_projection_to_json(value: object) -> dict[str, JSONValue]:
    projected = _json_value(value)
    if not isinstance(projected, dict):
        raise TypeError("runtime projection must encode as a JSON object")
    return projected


def _profile_slots(
    profile: RuntimeProfileSnapshot,
) -> tuple[RuntimeProfileSlotReference, ...]:
    return tuple(
        RuntimeProfileSlotReference(
            slot=capability.slot,
            shape=capability.shape,
            scope=capability.scope,
            refresh_boundary=capability.refresh_boundary,
            variation_semantic=capability.variation_semantic,
            selections=tuple(
                RuntimeProfileSelectionReference(
                    implementation=selection.implementation,
                    implementation_version=selection.implementation_version,
                    source=selection.source,
                    layer_id=selection.layer_id,
                    layer_priority=selection.layer_priority,
                    selection_priority=selection.selection_priority,
                )
                for selection in capability.selections
            ),
        )
        for capability in profile.capabilities
    )


def _clock_skew(clocks: EffectiveRuntimeClocks) -> tuple[EffectiveRuntimeSkew, ...]:
    skew: list[EffectiveRuntimeSkew] = []
    if clocks.profile.fingerprint != clocks.mount.profile_fingerprint:
        skew.append(
            _skew(
                "profile_mount_reference_skew",
                "profile.fingerprint",
                clocks.profile.fingerprint,
                "mount.profile_fingerprint",
                clocks.mount.profile_fingerprint,
            )
        )
    registration_mount = (
        f"{clocks.registration.graph_id}@{clocks.registration.mount_generation}"
    )
    mount = f"{clocks.mount.graph_id}@{clocks.mount.generation}"
    if registration_mount != mount:
        skew.append(
            _skew(
                "registration_mount_reference_skew",
                "registration.mount",
                registration_mount,
                "mount.generation",
                mount,
            )
        )
    model = clocks.model_surface
    if model is not None:
        if model.runtime_id != clocks.mount.runtime_id:
            skew.append(
                _skew(
                    "model_runtime_reference_skew",
                    "model_surface.runtime_id",
                    model.runtime_id,
                    "mount.runtime_id",
                    clocks.mount.runtime_id,
                )
            )
        if model.profile_fingerprint != clocks.profile.fingerprint:
            skew.append(
                _skew(
                    "model_profile_reference_skew",
                    "model_surface.profile_fingerprint",
                    model.profile_fingerprint,
                    "profile.fingerprint",
                    clocks.profile.fingerprint,
                )
            )
        if model.mount_generation != clocks.mount.generation:
            skew.append(
                _skew(
                    "model_mount_reference_skew",
                    "model_surface.mount_generation",
                    model.mount_generation,
                    "mount.generation",
                    clocks.mount.generation,
                )
            )
        if model.registration_revision != clocks.registration.revision:
            skew.append(
                _skew(
                    "model_registration_reference_skew",
                    "model_surface.registration_revision",
                    model.registration_revision,
                    "registration.revision",
                    clocks.registration.revision,
                )
            )
    return tuple(sorted(skew, key=lambda item: item.code))


def _require_model_surface_identity(
    graph: MountGraphSnapshot,
    model_surface: ModelSurfaceReference | None,
) -> None:
    if model_surface is None:
        return
    if not isinstance(model_surface, ModelSurfaceReference):
        raise TypeError("model_surface must be ModelSurfaceReference")
    if model_surface.product_id != graph.product_id:
        raise ValueError("Model Surface and Mount graph Product ids differ")


def _skew(
    code: EffectiveRuntimeSkewCode,
    left_clock: str,
    left_value: object,
    right_clock: str,
    right_value: object,
) -> EffectiveRuntimeSkew:
    return EffectiveRuntimeSkew(
        code=code,
        left_clock=left_clock,
        left_value=str(left_value),
        right_clock=right_clock,
        right_value=str(right_value),
    )


def _added(before: Mapping[str, object], after: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(sorted(after.keys() - before.keys()))


def _removed(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> tuple[str, ...]:
    return tuple(sorted(before.keys() - after.keys()))


def _replaced(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            key
            for key in before.keys() & after.keys()
            if before[key] != after[key]
        )
    )


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        _json_value(value),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_value(value: object) -> JSONValue:
    if value is None or type(value) in {str, bool, int, float}:
        return cast(JSONValue, value)
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("runtime projection JSON keys must be strings")
        return {cast(str, key): _json_value(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    raise TypeError(
        "runtime projection contains a non-JSON value: "
        f"{type(value).__name__}"
    )


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _require_fingerprint(value: object, *, name: str) -> str:
    normalized = _require_text(value, name=name)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{name} must be lowercase SHA-256 hex")
    return normalized


def _require_non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


__all__ = [
    "EFFECTIVE_RUNTIME_SCHEMA_VERSION",
    "EffectiveRuntimeClocks",
    "EffectiveRuntimeDiff",
    "EffectiveRuntimeSkew",
    "EffectiveRuntimeView",
    "ModelSurfaceReference",
    "MountGraphClock",
    "RegistrationInventoryClock",
    "RuntimeProfileClock",
    "RuntimeProfileSelectionReference",
    "RuntimeProfileSlotReference",
    "compose_effective_runtime_view",
    "compose_registration_inventory",
    "diff_effective_runtime_views",
    "effective_runtime_clocks",
    "runtime_projection_to_json",
    "runtime_profile_fingerprint",
]
