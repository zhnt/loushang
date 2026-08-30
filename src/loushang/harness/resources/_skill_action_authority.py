"""Private live Resource-owner registry for Catalog-managed Skill actions."""

from __future__ import annotations

import sys
import weakref
from collections.abc import Callable
from dataclasses import dataclass

_CONSUMER_MODULE = "loushang.harness.resources._skill_catalog_consumer"
_CONSUMER_TYPE = "SkillCatalogConsumer"
_CONSUMER_VERIFIER = "_verify_managed_action_owner_candidate"


@dataclass(frozen=True, slots=True, init=False)
class _CatalogActionOwnerCapability:
    """Opaque capability held only by one exact Skill Catalog consumer."""

    owner_identity: object

    def __init__(self) -> None:
        raise TypeError("Catalog action owner capabilities are Resource-owner-minted")


@dataclass(frozen=True, slots=True)
class _CatalogActionOwnerRecord:
    consumer_ref: Callable[[], object | None]
    capability: _CatalogActionOwnerCapability
    owner_identity: object
    verifier: Callable[[object, object], None]
    consumer_type: type[object]
    catalog: object
    catalog_generation: int
    snapshot_fingerprint: str
    projection_summaries: tuple[object, ...]
    candidates: tuple[tuple[object, object], ...]
    managed_action_sources: tuple[tuple[object, object], ...]


@dataclass(frozen=True, slots=True)
class _CatalogActionRegistration:
    action_ref: weakref.ReferenceType[object]
    consumer: object
    capability: _CatalogActionOwnerCapability
    owner_identity: object
    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    binding_source_fingerprint: str
    skill_root_identity: tuple[int, int]


_OWNER_CAPABILITIES: dict[int, _CatalogActionOwnerRecord] = {}
_REGISTRATIONS: dict[int, _CatalogActionRegistration] = {}


def _bind_catalog_action_owner(
    consumer: object,
    *,
    owner_identity: object,
) -> _CatalogActionOwnerCapability:
    """Bind action-mint authority to one canonical Resource Catalog consumer."""

    consumer_type = type(consumer)
    consumer_module = sys.modules.get(_CONSUMER_MODULE)
    verifier = consumer_type.__dict__.get(_CONSUMER_VERIFIER)
    if (
        consumer_type.__module__ != _CONSUMER_MODULE
        or consumer_type.__name__ != _CONSUMER_TYPE
        or consumer_module is None
        or getattr(consumer_module, _CONSUMER_TYPE, None) is not consumer_type
        or not callable(verifier)
        or type(owner_identity) is not object
        or getattr(consumer, "_managed_action_owner_identity", None)
        is not owner_identity
        or getattr(consumer, "_managed_action_owner_capability", None) is not None
        or _CONSUMER_VERIFIER in vars(consumer)
    ):
        raise TypeError("Catalog action owner requires the canonical Resource consumer")
    catalog = getattr(consumer, "_catalog", None)
    catalog_generation = getattr(consumer, "_catalog_generation", None)
    snapshot_fingerprint = getattr(consumer, "_snapshot_fingerprint", None)
    skills = getattr(consumer, "_skills", None)
    candidates = getattr(consumer, "_candidates", None)
    managed_action_sources = getattr(consumer, "_managed_action_sources", None)
    if (
        catalog is None
        or type(catalog_generation) is not int
        or not isinstance(snapshot_fingerprint, str)
        or type(skills) is not tuple
        or type(candidates) is not dict
        or type(managed_action_sources) is not dict
    ):
        raise TypeError("Catalog action owner consumer is not fully bound")
    capability = object.__new__(_CatalogActionOwnerCapability)
    object.__setattr__(capability, "owner_identity", owner_identity)
    capability_id = id(capability)

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _OWNER_CAPABILITIES.get(capability_id)
        if current is not None and current.consumer_ref is reference:
            _OWNER_CAPABILITIES.pop(capability_id, None)

    consumer_ref = weakref.ref(consumer, discard)
    _OWNER_CAPABILITIES[capability_id] = _CatalogActionOwnerRecord(
        consumer_ref=consumer_ref,
        capability=capability,
        owner_identity=owner_identity,
        verifier=verifier,
        consumer_type=consumer_type,
        catalog=catalog,
        catalog_generation=catalog_generation,
        snapshot_fingerprint=snapshot_fingerprint,
        projection_summaries=skills,
        candidates=tuple(candidates.items()),
        managed_action_sources=tuple(managed_action_sources.items()),
    )
    return capability


