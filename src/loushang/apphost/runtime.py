"""Canonical process-local Product binding owner for AppHost A0.3."""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from ._ownership import (
    DependentCloseChain,
    RetryableCloser,
    read_static_property,
)
from .catalog import AppHostCatalogV1, _RuntimeCatalogLease
from .contracts import (
    AppHostSessionLeaseV1,
    AppHostShutdownBudgetV1,
    AppHostShutdownPhase,
    AppHostShutdownReportV1,
    ProductDescriptorV1,
    SessionBindingKeyV1,
    SessionCandidateRefV1,
    SessionCreateRequestV1,
)
from .errors import (
    AppHostError,
    AppHostFailureCategory,
    CleanupIncompleteError,
    GenerationConflictError,
    GenerationRetiredError,
    ProductIncompatibleError,
)
from .router import AppHostRouterV1, _RuntimeCandidateRoute

_DEFAULT_SHUTDOWN_BUDGET = AppHostShutdownBudgetV1(30.0, 10.0)
_ACTIVE_RUNTIME_CALLBACKS: contextvars.ContextVar[frozenset[int]] = (
    contextvars.ContextVar("loushang_apphost_active_runtime_callbacks", default=frozenset())
)


class _RuntimeCleanupRegistry:
    """Retain unpublished dependent chains until exact settlement succeeds."""

    __slots__ = ("_lock", "_pending")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: set[DependentCloseChain] = set()

    async def settle_owned(
        self,
        chain: DependentCloseChain,
        *,
        primary: BaseException | None = None,
    ) -> None:
        async with self._lock:
            self._pending.add(chain)
        complete = await chain.settle()
        if complete:
            async with self._lock:
                self._pending.discard(chain)
            return
        raise CleanupIncompleteError(
            primary_category=(
                primary.category if isinstance(primary, AppHostError) else None
            ),
            cleanup_debt_count=max(1, chain.debt_count),
        ) from None

    async def settle_all(self) -> None:
        async with self._lock:
            pending = tuple(self._pending)
        results = await asyncio.gather(
            *(chain.settle() for chain in pending),
            return_exceptions=True,
        )
        completed = tuple(
            chain
            for chain, result in zip(pending, results, strict=True)
            if result is True
        )
        if completed:
            async with self._lock:
                self._pending.difference_update(completed)
        failures = tuple(
            chain
            for chain, result in zip(pending, results, strict=True)
            if result is not True
        )
        if failures:
            raise CleanupIncompleteError(
                cleanup_debt_count=max(
                    1,
                    sum(max(1, chain.debt_count) for chain in failures),
                )
            ) from None


class _BoundProfileView:
    """Frozen non-owning Product view passed to one profile callback."""

    __slots__ = ("_binding_key", "_opaque_binding")

    def __init__(self, raw: object, expected: SessionBindingKeyV1) -> None:
        try:
            binding_key = read_static_property(raw, "binding_key")
            if type(binding_key) is not SessionBindingKeyV1 or binding_key != expected:
                raise TypeError
            opaque_binding = read_static_property(raw, "opaque_binding")
        except BaseException:
            raise ProductIncompatibleError() from None
        self._binding_key = binding_key
        self._opaque_binding = opaque_binding

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key

    @property
    def opaque_binding(self) -> object:
        return self._opaque_binding


class _BoundRuntime:
    __slots__ = ("closer", "profile_view", "raw")

    def __init__(self, raw: object, expected: SessionBindingKeyV1) -> None:
        self.raw = raw
        try:
            binding_key = read_static_property(raw, "binding_key")
            if type(binding_key) is not SessionBindingKeyV1 or binding_key != expected:
                raise TypeError
            profile_binding = read_static_property(raw, "profile_binding")
            self.profile_view = _BoundProfileView(profile_binding, expected)
            self.closer = RetryableCloser.bind(raw)
        except BaseException:
            raise ProductIncompatibleError() from None


class _BoundProfileLease:
    __slots__ = ("closer", "profile_binding", "profile_id", "raw")

    def __init__(self, raw: object, expected_profile_id: str) -> None:
        self.raw = raw
        try:
            profile_id = read_static_property(raw, "profile_id")
            if type(profile_id) is not str or profile_id != expected_profile_id:
                raise TypeError
            self.profile_id = cast(str, profile_id)
            self.profile_binding = read_static_property(raw, "profile_binding")
            self.closer = RetryableCloser.bind(raw)
        except BaseException:
            raise AppHostError(AppHostFailureCategory.PROFILE_UNAVAILABLE) from None


