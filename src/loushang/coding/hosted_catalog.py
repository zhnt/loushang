"""Coding canonical Session owner for explicitly admitted hosted scopes.

Identity and create-idempotency facts live in the real transcript header, not
in a parallel Session index. Candidate tokens never supply filesystem paths.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

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
from loushang.apphost.integrations._canonical_transcript_catalog import (
    CanonicalTranscriptScope,
    _CanonicalTranscriptCandidateMethods,
    _CanonicalTranscriptCatalogMethods,
)
from loushang.appserver.protocol import (
    SessionIdentityV1,
    SessionScopeV1,
)
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryScopeV1,
    HostedSessionDiscoverySnapshotV1,
)
from loushang.foundation.json import JSONValue
from loushang.harness.conversation import ConversationHeader
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.runtime import ResolvedRuntimeProfile, RuntimeProfileBinding
from loushang.harness.transcript import (
    AgentTranscriptLifecycle,
    AgentTranscriptLifecycleSession,
    AgentTranscriptSessionFactory,
    _canonical_header,
)
from loushang.harness.transcript.product_session import ProductTranscriptSession

from .appservice_adapter import CodingHostedSessionBindingV1
from .composition_provenance import composition_header_metadata
from .composition_sets import resolve_coding_composition_set
from .product_plan import CODING_PRODUCT_ID, CODING_TRANSCRIPT_RUNTIME
from .resume_history import (
    MAX_CODING_RESUME_HISTORY_BYTES,
    CodingResumeHeaderPreview,
    CodingResumeHistoryPreview,
    inspect_coding_resume_header,
    read_coding_resume_snapshot,
)
from .resume_input_lookup import CodingResumeInputLookupQueryV1
from .resume_model_outcome import (
    CodingResumeModelOutcomeObservationV1,
    observe_coding_resume_model_outcome,
)
from .session_manager import (
    _LIFECYCLE,
    SessionManager,
    _coding_header_metadata,
    _resolve_coding_binding_input,
    _validate_coding_restored_header,
)

if TYPE_CHECKING:
    from .hosted_session import CodingHostedHistoryBindingV1

CODING_HOSTED_COMPATIBILITY_ID = "coding-hosted-v1"
_METADATA_KEY = "coding.hosted"
_MAX_CANDIDATES = 256
_MAX_TRANSCRIPT_BYTES = MAX_CODING_RESUME_HISTORY_BYTES
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


@dataclass(slots=True)
class CodingHostedResumeSourceV1:
    """Transferred read view plus the original catalog's Resume Writer owner."""

    record: _Record
    history_binding: CodingHostedHistoryBindingV1
    manager_type: type[SessionManager]
    writer_factory: AgentTranscriptSessionFactory[
        ResolvedRuntimeProfile,
        RuntimeProfileBinding,
    ]
    _require_current: Callable[[], None] = field(repr=False)
    _closed: bool = False

    @property
    def history(self) -> CodingResumeHistoryPreview:
        if self._closed:
            raise CodingHostedCatalogError()
        history = getattr(self.history_binding, "resume_history", None)
        if type(history) is not CodingResumeHistoryPreview:
            raise CodingHostedCatalogError()
        return history

    def require_current_source(self) -> None:
        if self._closed:
            raise CodingHostedCatalogError()
        self._require_current()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.history_binding.close()


