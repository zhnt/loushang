"""Canonical Product transcript coordination in the existing AppHost integration.

The actual Product adapter remains the sole catalog instance. Transcript readers,
factory/writer and StoreAdmission remain the original resource owners. Product
hooks project values or name actual constructors; none reborrow Code IO programs.
"""

from __future__ import annotations

import asyncio
import errno
import os
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, Protocol, TypeVar, cast

from loushang.apphost._ownership import _ClaimedCandidateView, _OpenedCandidateView
from loushang.apphost.contracts import (
    ClaimedSessionCandidateV1,
    SessionBindingKeyV1,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityCatalogPortV1,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.apphost.workspace_registry import (
    WorkspaceFileRead,
    WorkspacePreviewError,
    WorkspaceRegistrationError,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionAvailabilityV1,
    SessionCompatibilityV1,
    SessionDiscoveryCandidateV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    WorkspaceInfoV1,
    WorkspaceRequestV1,
    WorkspaceResultV1,
)
from loushang.appserver.protocol.workspace_preview import (
    WorkspaceDirectoryPreviewV1,
    WorkspaceFilePreviewV1,
    WorkspacePreviewEntryV1,
    WorkspacePreviewRequestV1,
    WorkspacePreviewV1,
)
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryScopeV1,
    HostedSessionDiscoverySnapshotV1,
)
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import ConversationHeader
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.transcript import (
    AgentTranscriptLifecycleContext,
    AgentTranscriptLifecycleSession,
    AgentTranscriptSessionFactory,
)
from loushang.harness.transcript._canonical_header import (
    _CanonicalTranscriptSourceMethods,
    read_canonical_transcript_header,
)
from loushang.harness.transcript.jsonl_file import AgentTranscriptFileLayout
from loushang.harness.transcript.product_session import ProductTranscriptSession
from loushang.harness.transcript.session_catalog import SessionDiscoveryReadBudget
from loushang.harness.transcript.store_admission import (
    _TranscriptStoreCatalogObservations,
)

if TYPE_CHECKING:
    from loushang.apphost.workspace_registry import HostWorkspaceRegistryPort


_WORKSPACE_CREATE_ERRORS: dict[int | None, AppErrorCodeV1] = {
    errno.ENOENT: AppErrorCodeV1.NOT_FOUND,
    errno.EEXIST: AppErrorCodeV1.ALREADY_EXISTS,
    errno.ENOTDIR: AppErrorCodeV1.INVALID_REQUEST,
    errno.ELOOP: AppErrorCodeV1.INVALID_REQUEST,
    errno.EINVAL: AppErrorCodeV1.INVALID_REQUEST,
    errno.ENAMETOOLONG: AppErrorCodeV1.INVALID_REQUEST,
    errno.EACCES: AppErrorCodeV1.PERMISSION_DENIED,
    errno.EPERM: AppErrorCodeV1.PERMISSION_DENIED,
    errno.EROFS: AppErrorCodeV1.PERMISSION_DENIED,
}


class CanonicalTranscriptScope(Protocol):
    @property
    def scope(self) -> SessionScopeV1: ...
    @property
    def session_dir(self) -> Path: ...
    @property
    def cwd(self) -> Path: ...
    @property
    def discovery_scope(self) -> SessionDiscoveryScope: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def source_id(self) -> str: ...


def session_identity_matches_open(
    request: SessionOpenSpecV1, identity: SessionIdentityV1
) -> bool:
    return (
        identity.product_id == request.product_id
        and identity.continuity_id == request.continuity_id
        and identity.scope is request.scope
        and identity.scope_fingerprint == request.scope_fingerprint
        and (request.session_id is None or identity.session_id == request.session_id)
    )


class CanonicalTranscriptRecord(Protocol):
    @property
    def projection(self) -> SessionIdentityProjectionV1: ...
    @property
    def identity(self) -> SessionIdentityV1: ...
    @property
    def scope(self) -> CanonicalTranscriptScope: ...
    @property
    def path(self) -> Path: ...
    @property
    def operation_id(self) -> str: ...
    @property
    def header(self) -> ConversationHeader: ...


def canonical_discovery_scope(scope: SessionScopeV1) -> SessionDiscoveryScope:
    return (
        SessionDiscoveryScope.CURRENT_DIRECTORY
        if scope is SessionScopeV1.CWD
        else SessionDiscoveryScope.USER_GLOBAL_CANONICAL
    )


def canonical_create_metadata(
    intent: SessionCreateIntentV1,
    scope: CanonicalTranscriptScope,
    session_id: str,
    *,
    compatibility_id: str,
) -> dict[str, JSONValue]:
    return {
        "version": 1,
        "compatibilityId": compatibility_id,
        "continuityId": intent.request.requested_continuity_id,
        "sessionId": session_id,
        "scope": scope.scope.value,
        "scopeFingerprint": scope.fingerprint,
        "operationId": intent.request.operation_id,
    }


