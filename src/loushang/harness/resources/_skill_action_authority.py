"""Private live Resource-owner registry for Catalog-managed Skill actions."""

from __future__ import annotations

import hashlib
import os
import stat
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True, init=False)
class _CatalogActionOwnerCapability:
    """Opaque capability held only by one Resource Catalog consumer."""

    owner_identity: object

    def __init__(self) -> None:
        raise TypeError("Catalog action owner capabilities are Resource-owner-minted")


@dataclass(frozen=True, slots=True)
class _CatalogActionFact:
    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    skill_content_digest: str
    source_kind: str
    source_revision: str
    action_document_digest: str
    capture_fingerprint: str
    declaration: tuple[object, ...]
    script_body: bytes
    skill_root: str
    skill_root_identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _CatalogActionOwnerRecord:
    consumer_ref: Callable[[], object | None]
    consumer_type: type[object]
    capability: _CatalogActionOwnerCapability
    owner_identity: object
    catalog: object
    catalog_generation: int
    snapshot_fingerprint: str
    action_facts: tuple[_CatalogActionFact, ...]


@dataclass(frozen=True, slots=True)
class _CatalogActionRegistration:
    action_ref: weakref.ReferenceType[object]
    consumer: object
    capability: _CatalogActionOwnerCapability
    owner_identity: object
    fact: _CatalogActionFact


_OWNER_CAPABILITIES: dict[int, _CatalogActionOwnerRecord] = {}
_REGISTRATIONS: dict[int, _CatalogActionRegistration] = {}


def _bind_catalog_action_owner(
    consumer: object,
    *,
    owner_identity: object,
) -> _CatalogActionOwnerCapability:
    """Freeze the action facts owned by one complete Catalog projection."""

    if (
        type(owner_identity) is not object
        or getattr(consumer, "_managed_action_owner_identity", None)
        is not owner_identity
        or getattr(consumer, "_managed_action_owner_capability", None) is not None
    ):
        raise TypeError("Catalog action owner requires a bound Resource consumer")
    catalog = getattr(consumer, "_catalog", None)
    catalog_generation = getattr(consumer, "_catalog_generation", None)
    snapshot_fingerprint = getattr(consumer, "_snapshot_fingerprint", None)
    if (
        catalog is None
        or type(catalog_generation) is not int
        or not isinstance(snapshot_fingerprint, str)
    ):
        raise TypeError("Catalog action owner consumer is not fully bound")
    action_facts = _consumer_action_facts(consumer)
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
        consumer_type=type(consumer),
        capability=capability,
        owner_identity=owner_identity,
        catalog=catalog,
        catalog_generation=catalog_generation,
        snapshot_fingerprint=snapshot_fingerprint,
        action_facts=action_facts,
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
    fact = _action_fact(action)
    if (
        fact not in owner.action_facts
        or getattr(action, "_owner_identity", None) is not owner.owner_identity
        or getattr(getattr(action, "selection", None), "_owner_identity", None)
        is not owner.owner_identity
    ):
        raise ValueError("Catalog action does not match its Resource owner")
    action_id = id(action)
    if action_id in _REGISTRATIONS:
        raise RuntimeError("Catalog action identity is already registered")
    consumer = owner.consumer_ref()
    assert consumer is not None

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
        fact=fact,
    )


def _verify_catalog_managed_skill_action(action: object) -> None:
    """Require a live exact registration minted from frozen owner facts."""

    registration = _REGISTRATIONS.get(id(action))
    if registration is None or registration.action_ref() is not action:
        raise ValueError("Catalog action is not live Resource-owner evidence")
    fact = _action_fact(action)
    owner = _verified_owner_record(registration.capability)
    if (
        owner is None
        or registration.fact not in owner.action_facts
        or fact != registration.fact
        or getattr(action, "_owner_identity", None) is not registration.owner_identity
        or getattr(getattr(action, "selection", None), "_owner_identity", None)
        is not registration.owner_identity
    ):
        raise ValueError("Catalog action is not live Resource-owner evidence")


def _verified_owner_record(
    capability: _CatalogActionOwnerCapability,
) -> _CatalogActionOwnerRecord | None:
    if type(capability) is not _CatalogActionOwnerCapability:
        return None
    record = _OWNER_CAPABILITIES.get(id(capability))
    consumer = record.consumer_ref() if record is not None else None
    if (
        record is None
        or record.capability is not capability
        or consumer is None
        or type(consumer) is not record.consumer_type
        or capability.owner_identity is not record.owner_identity
        or getattr(consumer, "_managed_action_owner_identity", None)
        is not record.owner_identity
        or getattr(consumer, "_managed_action_owner_capability", None) is not capability
        or getattr(consumer, "_catalog", None) is not record.catalog
        or getattr(consumer, "_catalog_generation", None) != record.catalog_generation
        or getattr(consumer, "_snapshot_fingerprint", None)
        != record.snapshot_fingerprint
    ):
        return None
    try:
        current_facts = _consumer_action_facts(consumer)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return record if current_facts == record.action_facts else None


