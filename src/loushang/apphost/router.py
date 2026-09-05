"""Explicit, non-executing Product candidate router for AppHost A0.2."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ._ownership import (
    AcquisitionStack,
    CloseGroup,
    RetryableCloser,
    bind_native_async,
    read_static_property,
)
from .catalog import AppHostCatalogV1, _ProductCatalogLease
from .contracts import (
    PreparedProductRouteV1,
    ProductDescriptorV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from .errors import (
    AppHostError,
    AppHostFailureCategory,
    CleanupIncompleteError,
    GenerationRetiredError,
    ProductIdentityRequiredError,
    ProductIncompatibleError,
    SessionCandidateStaleError,
    redacted_apphost_error,
)

AsyncCall = Callable[..., Awaitable[Any]]


class _SessionPort:
    __slots__ = ("create", "find", "list", "open")

    def __init__(self, value: object) -> None:
        try:
            self.list = bind_native_async(value, "list_identities")
            self.open = bind_native_async(value, "open_candidate")
            self.find = bind_native_async(value, "find_created_candidate")
            self.create = bind_native_async(value, "create_candidate")
        except BaseException:
            raise TypeError("sessions must expose native async static ports") from None


class _BoundCandidate:
    __slots__ = ("claim", "closer", "projection", "raw", "verify")

    def __init__(self, raw: object) -> None:
        self.raw = raw
        try:
            projection = read_static_property(raw, "projection")
            if type(projection) is not SessionIdentityProjectionV1:
                raise TypeError
            self.projection = projection
            self.verify = bind_native_async(raw, "verify_current")
            self.claim = bind_native_async(raw, "claim")
            self.closer = RetryableCloser.bind(raw)
        except BaseException:
            raise SessionCandidateStaleError() from None


class _BoundClaimed:
    __slots__ = ("closer", "opaque_binding", "raw", "reference")

    def __init__(self, raw: object) -> None:
        self.raw = raw
        try:
            reference = read_static_property(raw, "reference")
            if type(reference) is not SessionCandidateRefV1:
                raise TypeError
            self.reference = reference
            self.opaque_binding = read_static_property(raw, "opaque_binding")
            self.closer = RetryableCloser.bind(raw)
        except BaseException:
            raise SessionCandidateStaleError() from None


class _BoundOpened:
    __slots__ = ("binding_key", "closer", "raw")

    def __init__(self, raw: object) -> None:
        self.raw = raw
        try:
            binding_key = read_static_property(raw, "binding_key")
            if type(binding_key) is not SessionBindingKeyV1:
                raise TypeError
            # Validate but do not expose the opaque Product capability.
            read_static_property(raw, "opaque_binding")
            self.binding_key = binding_key
            self.closer = RetryableCloser.bind(raw)
        except BaseException:
            raise SessionCandidateStaleError() from None


class _ClaimedSnapshot:
    """Immutable borrow view supplied to an admitted Product callback."""

    __slots__ = ("_opaque_binding", "_reference")

    def __init__(self, value: _BoundClaimed) -> None:
        self._reference = value.reference
        self._opaque_binding = value.opaque_binding

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> object:
        return self._opaque_binding

    async def close(self) -> None:
        # Borrowers cannot settle the owner's handle.
        raise CleanupIncompleteError()


class _PreparedProductRoute:
    """Private retained preparation with identity facts and close only."""

    __slots__ = ("_binding_key", "_descriptor", "_generation_id", "_group")

    def __init__(
        self,
        *,
        group: CloseGroup,
        descriptor: ProductDescriptorV1,
        generation_id: str,
        binding_key: SessionBindingKeyV1,
    ) -> None:
        self._group = group
        self._descriptor = descriptor
        self._generation_id = generation_id
        self._binding_key = binding_key

    @property
    def descriptor(self) -> ProductDescriptorV1:
        return self._descriptor

    @property
    def generation_id(self) -> str:
        return self._generation_id

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key

    async def close(self) -> None:
        if not await self._group.settle():
            raise CleanupIncompleteError() from None


class _CleanupRegistry:
    """Router-owned retry registry for unpublished cleanup debt."""

    __slots__ = ("_lock", "_pending")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: set[CloseGroup] = set()

    async def settle_owned(
        self,
        group: CloseGroup,
        *,
        primary: BaseException | None = None,
    ) -> None:
        operation = asyncio.create_task(self._settle_once(group, primary=primary))
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await asyncio.shield(operation)
            raise

    async def _settle_once(
        self,
        group: CloseGroup,
        *,
        primary: BaseException | None,
    ) -> None:
        async with self._lock:
            self._pending.add(group)
        complete = await group.settle()
        if complete:
            async with self._lock:
                self._pending.discard(group)
            return
        raise CleanupIncompleteError(
            primary_category=_primary_category(primary),
            cleanup_debt_count=max(1, group.debt_count),
        ) from None

    async def settle_all(self) -> None:
        async with self._lock:
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
        if complete:
            async with self._lock:
                self._pending.difference_update(complete)
        debts = tuple(
            group.debt_count
            for group, result in zip(pending, results, strict=True)
            if result is not True
        )
        if debts:
            raise CleanupIncompleteError(
                cleanup_debt_count=max(1, sum(debts))
            ) from None


class AppHostRouterV1:
    """Route explicit Session candidates without Product runtime effects."""

    __slots__ = (
        "_active_operations",
        "_catalog",
        "_cleanup",
        "_closed",
        "_drained",
        "_lock",
        "_sessions",
    )

    def __init__(self, catalog: AppHostCatalogV1, sessions: object) -> None:
        if not isinstance(catalog, AppHostCatalogV1):
            raise TypeError("catalog must be AppHostCatalogV1")
        self._catalog = catalog
        self._sessions = _SessionPort(sessions)
        self._cleanup = _CleanupRegistry()
        self._lock = asyncio.Lock()
        self._closed = False
        self._active_operations = 0
        self._drained = asyncio.Event()
        self._drained.set()

    async def settle_pending_cleanup(self) -> None:
        """Retry all unpublished cleanup debt without exposing its owners."""

        await self._cleanup.settle_all()

    async def close(self) -> None:
        """Fence new routing, join in-flight work, and settle pending cleanup."""

        operation = asyncio.create_task(self._close_once())
        operation.add_done_callback(_observe_background_result)
        await asyncio.shield(operation)

    async def _close_once(self) -> None:
        async with self._lock:
            self._closed = True
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
        result = await _call_session(
            self._sessions.list,
            AppHostFailureCategory.SESSION_CANDIDATE_STALE,
            scopes,
            limit=limit,
        )
        if (
            not isinstance(result, tuple)
            or len(result) > limit
            or any(type(item) is not SessionIdentityProjectionV1 for item in result)
        ):
            raise SessionCandidateStaleError()
        return result

    async def prepare_resume(
        self,
        *,
        product_id: str,
        reference: SessionCandidateRefV1,
    ) -> PreparedProductRouteV1:
        await self._begin_operation()
        try:
            return await self._prepare_resume(
                product_id=product_id,
                reference=reference,
            )
        finally:
            self._finish_operation_now()

    async def _prepare_resume(
        self,
        *,
        product_id: str,
        reference: SessionCandidateRefV1,
    ) -> PreparedProductRouteV1:
        _require_product_id(product_id)
        stack = AcquisitionStack()
        try:
            admission = await self._catalog._acquire_product(product_id)
            stack.push_closer(admission.closer)
            candidate = await _open_candidate(
                self._sessions, reference, self._cleanup
            )
            stack.push_closer(candidate.closer)
            return await _prepare(
                admission,
                candidate,
                product_id,
                stack,
                self._cleanup,
            )
        except BaseException as error:
            await self._cleanup.settle_owned(
                stack.transfer(), primary=error
            )
            raise

    async def prepare_create(
        self,
        request: SessionCreateRequestV1,
    ) -> PreparedProductRouteV1:
        await self._begin_operation()
        try:
            return await self._prepare_create(request)
        finally:
            self._finish_operation_now()

    async def _prepare_create(
        self,
        request: SessionCreateRequestV1,
    ) -> PreparedProductRouteV1:
        if not isinstance(request, SessionCreateRequestV1):
            raise TypeError("request must be SessionCreateRequestV1")
        _require_product_id(request.product_id)

        # Lookup and fully release the recovery lease before current admission.
        found = await _call_session(
            self._sessions.find,
            AppHostFailureCategory.SESSION_CANDIDATE_STALE,
            request,
        )
        recovered_reference: SessionCandidateRefV1 | None = None
        if found is not None:
            lookup = await _bind_candidate_or_settle(found, self._cleanup)
            recovered_reference = lookup.projection.reference
            await self._cleanup.settle_owned(
                CloseGroup((lookup.closer,))
            )

        stack = AcquisitionStack()
        try:
            admission = await self._catalog._acquire_product(request.product_id)
            stack.push_closer(admission.closer)
            if recovered_reference is None:
                intent = SessionCreateIntentV1(
                    request=request,
                    product_compatibility_id=admission.descriptor.compatibility_id,
                )
                raw = await _call_session(
                    self._sessions.create,
                    AppHostFailureCategory.SESSION_CANDIDATE_STALE,
                    intent,
                )
                candidate = await _bind_candidate_or_settle(raw, self._cleanup)
            else:
                candidate = await _open_candidate(
                    self._sessions,
                    recovered_reference,
                    self._cleanup,
                )
            stack.push_closer(candidate.closer)
            return await _prepare(
                admission,
                candidate,
                request.product_id,
                stack,
                self._cleanup,
            )
        except BaseException as error:
            await self._cleanup.settle_owned(
                stack.transfer(), primary=error
            )
            raise

    async def import_candidate(
        self,
        *,
        product_id: str,
        reference: SessionCandidateRefV1,
    ) -> SessionCandidateRefV1:
        await self._begin_operation()
        try:
            return await self._import_candidate(
                product_id=product_id,
                reference=reference,
            )
        finally:
            self._finish_operation_now()

    async def _import_candidate(
        self,
        *,
        product_id: str,
        reference: SessionCandidateRefV1,
    ) -> SessionCandidateRefV1:
        _require_product_id(product_id)
        stack = AcquisitionStack()
        try:
            admission = await self._catalog._acquire_product(product_id)
            stack.push_closer(admission.closer)
            candidate = await _open_candidate(
                self._sessions, reference, self._cleanup
            )
            stack.push_closer(candidate.closer)
            if candidate.projection.mode is not SessionCandidateMode.MIGRATION_REQUIRED:
                raise ProductIncompatibleError()
            await _call_candidate(candidate.verify)
            claimed = await _claim(candidate, self._cleanup)
            stack.push_closer(claimed.closer)
            imported = await admission.import_legacy(_ClaimedSnapshot(claimed))
            if type(imported) is not SessionCandidateRefV1:
                raise SessionCandidateStaleError()
        except BaseException as error:
            await self._cleanup.settle_owned(
                stack.transfer(), primary=error
            )
            raise
        else:
            await self._cleanup.settle_owned(stack.transfer())
            return imported


async def _prepare(
    admission: _ProductCatalogLease,
    candidate: _BoundCandidate,
    product_id: str,
    stack: AcquisitionStack,
    cleanup: _CleanupRegistry,
) -> PreparedProductRouteV1:
    envelope = _canonical_envelope(candidate)
    if envelope.product_id != product_id:
        raise ProductIncompatibleError()
    if admission.descriptor.compatibility_id != envelope.product_compatibility_id:
        raise ProductIncompatibleError()
    await _call_candidate(candidate.verify)
    claimed = await _claim(candidate, cleanup)
    stack.push_closer(claimed.closer)
    raw_opened = await admission.validate(_ClaimedSnapshot(claimed), envelope)
    opened = await _bind_opened_or_settle(raw_opened, cleanup)
    stack.push_closer(opened.closer)
    expected = SessionBindingKeyV1(
        product_id=envelope.product_id,
        continuity_id=envelope.continuity_id,
        session_id=envelope.session_id,
    )
    if opened.binding_key != expected:
        raise ProductIncompatibleError()
    return _PreparedProductRoute(
        group=stack.transfer(),
        descriptor=admission.descriptor,
        generation_id=admission.generation_id,
        binding_key=expected,
    )


def _canonical_envelope(candidate: _BoundCandidate) -> SessionIdentityEnvelopeV1:
    projection = candidate.projection
    if (
        projection.mode is not SessionCandidateMode.CANONICAL
        or type(projection.envelope) is not SessionIdentityEnvelopeV1
    ):
        raise ProductIncompatibleError()
    return projection.envelope


async def _open_candidate(
    sessions: _SessionPort,
    reference: SessionCandidateRefV1,
    cleanup: _CleanupRegistry,
) -> _BoundCandidate:
    raw = await _call_session(
        sessions.open,
        AppHostFailureCategory.SESSION_CANDIDATE_STALE,
        reference,
    )
    return await _bind_candidate_or_settle(raw, cleanup)


async def _bind_candidate_or_settle(
    raw: object, cleanup: _CleanupRegistry
) -> _BoundCandidate:
    try:
        return _BoundCandidate(raw)
    except AppHostError:
        await _settle_rejected(raw, cleanup)
        raise


async def _claim(
    candidate: _BoundCandidate, cleanup: _CleanupRegistry
) -> _BoundClaimed:
    raw = await _call_candidate(candidate.claim)
    try:
        return _BoundClaimed(raw)
    except AppHostError:
        await _settle_rejected(raw, cleanup)
        raise


async def _bind_opened_or_settle(
    raw: object, cleanup: _CleanupRegistry
) -> _BoundOpened:
    try:
        return _BoundOpened(raw)
    except AppHostError:
        await _settle_rejected(raw, cleanup)
        raise


async def _settle_rejected(raw: object, cleanup: _CleanupRegistry) -> None:
    try:
        closer = RetryableCloser.bind(raw)
    except BaseException:
        raise CleanupIncompleteError() from None
    await cleanup.settle_owned(
        CloseGroup((closer,)), primary=SessionCandidateStaleError()
    )


async def _call_session(
    callback: AsyncCall,
    category: AppHostFailureCategory,
    *args: object,
    **kwargs: object,
) -> Any:
    try:
        return await callback(*args, **kwargs)
    except asyncio.CancelledError:
        raise
    except AppHostError as error:
        raise redacted_apphost_error(error.category) from None
    except BaseException:
        raise redacted_apphost_error(category) from None


async def _call_candidate(callback: AsyncCall) -> Any:
    return await _call_session(
        callback,
        AppHostFailureCategory.SESSION_CANDIDATE_STALE,
    )


def _primary_category(error: BaseException | None) -> AppHostFailureCategory | None:
    if isinstance(error, CleanupIncompleteError) and error.primary_category is not None:
        return error.primary_category
    return error.category if isinstance(error, AppHostError) else None


def _observe_background_result(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _require_product_id(product_id: str) -> None:
    if not isinstance(product_id, str) or not product_id:
        raise ProductIdentityRequiredError()


def _validate_list_request(
    scopes: tuple[SessionDiscoveryScope, ...], limit: int
) -> None:
    if (
        not isinstance(scopes, tuple)
        or not scopes
        or any(type(scope) is not SessionDiscoveryScope for scope in scopes)
        or len(scopes) != len(set(scopes))
    ):
        raise TypeError("scopes must be a unique non-empty scope tuple")
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("limit must be between 1 and 256")


__all__ = ["AppHostRouterV1"]