def read_canonical_create_identity(
    header: ConversationHeader,
    *,
    scope: SessionScopeV1,
    fingerprint: str,
    product_id: str,
    metadata_key: str,
    create_identity: Callable[[SessionCreateRequestV1], str],
    error: type[RuntimeError],
) -> tuple[SessionIdentityV1, str, str]:
    """Authenticate versioned create metadata against its original catalog scope."""
    raw = header.metadata.get(metadata_key)
    if not isinstance(raw, Mapping) or set(raw) != {
        "version",
        "compatibilityId",
        "continuityId",
        "sessionId",
        "scope",
        "scopeFingerprint",
        "operationId",
    }:
        raise error()
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise error()
    if any(type(value) is not str for key, value in raw.items() if key != "version"):
        raise error()
    if (
        raw["sessionId"] != header.conversation_id
        or raw["scope"] != scope.value
        or raw["scopeFingerprint"] != fingerprint
    ):
        raise error()
    operation_id = cast(str, raw["operationId"])
    continuity_id = cast(str, raw["continuityId"])
    request = SessionCreateRequestV1(
        product_id,
        fingerprint,
        operation_id,
        requested_continuity_id=continuity_id,
        requested_scope=canonical_discovery_scope(scope),
    )
    if create_identity(request) != header.conversation_id:
        raise error()
    identity = SessionIdentityV1(
        product_id, continuity_id, header.conversation_id, scope, fingerprint
    )
    return identity, cast(str, raw["compatibilityId"]), operation_id


@asynccontextmanager
async def close_unpublished_candidate(
    close: Callable[[], Awaitable[None]],
) -> AsyncIterator[None]:
    """On failed construction, settle the candidate that still holds custody."""
    try:
        yield
    except BaseException:
        await close()
        raise


class _AsyncBinding(Protocol):
    async def close(self) -> None: ...


RecordT = TypeVar("RecordT", bound=CanonicalTranscriptRecord)
CandidateT = TypeVar("CandidateT")
BindingInputT = TypeVar("BindingInputT")
ProductBindingT = TypeVar("ProductBindingT")
BindingT = TypeVar("BindingT", bound=_AsyncBinding)
ClaimedT = TypeVar("ClaimedT")
HistoryT = TypeVar("HistoryT")
ManagerT = TypeVar("ManagerT", bound=ProductTranscriptSession)


class _CanonicalWritableCandidateBinding(Generic[RecordT, ManagerT]):
    """Retain the original Writer or its completed Session until it transfers."""

    _candidate_error: ClassVar[type[RuntimeError]]

    def __init__(
        self, record: RecordT, manager: ManagerT, *, created: bool = False
    ) -> None:
        self.record = record
        self.created = created
        self._manager: ManagerT | None = manager
        self._dispose: Callable[[], Awaitable[None]] | None = (
            manager.dispose_runtime_profile
        )

    def manager_for_construction(self) -> ManagerT:
        if self._manager is None:
            raise self._candidate_error()
        return self._manager

    def retain_constructed_owner(self, dispose: Callable[[], Awaitable[None]]) -> None:
        self.manager_for_construction()
        self._dispose = dispose

    def take_manager(self) -> ManagerT:
        if self._manager is None:
            raise self._candidate_error()
        manager, self._manager = self._manager, None
        self._dispose = None
        return manager

    async def close(self) -> None:
        if self._dispose is not None:
            await self._dispose()
            self._dispose = None
            self._manager = None


class _CanonicalClaimedCandidate(_ClaimedCandidateView[BindingT]):
    async def close(self) -> None:
        await self.opaque_binding.close()


class _CanonicalRecordBinding(Protocol):
    @property
    def record(self) -> CanonicalTranscriptRecord: ...


RecordBindingT = TypeVar("RecordBindingT", bound=_CanonicalRecordBinding)


class _CanonicalOpenedCandidate(_OpenedCandidateView[RecordBindingT]):
    """A Product construction borrow whose claimed candidate still owns cleanup."""

    def __init__(self, binding: RecordBindingT) -> None:
        identity = binding.record.identity
        super().__init__(
            SessionBindingKeyV1(
                identity.product_id, identity.continuity_id, identity.session_id
            ),
            binding,
        )

    async def close(self) -> None:
        return None


def require_canonical_candidate_binding(
    candidate: ClaimedSessionCandidateV1,
    envelope: SessionIdentityEnvelopeV1,
    *,
    binding_types: tuple[type[RecordBindingT], ...],
    compatibility_id: str,
    error: type[RuntimeError],
) -> RecordBindingT:
    binding = candidate.opaque_binding
    if type(binding) not in binding_types:
        raise error()
    selected = cast(RecordBindingT, binding)
    projection = selected.record.projection
    if (
        projection.reference != candidate.reference
        or projection.envelope != envelope
        or projection.envelope is None
        or projection.envelope.product_compatibility_id != compatibility_id
    ):
        raise error()
    return selected