def _consumer_action_facts(consumer: object) -> tuple[_CatalogActionFact, ...]:
    summaries = getattr(consumer, "_skills", None)
    sources = getattr(consumer, "_managed_action_sources", None)
    if type(summaries) is not tuple or type(sources) is not dict:
        raise TypeError("Catalog action owner facts require a complete projection")
    summaries_by_candidate = {
        getattr(summary, "candidate_fingerprint"): summary for summary in summaries
    }
    if len(summaries_by_candidate) != len(summaries):
        raise ValueError("Catalog action owner candidates must be unique")
    facts: list[_CatalogActionFact] = []
    for candidate_fingerprint, source in sources.items():
        summary = summaries_by_candidate.get(candidate_fingerprint)
        if (
            summary is None
            or getattr(source, "candidate_fingerprint", None) != candidate_fingerprint
        ):
            raise ValueError("Catalog action source is outside its owner projection")
        capture = getattr(source, "capture")
        root, root_identity = _root_fact(getattr(source, "skill_root"))
        actions = getattr(capture, "actions")
        if type(actions) is not tuple or not actions:
            raise ValueError("Catalog action source capture must not be empty")
        for item in actions:
            declaration = getattr(item, "declaration")
            script_body = getattr(item, "script_body")
            if type(script_body) is not bytes or hashlib.sha256(
                script_body
            ).hexdigest() != getattr(declaration, "script_digest", None):
                raise ValueError("Catalog action source script evidence changed")
            facts.append(
                _CatalogActionFact(
                    catalog_generation=getattr(summary, "catalog_generation"),
                    catalog_snapshot_fingerprint=getattr(
                        summary,
                        "catalog_snapshot_fingerprint",
                    ),
                    candidate_fingerprint=candidate_fingerprint,
                    skill_content_digest=getattr(
                        summary,
                        "expected_content_digest",
                    ),
                    source_kind=getattr(capture, "source_kind"),
                    source_revision=getattr(capture, "source_revision"),
                    action_document_digest=getattr(
                        capture,
                        "action_document_digest",
                    ),
                    capture_fingerprint=getattr(capture, "capture_fingerprint"),
                    declaration=_declaration_fact(declaration),
                    script_body=script_body,
                    skill_root=root,
                    skill_root_identity=root_identity,
                )
            )
    ordered = tuple(
        sorted(
            facts,
            key=lambda fact: (
                fact.candidate_fingerprint,
                str(fact.declaration[1]),
            ),
        )
    )
    if len(set(ordered)) != len(ordered):
        raise ValueError("Catalog action owner facts must be unique")
    return ordered


def _action_fact(action: object) -> _CatalogActionFact:
    selection = getattr(action, "selection")
    declaration = getattr(action, "declaration")
    script_body = getattr(action, "_script_body")
    if type(script_body) is not bytes or hashlib.sha256(
        script_body
    ).hexdigest() != getattr(declaration, "script_digest", None):
        raise ValueError("Catalog action script evidence changed")
    root, root_identity = _root_fact(getattr(action, "skill_root"))
    if getattr(action, "_skill_root_identity", None) != root_identity:
        raise ValueError("Catalog action root identity changed")
    return _CatalogActionFact(
        catalog_generation=getattr(selection, "catalog_generation"),
        catalog_snapshot_fingerprint=getattr(
            selection,
            "catalog_snapshot_fingerprint",
        ),
        candidate_fingerprint=getattr(selection, "candidate_fingerprint"),
        skill_content_digest=getattr(selection, "skill_content_digest"),
        source_kind=getattr(selection, "source_kind"),
        source_revision=getattr(selection, "source_revision"),
        action_document_digest=getattr(action, "action_document_digest"),
        capture_fingerprint=getattr(action, "_source_capture_fingerprint"),
        declaration=_declaration_fact(declaration),
        script_body=script_body,
        skill_root=root,
        skill_root_identity=root_identity,
    )


def _declaration_fact(declaration: object) -> tuple[object, ...]:
    effects = tuple(
        (getattr(effect, "kind"), getattr(effect, "target"))
        for effect in getattr(declaration, "effects")
    )
    return (
        getattr(declaration, "declaration_version"),
        getattr(declaration, "action_id"),
        getattr(declaration, "script"),
        getattr(declaration, "script_digest"),
        getattr(declaration, "runtime"),
        tuple(getattr(declaration, "argv")),
        getattr(declaration, "cwd_policy"),
        tuple(tuple(item) for item in getattr(declaration, "environment")),
        effects,
        getattr(declaration, "containment"),
    )


def _root_fact(root: object) -> tuple[str, tuple[int, int]]:
    if not isinstance(root, str | os.PathLike):
        raise TypeError("Catalog action root must be path-like")
    path = Path(root)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("Catalog action root must be a resolved absolute directory")
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Catalog action root must be a directory")
    return str(path), (metadata.st_dev, metadata.st_ino)


__all__: list[str] = []
