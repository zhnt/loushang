from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Generic, Protocol, TypeVar

from loushang.harness.context.packing import ContextPacker
from loushang.harness.context.types import (
    CompactionArtifact,
    CompactionPlan,
    CompactionRequest,
    CompactionResult,
    CompactionStatus,
    ContextBundle,
    ContextDiagnostic,
    ContextItem,
    PackingRequest,
    ReductionRequest,
)

T = TypeVar("T")
R = TypeVar("R")


class CompactionStrategy(Protocol, Generic[T]):
    def plan(self, request: CompactionRequest[T]) -> CompactionPlan[T]: ...


class ContextReducer(Protocol, Generic[T]):
    async def reduce(self, request: ReductionRequest[T]) -> ContextItem[T]: ...


CompactionOperation = Callable[[], Awaitable[R]]
AbortDriver = Callable[[], None]


class CompactionCoordinator(Generic[R]):
    """Single-flight lifecycle shared by product and neutral compaction flows."""

    def __init__(self) -> None:
        self._is_compacting = False
        self._last_reason: str | None = None
        self._last_result: R | None = None
        self._last_error: str | None = None
        self._aborted = False
        self._abort_driver: AbortDriver | None = None
        self._active_task: asyncio.Task[object] | None = None

    @property
    def is_compacting(self) -> bool:
        return self._is_compacting

    def owns_current_task(self) -> bool:
        task = asyncio.current_task()
        return task is not None and self._active_task is task

    def get_status(self) -> CompactionStatus[R]:
        return CompactionStatus(
            is_compacting=self._is_compacting,
            last_reason=self._last_reason,
            last_result=self._last_result,
            last_error=self._last_error,
            aborted=self._aborted,
        )

    async def run(
        self,
        operation: CompactionOperation[R],
        *,
        reason: str,
        abort_driver: AbortDriver | None = None,
    ) -> R:
        if self._is_compacting:
            raise RuntimeError("Compaction already in progress")
        task = asyncio.current_task()
        self._begin(reason=reason, abort_driver=abort_driver)
        self._active_task = task
        try:
            result = await operation()
            self._last_result = result
            return result
        except asyncio.CancelledError:
            self._aborted = True
            self._last_error = "CancelledError"
            raise
        except Exception as exc:
            self._last_error = str(exc)
            raise
        finally:
            if self._active_task is task:
                self._active_task = None
            self._finish()

    def abort(self) -> None:
        if not self._is_compacting:
            return
        self._aborted = True
        if self._abort_driver is not None:
            self._abort_driver()

    async def wait(self) -> None:
        """Join the active compaction without taking ownership of its result."""

        task = self._active_task
        if task is None or task.done():
            return
        if task is asyncio.current_task():
            raise RuntimeError("cannot wait for compaction from its active task")
        await asyncio.gather(task, return_exceptions=True)

    def _begin(
        self,
        *,
        reason: str,
        abort_driver: AbortDriver | None,
    ) -> None:
        self._is_compacting = True
        self._last_reason = reason
        self._last_error = None
        self._aborted = False
        self._abort_driver = abort_driver

    def _finish(self) -> None:
        self._is_compacting = False
        self._abort_driver = None