def _register_catalog_managed_skill_action(
    action: object,
    *,
    owner_capability: _CatalogActionOwnerCapability,
) -> None:
    """Register one exact action through its live Resource-owner capability."""

    owner = _verified_owner_record(owner_capability)
    if owner is None:
        raise ValueError("Catalog action owner capability is not live")
    consumer = owner.consumer_ref()
    assert consumer is not None
    owner.verifier(consumer, action)
    action_id = id(action)
    if action_id in _REGISTRATIONS:
        raise RuntimeError("Catalog action identity is already registered")
    selection = getattr(action, "selection")

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _REGISTRATIONS.get(action_id)
        if current is not None and current.action_ref is reference:
            _REGISTRATIONS.pop(action_id, None)

    reference = weakref.ref(action, discard)
    _REGISTRATIONS[action_id] = _CatalogActionRegistration(
        action_ref=reference,
        consumer=consumer,
        capability=owner_capability,
        owner_identity=owner.owner_identity,
        catalog_generation=getattr(selection, "catalog_generation"),
        catalog_snapshot_fingerprint=getattr(
            selection,
            "catalog_snapshot_fingerprint",
        ),
        candidate_fingerprint=getattr(selection, "candidate_fingerprint"),
        binding_source_fingerprint=getattr(action, "binding_source_fingerprint"),
        skill_root_identity=getattr(action, "_skill_root_identity"),
    )


def _verify_catalog_managed_skill_action(action: object) -> None:
    """Require a live exact registration minted by the Resource owner."""

    registration = _REGISTRATIONS.get(id(action))
    selection = getattr(action, "selection", None)
    if (
        registration is None
        or registration.action_ref() is not action
        or _verified_owner_record(registration.capability) is None
        or getattr(action, "_owner_identity", None) is not registration.owner_identity
        or getattr(selection, "_owner_identity", None)
        is not registration.owner_identity
        or getattr(selection, "catalog_generation", None)
        != registration.catalog_generation
        or getattr(selection, "catalog_snapshot_fingerprint", None)
        != registration.catalog_snapshot_fingerprint
        or getattr(selection, "candidate_fingerprint", None)
        != registration.candidate_fingerprint
        or getattr(action, "binding_source_fingerprint", None)
        != registration.binding_source_fingerprint
        or getattr(action, "_skill_root_identity", None)
        != registration.skill_root_identity
    ):
        raise ValueError("Catalog action is not live Resource-owner evidence")
    owner = _OWNER_CAPABILITIES[id(registration.capability)]
    owner.verifier(registration.consumer, action)


def _verified_owner_record(
    capability: _CatalogActionOwnerCapability,
) -> _CatalogActionOwnerRecord | None:
    if type(capability) is not _CatalogActionOwnerCapability:
        return None
    record = _OWNER_CAPABILITIES.get(id(capability))
    consumer = record.consumer_ref() if record is not None else None
    consumer_type = type(consumer) if consumer is not None else None
    consumer_module = sys.modules.get(_CONSUMER_MODULE)
    candidates = getattr(consumer, "_candidates", None)
    managed_action_sources = getattr(consumer, "_managed_action_sources", None)
    if (
        record is None
        or record.capability is not capability
        or consumer is None
        or capability.owner_identity is not record.owner_identity
        or getattr(consumer, "_managed_action_owner_identity", None)
        is not record.owner_identity
        or getattr(consumer, "_managed_action_owner_capability", None) is not capability
        or getattr(consumer, "_catalog", None) is not record.catalog
        or getattr(consumer, "_catalog_generation", None) != record.catalog_generation
        or getattr(consumer, "_snapshot_fingerprint", None)
        != record.snapshot_fingerprint
        or getattr(consumer, "_skills", None) is not record.projection_summaries
        or type(candidates) is not dict
        or tuple(candidates.items()) != record.candidates
        or type(managed_action_sources) is not dict
        or tuple(managed_action_sources.items()) != record.managed_action_sources
        or consumer_type is not record.consumer_type
        or consumer_module is None
        or getattr(consumer_module, _CONSUMER_TYPE, None) is not consumer_type
        or _CONSUMER_VERIFIER in vars(consumer)
        or consumer_type.__dict__.get(_CONSUMER_VERIFIER) is not record.verifier
    ):
        return None
    return record


__all__: list[str] = []
