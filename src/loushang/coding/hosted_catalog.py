"""Coding canonical Session owner for explicitly admitted hosted scopes.

Identity and create-idempotency facts live in the real transcript header, not
in a parallel Session index. Candidate tokens never supply filesystem paths.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
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
from loushang.appserver.protocol import (
    SessionAvailabilityV1,
    SessionCompatibilityV1,
    SessionDiscoveryCandidateV1,
    SessionIdentityV1,
    SessionScopeV1,
)
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryScopeV1,
    HostedSessionDiscoverySnapshotV1,
)
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import ConversationHeader
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptLifecycleContext,
    AgentTranscriptLifecycleSession,
    AgentTranscriptSessionFactory,
)
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    load_agent_transcript_header,
)
from loushang.harness.transcript.session_catalog import (
    SessionDiscoveryReadBudget,
    session_file_authority_fingerprint,
)

from .product_plan import CODING_TRANSCRIPT_RUNTIME
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
_DISCOVERY_BYTES = 32 * 1024 * 1024


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
        return _scope_fingerprint(self.scope, self.session_dir, str(self.cwd))

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


def _scope_fingerprint(scope: SessionScopeV1, root: Path, cwd: str) -> str:
    parts = ["coding.hosted.scope/v1", scope.value, os.path.normcase(str(root))]
    if scope is SessionScopeV1.CWD:
        parts.append(os.path.normcase(cwd))
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


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


class _OwnedHostedTranscript(SessionManager):
    """Explicit managed candidate; never route an instance to legacy storage."""

    async def publish_index_summary(self) -> None:
        # The aggregate index is optional, and does not yet borrow owned IO.
        # Hosted discovery reads canonical headers instead of this cache.
        return None

    async def fork(self, leaf_id: str) -> _OwnedHostedTranscript:
        # Hosted continuity/create identities require their own clone intent.
        # Ordinary factory fork does not issue that identity envelope.
        raise CodingHostedCatalogError()


@dataclass(frozen=True, slots=True)
class _Record:
    projection: SessionIdentityProjectionV1
    identity: SessionIdentityV1
    scope: CodingHostedScopeV1
    path: Path = field(repr=False)
    operation_id: str
    header: ConversationHeader
    compatible: bool = True


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
        self._reference = reference
        self._binding = binding

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> CodingHostedCandidateBindingV1:
        return self._binding

    async def close(self) -> None:
        await self.opaque_binding.close()


class _Candidate:
    def __init__(
        self, record: _Record, binding: CodingHostedCandidateBindingV1
    ) -> None:
        self._record = record
        self._binding = binding
        self._claimed = False
        self._closed = False

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._record.projection

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
        self._binding_key = SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        )
        self._binding = binding

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key

    @property
    def opaque_binding(self) -> CodingHostedCandidateBindingV1:
        return self._binding

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

    def __init__(self, scopes: tuple[CodingHostedScopeV1, ...], *, owned_transcripts: bool = False,
                 store_state_root: Path | None = None, store_root_observed: threading.Event | None = None) -> None:
        if type(owned_transcripts) is not bool:
            raise TypeError("invalid owned transcript activation")
        if store_state_root is not None and not owned_transcripts:
            raise ValueError("store admission requires owned transcripts")
        if not scopes or any(type(item) is not CodingHostedScopeV1 for item in scopes):
            raise ValueError("invalid hosted scope bindings")
        if len({item.scope for item in scopes}) != len(scopes):
            raise ValueError("duplicate hosted scope")
        self._validate_scope_roots(scopes)
        self.scopes = scopes
        self._records: dict[SessionCandidateRefV1, _Record] = {}
        self._lock = asyncio.Lock()
        self._owned_factory = (
            AgentTranscriptSessionFactory(
                lifecycle=AgentTranscriptLifecycle(
                    bind_runtime=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle,
                    bind_runtime_owned=CODING_TRANSCRIPT_RUNTIME.bind_lifecycle_owned,
                ),
                resolve_binding_input=_resolve_coding_binding_input,
                header_metadata=_coding_header_metadata,
                validate_restored_header=_validate_coding_restored_header,
                session_file_factory=_session_path,
                owned_product_id="coding",
                store_state_root=store_state_root,
                store_root_observed=store_root_observed,
            ) if owned_transcripts else None
        )
        self._pending_sessions: dict[int, AgentTranscriptLifecycleSession[RuntimeProfileBinding]] = {}
        self._closing = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def _validate_scope_roots(self, scopes: tuple[CodingHostedScopeV1, ...]) -> None:
        if len({item.session_dir for item in scopes}) != len(scopes):
            raise ValueError("hosted scopes require distinct Session roots")

    def _read_record(self, scope: CodingHostedScopeV1, path: Path, *, discovery: bool = False) -> _Record | None:
        return _read_record(scope, path, discovery=discovery, owned=self._owned_factory is not None)

    def _record_compatible(self, record: _Record) -> bool:
        envelope = record.projection.envelope
        return record.compatible and envelope is not None and (
            envelope.product_compatibility_id == CODING_HOSTED_COMPATIBILITY_ID
        )

    def _record_available(self, record: _Record) -> bool:
        return self._record_compatible(record)

    def _validate_open_record(self, record: _Record) -> None:
        # Legacy v1 compatibility remains the Product validator's decision.
        # Managed catalogs additionally fence workspace/runtime before IO.
        return None

    def _display_identity(self, record: _Record) -> SessionIdentityV1:
        return record.identity

    def _record_visible(self, record: _Record) -> bool:
        return True

    def _new_root_creation(self) -> bool:
        return False

    def _directory_revision(self, path: Path) -> tuple[int, int, int] | None:
        return _directory_revision(path)

    def _validate_records(self, records: list[_Record]) -> None:
        identities = [item.identity.session_id for item in records]
        if len(set(identities)) != len(identities):
            raise CodingHostedCatalogError()

    @property
    def pending_sessions(self) -> tuple[AgentTranscriptLifecycleSession[RuntimeProfileBinding], ...]:
        return tuple(self._pending_sessions.values())

    def _on_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise CodingHostedCatalogError()

    def _accepting(self) -> None:
        if self._owned_factory is not None:
            self._on_loop()
            if self._closing:
                raise CodingHostedCatalogError()

    def fence(self) -> None:
        if self._owned_factory is not None:
            self._on_loop()
            self._closing = True
            self._owned_factory.fence()

    async def close(self) -> None:
        if self._owned_factory is None:
            return
        self._on_loop()
        failures: list[Exception] = []
        try:
            self.fence()
        except Exception as error:
            failures.append(error)
        async with self._lock:
            for session in self.pending_sessions:
                try:
                    await self._discard_session(session)
                except Exception as error:
                    failures.append(error)
            try:
                await self._owned_factory.close()
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

    async def _discard_session(self, session: AgentTranscriptLifecycleSession[RuntimeProfileBinding]) -> None:
        await session.dispose()
        self._pending_sessions.pop(id(session), None)

    async def _candidate_from_owned(
        self, session: AgentTranscriptLifecycleSession[RuntimeProfileBinding], scope: CodingHostedScopeV1,
        *, expected: _Record | None = None,
    ) -> _Candidate:
        # No await between receipt and retention; wrapper construction itself
        # can fail. Keep the original lifecycle rather than only its wrapper.
        self._pending_sessions[id(session)] = session
        try:
            self._accepting()
            manager = _OwnedHostedTranscript(lifecycle_session=session)
            assert manager.session_file is not None
            with session.sync_operation_scope():
                record = self._read_record(scope, manager.session_file)
            if (record is None or record.header != session.context.header
                    or (expected is not None and record != expected)):
                raise CodingHostedCatalogError()
            self._validate_open_record(record)
            # Recheck root identity after the read-only catalog observation.
            with session.sync_operation_scope():
                pass
            candidate = _Candidate(record, CodingHostedCandidateBindingV1(record, manager))
            self._accepting()
            self._pending_sessions.pop(id(session))
            return candidate
        except BaseException as error:
            try:
                await self._discard_session(session)
            except BaseException as cleanup_error:
                error.add_note(f"owned catalog cleanup retained: {type(cleanup_error).__name__}")
            raise

    async def _open(self, record: _Record) -> _Candidate:
        self._validate_open_record(record)
        if self._owned_factory is None:
            return await _open_record(record)
        if _revision(record.path) != record.projection.reference.revision:
            raise CodingHostedCatalogError()
        context = AgentTranscriptLifecycleContext(
            session_dir=record.scope.session_dir, cwd=str(record.scope.cwd), persist=True,
            header=record.header, session_file=record.path,
        )
        session = await self._owned_factory.restore_context(context)
        return await self._candidate_from_owned(session, record.scope, expected=record)

    async def discover_sessions(
        self, scope: HostedSessionDiscoveryScopeV1, *, stop: Callable[[], bool],
    ) -> HostedSessionDiscoverySnapshotV1:
        self._accepting()
        if type(scope) is not HostedSessionDiscoveryScopeV1 or scope.product_id != "coding":
            raise ValueError("unadmitted discovery scope")
        selected = next((item for item in self.scopes if (
            item.scope is scope.scope and item.fingerprint == scope.scope_fingerprint
        )), None)
        if selected is None:
            raise ValueError("unadmitted discovery scope")
        cancelled = threading.Event()
        loop = asyncio.get_running_loop()
        completed: asyncio.Future[HostedSessionDiscoverySnapshotV1 | None] = loop.create_future()
        submitted = threading.Event()
        admitted = False

        def read() -> None:
            submitted.wait()
            if not admitted:
                return  # Submission without a receipt grants no native read.
            try:
                value = self._read_discovery(
                    selected, scope, lambda: cancelled.is_set() or stop(),
                )
            except BaseException:
                value = None  # Never export a filesystem exception to the client.
            # Only actual read completion resolves this signal. Runner's task
            # cancellation cannot manufacture it by cancelling a to_thread Task.
            loop.call_soon_threadsafe(completed.set_result, value)

        try:
            loop.run_in_executor(None, read)
            admitted = True
        finally:
            submitted.set()
        while True:
            try:
                result = await asyncio.shield(completed)
                break
            except asyncio.CancelledError:
                cancelled.set()
        if cancelled.is_set():
            raise asyncio.CancelledError()
        if result is None:
            raise CodingHostedCatalogError()
        self._accepting()
        return result

    def _read_discovery(
        self, admitted: CodingHostedScopeV1, scope: HostedSessionDiscoveryScopeV1,
        stop: Callable[[], bool],
    ) -> HostedSessionDiscoverySnapshotV1:
        deadline = time.monotonic() + 5
        def stopped() -> bool:
            return stop() or time.monotonic() >= deadline
        if stopped():
            return HostedSessionDiscoverySnapshotV1(scope, (), False, omitted_count_exact=False)
        before = self._directory_revision(admitted.session_dir)
        if before is None:
            return HostedSessionDiscoverySnapshotV1(scope, (), True)
        layout = AgentTranscriptFileLayout(admitted.session_dir)
        scan = layout.scan_candidate_path_snapshot(
            layout.namespace, max_candidates=_MAX_CANDIDATES,
            should_stop=stopped, raise_on_error=True,
        )
        budget = SessionDiscoveryReadBudget(
            remaining_candidates=_MAX_CANDIDATES, remaining_bytes=_DISCOVERY_BYTES,
        )
        complete, omitted, duplicate = scan.complete, 0, False
        rows: dict[str, SessionDiscoveryCandidateV1] = {}
        seen: set[str] = set()
        for path in scan.paths:
            if stopped() or not budget.reserve(candidates=1, bytes_=64 * 1024):
                complete = False
                break
            try:
                record = self._read_record(admitted, path, discovery=True)
            except (OSError, ValueError, CodingHostedCatalogError):
                complete, omitted = False, omitted + 1
                continue
            if record is None:
                omitted += 1  # Legacy history is observed, never adopted.
                continue
            identity = self._display_identity(record)
            if identity.session_id in seen:
                duplicate, omitted = True, omitted + 1
                continue
            seen.add(identity.session_id)
            if not self._record_visible(record):
                continue
            compatible = self._record_compatible(record)
            rows[identity.session_id] = SessionDiscoveryCandidateV1(
                identity, f"Session {identity.session_id[:12]}",
                SessionCompatibilityV1.COMPATIBLE if compatible else SessionCompatibilityV1.UNSUPPORTED,
                SessionAvailabilityV1.AVAILABLE if self._record_available(record) else SessionAvailabilityV1.UNAVAILABLE,
            )
        if self._directory_revision(admitted.session_dir) != before or stopped():
            complete = False
        candidates = tuple(rows[key] for key in sorted(rows))
        if not complete or duplicate:
            # The strict routing owner cannot establish authority in a partial
            # or ambiguous directory; no display row promises otherwise.
            availability = (SessionAvailabilityV1.UNAVAILABLE if complete
                            else SessionAvailabilityV1.UNVERIFIED)
            candidates = tuple(replace(row, availability=availability) for row in candidates)
        return HostedSessionDiscoverySnapshotV1(scope, candidates, complete, omitted, complete)

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        self._accepting()
        if type(limit) is not int or not 1 <= limit <= _MAX_CANDIDATES:
            raise CodingHostedCatalogError()
        selected = tuple(item for item in self.scopes if item.discovery_scope in scopes)
        if len(selected) != len(scopes):
            raise CodingHostedCatalogError()
        async with self._lock:
            self._accepting()
            records: list[_Record] = []
            for scope in selected:
                before = self._directory_revision(scope.session_dir)
                if before is None:
                    continue
                layout = AgentTranscriptFileLayout(scope.session_dir)
                snapshot = layout.scan_candidate_path_snapshot(
                    layout.namespace, max_candidates=_MAX_CANDIDATES, raise_on_error=True,
                )
                if not snapshot.complete:
                    raise CodingHostedCatalogError()
                budget = SessionDiscoveryReadBudget(
                    remaining_candidates=_MAX_CANDIDATES, remaining_bytes=32 * 1024 * 1024,
                )
                for path in snapshot.paths:
                    if not budget.reserve(candidates=1, bytes_=64 * 1024):
                        raise CodingHostedCatalogError()
                    # Routing validates every bounded canonical header. A display
                    # summary's omitted row is never proof of missing authority.
                    record = self._read_record(scope, path)
                    if record is not None:
                        records.append(record)
                if self._directory_revision(scope.session_dir) != before:
                    raise CodingHostedCatalogError()
            self._validate_records(records)
            records = [record for record in records if self._record_visible(record)]
            if len(records) > limit:
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
        self._accepting()
        async with self._lock:
            self._accepting()
            record = self._records.get(reference)
            if record is None:
                raise CodingHostedCatalogError()
            return await self._open(record)

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
        self._accepting()
        async with self._lock:
            self._accepting()
            return await self._find(request)

    async def _find(self, request: SessionCreateRequestV1) -> _Candidate | None:
        scope = self._scope_for(request)
        path = scope.session_dir / f"hosted-{_create_identity(request)}.jsonl"
        if not path.exists() and not path.is_symlink():
            return None
        record = self._read_record(scope, path)
        if (
            record is None
            or record.operation_id != request.operation_id
            or record.identity.continuity_id != request.requested_continuity_id
            or record.projection.envelope is None
            or record.projection.envelope.product_compatibility_id
            != CODING_HOSTED_COMPATIBILITY_ID
        ):
            raise CodingHostedCatalogError()
        return await self._open(record)

    async def create_candidate(self, intent: SessionCreateIntentV1) -> _Candidate:
        self._accepting()
        if intent.product_compatibility_id != CODING_HOSTED_COMPATIBILITY_ID:
            raise CodingHostedCatalogError()
        async with self._lock:
            self._accepting()
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
            if self._owned_factory is not None:
                session = await self._owned_factory.new(
                    session_dir=scope.session_dir, cwd=str(scope.cwd), session_id=session_id,
                    additional_header_metadata={_METADATA_KEY: metadata}, defer_materialization=False,
                    create_root=self._new_root_creation(),
                )
                return await self._candidate_from_owned(session, scope)
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
                record = self._read_record(scope, manager.session_file)
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


def _directory_revision(path: Path) -> tuple[int, int, int] | None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(status.st_mode) or (
        getattr(status, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise CodingHostedCatalogError()
    return status.st_dev, status.st_ino, status.st_mtime_ns


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


def _read_record(
    scope: CodingHostedScopeV1, path: Path, *, discovery: bool = False, owned: bool = False,
) -> _Record | None:
    if path.parent != scope.session_dir:
        raise CodingHostedCatalogError()
    before = _revision(path)
    header = (
        load_agent_transcript_header(path, read_only=True) if owned else
        load_agent_transcript_header(path, blocking=False, create_lock=False) if discovery else
        load_agent_transcript_header(path)
    )
    if _revision(path) != before:
        raise CodingHostedCatalogError()
    raw = header.metadata.get(_METADATA_KEY)
    if raw is None:
        return None  # Legacy/default TUI transcripts are not implicitly adopted.
    identity, compatibility, operation = _hosted_header_identity(
        header, scope=scope.scope, fingerprint=scope.fingerprint,
    )
    envelope = SessionIdentityEnvelopeV1(
        "coding", compatibility, identity.continuity_id, identity.session_id,
        "coding.jsonl", identity.session_id,
    )
    projection = SessionIdentityProjectionV1(
        SessionCandidateRefV1(scope.source_id, identity.session_id, before),
        scope.discovery_scope, SessionCandidateMode.CANONICAL, envelope,
    )
    return _Record(projection, identity, scope, path, operation, header)


def _hosted_header_identity(
    header: ConversationHeader, *, scope: SessionScopeV1, fingerprint: str,
) -> tuple[SessionIdentityV1, str, str]:
    """Validate the original v1 identity independently of a selection view."""
    raw = header.metadata.get(_METADATA_KEY)
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
        or raw["scope"] != scope.value
        or raw["scopeFingerprint"] != fingerprint
    ):
        raise CodingHostedCatalogError()
    create_request = SessionCreateRequestV1(
        "coding",
        fingerprint,
        cast(str, raw["operationId"]),
        requested_continuity_id=cast(str, raw["continuityId"]),
        requested_scope=(SessionDiscoveryScope.CURRENT_DIRECTORY if scope is SessionScopeV1.CWD
                         else SessionDiscoveryScope.USER_GLOBAL_CANONICAL),
    )
    if _create_identity(create_request) != header.conversation_id:
        raise CodingHostedCatalogError()
    identity = SessionIdentityV1(
        "coding",
        cast(str, raw["continuityId"]),
        header.conversation_id,
        scope,
        fingerprint,
    )
    return identity, cast(str, raw["compatibilityId"]), cast(str, raw["operationId"])


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