class CodingHostedHistoryCandidateBindingV1:
    """Claimed display ownership, without transcript or runtime ownership."""

    def __init__(
        self, record: _Record, binding: CodingHostedSessionBindingV1,
        require_accepting: Callable[[], None],
        *,
        manager_type: type[SessionManager],
        writer_factory: AgentTranscriptSessionFactory[
            ResolvedRuntimeProfile,
            RuntimeProfileBinding,
        ],
    ) -> None:
        self.record = record
        self._binding: CodingHostedSessionBindingV1 | None = binding
        self._require_accepting = require_accepting
        self._manager_type = manager_type
        self._writer_factory = writer_factory

    @property
    def supports_writable_resume(self) -> bool:
        return self._writer_factory.owns_persistent_sessions

    def take_binding(self) -> CodingHostedHistoryBindingV1:
        from .hosted_session import CodingHostedHistoryBindingV1

        self.require_current_source()
        if type(self._binding) is not CodingHostedHistoryBindingV1:
            raise CodingHostedCatalogError()
        binding, self._binding = self._binding, None
        return binding

    def take_resume_source(self) -> CodingHostedResumeSourceV1:
        return CodingHostedResumeSourceV1(
            record=self.record,
            history_binding=self.take_binding(),
            manager_type=self._manager_type,
            writer_factory=self._writer_factory,
            _require_current=self.require_current_source,
        )

    def require_current_source(self) -> None:
        self._require_accepting()
        if _revision(self.record.path) != self.record.projection.reference.revision:
            raise CodingHostedCatalogError()

    async def close(self) -> None:
        binding = self._binding
        if binding is not None:
            await binding.close()
            self._binding = None


_CodingHostedCandidateBinding = (
    CodingHostedCandidateBindingV1 | CodingHostedHistoryCandidateBindingV1
)


class _Claimed:
    def __init__(
        self, reference: SessionCandidateRefV1, binding: _CodingHostedCandidateBinding
    ) -> None:
        self._reference = reference
        self._binding = binding

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> _CodingHostedCandidateBinding:
        return self._binding

    async def close(self) -> None:
        await self.opaque_binding.close()


class _Candidate(
    _CanonicalTranscriptCandidateMethods[
        _Record, _CodingHostedCandidateBinding, _Claimed
    ]
):
    def _catalog_error_class(self) -> type[RuntimeError]:
        return CodingHostedCatalogError

    def _maximum_transcript_bytes(self) -> int:
        return _MAX_TRANSCRIPT_BYTES

    def _history_source_guard(self) -> Callable[[], None] | None:
        return (
            self._binding.require_current_source
            if isinstance(self._binding, CodingHostedHistoryCandidateBindingV1)
            else None
        )

    def _claim_binding(
        self, reference: SessionCandidateRefV1, binding: _CodingHostedCandidateBinding
    ) -> _Claimed:
        return _Claimed(reference, binding)

    def __init__(
        self, record: _Record, binding: _CodingHostedCandidateBinding
    ) -> None:
        self._record = record
        self._binding = binding
        self._claimed = False
        self._closed = False


class _Opened:
    def __init__(self, binding: _CodingHostedCandidateBinding) -> None:
        identity = binding.record.identity
        self._binding_key = SessionBindingKeyV1(
            identity.product_id, identity.continuity_id, identity.session_id
        )
        self._binding = binding

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key

    @property
    def opaque_binding(self) -> _CodingHostedCandidateBinding:
        return self._binding

    async def close(self) -> None:
        # The candidate owns an unconsumed binding; Product owns a taken one.
        return None


class CodingHostedCandidateValidatorV1:
    async def open_product_candidate(
        self,
        candidate: ClaimedSessionCandidateV1,
        envelope: SessionIdentityEnvelopeV1,
    ) -> OpenedProductCandidateV1:
        binding = candidate.opaque_binding
        if type(binding) not in (
            CodingHostedCandidateBindingV1, CodingHostedHistoryCandidateBindingV1,
        ):
            raise CodingHostedCatalogError()
        binding = cast(_CodingHostedCandidateBinding, binding)
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


