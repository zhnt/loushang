"""Coding's shared-store catalog; discovery scopes are views, not stores.

Explicit composition only: the caller supplies an admitted canonical Session
root and workspace. Construction and discovery create no directories. An
explicit first-initialization grant permits the original transcript writer to
prepare a new root; this module resolves no defaults and does not change
Embedded writer behavior.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

from loushang.apphost import (
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.apphost.integrations._canonical_transcript_catalog import (
    CanonicalTranscriptScope,
    _ManagedCanonicalTranscriptCatalogMethods,
)
from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryScopeV1,
    HostedSessionDiscoverySnapshotV1,
)
from loushang.harness.conversation import ConversationHeader
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
from loushang.harness.transcript.store_admission import (
    TranscriptStoreAdmission,
    TranscriptStoreBinding,
)

from .hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedCatalogError,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
    _Candidate,
    _hosted_header_identity,
    _Record,
    _scope_fingerprint,
)
from .session_manager import (
    _resolve_coding_binding_input,
    _validate_coding_restored_header,
)

_MAX_STORE_OBSERVATIONS = 8


class CodingManagedSessionCatalogV1(
    _ManagedCanonicalTranscriptCatalogMethods[
        _Record, _Candidate, ResolvedRuntimeProfile, RuntimeProfileBinding
    ],
    CodingHostedSessionCatalogV1,
):
    """Reuse the existing owned lifecycle for two views of one physical root."""

    def _maximum_store_observations(self) -> int:
        return _MAX_STORE_OBSERVATIONS

    def __init__(self, *, session_root: Path, workspace: Path, initialize_session_root: bool = False,
                 store_state_root: Path | None = None) -> None:
        if type(initialize_session_root) is not bool:
            raise TypeError("invalid Session root initialization grant")
        if store_state_root is not None and initialize_session_root:
            raise ValueError("store admission cannot be combined with a root creation grant")
        # Trusted first-initialization authority, NOT a missing-directory test.
        # A production coordinator must prove this is a new store before
        # granting it; no CLI/default/restore path supplies it automatically.
        self._root_initialization = initialize_session_root
        self._root_observed = threading.Event()
        self._store_state_root = store_state_root
        self._store_probes: dict[TranscriptStoreAdmission, bool] = {}
        self._store_probe_lock = threading.Lock()
        self._store_probes_fenced = False
        self._store_active_reads = 0
        self._observed_store_binding: TranscriptStoreBinding | None = None
        self._observed_root_identity: tuple[int, int] | None = None
        super().__init__(tuple(
            CodingHostedScopeV1(scope, session_root, workspace)
            for scope in (SessionScopeV1.CWD, SessionScopeV1.USER_HOME)
        ), owned_transcripts=True, store_state_root=store_state_root, store_root_observed=self._root_observed)

    async def discover_sessions(
        self,
        scope: HostedSessionDiscoveryScopeV1,
        *,
        stop: Callable[[], bool],
    ) -> HostedSessionDiscoverySnapshotV1:
        return await super().discover_sessions(scope, stop=stop)

    def fence(self) -> None:
        return super().fence()

    async def close(self) -> None:
        return await super().close()

    def _validate_scope_roots(self, scopes: tuple[CodingHostedScopeV1, ...]) -> None:
        if len({item.session_dir for item in scopes}) != 1 or len({item.cwd for item in scopes}) != 1:
            raise ValueError("managed views require one canonical root and workspace")

    def _project_catalog_record(
        self,
        scope: CanonicalTranscriptScope,
        path: Path,
        before: str,
        header: ConversationHeader,
    ) -> _Record | None:
        scope = cast(CodingHostedScopeV1, scope)
        cwd = header.metadata.get("cwd")
        if (
            type(cwd) is not str
            or not cwd
            or "\x00" in cwd
            or (not os.path.isabs(cwd))
            or cwd.startswith("//")
            or (os.path.normpath(cwd) != cwd)
        ):
            raise CodingHostedCatalogError()
        try:
            cwd.encode("utf-8")
        except UnicodeError:
            raise CodingHostedCatalogError() from None
        if "coding.hosted" in header.metadata:
            raw = header.metadata["coding.hosted"]
            if not isinstance(raw, Mapping):
                raise CodingHostedCatalogError()
            try:
                original_scope = SessionScopeV1(raw.get("scope"))
            except (TypeError, ValueError):
                raise CodingHostedCatalogError() from None
            identity, compatibility, operation = _hosted_header_identity(
                header,
                scope=original_scope,
                fingerprint=_scope_fingerprint(original_scope, scope.session_dir, cwd),
            )
        else:
            session_id = header.conversation_id
            try:
                if "\x00" in session_id:
                    raise ValueError("invalid canonical identity")
                continuity = hashlib.sha256(
                    "\x00".join(
                        (
                            "coding.managed.continuity/v1",
                            "coding",
                            str(scope.session_dir),
                            session_id,
                        )
                    ).encode("utf-8")
                ).hexdigest()
                identity = SessionIdentityV1(
                    "coding",
                    continuity,
                    session_id,
                    SessionScopeV1.USER_HOME,
                    _scope_fingerprint(
                        SessionScopeV1.USER_HOME, scope.session_dir, cwd
                    ),
                )
            except (ValueError, UnicodeError):
                raise CodingHostedCatalogError() from None
            compatibility, operation = (CODING_HOSTED_COMPATIBILITY_ID, "")
        compatible = True
        try:
            _validate_coding_restored_header(
                header, _resolve_coding_binding_input(True), True
            )
        except (TypeError, ValueError):
            compatible = False
        envelope = SessionIdentityEnvelopeV1(
            "coding",
            compatibility,
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
        return _Record(projection, identity, scope, path, operation, header, compatible)

    def _record_available(self, record: _Record) -> bool:
        return self._record_compatible(record) and record.header.metadata.get("cwd") == str(record.scope.cwd)

    def _record_visible(self, record: _Record) -> bool:
        # Keep hidden records in the authority scan until duplicate detection
        # completes; a workspace filter cannot conceal a conflicting file.
        return record.scope.scope is SessionScopeV1.USER_HOME or record.header.metadata.get("cwd") == str(record.scope.cwd)

    def _validate_open_record(self, record: _Record) -> None:
        if not self._record_available(record):
            raise CodingHostedCatalogError()

    def _display_identity(self, record: _Record) -> SessionIdentityV1:
        # Wire observations belong to the admitted selection view. The
        # candidate binding retains the original canonical identity above.
        return replace(record.identity, scope=record.scope.scope, scope_fingerprint=record.scope.fingerprint)

    def _validate_records(self, records: list[_Record]) -> None:
        seen: dict[str, _Record] = {}
        for record in records:
            previous = seen.get(record.identity.session_id)
            if previous is not None and (
                previous.path != record.path or previous.header != record.header
                or previous.projection.envelope != record.projection.envelope
                or previous.projection.reference.revision != record.projection.reference.revision
                or previous.scope.scope is record.scope.scope
            ):
                raise CodingHostedCatalogError()
            seen[record.identity.session_id] = record


__all__ = ["CodingManagedSessionCatalogV1"]
