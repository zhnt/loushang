"""Private live Resource-owner registry for Catalog-managed Skill actions."""

from __future__ import annotations

import hashlib
import os
import stat
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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


@dataclass(frozen=True, slots=True, init=False)
class _CatalogActionOwnerSnapshot:
    """Immutable primitive facts prepared by one exact Resource owner."""

    action_facts: tuple[_CatalogActionFact, ...]

    def __init__(self) -> None:
        raise TypeError("Catalog action owner snapshots are Resource-owner-built")


@dataclass(frozen=True, slots=True, init=False)
class _CatalogActionOwnerGenerationLifecycle:
    """Opaque provenance for one authority-recorded Resource owner generation."""

    def __init__(self) -> None:
        raise TypeError("Catalog action owner lifecycle is Resource-owner-minted")


@dataclass(frozen=True, slots=True, init=False)
class _CatalogActionOwnerBinding:
    """Single-use owner construction binding consumed by one projection."""

    lifecycle: _CatalogActionOwnerGenerationLifecycle
    projection: object
    snapshot: _CatalogActionOwnerSnapshot
    owner_identity: object

    def __init__(self) -> None:
        raise TypeError("Catalog action owner bindings are Resource-owner-minted")


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class _CatalogActionOwnerLiveness:
    """Semantically neutral anchor retained by consumers and live actions."""

    def __init__(self) -> None:
        raise TypeError("Catalog action owner liveness is Resource-owner-minted")


@dataclass(slots=True)
class _CatalogActionOwnerGenerationRecord:
    owner_ref: Callable[[], object | None]
    lifecycle: _CatalogActionOwnerGenerationLifecycle
    state: Literal[
        "root_owned",
        "graph_constructing",
        "graph_owned",
        "retired",
    ]
    pending: dict[int, _CatalogActionOwnerBinding]


@dataclass(frozen=True, slots=True)
class _CatalogActionOwnerRecord:
    liveness_ref: Callable[[], object | None]
    capability: _CatalogActionOwnerCapability
    owner_identity: object
    snapshot: _CatalogActionOwnerSnapshot


@dataclass(frozen=True, slots=True)
class _CatalogActionRegistration:
    action_ref: weakref.ReferenceType[object]
    liveness: _CatalogActionOwnerLiveness
    capability: _CatalogActionOwnerCapability
    owner_identity: object
    fact: _CatalogActionFact


_OWNER_GENERATIONS: dict[int, _CatalogActionOwnerGenerationRecord] = {}
_OWNER_GENERATION_IDENTITIES: dict[int, int] = {}
_OWNER_CAPABILITIES: dict[int, _CatalogActionOwnerRecord] = {}
_REGISTRATIONS: dict[int, _CatalogActionRegistration] = {}


def _new_catalog_action_owner_generation_lifecycle(
    owner: object,
) -> _CatalogActionOwnerGenerationLifecycle:
    """Record provenance for one factory-created Resource owner generation."""

    owner_id = id(owner)
    existing_id = _OWNER_GENERATION_IDENTITIES.get(owner_id)
    if existing_id is not None:
        existing = _OWNER_GENERATIONS.get(existing_id)
        if existing is not None and existing.owner_ref() is owner:
            raise RuntimeError("Catalog action owner generation is already recorded")
        _OWNER_GENERATION_IDENTITIES.pop(owner_id, None)
    lifecycle = object.__new__(_CatalogActionOwnerGenerationLifecycle)
    lifecycle_id = id(lifecycle)

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _OWNER_GENERATIONS.get(lifecycle_id)
        if current is not None and current.owner_ref is reference:
            _OWNER_GENERATIONS.pop(lifecycle_id, None)
            if _OWNER_GENERATION_IDENTITIES.get(owner_id) == lifecycle_id:
                _OWNER_GENERATION_IDENTITIES.pop(owner_id, None)

    owner_ref = weakref.ref(owner, discard)
    _OWNER_GENERATIONS[lifecycle_id] = _CatalogActionOwnerGenerationRecord(
        owner_ref=owner_ref,
        lifecycle=lifecycle,
        state="root_owned",
        pending={},
    )
    _OWNER_GENERATION_IDENTITIES[owner_id] = lifecycle_id
    return lifecycle


