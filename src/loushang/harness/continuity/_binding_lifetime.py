"""Bound Continuity composition and failed construction cleanup lifetimes.

One existing binding owns shutdown flags and retry state; these methods add no
second manager, task registry, profile selection or publication authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import ClassVar

from loushang.harness.runtime import (
    RuntimeProfileBinder,
    RuntimeProfileBinding,
    await_owned_task,
)

from .hub import ContinuityHub
from .plugin_runtime import (
    ContinuityPluginGeneration,
    ContinuityPluginLifecycleError,
    ContinuityPluginPendingCleanup,
    ContinuityPluginPublication,
)


class _ContinuityCompositionLifetime:
    binding: RuntimeProfileBinding
    binder: RuntimeProfileBinder
    hub: ContinuityHub
    plugin_publication: ContinuityPluginPublication | None
    owned_cleanup: Callable[[], None] | None
    runtime_owned: bool
    _core_shutdown: bool
    _owned_cleanup_complete: bool
    _shutdown: bool

    async def dispose(self) -> None:
        """Release a caller view; the process-scoped runtime remains bound."""

        if not self.runtime_owned:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Close the authority, then dispose the process-scoped binding.

        Close-then-record: shutdown completion is recorded only after the hub
        has staled references, aborted outstanding activation leases, joined
        in-flight operations, and the binding has been disposed.  A failed or
        cancelled close leaves the composition unrecorded and retryable.
        """

        if self._shutdown:
            return
        if not self._core_shutdown:
            if self.plugin_publication is None:
                await self.hub.close()
            else:
                await self.plugin_publication.shutdown()
            await self.binder.dispose(self.binding)
            self._core_shutdown = True
        if not self._owned_cleanup_complete:
            if self.owned_cleanup is not None:
                self.owned_cleanup()
            self._owned_cleanup_complete = True
        self._shutdown = True


class _ContinuityBindingReservationLifetime:
    binder: RuntimeProfileBinder | None
    binding: RuntimeProfileBinding | None
    generation: ContinuityPluginGeneration | None
    construction_cleanup: ContinuityPluginPendingCleanup | None
    _base_cleanup_code: ClassVar[str]

    async def retry_cleanup(self) -> tuple[str, ...]:
        codes: list[str] = []
        construction_cleanup = self.construction_cleanup
        if construction_cleanup is not None:
            try:
                await construction_cleanup.retry()
            except BaseException:
                codes.append("continuity_provider_construction_cleanup_retryable")
            else:
                self.construction_cleanup = None
        generation = self.generation
        if generation is not None:
            try:
                await generation.dispose()
            except BaseException:
                codes.append("continuity_provider_generation_cleanup_retryable")
            else:
                self.generation = None
        if self.binder is not None and self.binding is not None:
            try:
                await self.binder.dispose(self.binding)
            except BaseException:
                codes.append(self._base_cleanup_code)
            else:
                self.binder = None
                self.binding = None
        return tuple(codes)


async def retry_bound_continuity_reservation(
    runtime: object,
    reservation: _ContinuityBindingReservationLifetime,
    *,
    binding_attribute: str,
) -> tuple[str, ...]:
    cleanup_task = asyncio.create_task(reservation.retry_cleanup())
    try:
        return await await_owned_task(cleanup_task)
    except asyncio.CancelledError:
        if cleanup_task.done() and not cleanup_task.cancelled():
            try:
                codes = cleanup_task.result()
            except BaseException:
                pass
            else:
                if not codes:
                    delete_runtime_binding_if(
                        runtime, reservation, binding_attribute=binding_attribute
                    )
        raise


async def shutdown_bound_continuity(
    runtime: object,
    *,
    binding_attribute: str,
    composition_type: type[_ContinuityCompositionLifetime],
    reservation_type: type[_ContinuityBindingReservationLifetime],
    cleanup_error_message: str,
    cleanup_error_code: str,
) -> None:
    composition = getattr(runtime, binding_attribute, None)
    if isinstance(composition, reservation_type):
        codes = await retry_bound_continuity_reservation(
            runtime,
            composition,
            binding_attribute=binding_attribute,
        )
        if codes:
            error = ContinuityPluginLifecycleError(
                cleanup_error_message,
                code=cleanup_error_code,
            )
            for code in codes:
                error.add_note(code)
            raise error
        delete_runtime_binding_if(
            runtime, composition, binding_attribute=binding_attribute
        )
        return
    if not isinstance(composition, composition_type):
        return
    shutdown_task = asyncio.create_task(composition.shutdown())
    try:
        await await_owned_task(shutdown_task)
    except asyncio.CancelledError:
        if shutdown_task.done() and not shutdown_task.cancelled():
            try:
                shutdown_task.result()
            except BaseException:
                pass
            else:
                delete_runtime_binding_if(
                    runtime, composition, binding_attribute=binding_attribute
                )
        raise
    delete_runtime_binding_if(runtime, composition, binding_attribute=binding_attribute)


def delete_runtime_binding_if(
    runtime: object, expected: object, *, binding_attribute: str
) -> None:
    if getattr(runtime, binding_attribute, None) is not expected:
        return
    with suppress(AttributeError):
        delattr(runtime, binding_attribute)