async def _bind_runtime_or_settle(
    raw: object,
    expected: SessionBindingKeyV1,
    cleanup: _RuntimeCleanupRegistry,
) -> _BoundRuntime:
    try:
        return _BoundRuntime(raw, expected)
    except AppHostError as error:
        await _settle_rejected(raw, cleanup, primary=error)
        raise


async def _bind_profile_or_settle(
    raw: object,
    expected_profile_id: str,
    cleanup: _RuntimeCleanupRegistry,
) -> _BoundProfileLease:
    try:
        return _BoundProfileLease(raw, expected_profile_id)
    except AppHostError as error:
        await _settle_rejected(raw, cleanup, primary=error)
        raise


async def _settle_rejected(
    raw: object,
    cleanup: _RuntimeCleanupRegistry,
    *,
    primary: BaseException,
) -> None:
    try:
        closer = RetryableCloser.bind(raw)
    except BaseException:
        raise CleanupIncompleteError() from None
    await cleanup.settle_owned(DependentCloseChain((closer,)), primary=primary)


class _Attachment:
    __slots__ = ("_binding", "_close_owner", "_profile", "_token")

    def __init__(
        self,
        binding: _LiveBinding,
        token: int,
        profile: _BoundProfileLease,
    ) -> None:
        self._binding = binding
        self._token = token
        self._profile = profile
        self._close_owner = RetryableCloser(self._close_once)

    @property
    def profile(self) -> _BoundProfileLease:
        return self._profile

    async def close(self) -> None:
        if not await self._close_owner.settle():
            raise CleanupIncompleteError(
                cleanup_debt_count=max(1, self._close_owner.debt_count)
            ) from None

    async def _close_once(self) -> None:
        if not await self._profile.closer.settle():
            raise CleanupIncompleteError(
                cleanup_debt_count=max(1, self._profile.closer.debt_count)
            ) from None
        await self._binding.release_attachment(self._token, self)


class _AttachedSessionLease:
    __slots__ = ("_attachment", "_binding")

    def __init__(self, binding: _LiveBinding, attachment: _Attachment) -> None:
        self._binding = binding
        self._attachment = attachment

    @property
    def descriptor(self) -> ProductDescriptorV1:
        return self._binding.descriptor

    @property
    def generation_id(self) -> str:
        return self._binding.generation_id

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding.binding_key

    @property
    def profile_id(self) -> str:
        return self._attachment.profile.profile_id

    @property
    def profile_binding(self) -> object:
        return self._attachment.profile.profile_binding

    async def close(self) -> None:
        await self._attachment.close()