class CodingHostedSessionCatalogV1(
    _CanonicalTranscriptCatalogMethods[
        _Record, _Candidate, ResolvedRuntimeProfile, RuntimeProfileBinding
    ]
):
    """Canonical create/resume owner over exact injected transcript directories."""

    def _catalog_error_class(self) -> type[RuntimeError]:
        return CodingHostedCatalogError

    def _maximum_transcript_bytes(self) -> int:
        return _MAX_TRANSCRIPT_BYTES

    def _product_id(self) -> str:
        return "coding"

    def _compatibility_id(self) -> str:
        return CODING_HOSTED_COMPATIBILITY_ID

    def _maximum_candidates(self) -> int:
        return _MAX_CANDIDATES

    def _discovery_bytes(self) -> int:
        return _DISCOVERY_BYTES

    def _create_identity(self, request: SessionCreateRequestV1) -> str:
        return _create_identity(request)

    def _session_name(self, request: SessionCreateRequestV1) -> str:
        return f"hosted-{_create_identity(request)}.jsonl"

    def _candidate_from_manager(
        self,
        record: _Record,
        manager: ProductTranscriptSession[
            ResolvedRuntimeProfile, RuntimeProfileBinding
        ],
    ) -> _Candidate:
        return _Candidate(
            record,
            CodingHostedCandidateBindingV1(record, cast(SessionManager, manager)),
        )

    def _project_catalog_record(
        self,
        scope: CanonicalTranscriptScope,
        path: Path,
        revision: str,
        header: ConversationHeader,
    ) -> _Record | None:
        scope = cast(CodingHostedScopeV1, scope)
        before = revision
        raw = header.metadata.get(_METADATA_KEY)
        if raw is None:
            return None
        identity, compatibility, operation = _hosted_header_identity(
            header, scope=scope.scope, fingerprint=scope.fingerprint
        )
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
        return _Record(projection, identity, scope, path, operation, header)

    def _new_header_metadata(
        self,
        intent: SessionCreateIntentV1,
        scope: CanonicalTranscriptScope,
        session_id: str,
    ) -> dict[str, JSONValue]:
        metadata: dict[str, JSONValue] = {
            "version": 1,
            "compatibilityId": CODING_HOSTED_COMPATIBILITY_ID,
            "continuityId": intent.request.requested_continuity_id,
            "sessionId": session_id,
            "scope": scope.scope.value,
            "scopeFingerprint": scope.fingerprint,
            "operationId": intent.request.operation_id,
        }
        return {
            _METADATA_KEY: metadata,
            **composition_header_metadata(
                resolve_coding_composition_set("coding-standard")
            ),
        }

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
        self._legacy_transcript_factory = _HOSTED_FACTORY
        self._legacy_transcript_type = _HostedTranscript
        self._owned_transcript_type = _OwnedHostedTranscript
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

    def _validate_records(self, records: list[_Record]) -> None:
        identities = [item.identity.session_id for item in records]
        if len(set(identities)) != len(identities):
            raise CodingHostedCatalogError()

    @property
    def pending_sessions(self) -> tuple[AgentTranscriptLifecycleSession[RuntimeProfileBinding], ...]:
        return tuple(self._pending_sessions.values())

    def fence(self) -> None:
        return super().fence()

    async def close(self) -> None:
        return await super().close()

    async def discover_sessions(
        self,
        scope: HostedSessionDiscoveryScopeV1,
        *,
        stop: Callable[[], bool],
    ) -> HostedSessionDiscoverySnapshotV1:
        return await super().discover_sessions(scope, stop=stop)

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        return await super().list_identities(scopes, limit=limit)

    async def open_candidate(self, reference: SessionCandidateRefV1) -> _Candidate:
        return await super().open_candidate(reference)

    async def preview_history_header(
        self, reference: SessionCandidateRefV1,
    ) -> CodingResumeHeaderPreview:
        """Inspect a discovered Header without claiming its writable candidate."""

        self._accepting()
        async with self._lock:
            self._accepting()
            record = self._records.get(reference)
            if record is None or _revision(record.path) != reference.revision:
                raise CodingHostedCatalogError()
            preview = inspect_coding_resume_header(record.header)
            if _revision(record.path) != reference.revision:
                raise CodingHostedCatalogError()
            return preview

    async def preview_history_snapshot(
        self, reference: SessionCandidateRefV1, *, max_bytes: int,
        selected_leaf_id: str | None = None,
    ) -> CodingResumeHistoryPreview:
        """Read bounded history from a discovered candidate without claiming it."""

        self._accepting()
        async with self._lock:
            self._accepting()
            record = self._records.get(reference)
            if record is None or _revision(record.path) != reference.revision:
                raise CodingHostedCatalogError()
        preview = await settled_io(
            read_coding_resume_snapshot, record.path, max_bytes=max_bytes,
            selected_leaf_id=selected_leaf_id,
        )
        self._accepting()
        if (
            _revision(record.path) != reference.revision
            or hashlib.sha256(preview.source_fingerprint.encode()).hexdigest()
            != reference.revision
            or preview.header_preview.header != record.header
        ):
            raise CodingHostedCatalogError()
        return preview

    async def open_history_binding(
        self, reference: SessionCandidateRefV1, *, max_bytes: int,
        selected_leaf_id: str | None = None,
    ) -> CodingHostedSessionBindingV1:
        """Open detached Hosted history without claiming a writable candidate.

        Current execution compatibility is not a historical display requirement.
        The discovered canonical identity and source revision remain required.
        This separate entry does not change idempotent create or writable open.
        """

        from .hosted_session import CodingHostedHistoryBindingV1

        preview = await self.preview_history_snapshot(
            reference, max_bytes=max_bytes, selected_leaf_id=selected_leaf_id,
        )
        async with self._lock:
            self._accepting()
            record = self._records.get(reference)
            if record is None or _revision(record.path) != reference.revision:
                raise CodingHostedCatalogError()
            identity = record.identity
        return CodingHostedHistoryBindingV1(identity, preview)

    async def preview_resume_model_outcome(
        self, reference: SessionCandidateRefV1, query: CodingResumeInputLookupQueryV1,
        *, max_bytes: int, selected_leaf_id: str | None = None,
    ) -> CodingResumeModelOutcomeObservationV1:
        """Observe original model facts under the current catalog source fence.

        The caller owns current read authorization. A stale discovery reference
        is rejected; no cached display, Writer or executable Runtime is used.
        """

        if type(query) is not CodingResumeInputLookupQueryV1:
            raise TypeError("invalid Coding Resume outcome query")
        history = await self.preview_history_snapshot(
            reference, max_bytes=max_bytes, selected_leaf_id=selected_leaf_id,
        )
        return observe_coding_resume_model_outcome(history, query)

    async def open_history_candidate(
        self, reference: SessionCandidateRefV1, *, max_bytes: int,
        selected_leaf_id: str | None = None,
    ) -> _Candidate:
        """Use the existing AppHost claim and factory chain for detached history."""

        binding = await self.open_history_binding(
            reference, max_bytes=max_bytes, selected_leaf_id=selected_leaf_id,
        )
        try:
            async with self._lock:
                self._accepting()
                record = self._records.get(reference)
                if record is None or _revision(record.path) != reference.revision:
                    raise CodingHostedCatalogError()
                return _Candidate(record, CodingHostedHistoryCandidateBindingV1(
                    record,
                    binding,
                    self._accepting,
                    manager_type=(
                        _OwnedHostedTranscript
                        if self._owned_factory is not None
                        else _HostedTranscript
                    ),
                    writer_factory=self._owned_factory or _HOSTED_FACTORY,
                ))
        except BaseException:
            await binding.close()
            raise

    def _scope_for(self, request: SessionCreateRequestV1) -> CodingHostedScopeV1:
        if request.product_id != "coding" or request.requested_continuity_id is None:
            raise CodingHostedCatalogError()
        for scope in self.scopes:
            if (
                scope.discovery_scope is request.requested_scope
                and scope.fingerprint == request.creator_scope_id
            ):
                return cast(CodingHostedScopeV1, scope)
        raise CodingHostedCatalogError()

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> _Candidate | None:
        return await super().find_created_candidate(request)

    async def create_candidate(self, intent: SessionCreateIntentV1) -> _Candidate:
        return await super().create_candidate(intent)


