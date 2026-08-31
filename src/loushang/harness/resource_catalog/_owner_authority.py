"""Resource-specific exact-factory facts for prepared owner generations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import PurePath

from loushang.harness.resources._catalog_records import ResourceCatalogSnapshot
from loushang.harness.resources._skill_action_authority import (
    _CatalogActionOwnerSnapshot,
    _freeze_catalog_action_owner_snapshot,
)
from loushang.harness.resources._skill_catalog_consumer import (
    build_effective_skill_catalog_projection,
)


@dataclass(frozen=True, slots=True, init=False)
class _ResourceOwnerFactoryIdentity:
    """Opaque identity issued inline by the exact Resource owner factory."""

    def __init__(self) -> None:
        raise TypeError("Resource owner generations are factory-minted")


@dataclass(slots=True)
class _ResourceOwnerLifecycle:
    ownership: str = "root_owned"
    retirement_owner: str | None = None
    active_loads: int = 0
    cleanup_started: bool = False


@dataclass(frozen=True, slots=True)
class _ResourceOwnerFactoryRecord:
    owner_ref: Callable[[], object | None]
    identity: _ResourceOwnerFactoryIdentity
    runtime_id: str
    catalog_generation: int
    provider_binding_fingerprint: str
    shadow: object
    resolution: object
    resolution_fact: object
    catalog_snapshot_fact: object
    source_snapshots_fact: object
    catalog_projection_fact: object
    skill_status_projection_fact: object
    runtime: object
    binder: object
    extension_source_lease: object | None
    dispose_lock: asyncio.Lock
    loads_drained: asyncio.Event
    action_snapshot: _CatalogActionOwnerSnapshot | None
    lifecycle: _ResourceOwnerLifecycle


_RESOURCE_OWNER_FACTORIES: dict[int, _ResourceOwnerFactoryRecord] = {}
_RESOURCE_OWNER_FACTORY_IDENTITIES: dict[int, int] = {}


def _freeze_resource_owner_action_snapshot(
    shadow: object,
) -> _CatalogActionOwnerSnapshot | None:
    snapshot = getattr(shadow, "catalog_snapshot", None)
    projection = getattr(shadow, "catalog_projection", None)
    if projection is None:
        return None
    if not isinstance(snapshot, ResourceCatalogSnapshot):
        raise TypeError("Resource owner action facts require a Catalog snapshot")
    effective = build_effective_skill_catalog_projection(
        snapshot=snapshot,
        projection=projection,
    )
    return _freeze_catalog_action_owner_snapshot(effective)


def _is_resource_owner_factory_recorded(owner: object) -> bool:
    record = _resource_owner_factory_record(owner)
    shadow = getattr(owner, "_shadow", None)
    if record is None or shadow is not record.shadow:
        return False
    try:
        current_action_snapshot = _freeze_resource_owner_action_snapshot(shadow)
        resolution = getattr(shadow, "resolution", None)
        resolution_fact = _freeze_resource_owner_resolution_fact(resolution)
        catalog_snapshot_fact = _freeze_resource_owner_fact(
            getattr(shadow, "catalog_snapshot", None)
        )
        source_snapshots_fact = _freeze_resource_owner_fact(
            getattr(shadow, "source_snapshots", None)
        )
        catalog_projection_fact = _freeze_resource_owner_fact(
            getattr(shadow, "catalog_projection", None)
        )
        skill_status_projection_fact = _freeze_resource_owner_fact(
            getattr(shadow, "skill_status_projection", None)
        )
    except (TypeError, ValueError, RuntimeError, KeyError, OSError):
        return False
    return bool(
        getattr(owner, "runtime_id", None) == record.runtime_id
        and getattr(owner, "catalog_generation", None) == record.catalog_generation
        and getattr(owner, "provider_binding_fingerprint", None)
        == record.provider_binding_fingerprint
        and resolution is record.resolution
        and resolution_fact == record.resolution_fact
        and catalog_snapshot_fact == record.catalog_snapshot_fact
        and source_snapshots_fact == record.source_snapshots_fact
        and catalog_projection_fact == record.catalog_projection_fact
        and skill_status_projection_fact == record.skill_status_projection_fact
        and getattr(shadow, "_runtime", None) is record.runtime
        and getattr(shadow, "_binder", None) is record.binder
        and getattr(shadow, "_extension_source_lease", None)
        is record.extension_source_lease
        and getattr(shadow, "_dispose_lock", None) is record.dispose_lock
        and getattr(shadow, "_loads_drained", None) is record.loads_drained
        and getattr(owner, "_ownership", None) == record.lifecycle.ownership
        and getattr(owner, "_retirement_owner", None)
        == record.lifecycle.retirement_owner
        and getattr(shadow, "_disposed", None)
        is (record.lifecycle.ownership == "disposed")
        and getattr(shadow, "_retiring", None)
        is (record.lifecycle.ownership == "retiring")
        and getattr(shadow, "_active_loads", None) == record.lifecycle.active_loads
        and current_action_snapshot == record.action_snapshot
    )


def _resource_owner_factory_record(
    owner: object,
) -> _ResourceOwnerFactoryRecord | None:
    identity = getattr(owner, "_resource_owner_factory_identity", None)
    record = (
        _RESOURCE_OWNER_FACTORIES.get(id(identity))
        if type(identity) is _ResourceOwnerFactoryIdentity
        else None
    )
    if (
        record is None
        or record.identity is not identity
        or record.owner_ref() is not owner
    ):
        return None
    return record


def _recorded_resource_owner_shadow(owner: object) -> object | None:
    """Return the original factory shadow for retryable cleanup."""

    identity_id = _RESOURCE_OWNER_FACTORY_IDENTITIES.get(id(owner))
    record = (
        _RESOURCE_OWNER_FACTORIES.get(identity_id)
        if identity_id is not None
        else None
    )
    if record is None or record.owner_ref() is not owner:
        return None
    return record.shadow


def _recorded_resource_owner_factory_record(
    owner: object,
) -> _ResourceOwnerFactoryRecord | None:
    identity_id = _RESOURCE_OWNER_FACTORY_IDENTITIES.get(id(owner))
    record = (
        _RESOURCE_OWNER_FACTORIES.get(identity_id)
        if identity_id is not None
        else None
    )
    if record is None or record.owner_ref() is not owner:
        return None
    return record


def _restore_recorded_resource_owner_cleanup_shadow(owner: object) -> object | None:
    """Restore only original operational dependencies before owner cleanup."""

    shadow = _recorded_resource_owner_shadow(owner)
    record = _recorded_resource_owner_factory_record(owner)
    if record is None or shadow is None or record.owner_ref() is not owner:
        return shadow
    setattr(shadow, "_runtime", record.runtime)
    setattr(shadow, "_binder", record.binder)
    setattr(shadow, "_extension_source_lease", record.extension_source_lease)
    setattr(shadow, "_dispose_lock", record.dispose_lock)
    setattr(shadow, "_loads_drained", record.loads_drained)
    if record.lifecycle.ownership != "disposed":
        setattr(shadow, "_disposed", False)
        setattr(shadow, "_retiring", record.lifecycle.cleanup_started)
        setattr(shadow, "_active_loads", record.lifecycle.active_loads)
        if record.lifecycle.active_loads:
            record.loads_drained.clear()
        else:
            record.loads_drained.set()
    record.lifecycle.cleanup_started = True
    return shadow


def _begin_recorded_resource_owner_load(owner: object) -> None:
    record = _resource_owner_factory_record(owner)
    if record is None:
        raise TypeError("Resource owner load lost factory authority")
    record.lifecycle.active_loads += 1


def _finish_recorded_resource_owner_load(owner: object) -> None:
    record = _recorded_resource_owner_factory_record(owner)
    if record is None or record.lifecycle.active_loads < 1:
        raise RuntimeError("Resource owner load custody is corrupt")
    record.lifecycle.active_loads -= 1


def _resource_owner_action_snapshot(
    owner: object,
) -> _CatalogActionOwnerSnapshot | None:
    if not _is_resource_owner_factory_recorded(owner):
        raise TypeError(
            "Resource owner operation requires an unchanged factory-recorded "
            "generation"
        )
    record = _resource_owner_factory_record(owner)
    assert record is not None
    return record.action_snapshot


def _freeze_resource_owner_fact(value: object) -> object:
    """Project a caller-reachable logical graph to immutable primitive facts."""

    return _freeze_resource_owner_value(value, active=set())


def _freeze_resource_owner_resolution_fact(resolution: object) -> object:
    """Freeze public resolution facts while retaining opaque authority identity."""

    definitions = getattr(resolution, "definitions")
    candidates = getattr(resolution, "candidates")
    admissions = getattr(resolution, "admissions")
    resolved_set = getattr(resolution, "resolved_set")
    authorities = getattr(resolution, "authorities")
    bindings = getattr(resolution, "bindings")
    return (
        _freeze_resource_owner_fact(definitions),
        _freeze_resource_owner_fact(candidates),
        _freeze_resource_owner_fact(admissions),
        _freeze_resource_owner_fact(resolved_set),
        tuple((type(item), id(item)) for item in authorities),
        tuple(
            (
                type(item),
                id(item),
                getattr(item, "binding_fingerprint", None),
            )
            for item in bindings
        ),
    )


def _freeze_resource_owner_value(value: object, *, active: set[int]) -> object:
    if value is None or type(value) in {bool, int, float, str, bytes}:
        return value
    if isinstance(value, PurePath):
        return ("path", type(value).__module__, type(value).__qualname__, str(value))
    if isinstance(value, Enum):
        return (
            "enum",
            type(value).__module__,
            type(value).__qualname__,
            _freeze_resource_owner_value(value.value, active=active),
        )
    identity = id(value)
    if identity in active:
        raise ValueError("Resource owner logical facts must not contain cycles")
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            items = tuple(
                sorted(
                    (
                        (
                            _freeze_resource_owner_value(key, active=active),
                            _freeze_resource_owner_value(item, active=active),
                        )
                        for key, item in value.items()
                    ),
                    key=repr,
                )
            )
            return ("mapping", items)
        if isinstance(value, tuple | list):
            return (
                "sequence",
                type(value).__qualname__,
                tuple(
                    _freeze_resource_owner_value(item, active=active)
                    for item in value
                ),
            )
        if isinstance(value, set | frozenset):
            return (
                "set",
                type(value).__qualname__,
                tuple(
                    sorted(
                        (
                            _freeze_resource_owner_value(item, active=active)
                            for item in value
                        ),
                        key=repr,
                    )
                ),
            )
        if is_dataclass(value) and not isinstance(value, type):
            return (
                "dataclass",
                type(value).__module__,
                type(value).__qualname__,
                tuple(
                    (
                        item.name,
                        _freeze_resource_owner_value(
                            getattr(value, item.name),
                            active=active,
                        ),
                    )
                    for item in fields(value)
                ),
            )
    finally:
        active.remove(identity)
    raise TypeError(
        "Resource owner logical fact has an unsupported value: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


__all__: list[str] = []
