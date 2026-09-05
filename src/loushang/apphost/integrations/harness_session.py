"""Optional dark adapter over the existing Harness Session discovery owner."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from collections import OrderedDict
from dataclasses import dataclass, field

from loushang.apphost._ownership import (
    CloseGroup,
    RetryableCloser,
    bind_native_async,
    read_static_property,
)
from loushang.apphost.contracts import (
    ClaimedSessionCandidateV1,
    SessionCandidateLeaseV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.apphost.errors import (
    AppHostError,
    AppHostFailureCategory,
    CleanupIncompleteError,
    GenerationRetiredError,
    SessionAmbiguousError,
    SessionCandidateStaleError,
    redacted_apphost_error,
)
from loushang.harness.conversation import ConversationJsonlHeaderCodec
from loushang.harness.journal import DEFAULT_JSONL_FORMAT
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.discovery import SessionLocator
from loushang.harness.transcript.session_catalog import (
    session_file_authority_fingerprint,
)

_MAX_CANDIDATE_CACHE = 1024
_MAX_HEADER_BYTES = 64 * 1024
HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1 = 8 * 1024 * 1024
HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1 = 8
_SNAPSHOT_CHUNK_BYTES = 64 * 1024
_HEADER_CODEC = ConversationJsonlHeaderCodec()


@dataclass(frozen=True, slots=True)
class HarnessSessionScopeBindingV1:
    """Explicit scope-to-existing-source binding supplied by outer composition."""

    scope: SessionDiscoveryScope
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, SessionDiscoveryScope):
            raise TypeError("scope must be SessionDiscoveryScope")
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ValueError("source_id must be non-empty")


@dataclass(frozen=True, slots=True)
class _CandidateRecord:
    projection: SessionIdentityProjectionV1
    locator: SessionLocator = field(repr=False)
    raw_revision: str = field(repr=False)


class _DescriptorOwner:
    __slots__ = ("_closed", "_descriptor")

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._closed = False

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise SessionCandidateStaleError()
        return self._descriptor

    async def close(self) -> None:
        if self._closed:
            return
        descriptor = self._descriptor
        self._descriptor = -1
        self._closed = True
        os.close(descriptor)


class _PinnedSessionContent:
    """Immutable claimed content snapshot with a redacted repr."""

    __slots__ = ("_content", "_conversation_id", "_source_id")

    def __init__(
        self,
        content: bytes,
        *,
        conversation_id: str,
        source_id: str,
    ) -> None:
        self._content = content
        self._conversation_id = conversation_id
        self._source_id = source_id

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def source_id(self) -> str:
        return self._source_id

    def read_bytes(
        self, *, max_bytes: int = HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1
    ) -> bytes:
        if (
            type(max_bytes) is not int
            or not 1 <= max_bytes <= HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1
        ):
            raise ValueError("max_bytes is outside the pinned read bound")
        if len(self._content) > max_bytes:
            raise SessionCandidateStaleError()
        return self._content

    def __repr__(self) -> str:
        return "<PinnedHarnessSessionContent>"


class _ClaimedCandidate:
    __slots__ = ("_binding", "_closed", "_reference")

    def __init__(
        self,
        reference: SessionCandidateRefV1,
        binding: _PinnedSessionContent,
    ) -> None:
        self._reference = reference
        self._binding = binding
        self._closed = False

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> object:
        if self._closed:
            raise SessionCandidateStaleError()
        return self._binding

    async def close(self) -> None:
        self._closed = True


class _CandidateLease:
    __slots__ = (
        "_claimed",
        "_closer",
        "_owner",
        "_projection",
        "_revision",
        "_snapshot",
    )

    def __init__(
        self,
        projection: SessionIdentityProjectionV1,
        owner: _DescriptorOwner,
        *,
        raw_revision: str,
        snapshot: bytes,
    ) -> None:
        self._projection = projection
        self._owner = owner
        self._revision = raw_revision
        self._claimed = False
        self._snapshot = snapshot
        self._closer = RetryableCloser.bind(owner)

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._projection

    async def verify_current(self) -> None:
        try:
            current = _status_fingerprint(os.fstat(self._owner.descriptor))
        except (OSError, AppHostError):
            raise SessionCandidateStaleError() from None
        if current != self._revision:
            raise SessionCandidateStaleError()

    async def claim(self) -> ClaimedSessionCandidateV1:
        if self._claimed:
            raise SessionCandidateStaleError()
        await self.verify_current()
        self._claimed = True
        return _ClaimedCandidate(
            self._projection.reference,
            _PinnedSessionContent(
                self._snapshot,
                conversation_id=_conversation_id(self._snapshot),
                source_id=self._projection.reference.source_id,
            ),
        )

    async def close(self) -> None:
        if not await self._closer.settle():
            raise CleanupIncompleteError() from None


class _CanonicalOwner:
    __slots__ = ("create", "find", "list", "open")

    def __init__(self, value: object) -> None:
        try:
            self.list = bind_native_async(value, "list_identities")
            self.open = bind_native_async(value, "open_candidate")
            self.find = bind_native_async(value, "find_created_candidate")
            self.create = bind_native_async(value, "create_candidate")
        except BaseException:
            raise TypeError("canonical owner has invalid async ports") from None


class _DeferredCanonicalOwner:
    """Adopt a raw return before inspecting any of its descriptors."""

    __slots__ = ("_callback", "_value")

    def __init__(self, value: object) -> None:
        self._value: object | None = value
        self._callback: object | None = None

    def bind_close(self) -> None:
        if self._callback is None:
            value = self._value
            if value is None:
                return
            self._callback = bind_native_async(value, "close")

    async def close(self) -> None:
        self.bind_close()
        callback = self._callback
        if callback is None:
            return
        await callback()  # type: ignore[operator]
        self._callback = None
        self._value = None


class _AdapterCleanupRegistry:
    """Retain canonical returns which the adapter could not safely publish."""

    __slots__ = ("_pending",)

    def __init__(self) -> None:
        self._pending: set[CloseGroup] = set()

    def adopt(self, group: CloseGroup) -> None:
        # No await may separate a raw owner return from this registration.
        self._pending.add(group)

    def release(self, group: CloseGroup) -> None:
        self._pending.discard(group)

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def settle_owned(
        self,
        group: CloseGroup,
        *,
        primary_category: AppHostFailureCategory,
    ) -> None:
        operation = asyncio.create_task(
            self._settle_once(group, primary_category=primary_category)
        )
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            # The adapter remains the owner until the shielded settlement records
            # either success or durable cleanup debt.
            await asyncio.shield(operation)
            raise

    async def _settle_once(
        self,
        group: CloseGroup,
        *,
        primary_category: AppHostFailureCategory,
    ) -> None:
        if await group.settle():
            self.release(group)
            return
        raise CleanupIncompleteError(
            primary_category=primary_category,
            cleanup_debt_count=max(1, group.debt_count),
        ) from None

    async def settle_all(self) -> None:
        pending = tuple(self._pending)
        results = await asyncio.gather(
            *(group.settle() for group in pending),
            return_exceptions=True,
        )
        complete = tuple(
            group
            for group, result in zip(pending, results, strict=True)
            if result is True
        )
        for group in complete:
            self.release(group)
        debts = tuple(
            group.debt_count
            for group, result in zip(pending, results, strict=True)
            if result is not True
        )
        if debts:
            raise CleanupIncompleteError(
                cleanup_debt_count=max(1, sum(debts))
            ) from None


class HarnessAppHostSessionAdapterV1:
    """AppHost-owned optional projection of an existing Harness owner.

    The adapter never derives a root from a scope, scans a directory, creates an
    index, or turns an opaque candidate token into a path. POSIX candidates are
    pinned by one no-follow descriptor. Windows opening remains fail-closed
    until a reviewed native retained-handle backend exists.
    """

    __slots__ = (
        "_active_operations",
        "_candidates",
        "_canonical_active",
        "_canonical_gate",
        "_canonical",
        "_cleanup",
        "_close_task",
        "_closed",
        "_drained",
        "_lock",
        "_runtime",
        "_scope_by_source",
    )

    def __init__(
        self,
        runtime: AgentTranscriptDirectoryRuntime,
        *,
        scope_bindings: tuple[HarnessSessionScopeBindingV1, ...],
        canonical_owner: object | None = None,
    ) -> None:
        if not isinstance(runtime, AgentTranscriptDirectoryRuntime):
            raise TypeError("runtime must be AgentTranscriptDirectoryRuntime")
        if not isinstance(scope_bindings, tuple) or not scope_bindings:
            raise TypeError("scope_bindings must be a non-empty tuple")
        if any(
            not isinstance(binding, HarnessSessionScopeBindingV1)
            for binding in scope_bindings
        ):
            raise TypeError("scope_bindings contain an invalid binding")
        source_ids = tuple(binding.source_id for binding in scope_bindings)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("each Harness Session source may be bound once")
        scopes = tuple(binding.scope for binding in scope_bindings)
        if len(scopes) != len(set(scopes)):
            raise ValueError("each AppHost Session scope may be bound once")
        admitted_source_ids = {
            runtime.authority_session_source.source_id,
            *(source.source_id for source in runtime.discovery_session_sources),
        }
        if not set(source_ids) <= admitted_source_ids:
            raise ValueError("scope binding source is not owned by this runtime")
        self._runtime = runtime
        self._scope_by_source = {
            binding.source_id: binding.scope for binding in scope_bindings
        }
        self._canonical = (
            None if canonical_owner is None else _CanonicalOwner(canonical_owner)
        )
        self._candidates: OrderedDict[
            SessionCandidateRefV1, _CandidateRecord
        ] = OrderedDict()
        self._cleanup = _AdapterCleanupRegistry()
        self._lock = asyncio.Lock()
        self._canonical_gate = asyncio.Lock()
        self._canonical_active = 0
        self._closed = False
        self._active_operations = 0
        self._drained = asyncio.Event()
        self._drained.set()
        self._close_task: asyncio.Task[None] | None = None

    async def settle_pending_cleanup(self) -> None:
        """Retry unpublished canonical-owner cleanup debt."""

        await self._cleanup.settle_all()

    async def close(self) -> None:
        """Fence new calls, join in-flight calls, and settle retained debt."""

        async with self._lock:
            self._closed = True
            if self._close_task is None or self._close_task.done():
                self._close_task = asyncio.create_task(self._close_once())
                self._close_task.add_done_callback(_observe_background_result)
            operation = self._close_task
        await asyncio.shield(operation)

    async def _close_once(self) -> None:
        await self._drained.wait()
        await self._cleanup.settle_all()

    async def _begin_operation(self) -> None:
        async with self._lock:
            if self._closed:
                raise GenerationRetiredError()
            if self._active_operations == 0:
                self._drained.clear()
            self._active_operations += 1

    def _finish_operation_now(self) -> None:
        self._active_operations -= 1
        if self._active_operations == 0:
            self._drained.set()

    async def _begin_canonical_provider_call(self) -> None:
        # External cleanup callbacks run outside adapter locks. The short gate
        # only closes the post-drain check/reservation race between starters.
        while True:
            await self._cleanup.settle_all()
            async with self._canonical_gate:
                if self._cleanup.has_pending:
                    continue
                async with self._lock:
                    if self._closed:
                        raise GenerationRetiredError()
                    if (
                        self._canonical_active
                        >= HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1
                    ):
                        raise AppHostError(AppHostFailureCategory.RUNTIME_UNAVAILABLE)
                    self._canonical_active += 1
                    return

    def _finish_canonical_provider_call_now(self) -> None:
        self._canonical_active -= 1

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        await self._begin_operation()
        try:
            return await self._list_identities(scopes, limit=limit)
        finally:
            self._finish_operation_now()

    async def _list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        _validate_list_request(scopes, limit)
        requested = set(scopes)
        projected: list[SessionIdentityProjectionV1] = []
        if self._canonical is not None:
            await self._begin_canonical_provider_call()
            try:
                raw = await _call_optional(
                    self._canonical.list, scopes, limit=limit
                )
            finally:
                self._finish_canonical_provider_call_now()
            if not isinstance(raw, tuple) or len(raw) > limit:
                raise SessionCandidateStaleError()
            if any(
                type(item) is not SessionIdentityProjectionV1
                or item.scope not in requested
                or item.mode is not SessionCandidateMode.CANONICAL
                or type(item.envelope) is not SessionIdentityEnvelopeV1
                for item in raw
            ):
                raise SessionCandidateStaleError()
            projected.extend(raw)
        if len(projected) < limit:
            try:
                summaries = self._runtime.list_discovered_session_summaries()
            except BaseException:
                raise SessionCandidateStaleError() from None
            for summary in summaries:
                discovery = summary.discovery
                if discovery is None:
                    continue
                scope = self._scope_by_source.get(discovery.locator.source_id)
                if scope not in requested:
                    continue
                if discovery.conflicts or discovery.health == "conflict":
                    raise SessionAmbiguousError()
                record = _project_legacy(discovery.locator, scope)
                self._remember(record)
                projected.append(record.projection)
                if len(projected) == limit:
                    break
        references = tuple(item.reference for item in projected)
        if len(references) != len(set(references)):
            raise SessionAmbiguousError()
        return tuple(projected)

    async def open_candidate(
        self, reference: SessionCandidateRefV1
    ) -> SessionCandidateLeaseV1:
        await self._begin_operation()
        try:
            return await self._open_candidate(reference)
        finally:
            self._finish_operation_now()

    async def _open_candidate(
        self, reference: SessionCandidateRefV1
    ) -> SessionCandidateLeaseV1:
        if not isinstance(reference, SessionCandidateRefV1):
            raise TypeError("reference must be SessionCandidateRefV1")
        record = self._candidates.get(reference)
        if record is None:
            if self._canonical is None:
                raise SessionCandidateStaleError()
            await self._begin_canonical_provider_call()
            try:
                return await _validate_canonical_candidate(
                    await _call_optional(self._canonical.open, reference),
                    cleanup=self._cleanup,
                    expected_reference=reference,
                )
            finally:
                self._finish_canonical_provider_call_now()
        return _open_pinned(record)

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> SessionCandidateLeaseV1 | None:
        await self._begin_operation()
        try:
            return await self._find_created_candidate(request)
        finally:
            self._finish_operation_now()

    async def _find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> SessionCandidateLeaseV1 | None:
        if self._canonical is None:
            return None
        await self._begin_canonical_provider_call()
        try:
            raw = await _call_optional(self._canonical.find, request)
            return (
                None
                if raw is None
                else await _validate_canonical_candidate(
                    raw,
                    cleanup=self._cleanup,
                    expected_product_id=request.product_id,
                )
            )
        finally:
            self._finish_canonical_provider_call_now()

    async def create_candidate(
        self, intent: SessionCreateIntentV1
    ) -> SessionCandidateLeaseV1:
        await self._begin_operation()
        try:
            return await self._create_candidate(intent)
        finally:
            self._finish_operation_now()

    async def _create_candidate(
        self, intent: SessionCreateIntentV1
    ) -> SessionCandidateLeaseV1:
        if self._canonical is None:
            raise AppHostError(AppHostFailureCategory.RUNTIME_UNAVAILABLE)
        await self._begin_canonical_provider_call()
        try:
            return await _validate_canonical_candidate(
                await _call_optional(self._canonical.create, intent),
                cleanup=self._cleanup,
                expected_product_id=intent.request.product_id,
                expected_compatibility_id=intent.product_compatibility_id,
            )
        finally:
            self._finish_canonical_provider_call_now()

    def _remember(self, record: _CandidateRecord) -> None:
        self._candidates[record.projection.reference] = record
        self._candidates.move_to_end(record.projection.reference)
        while len(self._candidates) > _MAX_CANDIDATE_CACHE:
            self._candidates.popitem(last=False)


async def _validate_canonical_candidate(
    value: object,
    *,
    cleanup: _AdapterCleanupRegistry,
    expected_reference: SessionCandidateRefV1 | None = None,
    expected_product_id: str | None = None,
    expected_compatibility_id: str | None = None,
) -> SessionCandidateLeaseV1:
    owner = _DeferredCanonicalOwner(value)
    group = CloseGroup((RetryableCloser.bind(owner),))
    cleanup.adopt(group)
    try:
        owner.bind_close()
        projected = read_static_property(value, "projection")
        if (
            type(projected) is not SessionIdentityProjectionV1
            or projected.mode is not SessionCandidateMode.CANONICAL
            or type(projected.envelope) is not SessionIdentityEnvelopeV1
            or (
                expected_reference is not None
                and projected.reference != expected_reference
            )
            or (
                expected_product_id is not None
                and projected.envelope.product_id != expected_product_id
            )
            or (
                expected_compatibility_id is not None
                and projected.envelope.product_compatibility_id
                != expected_compatibility_id
            )
        ):
            raise TypeError
        for name in ("verify_current", "claim"):
            bind_native_async(value, name)
    except asyncio.CancelledError:
        await cleanup.settle_owned(
            group,
            primary_category=AppHostFailureCategory.SESSION_CANDIDATE_STALE,
        )
        raise
    except BaseException:
        await cleanup.settle_owned(
            group,
            primary_category=AppHostFailureCategory.SESSION_CANDIDATE_STALE,
        )
        raise SessionCandidateStaleError() from None
    cleanup.release(group)
    return value  # type: ignore[return-value]


def _observe_background_result(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


async def _call_optional(callback: object, *args: object, **kwargs: object) -> object:
    try:
        return await callback(*args, **kwargs)  # type: ignore[operator]
    except asyncio.CancelledError:
        raise
    except AppHostError as error:
        raise redacted_apphost_error(error.category) from None
    except BaseException:
        raise redacted_apphost_error(
            AppHostFailureCategory.SESSION_CANDIDATE_STALE
        ) from None


def _validate_list_request(
    scopes: tuple[SessionDiscoveryScope, ...], limit: int
) -> None:
    if (
        not isinstance(scopes, tuple)
        or not scopes
        or any(not isinstance(scope, SessionDiscoveryScope) for scope in scopes)
        or len(scopes) != len(set(scopes))
    ):
        raise TypeError("scopes must be a unique non-empty scope tuple")
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("limit must be between 1 and 256")


def _project_legacy(
    locator: SessionLocator,
    scope: SessionDiscoveryScope,
) -> _CandidateRecord:
    digest = hashlib.sha256(
        (
            f"{locator.source_id}\0{locator.conversation_id}\0"
            f"{locator.session_file.as_posix()}"
        ).encode("utf-8")
    ).hexdigest()
    revision = hashlib.sha256(locator.revision.encode("utf-8")).hexdigest()
    reference = SessionCandidateRefV1(locator.source_id, digest, revision)
    return _CandidateRecord(
        projection=SessionIdentityProjectionV1(
            reference,
            scope,
            SessionCandidateMode.MIGRATION_REQUIRED,
            None,
        ),
        locator=locator,
        raw_revision=locator.revision,
    )


def _open_pinned(record: _CandidateRecord) -> _CandidateLease:
    if not _native_descriptor_supported():
        raise SessionCandidateStaleError()
    descriptor = -1
    parent = -1
    try:
        parent_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        parent = os.open(record.locator.session_file.parent, parent_flags)
        file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open(
            record.locator.session_file.name,
            file_flags,
            dir_fd=parent,
        )
        before = os.fstat(descriptor)
        descriptor_revision = _status_fingerprint(before)
        path_revision = session_file_authority_fingerprint(
            record.locator.session_file
        )
        if descriptor_revision != record.raw_revision or path_revision != (
            record.raw_revision
        ):
            raise SessionCandidateStaleError()
        snapshot = _read_sealed_snapshot(descriptor, before)
        if _conversation_id(snapshot) != record.locator.conversation_id:
            raise SessionCandidateStaleError()
    except AppHostError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise SessionCandidateStaleError() from None
    finally:
        if parent >= 0:
            os.close(parent)
    return _CandidateLease(
        record.projection,
        _DescriptorOwner(descriptor),
        raw_revision=descriptor_revision,
        snapshot=snapshot,
    )


def _native_descriptor_supported() -> bool:
    return (
        os.name == "posix"
        and all(hasattr(os, name) for name in ("O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW"))
        and hasattr(os, "pread")
    )


def _conversation_id(content: bytes) -> str:
    prefix = content[:_MAX_HEADER_BYTES]
    line = next((item for item in prefix.splitlines() if item.strip()), b"")
    if not line:
        raise SessionCandidateStaleError()
    try:
        value = json.loads(
            line.decode(DEFAULT_JSONL_FORMAT.encoding),
            parse_constant=_reject_json_constant,
        )
        if not isinstance(value, dict):
            raise TypeError
        return _HEADER_CODEC.decode_header(value).conversation_id
    except BaseException:
        raise SessionCandidateStaleError() from None


def _read_sealed_snapshot(descriptor: int, before: os.stat_result) -> bytes:
    if before.st_size > HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1:
        raise SessionCandidateStaleError()
    chunks: list[bytes] = []
    offset = 0
    while True:
        remaining = HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1 - offset
        request_size = min(_SNAPSHOT_CHUNK_BYTES, remaining + 1)
        chunk = os.pread(descriptor, request_size, offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
        if offset > HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1:
            raise SessionCandidateStaleError()
    after = os.fstat(descriptor)
    if (
        _status_fingerprint(before) != _status_fingerprint(after)
        or offset != after.st_size
    ):
        raise SessionCandidateStaleError()
    return b"".join(chunks)


def _reject_json_constant(_value: str) -> object:
    raise ValueError


def _status_fingerprint(status: os.stat_result) -> str:
    if not stat.S_ISREG(status.st_mode):
        raise SessionCandidateStaleError()
    return (
        f"stat-v1:{status.st_dev}:{status.st_ino}:{status.st_size}:"
        f"{status.st_mtime_ns}:{status.st_ctime_ns}"
    )


__all__ = [
    "HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1",
    "HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1",
    "HarnessAppHostSessionAdapterV1",
    "HarnessSessionScopeBindingV1",
]