class CodingHostedResumeCatalogV1:
    """Route only AppHost resume opens through the detached history owner.

    AppHost create uses ``create_candidate`` directly, so its original writable
    construction path remains unchanged. Existing-session attachment calls
    ``open_candidate`` and receives a history candidate that can transfer the
    exact source and original Writer factory to the one Product binding.
    """

    def __init__(
        self,
        catalog: CodingHostedSessionCatalogV1,
        *,
        max_bytes: int = _MAX_TRANSCRIPT_BYTES,
    ) -> None:
        if type(catalog) is not CodingHostedSessionCatalogV1:
            raise TypeError("Coding Hosted Resume catalog is invalid")
        if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_TRANSCRIPT_BYTES:
            raise ValueError("Coding Hosted Resume history budget is invalid")
        self._catalog = catalog
        self._max_bytes = max_bytes
        self._closing = False

    @property
    def scopes(self) -> tuple[CodingHostedScopeV1, ...]:
        return cast(tuple[CodingHostedScopeV1, ...], self._catalog.scopes)

    @property
    def pending_sessions(
        self,
    ) -> tuple[AgentTranscriptLifecycleSession[RuntimeProfileBinding], ...]:
        return self._catalog.pending_sessions

    @property
    def _owned_factory(
        self,
    ) -> AgentTranscriptSessionFactory[
        ResolvedRuntimeProfile,
        RuntimeProfileBinding,
    ] | None:
        return self._catalog._owned_factory

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        return await self._catalog.list_identities(scopes, limit=limit)

    async def open_candidate(self, reference: SessionCandidateRefV1) -> _Candidate:
        return await self._catalog.open_history_candidate(
            reference,
            max_bytes=self._max_bytes,
        )

    async def find_created_candidate(
        self, request: SessionCreateRequestV1,
    ) -> _Candidate | None:
        return await self._catalog.find_created_candidate(request)

    async def create_candidate(self, intent: SessionCreateIntentV1) -> _Candidate:
        return await self._catalog.create_candidate(intent)

    def fence(self) -> None:
        self._closing = True
        self._catalog.fence()

    async def close(self) -> None:
        self._closing = True
        await self._catalog.close()


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
    return _canonical_header.canonical_transcript_revision(
        path,
        maximum_bytes=lambda: _MAX_TRANSCRIPT_BYTES,
        error=CodingHostedCatalogError,
    )




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