class ContextCompactionCoordinator(Generic[T]):
    def __init__(
        self,
        *,
        packer: ContextPacker | None = None,
    ) -> None:
        self._packer = packer or ContextPacker()
        self._lifecycle: CompactionCoordinator[CompactionResult[T]] = (
            CompactionCoordinator()
        )

    @property
    def is_compacting(self) -> bool:
        return self._lifecycle.is_compacting

    def get_status(self) -> CompactionStatus[CompactionResult[T]]:
        return self._lifecycle.get_status()

    def abort(self) -> None:
        self._lifecycle.abort()

    async def compact(
        self,
        request: CompactionRequest[T],
        *,
        strategy: CompactionStrategy[T],
        reducer: ContextReducer[T] | None = None,
        reason: str = "requested",
    ) -> CompactionResult[T]:
        return await self._lifecycle.run(
            lambda: self._execute(request, strategy=strategy, reducer=reducer),
            reason=reason,
            abort_driver=_cancellation_driver(request.cancellation),
        )

    async def _execute(
        self,
        request: CompactionRequest[T],
        *,
        strategy: CompactionStrategy[T],
        reducer: ContextReducer[T] | None,
    ) -> CompactionResult[T]:
        if _is_cancelled(request.cancellation):
            return _aborted_result(request)

        try:
            plan = strategy.plan(request)
            if _is_cancelled(request.cancellation):
                return _aborted_result(request, plan=plan)
            if not plan.reduction_items:
                return self._result_without_reduction(request, plan)
            if reducer is None:
                raise ValueError("compaction plan requires a context reducer")

            summary = await reducer.reduce(
                ReductionRequest(
                    items=plan.reduction_items,
                    max_output_tokens=max(0, request.summary_reserve_tokens),
                    instructions=request.instructions,
                    cancellation=request.cancellation,
                )
            )
            if not isinstance(summary, ContextItem):
                raise TypeError("context reducer must return a ContextItem")
            if _is_cancelled(request.cancellation):
                return _aborted_result(request, plan=plan)
            return self._result_with_summary(request, plan, summary)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if request.failure_behavior == "raise":
                raise
            diagnostic = ContextDiagnostic(
                code="context_compaction_failed",
                message="Context compaction failed; the original bundle was retained.",
                details={"error": str(exc)},
            )
            return CompactionResult(
                outcome="failed",
                bundle=request.bundle,
                plan=None,
                source_tokens=request.bundle.source_tokens,
                output_tokens=request.bundle.source_tokens,
                diagnostics=(diagnostic,),
                error=str(exc),
            )

    def _result_without_reduction(
        self,
        request: CompactionRequest[T],
        plan: CompactionPlan[T],
    ) -> CompactionResult[T]:
        output = ContextBundle(
            items=plan.retained_items,
            metadata=request.bundle.metadata,
        )
        overflow = max(0, output.source_tokens - max(0, request.target_tokens))
        _raise_on_overflow(request, overflow)
        return CompactionResult(
            outcome="overflow" if overflow else "completed",
            bundle=output,
            plan=plan,
            source_tokens=request.bundle.source_tokens,
            output_tokens=output.source_tokens,
            overflow_tokens=overflow,
            diagnostics=plan.diagnostics,
        )

    def _result_with_summary(
        self,
        request: CompactionRequest[T],
        plan: CompactionPlan[T],
        summary: ContextItem[T],
    ) -> CompactionResult[T]:
        pinned_summary = replace(summary, pinned=True)
        combined = ContextBundle(
            items=(pinned_summary, *plan.retained_items),
            metadata=request.bundle.metadata,
        )
        packed = self._packer.pack(
            PackingRequest(
                bundle=combined,
                target_tokens=request.target_tokens,
                order=request.packing_order,
            )
        )
        overflow = packed.overflow_tokens
        _raise_on_overflow(request, overflow)
        artifact = CompactionArtifact(
            summary=summary,
            summarized_item_ids=tuple(
                item.item_id for item in plan.reduction_items
            ),
        )
        return CompactionResult(
            outcome="overflow" if overflow else "completed",
            bundle=packed.bundle,
            plan=plan,
            source_tokens=request.bundle.source_tokens,
            output_tokens=packed.bundle.source_tokens,
            overflow_tokens=overflow,
            artifact=artifact,
            diagnostics=(*plan.diagnostics, *packed.diagnostics),
        )


def _raise_on_overflow(request: CompactionRequest[Any], overflow: int) -> None:
    if overflow and request.overflow_behavior == "raise":
        raise ValueError(
            f"compacted context exceeds target budget by {overflow} tokens"
        )


def _aborted_result(
    request: CompactionRequest[T],
    *,
    plan: CompactionPlan[T] | None = None,
) -> CompactionResult[T]:
    return CompactionResult(
        outcome="aborted",
        bundle=request.bundle,
        plan=plan,
        source_tokens=request.bundle.source_tokens,
        output_tokens=request.bundle.source_tokens,
        diagnostics=(
            ContextDiagnostic(
                code="context_compaction_aborted",
                message="Context compaction was cancelled; the original bundle was retained.",
            ),
        ),
    )


def _is_cancelled(signal: object | None) -> bool:
    if signal is None:
        return False
    for name in ("cancelled", "is_cancelled", "is_set"):
        value = getattr(signal, name, None)
        if callable(value):
            try:
                return bool(value())
            except TypeError:
                continue
        if isinstance(value, bool):
            return value
    return False


def _cancellation_driver(signal: object | None) -> AbortDriver | None:
    if signal is None:
        return None
    for name in ("abort", "cancel", "set"):
        driver = getattr(signal, name, None)
        if callable(driver):
            return driver
    return None


__all__ = [
    "CompactionCoordinator",
    "CompactionStrategy",
    "ContextCompactionCoordinator",
    "ContextReducer",
]