class _CanonicalTranscriptCatalogMethods(
    _CanonicalTranscriptSourceMethods,
    Generic[RecordT, CandidateT, BindingInputT, ProductBindingT],
):
    scopes: tuple[CanonicalTranscriptScope, ...]
    _records: dict[SessionCandidateRefV1, RecordT]
    _lock: asyncio.Lock
    _owned_factory: AgentTranscriptSessionFactory[BindingInputT, ProductBindingT] | None
    _pending_sessions: dict[int, AgentTranscriptLifecycleSession[ProductBindingT]]
    _legacy_transcript_factory: AgentTranscriptSessionFactory[
        BindingInputT, ProductBindingT
    ]
    _legacy_transcript_type: type[
        ProductTranscriptSession[BindingInputT, ProductBindingT]
    ]
    _owned_transcript_type: type[
        ProductTranscriptSession[BindingInputT, ProductBindingT]
    ]
    _closing: bool
    _loop: asyncio.AbstractEventLoop | None

    def _initialize_catalog(
        self,
        scopes: tuple[CanonicalTranscriptScope, ...],
        *,
        legacy_factory: AgentTranscriptSessionFactory[BindingInputT, ProductBindingT],
        legacy_type: type[ProductTranscriptSession[BindingInputT, ProductBindingT]],
        owned_type: type[ProductTranscriptSession[BindingInputT, ProductBindingT]],
        make_owned_factory: (
            Callable[[], AgentTranscriptSessionFactory[BindingInputT, ProductBindingT]]
            | None
        ),
    ) -> None:
        self.scopes = scopes
        self._legacy_transcript_factory = legacy_factory
        self._legacy_transcript_type = legacy_type
        self._owned_transcript_type = owned_type
        self._records = {}
        self._lock = asyncio.Lock()
        self._owned_factory = (
            make_owned_factory() if make_owned_factory is not None else None
        )
        self._pending_sessions = {}
        self._closing = False
        self._loop = None

    @property
    def pending_sessions(
        self,
    ) -> tuple[AgentTranscriptLifecycleSession[ProductBindingT], ...]:
        return tuple(self._pending_sessions.values())

    def _product_id(self) -> str:
        raise NotImplementedError

    def _compatibility_id(self) -> str:
        raise NotImplementedError

    def _maximum_candidates(self) -> int:
        raise NotImplementedError

    def _discovery_bytes(self) -> int:
        raise NotImplementedError

    def _create_identity(self, request: SessionCreateRequestV1) -> str:
        raise NotImplementedError

    def _session_name(self, request: SessionCreateRequestV1) -> str:
        raise NotImplementedError

    def _candidate_from_manager(
        self,
        record: RecordT,
        manager: ProductTranscriptSession[BindingInputT, ProductBindingT],
        *,
        created: bool = False,
    ) -> CandidateT:
        raise NotImplementedError

    def _new_header_metadata(
        self,
        intent: SessionCreateIntentV1,
        scope: CanonicalTranscriptScope,
        session_id: str,
    ) -> dict[str, JSONValue]:
        raise NotImplementedError

    def _scope_for(self, request: SessionCreateRequestV1) -> CanonicalTranscriptScope:
        if (
            request.product_id != self._product_id()
            or request.requested_continuity_id is None
        ):
            raise self._catalog_error_class()()
        for scope in self.scopes:
            if (
                scope.discovery_scope is request.requested_scope
                and scope.fingerprint == request.creator_scope_id
            ):
                return scope
        raise self._catalog_error_class()()

    def _validate_open_record(self, record: RecordT) -> None:
        raise NotImplementedError

    def _display_identity(self, record: RecordT) -> SessionIdentityV1:
        return record.identity

    def _record_visible(self, record: RecordT) -> bool:
        return True

    def _record_compatible(self, record: RecordT) -> bool:
        raise NotImplementedError

    def _record_available(self, record: RecordT) -> bool:
        return self._record_compatible(record)

    def _validate_records(self, records: list[RecordT]) -> None:
        raise NotImplementedError

    def _new_root_creation(self) -> bool:
        return False

    def _project_catalog_record(
        self,
        scope: CanonicalTranscriptScope,
        path: Path,
        revision: str,
        header: ConversationHeader,
    ) -> RecordT | None:
        raise NotImplementedError

    def _candidate_layout(self, directory: Path) -> AgentTranscriptFileLayout:
        return AgentTranscriptFileLayout(directory)

    def _header_read_context(self) -> tuple[bool, threading.Event | None]:
        return self._owned_factory is not None, None

    def _read_record(
        self, scope: CanonicalTranscriptScope, path: Path, *, discovery: bool = False
    ) -> RecordT | None:
        owned, observed = self._header_read_context()
        revision, header = read_canonical_transcript_header(
            scope.session_dir,
            path,
            owned=owned,
            discovery=discovery,
            root_observed=observed,
            maximum_bytes=self._maximum_transcript_bytes,
            error=self._catalog_error,
        )
        return self._project_catalog_record(scope, path, revision, header)

    @asynccontextmanager
    async def _current_discovered_record(
        self, reference: SessionCandidateRefV1,
    ) -> AsyncIterator[RecordT]:
        async with self._lock:
            self._accepting()
            record = self._records.get(reference)
            if record is None or self._source_revision(record.path) != reference.revision:
                raise self._catalog_error()
            yield record

    async def _read_discovered_history(
        self,
        reference: SessionCandidateRefV1,
        read: Callable[[Path], HistoryT],
        matches_source: Callable[[HistoryT, str, ConversationHeader], bool],
    ) -> HistoryT:
        """Observe the exact discovered history without acquiring a Writer."""
        self._accepting()
        async with self._current_discovered_record(reference) as record:
            path = record.path
        history = await settled_io(read, path)
        self._accepting()
        if (
            self._source_revision(record.path) != reference.revision
            or not matches_source(history, reference.revision, record.header)
        ):
            raise self._catalog_error()
        return history

    async def _open_discovered_history_candidate(
        self,
        reference: SessionCandidateRefV1,
        binding: BindingT,
        project: Callable[[RecordT, BindingT], CandidateT],
    ) -> CandidateT:
        async with close_unpublished_candidate(lambda: binding.close()):
            async with self._current_discovered_record(reference) as record:
                return project(record, binding)

    def _admitted_scope(self, scope: SessionScopeV1, fingerprint: str) -> CanonicalTranscriptScope | None:
        return next(
            (item for item in self.scopes if item.scope is scope and item.fingerprint == fingerprint),
            None,
        )

    async def _delete_canonical_history(
        self, identity: SessionIdentityV1, session_path: Callable[[Path, str], Path],
    ) -> None:
        from loushang.harness.transcript.lifecycle import delete_agent_transcript_jsonl

        async with self._lock:
            self._accepting()
            scope = self._admitted_scope(identity.scope, identity.scope_fingerprint)
            if scope is None:
                raise self._catalog_error()
            path = session_path(scope.session_dir, identity.session_id)
            record = await settled_io(self._read_record, scope, path)
            if record is None or record.identity != identity or not self._record_compatible(record):
                raise self._catalog_error()
            await delete_agent_transcript_jsonl(path, maintenance_owner=self._owned_factory)
            self._records = {
                key: value for key, value in self._records.items() if value.identity != identity
            }

    @staticmethod
    def _record_lifecycle_context(record: RecordT) -> AgentTranscriptLifecycleContext:
        return AgentTranscriptLifecycleContext(
            session_dir=record.scope.session_dir,
            cwd=str(record.scope.cwd),
            persist=True,
            header=record.header,
            session_file=record.path,
        )

    async def _open_legacy_record(self, record: RecordT) -> CandidateT:
        revision = self._source_revision
        error = self._catalog_error
        factory = self._legacy_transcript_factory
        manager_type = self._legacy_transcript_type
        candidate = self._candidate_from_manager
        if revision(record.path) != record.projection.reference.revision:
            raise error()
        context = self._record_lifecycle_context(record)
        manager = manager_type(lifecycle_session=await factory.restore_context(context))
        async with close_unpublished_candidate(lambda: manager.dispose_runtime_profile()):
            if (
                manager.header != record.header
                or revision(record.path) != record.projection.reference.revision
            ):
                raise error()
            return candidate(record, manager)

    def _on_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise self._catalog_error_class()()

    def _accepting(self) -> None:
        if self._owned_factory is not None:
            self._on_loop()
            if self._closing:
                raise self._catalog_error_class()()

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

    async def _discard_session(
        self, session: AgentTranscriptLifecycleSession[ProductBindingT]
    ) -> None:
        await session.dispose()
        self._pending_sessions.pop(id(session), None)

    async def _candidate_from_owned(
        self,
        session: AgentTranscriptLifecycleSession[ProductBindingT],
        scope: CanonicalTranscriptScope,
        *,
        expected: RecordT | None = None,
    ) -> CandidateT:
        self._pending_sessions[id(session)] = session
        try:
            self._accepting()
            manager = self._owned_transcript_type(lifecycle_session=session)
            assert manager.session_file is not None
            with session.sync_operation_scope():
                record = self._read_record(scope, manager.session_file)
            if (
                record is None
                or record.header != session.context.header
                or (expected is not None and record != expected)
            ):
                raise self._catalog_error_class()()
            self._validate_open_record(record)
            with session.sync_operation_scope():
                pass
            candidate = self._candidate_from_manager(
                record, manager, created=expected is None
            )
            self._accepting()
            self._pending_sessions.pop(id(session))
            return candidate
        except BaseException as error:
            try:
                await self._discard_session(session)
            except BaseException as cleanup_error:
                error.add_note(
                    f"owned catalog cleanup retained: {type(cleanup_error).__name__}"
                )
            raise

    async def _open(self, record: RecordT) -> CandidateT:
        self._validate_open_record(record)
        if self._owned_factory is None:
            return await self._open_legacy_record(record)
        if self._source_revision(record.path) != record.projection.reference.revision:
            raise self._catalog_error_class()()
        context = self._record_lifecycle_context(record)
        session = await self._owned_factory.restore_context(context)
        return await self._candidate_from_owned(session, record.scope, expected=record)

    async def discover_sessions(
        self, scope: HostedSessionDiscoveryScopeV1, *, stop: Callable[[], bool]
    ) -> HostedSessionDiscoverySnapshotV1:
        self._accepting()
        if (
            type(scope) is not HostedSessionDiscoveryScopeV1
            or scope.product_id != self._product_id()
        ):
            raise ValueError("unadmitted discovery scope")
        selected = self._admitted_scope(scope.scope, scope.scope_fingerprint)
        if selected is None:
            raise ValueError("unadmitted discovery scope")
        cancelled = threading.Event()
        loop = asyncio.get_running_loop()
        completed: asyncio.Future[HostedSessionDiscoverySnapshotV1 | None] = (
            loop.create_future()
        )
        submitted = threading.Event()
        admitted = False

        def read() -> None:
            submitted.wait()
            if not admitted:
                return
            try:
                value = self._read_discovery(
                    selected, scope, lambda: cancelled.is_set() or stop()
                )
            except BaseException:
                value = None
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
            raise self._catalog_error_class()()
        self._accepting()
        return result

    def _read_discovery(
        self,
        admitted: CanonicalTranscriptScope,
        scope: HostedSessionDiscoveryScopeV1,
        stop: Callable[[], bool],
    ) -> HostedSessionDiscoverySnapshotV1:
        deadline = time.monotonic() + 5

        def stopped() -> bool:
            return stop() or time.monotonic() >= deadline

        if stopped():
            return HostedSessionDiscoverySnapshotV1(
                scope, (), False, omitted_count_exact=False
            )
        before = self._directory_revision(admitted.session_dir)
        if before is None:
            return HostedSessionDiscoverySnapshotV1(scope, (), True)
        layout = self._candidate_layout(admitted.session_dir)
        scan = layout.scan_candidate_path_snapshot(
            layout.namespace,
            max_candidates=self._maximum_candidates(),
            should_stop=stopped,
            raise_on_error=True,
        )
        budget = SessionDiscoveryReadBudget(
            remaining_candidates=self._maximum_candidates(),
            remaining_bytes=self._discovery_bytes(),
        )
        complete, omitted, duplicate = (scan.complete, 0, False)
        rows: dict[str, SessionDiscoveryCandidateV1] = {}
        seen: set[str] = set()
        for path in scan.paths:
            if stopped() or not budget.reserve(candidates=1, bytes_=64 * 1024):
                complete = False
                break
            try:
                record = self._read_record(admitted, path, discovery=True)
            except (OSError, ValueError, self._catalog_error_class()):
                complete, omitted = (False, omitted + 1)
                continue
            if record is None:
                omitted += 1
                continue
            identity = self._display_identity(record)
            if identity.session_id in seen:
                duplicate, omitted = (True, omitted + 1)
                continue
            seen.add(identity.session_id)
            if not self._record_visible(record):
                continue
            compatible = self._record_compatible(record)
            rows[identity.session_id] = SessionDiscoveryCandidateV1(
                identity,
                f"Session {identity.session_id[:12]}",
                SessionCompatibilityV1.COMPATIBLE
                if compatible
                else SessionCompatibilityV1.UNSUPPORTED,
                SessionAvailabilityV1.AVAILABLE
                if self._record_available(record)
                else SessionAvailabilityV1.UNAVAILABLE,
            )
        if self._directory_revision(admitted.session_dir) != before or stopped():
            complete = False
        candidates = tuple((rows[key] for key in sorted(rows)))
        if not complete or duplicate:
            availability = (
                SessionAvailabilityV1.UNAVAILABLE
                if complete
                else SessionAvailabilityV1.UNVERIFIED
            )
            candidates = tuple(
                (replace(row, availability=availability) for row in candidates)
            )
        return HostedSessionDiscoverySnapshotV1(
            scope, candidates, complete, omitted, complete
        )

    async def list_identities(
        self, scopes: tuple[SessionDiscoveryScope, ...], *, limit: int
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        self._accepting()
        if type(limit) is not int or not 1 <= limit <= self._maximum_candidates():
            raise self._catalog_error_class()()
        selected = tuple(
            (item for item in self.scopes if item.discovery_scope in scopes)
        )
        if len(selected) != len(scopes):
            raise self._catalog_error_class()()
        async with self._lock:
            self._accepting()
            records: list[RecordT] = []
            for scope in selected:
                before = self._directory_revision(scope.session_dir)
                if before is None:
                    continue
                layout = self._candidate_layout(scope.session_dir)
                snapshot = layout.scan_candidate_path_snapshot(
                    layout.namespace,
                    max_candidates=self._maximum_candidates(),
                    raise_on_error=True,
                )
                if not snapshot.complete:
                    raise self._catalog_error_class()()
                budget = SessionDiscoveryReadBudget(
                    remaining_candidates=self._maximum_candidates(),
                    remaining_bytes=32 * 1024 * 1024,
                )
                for path in snapshot.paths:
                    if not budget.reserve(candidates=1, bytes_=64 * 1024):
                        raise self._catalog_error_class()()
                    record = self._read_record(scope, path)
                    if record is not None:
                        records.append(record)
                if self._directory_revision(scope.session_dir) != before:
                    raise self._catalog_error_class()()
            self._validate_records(records)
            records = [record for record in records if self._record_visible(record)]
            if len(records) > limit:
                raise self._catalog_error_class()()
            selected_sources = {scope.source_id for scope in selected}
            self._records = {
                reference: record
                for reference, record in self._records.items()
                if reference.source_id not in selected_sources
            }
            self._records.update(
                ((record.projection.reference, record) for record in records)
            )
            return tuple((record.projection for record in records))

    async def open_candidate(self, reference: SessionCandidateRefV1) -> CandidateT:
        self._accepting()
        async with self._lock:
            self._accepting()
            record = self._records.get(reference)
            if record is None:
                raise self._catalog_error_class()()
            return await self._open(record)

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> CandidateT | None:
        self._accepting()
        async with self._lock:
            self._accepting()
            return await self._find(request)

    async def _find(self, request: SessionCreateRequestV1) -> CandidateT | None:
        scope = self._scope_for(request)
        path = scope.session_dir / self._session_name(request)
        if not path.exists() and (not path.is_symlink()):
            return None
        record = self._read_record(scope, path)
        if (
            record is None
            or record.operation_id != request.operation_id
            or record.identity.continuity_id != request.requested_continuity_id
            or (record.projection.envelope is None)
            or (
                record.projection.envelope.product_compatibility_id
                != self._compatibility_id()
            )
        ):
            raise self._catalog_error_class()()
        return await self._open(record)

    async def create_candidate(self, intent: SessionCreateIntentV1) -> CandidateT:
        self._accepting()
        if intent.product_compatibility_id != self._compatibility_id():
            raise self._catalog_error_class()()
        async with self._lock:
            self._accepting()
            existing = await self._find(intent.request)
            if existing is not None:
                return existing
            scope = self._scope_for(intent.request)
            session_id = self._create_identity(intent.request)
            header_metadata = self._new_header_metadata(intent, scope, session_id)
            if self._owned_factory is not None:
                session = await self._owned_factory.new(
                    session_dir=scope.session_dir,
                    cwd=str(scope.cwd),
                    session_id=session_id,
                    additional_header_metadata=header_metadata,
                    defer_materialization=False,
                    create_root=self._new_root_creation(),
                )
                return await self._candidate_from_owned(session, scope)
            try:
                manager = await self._legacy_transcript_type.new(
                    session_dir=scope.session_dir,
                    cwd=str(scope.cwd),
                    session_id=session_id,
                    additional_header_metadata=header_metadata,
                    defer_materialization=False,
                )
            except Exception:
                recovered = await self._find(intent.request)
                if recovered is None:
                    raise self._catalog_error_class()() from None
                return recovered
            async with close_unpublished_candidate(lambda: manager.dispose_runtime_profile()):
                assert manager.session_file is not None
                record = self._read_record(scope, manager.session_file)
                if record is None:
                    raise self._catalog_error_class()()
                return self._candidate_from_manager(record, manager, created=True)


class _ManagedCanonicalTranscriptCatalogMethods(
    _TranscriptStoreCatalogObservations,
    _CanonicalTranscriptCatalogMethods[
        RecordT, CandidateT, BindingInputT, ProductBindingT
    ],
):
    _root_initialization: bool
    _root_observed: threading.Event

    def _initialize_managed_store(
        self, store_state_root: Path | None, *, initialize_session_root: bool
    ) -> None:
        if type(initialize_session_root) is not bool:
            raise TypeError("invalid Session root initialization grant")
        if store_state_root is not None and initialize_session_root:
            raise ValueError("store admission cannot be combined with a root creation grant")
        # A caller must have established first-initialization authority.
        self._root_initialization = initialize_session_root
        self._initialize_store_observations(store_state_root)

    def _header_read_context(self) -> tuple[bool, threading.Event | None]:
        return True, self._root_observed

    def _accepting(self) -> None:
        super()._accepting()
        if os.path.lexists(self.scopes[0].session_dir):
            self._root_observed.set()
        if self._root_observed.is_set():
            self._root_initialization = False

    def _new_root_creation(self) -> bool:
        grant, self._root_initialization = (self._root_initialization, False)
        return grant and (not self._root_observed.is_set())

    async def discover_sessions(
        self, scope: HostedSessionDiscoveryScopeV1, *, stop: Callable[[], bool]
    ) -> HostedSessionDiscoverySnapshotV1:
        self._accepting()
        with self._store_probe_lock:
            if (
                self._store_probes_fenced
                or self._store_active_reads >= self._maximum_store_observations()
            ):
                raise self._catalog_error_class()()
            self._store_active_reads += 1
        try:
            return await super().discover_sessions(scope, stop=stop)
        finally:
            with self._store_probe_lock:
                self._store_active_reads -= 1

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


class _CanonicalTranscriptCandidateMethods(
    _CanonicalTranscriptSourceMethods, Generic[RecordT, BindingT, ClaimedT]
):
    _record: RecordT
    _binding: BindingT
    _claimed: bool
    _closed: bool

    def _history_source_guard(self) -> Callable[[], None] | None:
        raise NotImplementedError

    def _claim_binding(
        self, reference: SessionCandidateRefV1, binding: BindingT
    ) -> ClaimedT:
        raise NotImplementedError

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._record.projection

    async def verify_current(self) -> None:
        if self._closed:
            raise self._catalog_error_class()()
        guard = self._history_source_guard()
        if guard is not None:
            guard()
        elif (
            self._source_revision(self._record.path)
            != self.projection.reference.revision
        ):
            raise self._catalog_error()

    async def claim(self) -> ClaimedT:
        await self.verify_current()
        if self._claimed:
            raise self._catalog_error_class()()
        self._claimed = True
        return self._claim_binding(self.projection.reference, self._binding)

    async def close(self) -> None:
        self._closed = True
        if not self._claimed:
            await self._binding.close()


class _WorkspaceSessionCatalogPort(SessionIdentityCatalogPortV1, Protocol):
    @property
    def scopes(self) -> tuple[CanonicalTranscriptScope, ...]: ...
    @property
    def pending_sessions(self) -> tuple[object, ...]: ...
    async def discover_sessions(
        self, scope: HostedSessionDiscoveryScopeV1, *, stop: Callable[[], bool]
    ) -> HostedSessionDiscoverySnapshotV1: ...
    async def delete_session_history(self, identity: SessionIdentityV1) -> None: ...
    def fence(self) -> None: ...
    async def close(self) -> None: ...


WorkspaceCatalogT = TypeVar("WorkspaceCatalogT", bound=_WorkspaceSessionCatalogPort)


class _WorkspaceTranscriptCatalogMethods(Generic[WorkspaceCatalogT]):
    """Retain workspace catalogs and route their existing transcript owners.

    Product adapters supply actual catalog construction and candidate-open
    policy. The adapter remains the sole collection object; Registry and child
    catalogs retain their existing native storage and Session lifetimes.
    """

    registry: HostWorkspaceRegistryPort
    _catalogs: dict[Path, WorkspaceCatalogT]
    _loaded: bool
    _closed: bool

    def _create_catalog(self, path: Path) -> WorkspaceCatalogT:
        raise NotImplementedError

    async def _open_workspace_candidate(self, catalog: WorkspaceCatalogT, reference):
        raise NotImplementedError

    async def _inspect_workspace(
        self, path: Path, catalog: WorkspaceCatalogT,
        scope: CanonicalTranscriptScope, session_id: str | None,
    ) -> dict[str, object]:
        raise NotImplementedError

    async def _select_workspace_for_read(self, path: str) -> Path:
        if self._closed:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        try:
            return await settled_io(self.registry.select, path)
        except (OSError, ValueError):
            raise AppServiceError(AppErrorCodeV1.NOT_FOUND) from None

    async def _registered_workspace_for_read(self, path: str) -> tuple[Path, WorkspaceCatalogT]:
        root = await self._select_workspace_for_read(path)
        catalog = self._catalogs.get(root)
        if catalog is None:
            raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
        return root, catalog

    async def _preview_workspace(self, path: str, request: WorkspacePreviewRequestV1) -> WorkspaceResultV1:
        root, catalog = await self._registered_workspace_for_read(path)
        scope = catalog.scopes[0]
        if root != Path(path) or scope.fingerprint != request.scope_fingerprint:
            raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
        try:
            opened = await settled_io(self.registry.preview, root, request.reference, request.base)
        except WorkspacePreviewError as exc:
            raise AppServiceError(AppErrorCodeV1(exc.code)) from None
        preview: WorkspacePreviewV1
        if isinstance(opened, WorkspaceFileRead):
            preview = WorkspaceFilePreviewV1(opened.path, opened.text)
        else:
            entries = tuple(WorkspacePreviewEntryV1(name, kind) for name, kind in opened.entries)
            preview = WorkspaceDirectoryPreviewV1(opened.path, entries, opened.limited)
        return WorkspaceResultV1((_workspace_info(root, scope, preview=preview),))

    async def workspace(self, request: WorkspaceRequestV1) -> WorkspaceResultV1:
        if request.preview is not None and request.path is not None:
            return await self._preview_workspace(request.path, request.preview)
        if request.action == "inspect":
            path, catalog = await self._registered_workspace_for_read(cast(str, request.path))
            if self.registry.is_temporary(path):
                raise AppServiceError(AppErrorCodeV1.NOT_FOUND)
            scope = catalog.scopes[0]
            report = await self._inspect_workspace(path, catalog, scope, request.session_id)
            return WorkspaceResultV1((_workspace_info(path, scope, inspection=report),))
        entries = await self._workspace_entries(request)
        return WorkspaceResultV1(tuple(_workspace_info(path, catalog.scopes[0]) for path, catalog in entries))

    async def delete_session_history(self, identity: SessionIdentityV1) -> None:
        catalog = self._find(lambda scope: scope.fingerprint == identity.scope_fingerprint)
        await catalog.delete_session_history(identity)

    async def _workspace_entries(self, request):
        if request.action == "register":
            await self.register(request.path)
        elif request.action == "create":
            path = await self._create_workspace(request.path)
            return ((path, self._add(path)),)
        elif request.action == "allocate-temporary":
            path = await asyncio.to_thread(self.registry.allocate_temporary)
            self._add(path)
        elif request.action == "open":
            selected = await self.select(request.path)
        elif request.action == "unregister":
            path = Path(request.path)
            catalog = self._catalogs.get(path)
            if catalog is not None:
                await catalog.close()
            await asyncio.to_thread(self.registry.unregister, request.path)
            self._catalogs.pop(path, None)
        entries = self._catalogs.items()
        if request.action == "open":
            entries = ((selected.cwd, self._catalogs[selected.cwd]),)
        elif request.action == "allocate-temporary":
            entries = ((path, self._catalogs[path]),)
        elif request.action == "projects":
            entries = (
                (root, catalog)
                for root, catalog in entries
                if not self.registry.is_temporary(root)
            )
        return entries

    async def load(self) -> None:
        if not self._loaded:
            for path in await asyncio.to_thread(self._load_paths):
                self._add(path)
            self._loaded = True

    def _load_paths(self) -> tuple[Path, ...]:
        self.registry.open()
        return self.registry.list()

    @property
    def scopes(self):
        return tuple(catalog.scopes[0] for catalog in self._catalogs.values())

    @property
    def pending_sessions(self):
        return tuple(
            session
            for catalog in self._catalogs.values()
            for session in catalog.pending_sessions
        )

    def _add(self, path: Path) -> WorkspaceCatalogT:
        if self._closed:
            raise ValueError("workspace_catalog_closed")
        if path not in self._catalogs:
            self._catalogs[path] = self._create_catalog(path)
        return self._catalogs[path]

    async def _create_workspace(self, value: str) -> Path:
        try:
            return await asyncio.to_thread(self.registry.create, value)
        except WorkspaceRegistrationError as exc:
            raise AppServiceError(AppErrorCodeV1.WORKSPACE_REGISTRATION_FAILED) from exc
        except ValueError as exc:
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST) from exc
        except OSError as exc:
            code = _WORKSPACE_CREATE_ERRORS.get(exc.errno, AppErrorCodeV1.OPERATION_UNAVAILABLE)
            raise AppServiceError(code) from exc

    async def register(self, value: str) -> Path:
        path = await asyncio.to_thread(self.registry.register, value)
        self._add(path)
        return path

    async def select(self, value: str):
        path = await asyncio.to_thread(self.registry.select, value)
        return self._add(path).scopes[0]

    def _for_create(self, request):
        return self._find(lambda scope: scope.fingerprint == request.creator_scope_id)

    def _for_reference(self, reference):
        return self._find(lambda scope: scope.source_id == reference.source_id)

    def _find(self, matches):
        if not self._closed:
            for catalog in self._catalogs.values():
                if any(matches(scope) for scope in catalog.scopes):
                    return catalog
        raise ValueError("workspace_not_registered")

    async def discover_sessions(self, scope, *, stop):
        catalog = self._find(
            lambda item: (
                item.scope is scope.scope
                and item.fingerprint == scope.scope_fingerprint
            )
        )
        return await catalog.discover_sessions(scope, stop=stop)

    async def workspace_identities(self, fingerprint, scope, *, limit):
        catalog = self._find(
            lambda item: (
                item.fingerprint == fingerprint and item.discovery_scope is scope
            )
        )
        return await catalog.list_identities((scope,), limit=limit)

    async def list_identities(self, scopes, *, limit):
        result = []
        for catalog in self._catalogs.values():
            result.extend(await catalog.list_identities(scopes, limit=limit))
            if len(result) > limit:
                raise ValueError("session_catalog_limit")
        return tuple(result)

    async def open_candidate(self, reference):
        catalog = self._for_reference(reference)
        return await self._open_workspace_candidate(catalog, reference)

    async def find_created_candidate(self, request):
        return await self._for_create(request).find_created_candidate(request)

    async def create_candidate(self, intent):
        return await self._for_create(intent.request).create_candidate(intent)

    def fence(self) -> None:
        self._closed = True
        for catalog in self._catalogs.values():
            catalog.fence()

    async def close(self) -> None:
        self.fence()
        results = await asyncio.gather(
            *(c.close() for c in self._catalogs.values()), return_exceptions=True
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup("workspace_cleanup_incomplete", failures)
        await asyncio.to_thread(self.registry.close)


def _workspace_info(
    path: Path,
    scope: CanonicalTranscriptScope,
    *,
    inspection: dict[str, object] | None = None,
    preview: WorkspacePreviewV1 | None = None,
) -> WorkspaceInfoV1:
    return WorkspaceInfoV1(str(path), scope.scope, scope.fingerprint, inspection, preview)