def _begin_catalog_action_owner_generation(
    lifecycle: _CatalogActionOwnerGenerationLifecycle,
    *,
    owner: object,
) -> None:
    record = _require_owner_generation_record(lifecycle, owner=owner)
    if record.state != "root_owned":
        raise RuntimeError("Catalog action owner generation cannot begin graph claim")
    record.state = "graph_constructing"


def _commit_catalog_action_owner_generation(
    lifecycle: _CatalogActionOwnerGenerationLifecycle,
    *,
    owner: object,
) -> None:
    record = _require_owner_generation_record(lifecycle, owner=owner)
    if record.state != "graph_constructing":
        raise RuntimeError("Catalog action owner graph claim was not started")
    record.state = "graph_owned"


def _restore_catalog_action_owner_generation(
    lifecycle: _CatalogActionOwnerGenerationLifecycle,
    *,
    owner: object,
) -> None:
    record = _require_owner_generation_record(lifecycle, owner=owner)
    if record.state != "graph_constructing":
        raise RuntimeError("Catalog action owner graph claim is not in progress")
    record.pending.clear()
    record.state = "root_owned"


def _retire_catalog_action_owner_generation(
    lifecycle: _CatalogActionOwnerGenerationLifecycle,
    *,
    owner: object,
) -> None:
    record = _require_owner_generation_record(lifecycle, owner=owner)
    if record.state == "retired":
        return
    if record.state not in {"root_owned", "graph_owned"}:
        raise RuntimeError("Catalog action owner generation cannot retire now")
    record.pending.clear()
    record.state = "retired"


def _prepare_catalog_action_owner_binding(
    lifecycle: _CatalogActionOwnerGenerationLifecycle,
    *,
    owner: object,
    projection: object,
) -> _CatalogActionOwnerBinding:
    """Prepare one external, authority-owned construction registration."""

    record = _require_owner_generation_record(lifecycle, owner=owner)
    if record.state != "graph_owned":
        raise RuntimeError("Catalog action owner generation is not graph-owned")
    snapshot = _freeze_catalog_action_owner_snapshot(projection)
    binding = object.__new__(_CatalogActionOwnerBinding)
    object.__setattr__(binding, "lifecycle", lifecycle)
    object.__setattr__(binding, "projection", projection)
    object.__setattr__(binding, "snapshot", snapshot)
    object.__setattr__(binding, "owner_identity", object())
    if id(binding) in record.pending:
        raise RuntimeError("Catalog action owner construction is already pending")
    record.pending[id(binding)] = binding
    return binding


def _cancel_catalog_action_owner_binding(
    binding: _CatalogActionOwnerBinding,
) -> None:
    if type(binding) is not _CatalogActionOwnerBinding:
        return
    record = _OWNER_GENERATIONS.get(id(binding.lifecycle))
    if record is not None and record.pending.get(id(binding)) is binding:
        record.pending.pop(id(binding), None)


