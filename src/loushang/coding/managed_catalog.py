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

from loushang.apphost import (
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryScopeV1,
    HostedSessionDiscoverySnapshotV1,
)
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.transcript.jsonl_file import load_agent_transcript_header
from loushang.harness.transcript.store_admission import (
    TranscriptStoreAdmission,
    TranscriptStoreBinding,
)

from .hosted_catalog import (
    CODING_HOSTED_COMPATIBILITY_ID,
    CodingHostedCatalogError,
    CodingHostedScopeV1,
    CodingHostedSessionCatalogV1,
    _hosted_header_identity,
    _Record,
    _revision,
    _scope_fingerprint,
)
from .session_manager import (
    _resolve_coding_binding_input,
    _validate_coding_restored_header,
)

_MAX_STORE_OBSERVATIONS = 8


class CodingManagedSessionCatalogV1(CodingHostedSessionCatalogV1):
    """Reuse the existing owned lifecycle for two views of one physical root."""

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

    def _accepting(self) -> None:
        super()._accepting()
        if os.path.lexists(self.scopes[0].session_dir):
            self._root_observed.set()
        if self._root_observed.is_set():
            # Once this catalog observes an existing root it cannot authorize
            # recreating it, even if it is later moved or lost.
            self._root_initialization = False

    def _new_root_creation(self) -> bool:
        grant, self._root_initialization = self._root_initialization, False
        return grant and not self._root_observed.is_set()

    def _directory_revision(self, path: Path) -> tuple[int, int, int] | None:
        probe = None
        if self._store_state_root is not None:
            probe = TranscriptStoreAdmission(path, state_root=self._store_state_root,
                                             root_observed=self._root_observed)
            with self._store_probe_lock:
                if (self._store_probes_fenced or len(self._store_probes) >= _MAX_STORE_OBSERVATIONS
                        or any(not active for active in self._store_probes.values())):
                    raise CodingHostedCatalogError()
                self._store_probes[probe] = True  # Retain before native IO, including worker reads.
        try:
            binding = probe.inspect() if probe is not None else None
            if probe is not None:
                with self._store_probe_lock:
                    if self._observed_store_binding is not None and binding != self._observed_store_binding:
                        raise CodingHostedCatalogError()
                    if binding is not None:
                        self._observed_store_binding = binding
            revision = super()._directory_revision(path)
            if revision is not None:
                self._root_observed.set()
                if probe is not None:
                    with self._store_probe_lock:
                        if self._observed_root_identity is not None and revision[:2] != self._observed_root_identity:
                            raise CodingHostedCatalogError()
                        self._observed_root_identity = revision[:2]
            if binding is not None:
                assert probe is not None
                probe.check()
                if revision is None or revision[:2] != binding.root_identity:
                    raise CodingHostedCatalogError()
            if revision is None and self._root_observed.is_set():
                raise CodingHostedCatalogError()
        except BaseException as error:
            self._root_observed.set()  # Unknown observation cannot authorize creation.
            if probe is not None:
                try:
                    self._finish_store_probe(probe)
                except BaseException as cleanup_error:
                    error.add_note(f"store observation cleanup retained: {type(cleanup_error).__name__}")
            raise
        else:
            if probe is not None:
                self._finish_store_probe(probe)
        return revision

    async def discover_sessions(
        self, scope: HostedSessionDiscoveryScopeV1, *, stop: Callable[[], bool],
    ) -> HostedSessionDiscoverySnapshotV1:
        self._accepting()
        with self._store_probe_lock:
            if self._store_probes_fenced or self._store_active_reads >= _MAX_STORE_OBSERVATIONS:
                raise CodingHostedCatalogError()
            self._store_active_reads += 1
        try:
            return await super().discover_sessions(scope, stop=stop)
        finally:
            with self._store_probe_lock:
                self._store_active_reads -= 1

    def _finish_store_probe(self, probe: TranscriptStoreAdmission) -> None:
        try:
            probe.close()
        except BaseException:
            with self._store_probe_lock:
                self._store_probes[probe] = False  # Native read ended, cleanup still owned.
            raise
        else:
            with self._store_probe_lock:
                self._store_probes.pop(probe, None)

    def fence(self) -> None:
        self._on_loop()
        try:
            super().fence()
        finally:
            with self._store_probe_lock:
                self._store_probes_fenced = True

    async def close(self) -> None:
        self._on_loop()
        failures: list[Exception] = []
        try:
            await super().close()
        except Exception as error:
            failures.append(error)
        if self._store_state_root is not None:
            try:
                await settled_io(self._close_store_probes)
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

    def _close_store_probes(self) -> None:
        with self._store_probe_lock:
            probes = tuple(self._store_probes.items())
            active_reads = self._store_active_reads
        failures: list[Exception] = [CodingHostedCatalogError()] if active_reads else []
        for probe, active in probes:
            if active:
                # Discovery's original worker still owns the native call. Its
                # caller waits for completion; close must not free borrowed fds.
                failures.append(CodingHostedCatalogError())
                continue
            try:
                self._finish_store_probe(probe)
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

    def _validate_scope_roots(self, scopes: tuple[CodingHostedScopeV1, ...]) -> None:
        if len({item.session_dir for item in scopes}) != 1 or len({item.cwd for item in scopes}) != 1:
            raise ValueError("managed views require one canonical root and workspace")

    def _read_record(self, scope: CodingHostedScopeV1, path: Path, *, discovery: bool = False) -> _Record | None:
        if path.parent != scope.session_dir:
            raise CodingHostedCatalogError()
        self._root_observed.set()  # Reading a selected history is not first initialization.
        before = _revision(path)
        header = load_agent_transcript_header(path, read_only=True)
        if _revision(path) != before:
            raise CodingHostedCatalogError()
        cwd = header.metadata.get("cwd")
        if (type(cwd) is not str or not cwd or "\0" in cwd or not os.path.isabs(cwd)
                or cwd.startswith("//") or os.path.normpath(cwd) != cwd):
            raise CodingHostedCatalogError()
        # Never resolve an untrusted header path or require a historical
        # workspace to exist merely to display it as unavailable.
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
                header, scope=original_scope,
                fingerprint=_scope_fingerprint(original_scope, scope.session_dir, cwd),
            )
        else:
            session_id = header.conversation_id
            try:
                if "\0" in session_id:
                    raise ValueError("invalid canonical identity")
                continuity = hashlib.sha256("\0".join((
                    "coding.managed.continuity/v1", "coding", str(scope.session_dir), session_id,
                )).encode("utf-8")).hexdigest()
                identity = SessionIdentityV1(
                    "coding", continuity, session_id, SessionScopeV1.USER_HOME,
                    _scope_fingerprint(SessionScopeV1.USER_HOME, scope.session_dir, cwd),
                )
            except (ValueError, UnicodeError):
                raise CodingHostedCatalogError() from None
            compatibility, operation = CODING_HOSTED_COMPATIBILITY_ID, ""
        compatible = True
        try:
            _validate_coding_restored_header(header, _resolve_coding_binding_input(True), True)
        except (TypeError, ValueError):
            compatible = False
        envelope = SessionIdentityEnvelopeV1(
            "coding", compatibility, identity.continuity_id, identity.session_id,
            "coding.jsonl", identity.session_id,
        )
        projection = SessionIdentityProjectionV1(
            SessionCandidateRefV1(scope.source_id, identity.session_id, before),
            scope.discovery_scope, SessionCandidateMode.CANONICAL, envelope,
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
