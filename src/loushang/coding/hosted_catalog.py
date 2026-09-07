"""Coding canonical Session owner for explicitly admitted hosted scopes.

Identity and create-idempotency facts live in the real transcript header, not
in a parallel Session index. Candidate tokens never supply filesystem paths.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from loushang.apphost import (
    ClaimedSessionCandidateV1,
    OpenedProductCandidateV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import ConversationHeader
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
from loushang.harness.transcript import (
    AgentTranscriptLifecycleContext,
    AgentTranscriptSessionFactory,
)
from loushang.harness.transcript.jsonl_file import load_agent_transcript_header
from loushang.harness.transcript.session_catalog import (
    AgentTranscriptSessionCatalog,
    SessionDiscoveryReadBudget,
    session_file_authority_fingerprint,
)

from .session_manager import (
    _LIFECYCLE,
    SessionManager,
    _coding_header_metadata,
    _resolve_coding_binding_input,
    _validate_coding_restored_header,
)

CODING_HOSTED_COMPATIBILITY_ID = "coding-hosted-v1"
_METADATA_KEY = "coding.hosted"
_MAX_CANDIDATES = 256
_MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024


class CodingHostedCatalogError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("coding_hosted_candidate_unavailable")


@dataclass(frozen=True, slots=True)
class CodingHostedScopeV1:
    scope: SessionScopeV1
    session_dir: Path = field(repr=False)
    cwd: Path = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.scope) is not SessionScopeV1:
            raise ValueError("invalid hosted scope")
        for value in (self.session_dir, self.cwd):
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError("hosted scope requires admitted absolute paths")
            if value != value.resolve():
                raise ValueError("hosted scope paths must already be canonical")
        if not self.cwd.is_dir():
            raise ValueError("hosted workspace must exist")

    @property
    def fingerprint(self) -> str:
        parts = [
            "coding.hosted.scope/v1",
            self.scope.value,
            os.path.normcase(str(self.session_dir)),
        ]
        if self.scope is SessionScopeV1.CWD:
            parts.append(os.path.normcase(str(self.cwd)))
        material = "\0".join(parts)
        return hashlib.sha256(material.encode()).hexdigest()

    @property
    def discovery_scope(self) -> SessionDiscoveryScope:
        return (
            SessionDiscoveryScope.CURRENT_DIRECTORY
            if self.scope is SessionScopeV1.CWD
            else SessionDiscoveryScope.USER_GLOBAL_CANONICAL
        )

    @property
    def source_id(self) -> str:
        return f"coding.hosted.{self.scope.value}"


def _session_path(root: Path, header: ConversationHeader) -> Path:
    # This callback only receives the owner's SHA-256 create identity.
    session_id = header.conversation_id
    if len(session_id) != 64 or any(
        char not in "0123456789abcdef" for char in session_id
    ):
        raise CodingHostedCatalogError()
    return root / f"hosted-{session_id}.jsonl"


_HOSTED_FACTORY = AgentTranscriptSessionFactory(
    lifecycle=_LIFECYCLE,
    resolve_binding_input=_resolve_coding_binding_input,
    header_metadata=_coding_header_metadata,
    validate_restored_header=_validate_coding_restored_header,
    session_file_factory=_session_path,
)


class _HostedTranscript(SessionManager):
    @classmethod
    def _session_factory(
        cls,
    ) -> AgentTranscriptSessionFactory[ResolvedRuntimeProfile, RuntimeProfileBinding]:
        return _HOSTED_FACTORY


@dataclass(frozen=True, slots=True)
class _Record:
    projection: SessionIdentityProjectionV1
    identity: SessionIdentityV1
    scope: CodingHostedScopeV1
    path: Path = field(repr=False)
    operation_id: str
    header: ConversationHeader


class CodingHostedCandidateBindingV1:
    """One already-open transcript; Product Session construction takes it once."""

    def __init__(self, record: _Record, manager: SessionManager) -> None:
        self.record = record
        self._manager: SessionManager | None = manager
        self._dispose: Callable[[], Awaitable[None]] | None = (
            manager.dispose_runtime_profile
        )

    def manager_for_construction(self) -> SessionManager:
        if self._manager is None:
            raise CodingHostedCatalogError()
        return self._manager

    def retain_constructed_owner(self, dispose: Callable[[], Awaitable[None]]) -> None:
        """Keep construction cleanup reachable until the completed binding transfers."""
        self.manager_for_construction()
        self._dispose = dispose

    def take_manager(self) -> SessionManager:
        if self._manager is None:
            raise CodingHostedCatalogError()
        manager, self._manager = self._manager, None
        self._dispose = None
        return manager

    async def close(self) -> None:
        if self._dispose is not None:
            await self._dispose()
            self._dispose = None
            self._manager = None


class _Claimed:
    def __init__(
        self, reference: SessionCandidateRefV1, binding: CodingHostedCandidateBindingV1
    ) -> None:
        self.reference = reference
        self.opaque_binding = binding

    async def close(self) -> None:
        await self.opaque_binding.close()


class _Candidate:
    def __init__(
        self, record: _Record, binding: CodingHostedCandidateBindingV1
    ) -> None:
        self.projection = record.projection
        self._record = record
        self._binding = binding
        self._claimed = False
        self._closed = False

    async def verify_current(self) -> None:
        if (
            self._closed
            or _revision(self._record.path) != self.projection.reference.revision
        ):
            raise CodingHostedCatalogError()

    async def claim(self) -> _Claimed:
        await self.verify_current()
        if self._claimed:
            raise CodingHostedCatalogError()
        self._claimed = True
        return _Claimed(self.projection.reference, self._binding)

    async def close(self) -> None:
        self._closed = True
        if not self._claimed:
            await self._binding.close()


class _Opened:
    def __init__(self, binding: CodingHostedCandidateBindingV1) -> None:
        identity = binding.record.identity
        self.binding_key = SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        )
        self.opaque_binding = binding

    async def close(self) -> None:
        # The candidate owns an unconsumed transcript; Product owns a taken one.
        return None


class CodingHostedCandidateValidatorV1:
    async def open_product_candidate(
        self,
        candidate: ClaimedSessionCandidateV1,
        envelope: SessionIdentityEnvelopeV1,
    ) -> OpenedProductCandidateV1:
        binding = candidate.opaque_binding
        if type(binding) is not CodingHostedCandidateBindingV1:
            raise CodingHostedCatalogError()
        if binding.record.projection.reference != candidate.reference:
            raise CodingHostedCatalogError()
        if binding.record.projection.envelope != envelope:
            raise CodingHostedCatalogError()
        if binding.record.projection.envelope is None or (
            binding.record.projection.envelope.product_compatibility_id
            != CODING_HOSTED_COMPATIBILITY_ID
        ):
            raise CodingHostedCatalogError()
        return _Opened(binding)


class CodingHostedSessionCatalogV1:
    """Canonical create/resume owner over exact injected transcript directories."""

    def __init__(self, scopes: tuple[CodingHostedScopeV1, ...]) -> None:
        if not scopes or any(type(item) is not CodingHostedScopeV1 for item in scopes):
            raise ValueError("invalid hosted scope bindings")
        if len({item.scope for item in scopes}) != len(scopes):
            raise ValueError("duplicate hosted scope")
        if len({item.session_dir for item in scopes}) != len(scopes):
            raise ValueError("hosted scopes require distinct Session roots")
        self.scopes = scopes
        self._records: dict[SessionCandidateRefV1, _Record] = {}
        self._lock = asyncio.Lock()

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        if type(limit) is not int or not 1 <= limit <= _MAX_CANDIDATES:
            raise CodingHostedCatalogError()
        selected = tuple(item for item in self.scopes if item.discovery_scope in scopes)
        if len(selected) != len(scopes):
            raise CodingHostedCatalogError()
        async with self._lock:
            records: list[_Record] = []
            for scope in selected:
                snapshot = AgentTranscriptSessionCatalog(
                    scope.session_dir
                ).bounded_index_snapshot(
                    enrich_limit=_MAX_CANDIDATES,
                    segment_bytes=32768,
                    read_budget=SessionDiscoveryReadBudget(
                        remaining_candidates=_MAX_CANDIDATES,
                        remaining_bytes=32 * 1024 * 1024,
                    ),
                )
                if (
                    not snapshot.complete
                    or snapshot.enriched_count != snapshot.authority_count
                ):
                    raise CodingHostedCatalogError()
                for item in snapshot.items:
                    path = item.projection.session_file
                    if path is None:
                        continue
                    record = _read_record(scope, path)
                    if record is not None:
                        records.append(record)
            identities = [item.identity.session_id for item in records]
            if len(set(identities)) != len(identities) or len(records) > limit:
                raise CodingHostedCatalogError()
            # Independent cwd/home discovery must not invalidate an in-flight
            # candidate from the other source. Each source still replaces its
            # complete bounded snapshot, so revisions cannot accumulate.
            selected_sources = {scope.source_id for scope in selected}
            self._records = {
                reference: record
                for reference, record in self._records.items()
                if reference.source_id not in selected_sources
            }
            self._records.update(
                (record.projection.reference, record) for record in records
            )
            return tuple(record.projection for record in records)

    async def open_candidate(self, reference: SessionCandidateRefV1) -> _Candidate:
        async with self._lock:
            record = self._records.get(reference)
            if record is None:
                raise CodingHostedCatalogError()
            return await _open_record(record)

    def _scope_for(self, request: SessionCreateRequestV1) -> CodingHostedScopeV1:
        if request.product_id != "coding" or request.requested_continuity_id is None:
            raise CodingHostedCatalogError()
        for scope in self.scopes:
            if (
                scope.discovery_scope is request.requested_scope
                and scope.fingerprint == request.creator_scope_id
            ):
                return scope
        raise CodingHostedCatalogError()

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> _Candidate | None:
        async with self._lock:
            return await self._find(request)

    async def _find(self, request: SessionCreateRequestV1) -> _Candidate | None:
        scope = self._scope_for(request)
        path = scope.session_dir / f"hosted-{_create_identity(request)}.jsonl"
        if not path.exists() and not path.is_symlink():
            return None
        record = _read_record(scope, path)
        if (
            record is None
            or record.operation_id != request.operation_id
            or record.identity.continuity_id != request.requested_continuity_id
            or record.projection.envelope is None
            or record.projection.envelope.product_compatibility_id
            != CODING_HOSTED_COMPATIBILITY_ID
        ):
            raise CodingHostedCatalogError()
        return await _open_record(record)

    async def create_candidate(self, intent: SessionCreateIntentV1) -> _Candidate:
        if intent.product_compatibility_id != CODING_HOSTED_COMPATIBILITY_ID:
            raise CodingHostedCatalogError()
        async with self._lock:
            existing = await self._find(intent.request)
            if existing is not None:
                return existing
            scope = self._scope_for(intent.request)
            session_id = _create_identity(intent.request)
            metadata: dict[str, JSONValue] = {
                "version": 1,
                "compatibilityId": CODING_HOSTED_COMPATIBILITY_ID,
                "continuityId": intent.request.requested_continuity_id,
                "sessionId": session_id,
                "scope": scope.scope.value,
                "scopeFingerprint": scope.fingerprint,
                "operationId": intent.request.operation_id,
            }
            try:
                manager = await _HostedTranscript.new(
                    session_dir=scope.session_dir,
                    cwd=str(scope.cwd),
                    session_id=session_id,
                    additional_header_metadata={_METADATA_KEY: metadata},
                    defer_materialization=False,
                )
            except Exception:
                # A concurrent same-key creator may have committed first.
                recovered = await self._find(intent.request)
                if recovered is None:
                    raise CodingHostedCatalogError() from None
                return recovered
            try:
                assert manager.session_file is not None
                record = _read_record(scope, manager.session_file)
                if record is None:
                    raise CodingHostedCatalogError()
                return _Candidate(
                    record, CodingHostedCandidateBindingV1(record, manager)
                )
            except BaseException:
                await manager.dispose_runtime_profile()
                raise


def _create_identity(request: SessionCreateRequestV1) -> str:
    return hashlib.sha256(
        "\0".join(
            (
                "coding.hosted.create/v1",
                request.product_id,
                request.creator_scope_id,
                request.operation_id,
            )
        ).encode()
    ).hexdigest()


def _revision(path: Path) -> str:
    status = path.lstat()
    if (
        not stat.S_ISREG(status.st_mode)
        or getattr(status, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        or status.st_size > _MAX_TRANSCRIPT_BYTES
    ):
        raise CodingHostedCatalogError()
    return hashlib.sha256(session_file_authority_fingerprint(path).encode()).hexdigest()


def _read_record(scope: CodingHostedScopeV1, path: Path) -> _Record | None:
    if path.parent != scope.session_dir:
        raise CodingHostedCatalogError()
    before = _revision(path)
    header = load_agent_transcript_header(path)
    if _revision(path) != before:
        raise CodingHostedCatalogError()
    raw = header.metadata.get(_METADATA_KEY)
    if raw is None:
        return None  # Legacy/default TUI transcripts are not implicitly adopted.
    if not isinstance(raw, Mapping) or set(raw) != {
        "version",
        "compatibilityId",
        "continuityId",
        "sessionId",
        "scope",
        "scopeFingerprint",
        "operationId",
    }:
        raise CodingHostedCatalogError()
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise CodingHostedCatalogError()
    if any(type(value) is not str for key, value in raw.items() if key != "version"):
        raise CodingHostedCatalogError()
    if (
        raw["sessionId"] != header.conversation_id
        or raw["scope"] != scope.scope.value
        or raw["scopeFingerprint"] != scope.fingerprint
    ):
        raise CodingHostedCatalogError()
    create_request = SessionCreateRequestV1(
        "coding",
        scope.fingerprint,
        cast(str, raw["operationId"]),
        requested_continuity_id=cast(str, raw["continuityId"]),
        requested_scope=scope.discovery_scope,
    )
    if _create_identity(create_request) != header.conversation_id:
        raise CodingHostedCatalogError()
    identity = SessionIdentityV1(
        "coding",
        cast(str, raw["continuityId"]),
        header.conversation_id,
        scope.scope,
        scope.fingerprint,
    )
    envelope = SessionIdentityEnvelopeV1(
        "coding",
        cast(str, raw["compatibilityId"]),
        identity.continuity_id,
        identity.session_id,
        "coding.jsonl",
        identity.session_id,
    )
    projection = SessionIdentityProjectionV1(
        SessionCandidateRefV1(scope.source_id, identity.session_id, before),
        scope.discovery_scope,
        SessionCandidateMode.CANONICAL,
        envelope,
    )
    return _Record(
        projection, identity, scope, path, cast(str, raw["operationId"]), header
    )


async def _open_record(record: _Record) -> _Candidate:
    if _revision(record.path) != record.projection.reference.revision:
        raise CodingHostedCatalogError()
    context = AgentTranscriptLifecycleContext(
        session_dir=record.scope.session_dir,
        cwd=str(record.scope.cwd),
        persist=True,
        header=record.header,
        session_file=record.path,
    )
    manager = _HostedTranscript(
        lifecycle_session=await _HOSTED_FACTORY.restore_context(context)
    )
    try:
        if (
            manager.header != record.header
            or _revision(record.path) != record.projection.reference.revision
        ):
            raise CodingHostedCatalogError()
        return _Candidate(record, CodingHostedCandidateBindingV1(record, manager))
    except BaseException:
        await manager.dispose_runtime_profile()
        raise


__all__ = [
    "CODING_HOSTED_COMPATIBILITY_ID",
    "CodingHostedCandidateBindingV1",
    "CodingHostedCandidateValidatorV1",
    "CodingHostedCatalogError",
    "CodingHostedScopeV1",
    "CodingHostedSessionCatalogV1",
]
