"""Private retryable settlement primitives for AppHost-owned resources."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Literal,
    Protocol,
    TypeVar,
    cast,
)

from loushang.foundation._owned_tasks import _try_settle_owned_closes

from .contracts import (
    AppHostSessionLeaseV1,
    SessionBindingKeyV1,
    SessionCandidateRefV1,
    SessionCreateRequestV1,
)
from .errors import CleanupIncompleteError

if TYPE_CHECKING:
    from .catalog import AppHostCatalogV1
    from .contracts import (
        AppHostCatalogInputV1,
        AppHostShutdownBudgetV1,
        AppHostShutdownReportV1,
    )
    from .runtime import AppHostRuntimeV1

AsyncClose = Callable[[], Awaitable[None]]
AsyncCall = Callable[..., Awaitable[Any]]
PayloadT = TypeVar("PayloadT")


class _CandidatePayloadView(Generic[PayloadT]):
    __slots__ = ("_binding",)

    _binding: PayloadT

    @property
    def opaque_binding(self) -> PayloadT:
        return self._binding


class _ClaimedCandidateView(_CandidatePayloadView[PayloadT]):
    __slots__ = ("_reference",)

    def __init__(self, reference: SessionCandidateRefV1, binding: PayloadT) -> None:
        self._reference = reference
        self._binding = binding

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference


class _OpenedCandidateView(_CandidatePayloadView[PayloadT]):
    __slots__ = ("_binding_key",)

    def __init__(self, binding_key: SessionBindingKeyV1, binding: PayloadT) -> None:
        self._binding_key = binding_key
        self._binding = binding

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key


class RetryableCloser:
    """Join concurrent close calls and retry only an unsettled callback."""

    __slots__ = ("_callback", "_complete", "_debt_count", "_lock", "_task")

    def __init__(self, callback: AsyncClose) -> None:
        self._callback = callback
        self._complete = False
        self._debt_count = 0
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[bool] | None = None

    @classmethod
    def bind(cls, value: object) -> RetryableCloser:
        return cls(bind_native_async(value, "close"))

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def debt_count(self) -> int:
        return self._debt_count

    async def settle(self) -> bool:
        async with self._lock:
            if self._complete:
                return True
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_once())
            task = self._task
        return await asyncio.shield(task)

    async def _run_once(self) -> bool:
        try:
            await self._callback()
        except BaseException:
            self._debt_count += 1
            return False
        self._complete = True
        return True


class CloseGroup:
    """Retryable reverse-order settlement retaining only unresolved owners."""

    __slots__ = ("_closers", "_complete", "_lock", "_task")

    def __init__(self, closers: Iterable[RetryableCloser] = ()) -> None:
        self._closers = list(closers)
        self._complete = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[bool] | None = None

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def debt_count(self) -> int:
        return sum(closer.debt_count for closer in self._closers)

    def append(self, closer: RetryableCloser) -> None:
        if self._task is not None or self._complete:
            raise RuntimeError("cannot append after settlement begins")
        self._closers.append(closer)

    async def settle(self) -> bool:
        async with self._lock:
            if self._complete:
                return True
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_once())
            task = self._task
        return await asyncio.shield(task)

    async def close(self) -> None:
        if not await self.settle():
            raise CleanupIncompleteError(cleanup_debt_count=self.debt_count) from None

    async def _run_once(self) -> bool:
        complete = True
        for closer in reversed(self._closers):
            if closer.complete:
                continue
            if not await closer.settle():
                complete = False
        self._complete = complete
        return complete


class DependentCloseChain:
    """Retryable reverse-order settlement that preserves dependencies.

    Unlike :class:`CloseGroup`, a failed closer fences every earlier owner in
    the acquisition chain.  A retry resumes at the same dependent owner and
    reaches its prerequisites only after it has settled.
    """

    __slots__ = ("_closers", "_complete", "_lock", "_task")

    def __init__(self, closers: Iterable[RetryableCloser]) -> None:
        self._closers = list(closers)
        self._complete = not self._closers
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[bool] | None = None

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def debt_count(self) -> int:
        return sum(closer.debt_count for closer in self._closers)

    async def settle(self) -> bool:
        async with self._lock:
            if self._complete:
                return True
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_once())
            task = self._task
        return await asyncio.shield(task)

    async def close(self) -> None:
        if not await self.settle():
            raise CleanupIncompleteError(
                cleanup_debt_count=max(1, self.debt_count)
            ) from None

    async def _run_once(self) -> bool:
        for closer in reversed(self._closers):
            if closer.complete:
                continue
            if not await closer.settle():
                return False
        self._complete = True
        return True


class AcquisitionStack:
    """Record actual acquisition order and transfer it to one close group."""

    __slots__ = ("_closers", "_transferred")

    def __init__(self) -> None:
        self._closers: list[RetryableCloser] = []
        self._transferred = False

    def push(self, value: object) -> RetryableCloser:
        if self._transferred:
            raise RuntimeError("acquisition stack was transferred")
        closer = RetryableCloser.bind(value)
        self._closers.append(closer)
        return closer

    def push_closer(self, closer: RetryableCloser) -> None:
        if self._transferred:
            raise RuntimeError("acquisition stack was transferred")
        self._closers.append(closer)

    def transfer(self) -> CloseGroup:
        if self._transferred:
            raise RuntimeError("acquisition stack was transferred")
        self._transferred = True
        return CloseGroup(self._closers)

    async def unwind(self) -> None:
        if self._transferred:
            return
        self._transferred = True
        await CloseGroup(self._closers).close()


def bind_native_async(value: object, name: str) -> AsyncCall:
    """Bind one class-defined native-async descriptor without dynamic lookup."""

    if inspect.getattr_static(
        type(value), "__getattribute__", object.__getattribute__
    ) is not object.__getattribute__:
        raise TypeError("dynamic attribute dispatch is forbidden")
    descriptor = inspect.getattr_static(type(value), name, None)
    if inspect.getattr_static(value, name, None) is not descriptor:
        raise TypeError("instance callback shadow is forbidden")
    inspected = (
        descriptor.__func__
        if isinstance(descriptor, (classmethod, staticmethod))
        else descriptor
    )
    if not inspect.iscoroutinefunction(inspected):
        raise TypeError("native async class descriptor required")
    return cast(AsyncCall, descriptor.__get__(value, type(value)))


def read_static_property(value: object, name: str) -> object:
    """Read one class-defined property once without invoking attribute hooks."""

    if inspect.getattr_static(
        type(value), "__getattribute__", object.__getattribute__
    ) is not object.__getattribute__:
        raise TypeError("dynamic attribute dispatch is forbidden")
    descriptor = inspect.getattr_static(type(value), name, None)
    if not isinstance(descriptor, property):
        raise TypeError("class-defined property required")
    if inspect.getattr_static(value, name, None) is not descriptor:
        raise TypeError("instance property shadow is forbidden")
    return descriptor.__get__(value, type(value))


class _ConstructionCloseOwner(Protocol):
    async def close(self) -> None: ...


_ConstructedT = TypeVar("_ConstructedT")


async def _construct_product_apphost(
    catalog_input: Callable[[], AppHostCatalogInputV1],
    sessions: object,
    product_factory: _ConstructionCloseOwner,
    bind: Callable[[AppHostRuntimeV1], _ConstructedT],
    *,
    cleanup_failure: RuntimeError,
    join_owned: Callable[[asyncio.Task[None]], Awaitable[None]],
    construction_failure: RuntimeError | None = None,
    close_runtime_on_failure: bool = True,
    caught: tuple[type[BaseException], ...] = (BaseException,),
) -> _ConstructedT:
    """Hold upstream owners until the Product has successfully bound its Host."""
    from .catalog import AppHostCatalogV1
    from .runtime import AppHostRuntimeV1

    catalog = None
    runtime = None
    try:
        catalog = await AppHostCatalogV1.admit(catalog_input())
        runtime = AppHostRuntimeV1(catalog, sessions)
        return bind(runtime)
    except caught as error:
        await _settle_failed_product_construction(
            runtime if close_runtime_on_failure else None,
            catalog,
            product_factory,
            failure=cleanup_failure,
            join_owned=join_owned,
        )
        if construction_failure is not None and isinstance(error, Exception):
            raise construction_failure from error
        raise


async def _settle_failed_product_construction(
    runtime: AppHostRuntimeV1 | None,
    catalog: AppHostCatalogV1 | None,
    product_factory: _ConstructionCloseOwner,
    *,
    failure: RuntimeError,
    join_owned: Callable[[asyncio.Task[None]], Awaitable[None]],
) -> None:
    """Release the most complete Host owner, then the unpublished Product."""
    outer_owner = runtime if runtime is not None else catalog
    close_outer = () if outer_owner is None else (lambda: outer_owner.close(),)
    await _settle_owned_closes(
        *close_outer,
        lambda: product_factory.close(),
        failure=failure,
        join_owned=join_owned,
    )


async def _settle_owned_closes(
    *closes: AsyncClose | None,
    failure: RuntimeError,
    join_owned: Callable[[asyncio.Task[None]], Awaitable[None]],
) -> None:
    """Attempt every close in order, including when an earlier owner fails."""

    async def settle() -> None:
        if not await _try_settle_owned_closes(*closes):
            raise failure from None

    task = asyncio.create_task(settle())
    await join_owned(task)


class _CompletionReport(Protocol):
    @property
    def completed(self) -> bool: ...


_ReportT = TypeVar("_ReportT", bound=_CompletionReport)


def _observe_background_result(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


def _report_task_needs_retry(task: asyncio.Task[_ReportT]) -> bool:
    return task.done() and (
        task.cancelled() or task.exception() is not None or not task.result().completed
    )


_SettlementMode = Literal["close", "rollback"]
_SettlementPhase = Literal["rollback_latch", "apphost_shutdown", "product_cleanup"]
_LatchT = TypeVar("_LatchT")
_LatchCo = TypeVar("_LatchCo", covariant=True)
_EXPLICIT_PRODUCT_LIFECYCLE_SLOTS: tuple[str, ...] = ()


class _ProductRollbackControl(Protocol[_LatchCo]):
    async def latch_future_attempts(self) -> _LatchCo: ...


class _ExplicitProductAppHostLifecycle(Generic[_LatchT, _ReportT]):
    """Admission and ordered settlement for an explicitly composed Product."""

    __slots__ = _EXPLICIT_PRODUCT_LIFECYCLE_SLOTS
    _product_id: ClassVar[str]
    _rollback_latch_type: type[_LatchT]
    _settlement_report_type: Callable[..., _ReportT]

    def _composition_error(self, code: str) -> RuntimeError:
        raise NotImplementedError

    def _initialize_lifecycle(
        self,
        runtime: AppHostRuntimeV1,
        product_factory: _ConstructionCloseOwner,
        rollback_control: _ProductRollbackControl[_LatchT],
        shutdown_budget: AppHostShutdownBudgetV1,
    ) -> None:
        self._runtime = runtime
        self._product_factory = product_factory
        self._rollback_control = rollback_control
        self._shutdown_budget = shutdown_budget
        self._accepting = True
        self._admission_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._control_mode: _SettlementMode | None = None
        self._control_task: asyncio.Task[_ReportT] | None = None
        self._rollback_latch: _LatchT | None = None

    @property
    def accepting(self) -> bool:
        return self._accepting

    async def attach_resume(
        self,
        *,
        reference: SessionCandidateRefV1,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        await self._admit()
        return await self._runtime.attach_resume(
            product_id=self._product_id,
            reference=reference,
            profile_id=profile_id,
        )

    async def attach_create(
        self,
        request: SessionCreateRequestV1,
        *,
        profile_id: str,
    ) -> AppHostSessionLeaseV1:
        await self._admit()
        if request.product_id != self._product_id:
            raise self._composition_error("product_mismatch")
        return await self._runtime.attach_create(request, profile_id=profile_id)

    async def close_session(self, key: SessionBindingKeyV1) -> None:
        await self._admit()
        await self._runtime.close_session(key)

    async def _rollback(self) -> _ReportT:
        task = await self._settlement_task("rollback")
        return await asyncio.shield(task)

    async def close(self) -> None:
        task = await self._settlement_task("close")
        report = await asyncio.shield(task)
        if not report.completed:
            raise self._composition_error("cleanup_incomplete")

    async def _admit(self) -> None:
        async with self._admission_lock:
            if not self._accepting:
                raise self._composition_error("fenced")

    async def _fence(self) -> None:
        async with self._admission_lock:
            self._accepting = False

    async def _settlement_task(
        self,
        requested_mode: _SettlementMode,
    ) -> asyncio.Task[_ReportT]:
        async with self._control_lock:
            task = self._control_task
            mode = self._control_mode
            if mode == "close" and requested_mode == "rollback":
                assert task is not None
                effective_mode: _SettlementMode = "rollback"
                settle = self._upgrade_close_to_rollback(task)
            elif task is None or _report_task_needs_retry(task):
                effective_mode = "rollback" if mode == "rollback" else requested_mode
                settle = self._settle_once(effective_mode)
            else:
                return task
            task = asyncio.create_task(settle)
            task.add_done_callback(_observe_background_result)
            self._control_task = task
            self._control_mode = effective_mode
            return task

    async def _settle_once(
        self,
        mode: _SettlementMode,
        *,
        attempt_rollback_latch: bool = True,
    ) -> _ReportT:
        await self._fence()
        failed: list[_SettlementPhase] = []

        if (
            mode == "rollback"
            and self._rollback_latch is None
            and (not attempt_rollback_latch or not await self._latch_rollback())
        ):
            failed.append("rollback_latch")

        shutdown: AppHostShutdownReportV1 | None = None
        try:
            shutdown = await self._runtime.shutdown(self._shutdown_budget)
            if not shutdown.completed:
                failed.append("apphost_shutdown")
        except Exception:
            failed.append("apphost_shutdown")

        product_cleanup_complete = False
        if shutdown is not None and shutdown.completed:
            try:
                await self._product_factory.close()
                product_cleanup_complete = True
            except Exception:
                failed.append("product_cleanup")

        failed_phases = tuple(dict.fromkeys(failed))
        completed = (
            (mode == "close" or self._rollback_latch is not None)
            and shutdown is not None
            and shutdown.completed
            and product_cleanup_complete
            and not failed_phases
        )
        return self._settlement_report_type(
            mode=mode,
            completed=completed,
            admission_fenced=True,
            rollback_latch=(self._rollback_latch if mode == "rollback" else None),
            apphost_shutdown=shutdown,
            product_cleanup_complete=product_cleanup_complete,
            failed_phases=failed_phases,
        )

    async def _upgrade_close_to_rollback(
        self,
        close_task: asyncio.Task[_ReportT],
    ) -> _ReportT:
        """Make an emergency rollback dominate an earlier normal close."""

        await self._fence()
        await self._latch_rollback()
        with suppress(asyncio.CancelledError, Exception):
            await asyncio.shield(close_task)
        # The retryable runtime/factory owners, rather than the prior task
        # result, determine whether the upgraded settlement is complete.
        return await self._settle_once(
            "rollback",
            attempt_rollback_latch=False,
        )

    async def _latch_rollback(self) -> bool:
        if self._rollback_latch is not None:
            return True
        try:
            raw_latch = await self._rollback_control.latch_future_attempts()
            if type(raw_latch) is not self._rollback_latch_type:
                raise TypeError("rollback control returned an invalid latch")
        except Exception:
            return False
        self._rollback_latch = raw_latch
        return True


def _method_descriptor(value: object, name: str) -> object:
    descriptor = inspect.getattr_static(type(value), name, None)
    if isinstance(descriptor, (classmethod, staticmethod)):
        return descriptor.__func__
    return descriptor


def _require_async_method(value: object, name: str, *, label: str) -> None:
    if not inspect.iscoroutinefunction(_method_descriptor(value, name)):
        raise TypeError(f"{label} {name} port is invalid")


def _require_session_catalog_methods(value: object, *, label: str) -> None:
    for name in ("list_identities", "open_candidate", "find_created_candidate", "create_candidate"):
        _require_async_method(value, name, label=label)


__all__: list[str] = []