def _consume_catalog_action_owner_binding(
    binding: _CatalogActionOwnerBinding,
    *,
    projection: object,
) -> tuple[
    object,
    _CatalogActionOwnerCapability,
    _CatalogActionOwnerLiveness,
]:
    """Atomically consume one owner-prepared binding for its exact projection."""

    if type(binding) is not _CatalogActionOwnerBinding:
        raise TypeError("Catalog action owner binding is invalid")
    lifecycle = getattr(binding, "lifecycle", None)
    record = (
        _OWNER_GENERATIONS.get(id(lifecycle))
        if type(lifecycle) is _CatalogActionOwnerGenerationLifecycle
        else None
    )
    if (
        record is None
        or record.lifecycle is not lifecycle
        or record.owner_ref() is None
        or record.state != "graph_owned"
        or record.pending.get(id(binding)) is not binding
        or getattr(binding, "projection", None) is not projection
        or type(getattr(binding, "snapshot", None)) is not _CatalogActionOwnerSnapshot
        or type(getattr(binding, "owner_identity", None)) is not object
    ):
        raise TypeError("Catalog action owner binding is not live owner evidence")
    record.pending.pop(id(binding), None)
    capability = object.__new__(_CatalogActionOwnerCapability)
    object.__setattr__(capability, "owner_identity", binding.owner_identity)
    liveness = object.__new__(_CatalogActionOwnerLiveness)
    capability_id = id(capability)

    def discard(
        reference: weakref.ReferenceType[_CatalogActionOwnerLiveness],
    ) -> None:
        current = _OWNER_CAPABILITIES.get(capability_id)
        if current is not None and current.liveness_ref is reference:
            _OWNER_CAPABILITIES.pop(capability_id, None)

    liveness_ref = weakref.ref(liveness, discard)
    _OWNER_CAPABILITIES[capability_id] = _CatalogActionOwnerRecord(
        liveness_ref=liveness_ref,
        capability=capability,
        owner_identity=binding.owner_identity,
        snapshot=binding.snapshot,
    )
    return binding.owner_identity, capability, liveness


def _require_owner_generation_record(
    lifecycle: _CatalogActionOwnerGenerationLifecycle,
    *,
    owner: object,
) -> _CatalogActionOwnerGenerationRecord:
    if type(lifecycle) is not _CatalogActionOwnerGenerationLifecycle:
        raise TypeError("Catalog action owner lifecycle is invalid")
    record = _OWNER_GENERATIONS.get(id(lifecycle))
    if (
        record is None
        or record.lifecycle is not lifecycle
        or record.owner_ref() is not owner
    ):
        raise TypeError("Catalog action owner generation is not authority-recorded")
    return record


def _freeze_catalog_action_owner_snapshot(
    projection: object,
) -> _CatalogActionOwnerSnapshot:
    """Freeze primitive action facts from an owner-derived projection."""

    summaries = getattr(projection, "skills", None)
    source_items = getattr(projection, "managed_action_sources", None)
    if type(summaries) is not tuple or type(source_items) is not tuple:
        raise TypeError("Catalog action owner facts require a complete projection")
    sources = {
        getattr(source, "candidate_fingerprint", None): source
        for source in source_items
    }
    if len(sources) != len(source_items) or None in sources:
        raise ValueError("Catalog action owner sources must be unique")
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
                    candidate_fingerprint=str(candidate_fingerprint),
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
    snapshot = object.__new__(_CatalogActionOwnerSnapshot)
    object.__setattr__(snapshot, "action_facts", ordered)
    return snapshot


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
        fact not in owner.snapshot.action_facts
        or getattr(action, "_owner_identity", None) is not owner.owner_identity
        or getattr(getattr(action, "selection", None), "_owner_identity", None)
        is not owner.owner_identity
    ):
        raise ValueError("Catalog action does not match its Resource owner")
    action_id = id(action)
    if action_id in _REGISTRATIONS:
        raise RuntimeError("Catalog action identity is already registered")
    liveness = owner.liveness_ref()
    assert type(liveness) is _CatalogActionOwnerLiveness

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _REGISTRATIONS.get(action_id)
        if current is not None and current.action_ref is reference:
            _REGISTRATIONS.pop(action_id, None)

    reference = weakref.ref(action, discard)
    _REGISTRATIONS[action_id] = _CatalogActionRegistration(
        action_ref=reference,
        liveness=liveness,
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
        or registration.fact not in owner.snapshot.action_facts
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
    liveness = record.liveness_ref() if record is not None else None
    if (
        record is None
        or record.capability is not capability
        or type(liveness) is not _CatalogActionOwnerLiveness
        or capability.owner_identity is not record.owner_identity
    ):
        return None
    return record


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
