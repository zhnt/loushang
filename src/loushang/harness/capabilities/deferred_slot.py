"""Session-owned activation slot for a separately sealed Capability generation.

The declaration is inert. A Product supplies fresh selection and admission in
``prepare`` when an explicit caller first activates the slot. The prepared
generation owns its private graph and any staged registrations; publication is
synchronous so the generation and its public tools appear in one event-loop turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar, cast, runtime_checkable

from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic

DeferredSlotState = Literal[
    "dormant", "activating", "active", "failed", "closing", "closed"
]


@runtime_checkable
class PreparedDeferredCapability(Protocol):
    """One owned candidate, including rollback after partial preparation."""

    async def prepare(self) -> None: ...

    def publish(self) -> None: ...

    async def dispose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DeferredCapabilityDeclaration:
    capability_id: str
    facet_ids: tuple[str, ...]
    tool_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("deferred Capability id must be nonempty")
        for label, names in (
            ("facet", self.facet_ids),
            ("tool", self.tool_names),
        ):
            if (
                not isinstance(names, tuple)
                or not names
                or any(not isinstance(name, str) or not name.strip() for name in names)
                or len(set(names)) != len(names)
            ):
                raise ValueError(f"deferred Capability {label} identities are invalid")


CandidateT = TypeVar("CandidateT", bound=PreparedDeferredCapability)


class DeferredCapabilitySlot(Generic[CandidateT]):
    """Single-flight activation with a Session-owned close and retry boundary.

    ``create`` must only allocate an inert candidate. The slot retains it
    before the first preparation await, so failed cleanup remains retryable.
    Cancelling a caller never cancels the activation task. Closing waits for
    preparation to settle, skips publication if it has not happened, and
    disposes the candidate. A failed publication must be fully disposed before
    an explicit retry is accepted.
    """

    def __init__(
        self,
        declaration: DeferredCapabilityDeclaration,
        create: Callable[[], CandidateT],
    ) -> None:
        if not isinstance(declaration, DeferredCapabilityDeclaration):
            raise TypeError("deferred slot requires a Capability declaration")
        if not callable(create):
            raise TypeError("deferred slot requires an inert candidate factory")
        self.declaration = declaration
        self._create = create
        self._state: DeferredSlotState = "dormant"
        self._candidate: CandidateT | None = None
        self._activation_task: asyncio.Task[CandidateT] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None

    @property
    def state(self) -> DeferredSlotState:
        return self._state

    @property
    def active(self) -> CandidateT | None:
        return self._candidate if self._state == "active" else None

    async def activate(self, *, retry: bool = False) -> CandidateT:
        if self._state == "active":
            return cast(CandidateT, self._candidate)
        if self._state in {"closing", "closed"}:
            raise RuntimeError("deferred Capability slot is closing")
        if self._state == "failed":
            if not retry:
                raise RuntimeError("deferred Capability activation failed") from self._failure
            if self._candidate is not None:
                raise RuntimeError("deferred Capability cleanup is pending")
        task = self._activation_task
        if self._state != "activating":
            self._state = "activating"
            self._failure = None
            task = asyncio.create_task(self._activate_once())
            self._activation_task = task
        assert task is not None
        return await asyncio.shield(task)

    async def _activate_once(self) -> CandidateT:
        try:
            candidate = self._create()
            if not isinstance(candidate, PreparedDeferredCapability):
                raise TypeError("deferred factory returned an invalid candidate")
            self._candidate = candidate
            await candidate.prepare()
            if self._state == "closing":
                raise RuntimeError("deferred Capability slot closed during preparation")
            candidate.publish()
            self._state = "active"
            return candidate
        except BaseException as error:
            cleanup_candidate = self._candidate
            if cleanup_candidate is not None:
                try:
                    await cleanup_candidate.dispose()
                except BaseException as cleanup_error:
                    error.add_note(
                        "deferred Capability rollback remains pending: "
                        f"{cleanup_error!r}"
                    )
                else:
                    self._candidate = None
            if self._state != "closing":
                self._state = "failed"
                self._failure = error
            raise

    async def close(self) -> None:
        if self._state == "closed":
            return
        self._state = "closing"
        task = self._close_task
        if task is None or task.done():
            task = asyncio.create_task(self._close_once())
            self._close_task = task
        await _await_cancellation_atomic(task)

    async def _close_once(self) -> None:
        activation = self._activation_task
        if activation is not None:
            try:
                with suppress(Exception):
                    await asyncio.shield(activation)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
        candidate = self._candidate
        if candidate is not None:
            await candidate.dispose()
            self._candidate = None
        self._state = "closed"


__all__ = [
    "DeferredCapabilityDeclaration",
    "DeferredCapabilitySlot",
    "DeferredSlotState",
    "PreparedDeferredCapability",
]
