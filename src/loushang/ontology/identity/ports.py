"""Read-only identity resolver port and explicit failure contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from loushang.ontology.identity.model import (
    IdentityResolution,
    IdentityResolutionStatus,
    SourceRecordIdentity,
)


@runtime_checkable
class IdentityResolver(Protocol):
    """Product-provided resolver; matching and review remain outside Ontology."""

    def resolve_identity(
        self,
        source_identity: SourceRecordIdentity,
    ) -> IdentityResolution | None: ...


class IdentityResolutionError(ValueError):
    """Stable refusal to turn a non-confirmed record into a canonical UUID."""

    def __init__(
        self,
        code: str,
        source_identity: SourceRecordIdentity,
        message: str,
    ) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")
        if not isinstance(source_identity, SourceRecordIdentity):
            raise TypeError("source_identity must be a SourceRecordIdentity")
        self.code = code
        self.source_identity = source_identity
        super().__init__(message)


def require_confirmed_identity(
    resolver: IdentityResolver,
    source_identity: SourceRecordIdentity,
) -> UUID:
    """Return one explicitly confirmed UUID or fail without choosing a candidate."""

    if not isinstance(resolver, IdentityResolver):
        raise TypeError("resolver must implement IdentityResolver")
    if not isinstance(source_identity, SourceRecordIdentity):
        raise TypeError("source_identity must be a SourceRecordIdentity")
    resolution = resolver.resolve_identity(source_identity)
    if resolution is None:
        raise IdentityResolutionError(
            "identity_missing",
            source_identity,
            "source record is absent from the selected identity crosswalk",
        )
    if resolution.source_identity != source_identity:
        raise IdentityResolutionError(
            "identity_source_mismatch",
            source_identity,
            "identity resolver returned a result for a different source record",
        )
    if resolution.status is IdentityResolutionStatus.UNRESOLVED:
        raise IdentityResolutionError(
            "identity_unresolved",
            source_identity,
            "source record has no confirmed canonical identity",
        )
    if resolution.status is IdentityResolutionStatus.CONFLICT:
        raise IdentityResolutionError(
            "identity_conflict",
            source_identity,
            "source record has conflicting canonical identity candidates",
        )
    assert resolution.canonical_object_id is not None
    return resolution.canonical_object_id


__all__ = [
    "IdentityResolutionError",
    "IdentityResolver",
    "require_confirmed_identity",
]