class _LiveBinding:
    """Sole owner of one Product runtime and all exact profile attachments."""

    __slots__ = (
        "_accepting",
        "_admission",
        "_all_drained",
        "_attachments",
        "_cleanup",
        "_close_owner",
        "_inflight",
        "_inflight_drained",
        "_lock",
        "_next_token",
        "_owner_chain",
        "_runtime",
        "binding_key",
        "descriptor",
        "generation_id",
    )

    def __init__(
        self,
        *,
        admission: _RuntimeCatalogLease,
        runtime: _BoundRuntime,
        cleanup: _RuntimeCleanupRegistry,
    ) -> None:
        self._admission = admission
        self._runtime = runtime
        self._cleanup = cleanup
        self.binding_key = runtime.profile_view.binding_key
        self.descriptor = admission.descriptor
        self.generation_id = admission.generation_id
        self._owner_chain = DependentCloseChain(
            (RetryableCloser.bind(admission), runtime.closer)
        )
        self._accepting = True
        self._attachments: dict[int, _Attachment] = {}
        self._inflight: set[int] = set()
        self._next_token = 0
        self._lock = asyncio.Lock()
        self._inflight_drained = asyncio.Event()
        self._inflight_drained.set()
        self._all_drained = asyncio.Event()
        self._all_drained.set()
        self._close_owner = RetryableCloser(self._close_once)

    async def reserve_attachment(self) -> int:
        async with self._lock:
            if not self._accepting:
                raise GenerationConflictError()
            self._next_token += 1
            token = self._next_token
            self._inflight.add(token)
            self._inflight_drained.clear()
            self._all_drained.clear()
            return token

    async def abort_reservation(self, token: int) -> None:
        async with self._lock:
            self._inflight.discard(token)
            self._refresh_drain_events()

    async def bind_reserved_profile(
        self,
        token: int,
        profile_id: str,
    ) -> _AttachedSessionLease:
        raw = await self._admission.bind_profile(
            profile_id,
            self._runtime.profile_view,
        )
        profile = await _bind_profile_or_settle(raw, profile_id, self._cleanup)
        attachment = _Attachment(self, token, profile)
        async with self._lock:
            if token not in self._inflight:
                rejected = True
            else:
                self._inflight.remove(token)
                self._attachments[token] = attachment
                self._refresh_drain_events()
                rejected = False
        if rejected:
            await attachment.close()
            raise GenerationConflictError()
        return _AttachedSessionLease(self, attachment)

    async def release_attachment(
        self,
        token: int,
        attachment: _Attachment,
    ) -> None:
        async with self._lock:
            if self._attachments.get(token) is attachment:
                del self._attachments[token]
            self._refresh_drain_events()

    async def fence(self) -> None:
        async with self._lock:
            self._accepting = False
            self._refresh_drain_events()

    async def close(self) -> None:
        if not await self._close_owner.settle():
            raise CleanupIncompleteError(
                cleanup_debt_count=max(1, self._close_owner.debt_count)
            ) from None

    async def _close_once(self) -> None:
        await self.fence()
        await self._inflight_drained.wait()
        async with self._lock:
            attachments = tuple(self._attachments.values())
        results = await asyncio.gather(
            *(attachment.close() for attachment in attachments),
            return_exceptions=True,
        )
        failures = tuple(result for result in results if isinstance(result, BaseException))
        if failures:
            raise CleanupIncompleteError(cleanup_debt_count=len(failures)) from None
        await self._all_drained.wait()
        await self._owner_chain.close()

    def _refresh_drain_events(self) -> None:
        if self._inflight:
            self._inflight_drained.clear()
        else:
            self._inflight_drained.set()
        if self._inflight or self._attachments:
            self._all_drained.clear()
        else:
            self._all_drained.set()


@dataclass(slots=True)
class _LiveSlot:
    task: asyncio.Task[_LiveBinding]
    accepting: bool = True


