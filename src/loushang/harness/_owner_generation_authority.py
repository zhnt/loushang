"""Neutral exact-factory authority for owner-generation attachment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True, init=False)
class _OwnerCandidateFactoryIdentity:
    """Opaque identity issued inline by a canonical candidate factory."""

    def __init__(self) -> None:
        raise TypeError("Owner candidates are factory-minted")


@dataclass(frozen=True, slots=True, init=False)
class _OwnerGenerationFactoryIdentity:
    """Opaque identity issued inline by a canonical generation factory."""

    def __init__(self) -> None:
        raise TypeError("Owner generations are factory-minted")


@dataclass(frozen=True, slots=True, init=False)
class _OwnerGenerationAttachmentReceipt:
    """Single-use proof of one exact candidate-to-generation attachment."""

    def __init__(self) -> None:
        raise TypeError("Owner generation attachments are candidate-minted")


@dataclass(frozen=True, slots=True)
class _OwnerCandidateFactoryRecord:
    candidate_ref: Callable[[], object | None]
    identity: _OwnerCandidateFactoryIdentity


@dataclass(frozen=True, slots=True)
class _OwnerGenerationFactoryRecord:
    owner_ref: Callable[[], object | None]
    identity: _OwnerGenerationFactoryIdentity


@dataclass(slots=True)
class _OwnerGenerationAttachmentRecord:
    candidate_ref: Callable[[], object | None]
    owner_ref: Callable[[], object | None]
    receipt: _OwnerGenerationAttachmentReceipt
    state: Literal["attached", "consumed"]


_OWNER_CANDIDATE_FACTORIES: dict[int, _OwnerCandidateFactoryRecord] = {}
_OWNER_GENERATION_FACTORIES: dict[int, _OwnerGenerationFactoryRecord] = {}
_OWNER_GENERATION_ATTACHMENTS: dict[int, _OwnerGenerationAttachmentRecord] = {}


def _is_owner_candidate_factory_recorded(candidate: object) -> bool:
    identity = getattr(candidate, "_owner_candidate_factory_identity", None)
    record = (
        _OWNER_CANDIDATE_FACTORIES.get(id(identity))
        if type(identity) is _OwnerCandidateFactoryIdentity
        else None
    )
    return bool(
        record is not None
        and record.identity is identity
        and record.candidate_ref() is candidate
    )


def _is_owner_generation_factory_recorded(owner: object) -> bool:
    identity = getattr(owner, "_owner_generation_factory_identity", None)
    record = (
        _OWNER_GENERATION_FACTORIES.get(id(identity))
        if type(identity) is _OwnerGenerationFactoryIdentity
        else None
    )
    return bool(
        record is not None
        and record.identity is identity
        and record.owner_ref() is owner
    )


def _commit_owner_generation_attachment(
    receipt: _OwnerGenerationAttachmentReceipt,
    *,
    owner: object,
) -> None:
    """Consume the rollback right after downstream enrollment commits."""

    _require_owner_generation_attachment(
        receipt,
        owner=owner,
        expected_state="consumed",
    )
    _OWNER_GENERATION_ATTACHMENTS.pop(id(receipt), None)


def _rollback_owner_generation_attachment(
    receipt: _OwnerGenerationAttachmentReceipt,
    *,
    candidate: object,
    owner: object,
) -> None:
    """Consume an uncommitted attachment's single-use rollback right."""

    record = _require_owner_generation_attachment(
        receipt,
        owner=owner,
        expected_state=None,
    )
    if record.candidate_ref() is not candidate:
        raise TypeError("Owner generation rollback lost its exact candidate")
    _OWNER_GENERATION_ATTACHMENTS.pop(id(receipt), None)


def _consume_owner_generation_attachment(
    receipt: _OwnerGenerationAttachmentReceipt,
    *,
    owner: object,
) -> object:
    """Consume one live exact attachment and return its recorded candidate."""

    if type(receipt) is not _OwnerGenerationAttachmentReceipt:
        raise TypeError("Owner generation attachment receipt is invalid")
    record = _OWNER_GENERATION_ATTACHMENTS.get(id(receipt))
    candidate = record.candidate_ref() if record is not None else None
    require_owner = (
        getattr(candidate, "_require_prepared_owner_generation", None)
        if candidate is not None
        else None
    )
    if (
        record is None
        or record.receipt is not receipt
        or record.state != "attached"
        or record.owner_ref() is not owner
        or not _is_owner_candidate_factory_recorded(candidate)
        or not _is_owner_generation_factory_recorded(owner)
        or getattr(candidate, "ownership_state", None) != "root_owned"
        or not callable(require_owner)
        or require_owner() is not owner
    ):
        raise TypeError("Owner generation attachment is not live exact evidence")
    record.state = "consumed"
    return candidate


def _require_owner_generation_attachment(
    receipt: _OwnerGenerationAttachmentReceipt,
    *,
    owner: object,
    expected_state: Literal["attached", "consumed"] | None,
) -> _OwnerGenerationAttachmentRecord:
    if type(receipt) is not _OwnerGenerationAttachmentReceipt:
        raise TypeError("Owner generation attachment receipt is invalid")
    record = _OWNER_GENERATION_ATTACHMENTS.get(id(receipt))
    if (
        record is None
        or record.receipt is not receipt
        or record.owner_ref() is not owner
        or (expected_state is not None and record.state != expected_state)
    ):
        raise TypeError("Owner generation attachment is not live exact evidence")
    return record


__all__: list[str] = []
