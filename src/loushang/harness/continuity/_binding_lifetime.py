"""Bound Continuity composition and failed construction cleanup lifetimes.

One existing binding owns shutdown flags and retry state; these methods add no
second manager, task registry, profile selection or publication authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import ClassVar, TypeVar

from loushang.harness.capabilities.owner_component_host import (
    CapabilityOwnerComponentHost,
)
from loushang.harness.runtime import (
    RuntimeProfileBinder,
    RuntimeProfileBinding,
    await_owned_task,
)

from .composition import ExperienceComposition
from .hub import ContinuityHub
from .import_provider import ContinuityActivationBridge
from .mutation import ContinuityDeletionRecoveryAuthority
from .plugin_runtime import (
    ContinuityPluginGeneration,
    ContinuityPluginGenerationAuthority,
    ContinuityPluginInstanceFamilyAuthority,
    ContinuityPluginLifecycleError,
    ContinuityPluginPendingCleanup,
    ContinuityPluginPublication,
    ResolvedContinuityPluginSelection,
    construct_continuity_plugin_generation,
    publish_continuity_plugin_generation,
    publish_continuity_plugin_generation_with_mutations,
)


class _ContinuityCompositionLifetime:
    binding: RuntimeProfileBinding
    binder: RuntimeProfileBinder
    hub: ContinuityHub
    plugin_publication: ContinuityPluginPublication | None
    owned_cleanup: Callable[[], None] | None
    runtime_owned: bool
    configured_request_fingerprint: str | None
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


_CompositionT = TypeVar("_CompositionT", bound=_ContinuityCompositionLifetime)


async def bind_continuity_plugin_generation(
    runtime: object,
    reservation: _ContinuityBindingReservationLifetime,
    *,
    binding_attribute: str,
    generation_authority: ContinuityPluginGenerationAuthority,
    resolved_plugins: ResolvedContinuityPluginSelection,
    component_host: CapabilityOwnerComponentHost,
    activation_decision_ids: Mapping[str, str],
    instance_family_authority: ContinuityPluginInstanceFamilyAuthority,
    deletion_authority: ContinuityDeletionRecoveryAuthority | None,
    compose_base: Callable[
        [], tuple[RuntimeProfileBinder, RuntimeProfileBinding, ExperienceComposition]
    ],
    create_activation_bridge: Callable[[], ContinuityActivationBridge],
    make_composition: Callable[
        [RuntimeProfileBinder, RuntimeProfileBinding, ContinuityPluginPublication],
        _CompositionT,
    ],
    label: str,
    cleanup_error_code: str,
) -> _CompositionT:
    """Hold the original reservation from construction through publication."""
    try:
        setattr(runtime, binding_attribute, reservation)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError(
            "Plugin continuity runtime must retain its sealed binding"
        ) from exc
    try:
        binder, binding, base = compose_base()
        reservation.binder = binder
        reservation.binding = binding
        generation = await construct_continuity_plugin_generation(
            resolved_plugins,
            component_host=component_host,
            activation_decision_ids=activation_decision_ids,
            instance_family_authority=instance_family_authority,
            generation_authority=generation_authority,
        )
        reservation.generation = generation
        activation_bridge = create_activation_bridge()
        if deletion_authority is None:
            publication = publish_continuity_plugin_generation(
                base,
                generation,
                activation_bridge=activation_bridge,
            )
        else:
            publication = await publish_continuity_plugin_generation_with_mutations(
                base,
                generation,
                activation_bridge=activation_bridge,
                deletion_authority=deletion_authority,
            )
    except BaseException as error:
        if (
            isinstance(error, ContinuityPluginLifecycleError)
            and error.pending_cleanup is not None
        ):
            reservation.construction_cleanup = error.pending_cleanup
        codes = await retry_bound_continuity_reservation(
            runtime,
            reservation,
            binding_attribute=binding_attribute,
        )
        if codes:
            raise _cleanup_error(
                f"{label} binding cleanup remains retryable.", cleanup_error_code, codes
            ) from error
        raise

    composition = make_composition(binder, binding, publication)
    if getattr(runtime, binding_attribute, None) is not reservation:
        raise RuntimeError(f"{label} binding reservation was replaced")
    setattr(runtime, binding_attribute, composition)
    composition.runtime_owned = True
    return composition


def _cleanup_error(
    message: str,
    code: str,
    cleanup_codes: tuple[str, ...],
) -> ContinuityPluginLifecycleError:
    error = ContinuityPluginLifecycleError(message, code=code)
    for cleanup_code in cleanup_codes:
        error.add_note(cleanup_code)
    return error


async def retry_bound_continuity_reservation(
    runtime: object,
    reservation: _ContinuityBindingReservationLifetime,
    *,
    binding_attribute: str,
) -> tuple[str, ...]:
    cleanup_task = asyncio.create_task(reservation.retry_cleanup())
    try:
        codes = await await_owned_task(cleanup_task)
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
    if not codes:
        delete_runtime_binding_if(
            runtime, reservation, binding_attribute=binding_attribute
        )
    return codes


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
            raise _cleanup_error(cleanup_error_message, cleanup_error_code, codes)
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