class _LiveBindingRegistry:
    __slots__ = ("_cleanup", "_closed", "_lock", "_slots")

    def __init__(self, cleanup: _RuntimeCleanupRegistry) -> None:
        self._cleanup = cleanup
        self._closed = False
        self._lock = asyncio.Lock()
        self._slots: dict[SessionBindingKeyV1, _LiveSlot] = {}

    async def attach(
        self,
        route: _RuntimeCandidateRoute,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        if not isinstance(profile_id, str) or not profile_id:
            await route.close()
            raise AppHostError(AppHostFailureCategory.PROFILE_UNAVAILABLE)
        try:
            slot, creator = await self._select(route)
        except BaseException:
            await route.close()
            raise
        try:
            binding = await asyncio.shield(slot.task)
        except BaseException:
            await route.close()
            await self._drop_failed(route.binding_key, slot)
            raise

        try:
            token = await self._reserve(route.binding_key, slot, binding)
        except BaseException:
            await route.close()
            await self._close_unclaimed_if_fenced(route.binding_key, slot, binding)
            raise

        try:
            if not creator:
                await route.discard_current()
                opened = await route.open_with(binding._admission)
                await opened.close()
            await route.close()
            return await binding.bind_reserved_profile(token, profile_id)
        except BaseException:
            await binding.abort_reservation(token)
            await route.close()
            raise

    async def _select(
        self,
        route: _RuntimeCandidateRoute,
    ) -> tuple[_LiveSlot, bool]:
        async with self._lock:
            if self._closed:
                raise GenerationRetiredError()
            current = self._slots.get(route.binding_key)
            if current is not None:
                if not current.accepting:
                    raise GenerationConflictError()
                return current, False
            task = asyncio.create_task(self._build(route))
            task.add_done_callback(_observe_background_result)
            slot = _LiveSlot(task)
            self._slots[route.binding_key] = slot
            return slot, True

    async def _build(self, route: _RuntimeCandidateRoute) -> _LiveBinding:
        admission: _RuntimeCatalogLease | None = None
        runtime: _BoundRuntime | None = None
        opened = None
        try:
            admission = await route.acquire_current()
            opened = await route.open_with(admission)
            raw_runtime = await admission.create(opened.candidate)
            runtime = await _bind_runtime_or_settle(
                raw_runtime,
                route.binding_key,
                self._cleanup,
            )
            await opened.close()
            opened = None
            await route.close()
            return _LiveBinding(
                admission=admission,
                runtime=runtime,
                cleanup=self._cleanup,
            )
        except BaseException as error:
            failures: list[BaseException] = []
            if opened is not None:
                try:
                    await opened.close()
                except BaseException as cleanup_error:
                    failures.append(cleanup_error)
            try:
                await route.close()
            except BaseException as cleanup_error:
                failures.append(cleanup_error)
            if admission is not None:
                chain = DependentCloseChain(
                    (
                        RetryableCloser.bind(admission),
                        *((runtime.closer,) if runtime is not None else ()),
                    )
                )
                try:
                    await self._cleanup.settle_owned(chain)
                except BaseException as cleanup_error:
                    failures.append(cleanup_error)
            if failures:
                raise CleanupIncompleteError(
                    primary_category=(
                        error.category if isinstance(error, AppHostError) else None
                    ),
                    cleanup_debt_count=len(failures),
                ) from None
            raise

    async def _reserve(
        self,
        key: SessionBindingKeyV1,
        slot: _LiveSlot,
        binding: _LiveBinding,
    ) -> int:
        async with self._lock:
            if self._closed or self._slots.get(key) is not slot or not slot.accepting:
                raise GenerationConflictError()
        return await binding.reserve_attachment()

    async def _drop_failed(
        self,
        key: SessionBindingKeyV1,
        slot: _LiveSlot,
    ) -> None:
        async with self._lock:
            if self._slots.get(key) is slot:
                del self._slots[key]

    async def _close_unclaimed_if_fenced(
        self,
        key: SessionBindingKeyV1,
        slot: _LiveSlot,
        binding: _LiveBinding,
    ) -> None:
        async with self._lock:
            fenced = self._closed or not slot.accepting
        if fenced:
            try:
                await binding.close()
            except AppHostError:
                return
            async with self._lock:
                if self._slots.get(key) is slot:
                    del self._slots[key]

    async def close_key(self, key: SessionBindingKeyV1) -> None:
        if not isinstance(key, SessionBindingKeyV1):
            raise TypeError("key must be SessionBindingKeyV1")
        async with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                return
            slot.accepting = False
        try:
            binding = await asyncio.shield(slot.task)
        except BaseException:
            await self._drop_failed(key, slot)
            raise
        await binding.close()
        async with self._lock:
            if self._slots.get(key) is slot:
                del self._slots[key]

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            slots = tuple(self._slots.items())
            for _, slot in slots:
                slot.accepting = False
        results = await asyncio.gather(
            *(self._close_slot(key, slot) for key, slot in slots),
            return_exceptions=True,
        )
        failures = [
            result for result in results if isinstance(result, BaseException)
        ]
        try:
            await self._cleanup.settle_all()
        except BaseException as error:
            failures.append(error)
        if failures:
            raise CleanupIncompleteError(cleanup_debt_count=len(failures)) from None

    async def settle_pending_cleanup(self) -> None:
        async with self._lock:
            fenced = tuple(
                (key, slot) for key, slot in self._slots.items() if not slot.accepting
            )
        results = await asyncio.gather(
            *(self._close_slot(key, slot) for key, slot in fenced),
            return_exceptions=True,
        )
        failures = [
            result for result in results if isinstance(result, BaseException)
        ]
        try:
            await self._cleanup.settle_all()
        except BaseException as error:
            failures.append(error)
        if failures:
            raise CleanupIncompleteError(cleanup_debt_count=len(failures)) from None

    async def _close_slot(
        self,
        key: SessionBindingKeyV1,
        slot: _LiveSlot,
    ) -> None:
        try:
            binding = await asyncio.shield(slot.task)
        except BaseException:
            # Construction owns and registers any unpublished cleanup before it
            # fails.  The failed task itself is not a live binding.
            await self._drop_failed(key, slot)
            return
        await binding.close()
        async with self._lock:
            if self._slots.get(key) is slot:
                del self._slots[key]


class AppHostRuntimeV1:
    """A0.3 composition root for explicit Session-scoped Product attachments."""

    __slots__ = (
        "_active_operations",
        "_catalog",
        "_cleanup",
        "_closed",
        "_drained",
        "_lock",
        "_phase_tasks",
        "_registry",
        "_router",
        "_shutdown_lock",
        "_shutdown_task",
    )

    def __init__(self, catalog: AppHostCatalogV1, sessions: object) -> None:
        if not isinstance(catalog, AppHostCatalogV1):
            raise TypeError("catalog must be AppHostCatalogV1")
        self._catalog = catalog
        self._router = AppHostRouterV1(catalog, sessions)
        self._cleanup = _RuntimeCleanupRegistry()
        self._registry = _LiveBindingRegistry(self._cleanup)
        self._lock = asyncio.Lock()
        self._closed = False
        self._active_operations = 0
        self._drained = asyncio.Event()
        self._drained.set()
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_task: asyncio.Task[AppHostShutdownReportV1] | None = None
        self._phase_tasks: dict[AppHostShutdownPhase, asyncio.Task[None]] = {}

    async def attach_resume(
        self,
        *,
        product_id: str,
        reference: SessionCandidateRefV1,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        self._reject_reentry()
        operation = asyncio.create_task(
            self._run_attach_resume(
                product_id=product_id,
                reference=reference,
                profile_id=profile_id,
            )
        )
        return await self._join_attachment(operation)

    async def attach_create(
        self,
        request: SessionCreateRequestV1,
        *,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        self._reject_reentry()
        operation = asyncio.create_task(
            self._run_attach_create(request, profile_id=profile_id)
        )
        return await self._join_attachment(operation)

    async def _run_attach_resume(
        self,
        *,
        product_id: str,
        reference: SessionCandidateRefV1,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        await self._begin_operation()
        context = self._enter_callback_domain()
        try:
            route = await self._router._prepare_runtime_resume_candidate(
                product_id=product_id,
                reference=reference,
            )
            return await self._registry.attach(route, profile_id)
        finally:
            _ACTIVE_RUNTIME_CALLBACKS.reset(context)
            await self._finish_operation()

    async def _run_attach_create(
        self,
        request: SessionCreateRequestV1,
        *,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        await self._begin_operation()
        context = self._enter_callback_domain()
        try:
            route = await self._router._prepare_runtime_create_candidate(request)
            return await self._registry.attach(route, profile_id)
        finally:
            _ACTIVE_RUNTIME_CALLBACKS.reset(context)
            await self._finish_operation()

    async def close_session(self, key: SessionBindingKeyV1) -> None:
        self._reject_reentry()
        operation = asyncio.create_task(self._run_close_session(key))
        operation.add_done_callback(_observe_background_result)
        await asyncio.shield(operation)

    async def _run_close_session(self, key: SessionBindingKeyV1) -> None:
        await self._begin_operation()
        context = self._enter_callback_domain()
        try:
            await self._registry.close_key(key)
        finally:
            _ACTIVE_RUNTIME_CALLBACKS.reset(context)
            await self._finish_operation()

    async def settle_pending_cleanup(self) -> None:
        self._reject_reentry()
        context = self._enter_callback_domain()
        try:
            await self._registry.settle_pending_cleanup()
            await self._router.settle_pending_cleanup()
            await self._catalog.settle_retiring()
        finally:
            _ACTIVE_RUNTIME_CALLBACKS.reset(context)

    async def shutdown(
        self,
        budget: AppHostShutdownBudgetV1,
    ) -> AppHostShutdownReportV1:
        self._reject_reentry()
        if not isinstance(budget, AppHostShutdownBudgetV1):
            raise TypeError("budget must be AppHostShutdownBudgetV1")
        async with self._shutdown_lock:
            task = self._shutdown_task
            if _shutdown_needs_retry(task):
                task = asyncio.create_task(self._shutdown_once(budget))
                task.add_done_callback(_observe_background_result)
                self._shutdown_task = task
        assert task is not None
        return await asyncio.shield(task)

    async def close(self) -> None:
        report = await self.shutdown(_DEFAULT_SHUTDOWN_BUDGET)
        if not report.completed:
            raise CleanupIncompleteError(
                cleanup_debt_count=max(
                    1,
                    len(report.timed_out_phases) + len(report.failed_phases),
                )
            ) from None

    async def _shutdown_once(
        self,
        budget: AppHostShutdownBudgetV1,
    ) -> AppHostShutdownReportV1:
        context = self._enter_callback_domain()
        try:
            async with self._lock:
                self._closed = True
            loop = asyncio.get_running_loop()
            deadline = loop.time() + budget.overall_timeout_seconds
            timed_out: list[AppHostShutdownPhase] = []
            failed: list[AppHostShutdownPhase] = []

            admission = await self._run_phase(
                AppHostShutdownPhase.ADMISSION,
                self._drained.wait,
                budget,
                deadline,
                timed_out,
                failed,
            )
            if not admission:
                return _shutdown_report(timed_out, failed)

            bindings = await self._run_phase(
                AppHostShutdownPhase.BINDINGS,
                self._registry.close,
                budget,
                deadline,
                timed_out,
                failed,
            )
            router = await self._run_phase(
                AppHostShutdownPhase.ROUTER,
                self._router.close,
                budget,
                deadline,
                timed_out,
                failed,
            )
            if bindings and router:
                await self._run_phase(
                    AppHostShutdownPhase.CATALOG,
                    self._catalog.close,
                    budget,
                    deadline,
                    timed_out,
                    failed,
                )
            return _shutdown_report(timed_out, failed)
        finally:
            _ACTIVE_RUNTIME_CALLBACKS.reset(context)

    async def _run_phase(
        self,
        phase: AppHostShutdownPhase,
        callback: Callable[[], Awaitable[Any]],
        budget: AppHostShutdownBudgetV1,
        deadline: float,
        timed_out: list[AppHostShutdownPhase],
        failed: list[AppHostShutdownPhase],
    ) -> bool:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            timed_out.append(phase)
            return False
        task = self._phase_tasks.get(phase)
        if task is None or (
            task.done() and (task.cancelled() or task.exception() is not None)
        ):
            task = asyncio.create_task(_await_none(callback))
            task.add_done_callback(_observe_background_result)
            self._phase_tasks[phase] = task
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=min(remaining, budget.phase_timeout_seconds),
            )
        except TimeoutError:
            timed_out.append(phase)
            return False
        except BaseException:
            failed.append(phase)
            return False
        return True

    async def _begin_operation(self) -> None:
        async with self._lock:
            if self._closed:
                raise GenerationRetiredError()
            if self._active_operations == 0:
                self._drained.clear()
            self._active_operations += 1

    async def _finish_operation(self) -> None:
        async with self._lock:
            self._active_operations -= 1
            if self._active_operations == 0:
                self._drained.set()

    async def _join_attachment(
        self,
        operation: asyncio.Task[AppHostSessionLeaseV1],
    ) -> AppHostSessionLeaseV1:
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            try:
                attachment = await asyncio.shield(operation)
            except CleanupIncompleteError:
                raise
            except BaseException:
                raise asyncio.CancelledError from None
            try:
                await attachment.close()
            except BaseException:
                raise CleanupIncompleteError() from None
            raise

    def _reject_reentry(self) -> None:
        if id(self) in _ACTIVE_RUNTIME_CALLBACKS.get():
            raise AppHostError(AppHostFailureCategory.RUNTIME_UNAVAILABLE)

    def _enter_callback_domain(self) -> contextvars.Token[frozenset[int]]:
        active = _ACTIVE_RUNTIME_CALLBACKS.get()
        return _ACTIVE_RUNTIME_CALLBACKS.set(active | {id(self)})


async def _await_none(callback: Callable[[], Awaitable[Any]]) -> None:
    await callback()


def _shutdown_report(
    timed_out: list[AppHostShutdownPhase],
    failed: list[AppHostShutdownPhase],
) -> AppHostShutdownReportV1:
    return AppHostShutdownReportV1(
        completed=not timed_out and not failed,
        timed_out_phases=tuple(timed_out),
        failed_phases=tuple(failed),
    )


def _shutdown_needs_retry(
    task: asyncio.Task[AppHostShutdownReportV1] | None,
) -> bool:
    if task is None or task.cancelled():
        return True
    if not task.done():
        return False
    try:
        return not task.result().completed
    except BaseException:
        return True


def _observe_background_result(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["AppHostRuntimeV1"]
