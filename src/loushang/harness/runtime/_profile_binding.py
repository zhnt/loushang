"""Live capability registry, binding, refresh, and disposal mechanics."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from loushang.foundation.json import dump_json_value
from loushang.harness.runtime._profile_types import (
    ResolvedRuntimeCapability,
    ResolvedRuntimeProfile,
    ResolvedRuntimeSelection,
    RuntimeCapabilitySelection,
    _require_integer,
    _require_nonempty_string,
)
from loushang.harness.runtime.bindings import RuntimeBindingLease, RuntimeBindingState
from loushang.harness.runtime.registration import _await_cancellation_atomic

RuntimeCapabilityFactory = Callable[
    [RuntimeCapabilitySelection, object | None], object | Awaitable[object]
]
RuntimeCapabilityDisposer = Callable[[object, object | None], None | Awaitable[None]]


@dataclass(frozen=True)
class RuntimeCapabilityImplementation:
    """One registered factory for an exact slot, key, and wire version."""

    slot: str
    implementation: str
    implementation_version: int
    create: RuntimeCapabilityFactory
    dispose: RuntimeCapabilityDisposer | None = None

    def __post_init__(self) -> None:
        _require_nonempty_string(self.slot, name="implementation slot")
        _require_nonempty_string(self.implementation, name="implementation key")
        _require_integer(
            self.implementation_version,
            name="implementation version",
            minimum=1,
        )
        if not callable(self.create):
            raise TypeError("implementation create must be callable")
        if self.dispose is not None and not callable(self.dispose):
            raise TypeError("implementation dispose must be callable when supplied")


class RuntimeCapabilityRegistry:
    """Exact implementation registry used only by an explicit binder."""

    def __init__(
        self,
        implementations: Iterable[RuntimeCapabilityImplementation] = (),
    ) -> None:
        self._implementations: dict[
            tuple[str, str, int], RuntimeCapabilityImplementation
        ] = {}
        for implementation in implementations:
            self.register(implementation)

    def register(self, implementation: RuntimeCapabilityImplementation) -> None:
        if not isinstance(implementation, RuntimeCapabilityImplementation):
            raise TypeError(
                "implementation must be a RuntimeCapabilityImplementation value"
            )
        key = (
            implementation.slot,
            implementation.implementation,
            implementation.implementation_version,
        )
        if key in self._implementations:
            raise ValueError(
                "runtime capability implementation already registered: "
                + "/".join((key[0], key[1], str(key[2])))
            )
        self._implementations[key] = implementation

    def resolve(
        self,
        selection: RuntimeCapabilitySelection,
    ) -> RuntimeCapabilityImplementation:
        key = (
            selection.slot,
            selection.implementation,
            selection.implementation_version,
        )
        try:
            return self._implementations[key]
        except KeyError as exc:
            raise RuntimeCapabilityBindingError(
                "no registered factory matches the resolved selection",
                slot=selection.slot,
                implementation=selection.implementation,
                implementation_version=selection.implementation_version,
            ) from exc


class RuntimeCapabilityBindingError(RuntimeError):
    """Raised when a capability factory or disposer cannot complete safely."""

    def __init__(
        self,
        message: str,
        *,
        slot: str,
        implementation: str | None = None,
        implementation_version: int | None = None,
    ) -> None:
        self.slot = slot
        self.implementation = implementation
        self.implementation_version = implementation_version
        detail = f"{message} [slot={slot}"
        if implementation is not None:
            detail += f", implementation={implementation}"
        if implementation_version is not None:
            detail += f", version={implementation_version}"
        super().__init__(detail + "]")


class SealedRuntimeCapabilityError(RuntimeError):
    """Raised when a session-sealed selection is changed after binding."""

    def __init__(self, slot: str) -> None:
        self.slot = slot
        super().__init__(f"runtime capability is sealed for this session: {slot}")


@dataclass(frozen=True)
class RuntimeProfileBindings:
    """Live values created from one profile, exposed through a generation lease."""

    profile: ResolvedRuntimeProfile
    values: Mapping[str, object | tuple[object, ...]]


@dataclass(frozen=True)
class _BoundRuntimeCapability:
    resolved: ResolvedRuntimeSelection
    implementation: RuntimeCapabilityImplementation
    value: object


class RuntimeProfileBinding:
    """Own one live profile and its generation-scoped read leases."""

    def __init__(
        self,
        *,
        profile: ResolvedRuntimeProfile,
        context: object | None,
        state: RuntimeBindingState[RuntimeProfileBindings],
        bound: Mapping[str, tuple[_BoundRuntimeCapability, ...]],
    ) -> None:
        self._profile = profile
        self._context = context
        self._state = state
        self._bound = dict(bound)
        self._closed = False
        self._dispose_task: (
            asyncio.Task[tuple[RuntimeCapabilityBindingError, ...]] | None
        ) = None

    @property
    def profile(self) -> ResolvedRuntimeProfile:
        return self._profile

    @property
    def is_closed(self) -> bool:
        return self._closed

    def capture(self) -> RuntimeBindingLease[RuntimeProfileBindings]:
        self._require_open()
        return self._state.capture()

    def value(self, slot: str) -> object | tuple[object, ...]:
        self._require_open()
        values = self._state.require().values
        try:
            return values[slot]
        except KeyError as exc:
            raise KeyError(f"runtime capability is not bound: {slot}") from exc

    def values(self) -> Mapping[str, object | tuple[object, ...]]:
        self._require_open()
        return self._state.require().values

    def _replace(
        self,
        *,
        profile: ResolvedRuntimeProfile,
        bound: Mapping[str, tuple[_BoundRuntimeCapability, ...]],
    ) -> None:
        self._profile = profile
        self._bound = dict(bound)
        self._state.refresh(_live_bindings(profile, self._bound))
        self._state.invalidate("runtime profile binding was refreshed")

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("runtime profile binding is closed")


class RuntimeProfileBinder:
    """Create, refresh, and dispose instances from an already-resolved profile."""

    def __init__(self, registry: RuntimeCapabilityRegistry) -> None:
        self._registry = registry

    async def bind(
        self,
        profile: ResolvedRuntimeProfile,
        *,
        context: object | None = None,
    ) -> RuntimeProfileBinding:
        bound = await self._create_profile(profile, context=context)
        state = RuntimeBindingState[RuntimeProfileBindings](
            unbound_message="runtime profile binding has not been initialized",
            stale_message="runtime profile binding was refreshed",
        )
        state.bind(_live_bindings(profile, bound))
        return RuntimeProfileBinding(
            profile=profile,
            context=context,
            state=state,
            bound=bound,
        )

    def bind_sync(
        self,
        profile: ResolvedRuntimeProfile,
        *,
        context: object | None = None,
    ) -> RuntimeProfileBinding:
        """Bind only synchronous factories without creating an event loop.

        Product bootstrap is often synchronous.  It may use this narrow path
        for pure factories, while factories that perform I/O or other async
        work must continue through :meth:`bind`.
        """

        bound = self._create_profile_sync(profile, context=context)
        state = RuntimeBindingState[RuntimeProfileBindings](
            unbound_message="runtime profile binding has not been initialized",
            stale_message="runtime profile binding was refreshed",
        )
        state.bind(_live_bindings(profile, bound))
        return RuntimeProfileBinding(
            profile=profile,
            context=context,
            state=state,
            bound=bound,
        )

    async def rebind(
        self,
        binding: RuntimeProfileBinding,
        profile: ResolvedRuntimeProfile,
        *,
        boundary: Literal["turn"] = "turn",
    ) -> None:
        if boundary != "turn":
            raise ValueError(
                "runtime profile rebind is only supported at a turn boundary"
            )
        binding._require_open()
        if binding.profile.product_id != profile.product_id:
            raise ValueError("a binding cannot change Product runtime plans")

        previous = {
            capability.slot.key: capability
            for capability in binding.profile.capabilities
        }
        target = {
            capability.slot.key: capability for capability in profile.capabilities
        }
        changed_keys = tuple(
            key
            for key in sorted(set(previous) | set(target))
            if _capability_signature(previous.get(key))
            != _capability_signature(target.get(key))
        )
        if not changed_keys:
            return
        for key in changed_keys:
            capability = target.get(key) or previous[key]
            if capability.slot.refresh_boundary == "sealed":
                raise SealedRuntimeCapabilityError(key)

        replacements: dict[str, tuple[_BoundRuntimeCapability, ...]] = {}
        created: list[_BoundRuntimeCapability] = []
        try:
            for capability in profile.capabilities:
                if capability.slot.key not in changed_keys:
                    continue
                entries = await self._create_capability(
                    capability, context=binding._context
                )
                replacements[capability.slot.key] = entries
                created.extend(entries)
        except asyncio.CancelledError as exc:
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=binding._context,
            )
            _annotate_cleanup_errors(exc, errors)
            raise
        except Exception as exc:
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=binding._context,
            )
            _annotate_cleanup_errors(exc, errors)
            raise

        retired = tuple(
            entry
            for key, entries in binding._bound.items()
            if key in changed_keys
            for entry in entries
        )
        updated = dict(binding._bound)
        for key in changed_keys:
            updated.pop(key, None)
        updated.update(replacements)
        try:
            binding._require_open()
        except RuntimeError as exc:
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=binding._context,
            )
            _annotate_cleanup_errors(exc, errors)
            raise
        binding._replace(profile=profile, bound=updated)
        errors = await self._dispose_entries_cancellation_atomic(
            retired,
            context=binding._context,
        )
        _raise_disposal_errors(
            errors,
            note="replacement generation was published before retirement failed",
        )

    async def dispose(self, binding: RuntimeProfileBinding) -> None:
        task = binding._dispose_task
        if task is not None and task.done():
            return
        if task is None:
            if binding._closed:
                return
            entries = tuple(
                entry for bound in binding._bound.values() for entry in bound
            )
            binding._closed = True
            binding._state.invalidate("runtime profile binding was disposed")
            task = asyncio.create_task(
                self._dispose_entries_collecting(
                    entries,
                    context=binding._context,
                )
            )
            binding._dispose_task = task
        errors = await self._await_disposal_task(task)
        _raise_disposal_errors(errors)

    def dispose_sync(self, binding: RuntimeProfileBinding) -> None:
        """Dispose a binding created from synchronous factories."""

        task = binding._dispose_task
        if task is not None and task.done():
            return
        if task is not None:
            raise RuntimeError(
                "runtime profile binding disposal is already asynchronous"
            )
        if binding._closed:
            return
        entries = tuple(entry for bound in binding._bound.values() for entry in bound)
        binding._closed = True
        binding._state.invalidate("runtime profile binding was disposed")
        errors = self._dispose_entries_collecting_sync(
            entries,
            context=binding._context,
        )
        _raise_disposal_errors(errors)

    def _create_profile_sync(
        self,
        profile: ResolvedRuntimeProfile,
        *,
        context: object | None,
    ) -> dict[str, tuple[_BoundRuntimeCapability, ...]]:
        bound: dict[str, tuple[_BoundRuntimeCapability, ...]] = {}
        created: list[_BoundRuntimeCapability] = []
        try:
            for capability in profile.capabilities:
                entries = self._create_capability_sync(capability, context=context)
                if entries:
                    bound[capability.slot.key] = entries
                    created.extend(entries)
        except asyncio.CancelledError as exc:
            errors = self._dispose_entries_collecting_sync(created, context=context)
            _annotate_cleanup_errors(exc, errors)
            raise
        except Exception as exc:
            errors = self._dispose_entries_collecting_sync(created, context=context)
            _annotate_cleanup_errors(exc, errors)
            raise
        return bound

    def _create_capability_sync(
        self,
        capability: ResolvedRuntimeCapability,
        *,
        context: object | None,
    ) -> tuple[_BoundRuntimeCapability, ...]:
        created: list[_BoundRuntimeCapability] = []
        try:
            for resolved in capability.selections:
                implementation = self._registry.resolve(resolved.selection)
                value = _require_sync_result(
                    implementation.create(resolved.selection, context),
                    slot=resolved.selection.slot,
                    implementation=resolved.selection.implementation,
                    implementation_version=resolved.selection.implementation_version,
                    action="factory",
                )
                created.append(
                    _BoundRuntimeCapability(
                        resolved=resolved,
                        implementation=implementation,
                        value=value,
                    )
                )
        except asyncio.CancelledError as exc:
            errors = self._dispose_entries_collecting_sync(created, context=context)
            _annotate_cleanup_errors(exc, errors)
            raise
        except RuntimeCapabilityBindingError as exc:
            errors = self._dispose_entries_collecting_sync(created, context=context)
            _annotate_cleanup_errors(exc, errors)
            raise
        except Exception as exc:
            selection = capability.selections[len(created)].selection
            error = RuntimeCapabilityBindingError(
                "capability factory failed",
                slot=selection.slot,
                implementation=selection.implementation,
                implementation_version=selection.implementation_version,
            )
            errors = self._dispose_entries_collecting_sync(created, context=context)
            _annotate_cleanup_errors(error, errors)
            raise error from exc
        return tuple(created)

    async def _create_profile(
        self,
        profile: ResolvedRuntimeProfile,
        *,
        context: object | None,
    ) -> dict[str, tuple[_BoundRuntimeCapability, ...]]:
        bound: dict[str, tuple[_BoundRuntimeCapability, ...]] = {}
        created: list[_BoundRuntimeCapability] = []
        try:
            for capability in profile.capabilities:
                entries = await self._create_capability(capability, context=context)
                if entries:
                    bound[capability.slot.key] = entries
                    created.extend(entries)
        except asyncio.CancelledError as exc:
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=context,
            )
            _annotate_cleanup_errors(exc, errors)
            raise
        except Exception as exc:
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=context,
            )
            _annotate_cleanup_errors(exc, errors)
            raise
        return bound

    async def _create_capability(
        self,
        capability: ResolvedRuntimeCapability,
        *,
        context: object | None,
    ) -> tuple[_BoundRuntimeCapability, ...]:
        created: list[_BoundRuntimeCapability] = []
        try:
            for resolved in capability.selections:
                implementation = self._registry.resolve(resolved.selection)
                value = await _await_result(
                    implementation.create(resolved.selection, context)
                )
                created.append(
                    _BoundRuntimeCapability(
                        resolved=resolved,
                        implementation=implementation,
                        value=value,
                    )
                )
        except asyncio.CancelledError as exc:
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=context,
            )
            _annotate_cleanup_errors(exc, errors)
            raise
        except RuntimeCapabilityBindingError as exc:
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=context,
            )
            _annotate_cleanup_errors(exc, errors)
            raise
        except Exception as exc:
            selection = capability.selections[len(created)].selection
            error = RuntimeCapabilityBindingError(
                "capability factory failed",
                slot=selection.slot,
                implementation=selection.implementation,
                implementation_version=selection.implementation_version,
            )
            errors = await self._dispose_entries_cancellation_atomic(
                created,
                context=context,
            )
            _annotate_cleanup_errors(error, errors)
            raise error from exc
        return tuple(created)

    async def _dispose_entries_cancellation_atomic(
        self,
        entries: Iterable[_BoundRuntimeCapability],
        *,
        context: object | None,
    ) -> tuple[RuntimeCapabilityBindingError, ...]:
        task = asyncio.create_task(
            self._dispose_entries_collecting(entries, context=context)
        )
        return await self._await_disposal_task(task)

    async def _await_disposal_task(
        self,
        task: asyncio.Task[tuple[RuntimeCapabilityBindingError, ...]],
    ) -> tuple[RuntimeCapabilityBindingError, ...]:
        try:
            return await _await_cancellation_atomic(task)
        except asyncio.CancelledError as exc:
            _annotate_cleanup_errors(exc, task.result())
            raise

    async def _dispose_entries_collecting(
        self,
        entries: Iterable[_BoundRuntimeCapability],
        *,
        context: object | None,
    ) -> tuple[RuntimeCapabilityBindingError, ...]:
        errors: list[RuntimeCapabilityBindingError] = []
        for entry in reversed(tuple(entries)):
            if entry.implementation.dispose is None:
                continue
            try:
                await _await_result(entry.implementation.dispose(entry.value, context))
                # Attribute cancellation requested synchronously by this
                # disposer to this entry before advancing to the next one.
                await asyncio.sleep(0)
            except asyncio.CancelledError as exc:
                errors.append(_disposal_error(entry, cause=exc))
            except Exception as exc:
                errors.append(_disposal_error(entry, cause=exc))
        return tuple(errors)

    def _dispose_entries_collecting_sync(
        self,
        entries: Iterable[_BoundRuntimeCapability],
        *,
        context: object | None,
    ) -> tuple[RuntimeCapabilityBindingError, ...]:
        errors: list[RuntimeCapabilityBindingError] = []
        for entry in reversed(tuple(entries)):
            if entry.implementation.dispose is None:
                continue
            try:
                _require_sync_result(
                    entry.implementation.dispose(entry.value, context),
                    slot=entry.resolved.selection.slot,
                    implementation=entry.resolved.selection.implementation,
                    implementation_version=entry.resolved.selection.implementation_version,
                    action="disposer",
                )
            except RuntimeCapabilityBindingError as exc:
                errors.append(exc)
            except Exception as exc:
                errors.append(_disposal_error(entry, cause=exc))
        return tuple(errors)


def _disposal_error(
    entry: _BoundRuntimeCapability,
    *,
    cause: BaseException,
) -> RuntimeCapabilityBindingError:
    error = RuntimeCapabilityBindingError(
        "capability disposer failed",
        slot=entry.resolved.selection.slot,
        implementation=entry.resolved.selection.implementation,
        implementation_version=entry.resolved.selection.implementation_version,
    )
    error.__cause__ = cause
    return error


def _annotate_cleanup_errors(
    primary: BaseException,
    errors: Iterable[RuntimeCapabilityBindingError],
) -> None:
    for error in errors:
        primary.add_note(f"rollback cleanup also failed: {error}")


def _raise_disposal_errors(
    errors: tuple[RuntimeCapabilityBindingError, ...],
    *,
    note: str | None = None,
) -> None:
    if not errors:
        return
    first = errors[0]
    if note is not None:
        first.add_note(note)
    for additional in errors[1:]:
        first.add_note(f"additional disposal failure: {additional}")
    raise first


async def _await_result(value: object | Awaitable[object]) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _require_sync_result(
    value: object | Awaitable[object],
    *,
    slot: str,
    implementation: str,
    implementation_version: int,
    action: str,
) -> object:
    if not inspect.isawaitable(value):
        return value
    if inspect.iscoroutine(value):
        value.close()
    raise RuntimeCapabilityBindingError(
        f"synchronous binding cannot await a capability {action}",
        slot=slot,
        implementation=implementation,
        implementation_version=implementation_version,
    )


def _capability_signature(
    capability: ResolvedRuntimeCapability | None,
) -> tuple[object, ...] | None:
    if capability is None:
        return None
    return (
        capability.slot,
        tuple(
            (
                resolved.selection.implementation,
                resolved.selection.implementation_version,
                dump_json_value(
                    resolved.selection.config,
                    name="resolved selection config",
                    sort_keys=True,
                ),
                resolved.source,
                resolved.layer_id,
                resolved.layer_priority,
                resolved.selection.priority,
            )
            for resolved in capability.selections
        ),
    )


def _live_bindings(
    profile: ResolvedRuntimeProfile,
    bound: Mapping[str, tuple[_BoundRuntimeCapability, ...]],
) -> RuntimeProfileBindings:
    values: dict[str, object | tuple[object, ...]] = {}
    for capability in profile.capabilities:
        entries = bound.get(capability.slot.key, ())
        if not entries:
            continue
        if capability.slot.shape in {"single", "exclusive"}:
            values[capability.slot.key] = entries[0].value
        else:
            values[capability.slot.key] = tuple(entry.value for entry in entries)
    return RuntimeProfileBindings(profile=profile, values=values)


# Initial shared vocabulary.  These identifiers are neutral contracts, not
# imports of a particular store, transcript, or compaction implementation.