__all__ = [
    "CODING_HOSTED_COMPATIBILITY_ID",
    "CodingHostedCandidateBindingV1",
    "CodingHostedCandidateValidatorV1",
    "CodingHostedCatalogError",
    "CodingHostedHistoryCandidateBindingV1",
    "CodingHostedResumeCatalogV1",
    "CodingHostedResumeSourceV1",
    "CodingHostedScopeV1",
    "CodingHostedSessionCatalogV1",
]


def _coding_hosted_identity_from_envelope(
    envelope: SessionIdentityEnvelopeV1,
    *,
    discovery_scope: SessionDiscoveryScope,
    scope_fingerprint: str,
) -> SessionIdentityV1:
    """Project a canonical path-free AppHost envelope into the App Contract."""

    if type(envelope) is not SessionIdentityEnvelopeV1 or envelope.product_id != (
        CODING_PRODUCT_ID
    ):
        raise ValueError("Coding hosted Session envelope is invalid")
    if type(discovery_scope) is not SessionDiscoveryScope:
        raise TypeError("Coding hosted discovery scope is invalid")
    scope = (
        SessionScopeV1.CWD
        if discovery_scope is SessionDiscoveryScope.CURRENT_DIRECTORY
        else SessionScopeV1.USER_HOME
    )
    return SessionIdentityV1(
        product_id=envelope.product_id,
        continuity_id=envelope.continuity_id,
        session_id=envelope.session_id,
        scope=scope,
        scope_fingerprint=scope_fingerprint,
    )
