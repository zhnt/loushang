"""Registration ownership for one admitted Extension generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TypeVar

from loushang.harness.runtime.registration import (
    RegistrationIdentity,
    RegistrationLease,
    RegistrationLeaseState,
    RegistrationOwner,
    RegistrationScope,
    RegistrationScopeDisposalResult,
)

T = TypeVar("T")


@dataclass(frozen=True)
class ExtensionGenerationDisposalResult:
    """Reverse-ordered cleanup reports for one Extension generation."""

    scopes: tuple[RegistrationScopeDisposalResult, ...]

    @property
    def has_failures(self) -> bool:
        return any(scope.has_failures for scope in self.scopes)


class ExtensionGenerationRegistrations:
    """Collect setup and post-publication leases for one Extension owner.

    The setup scope gives admission one rollback transaction. Once published,
    each later live mutation receives a committed one-lease scope so unload can
    still retire every contribution in exact reverse registration order.
    """

    def __init__(self, owner: RegistrationOwner) -> None:
        self._owner = owner
        self._setup = RegistrationScope(owner)
        self._late: list[RegistrationScope] = []
        self._published = False
        self._dispose_task: asyncio.Task[ExtensionGenerationDisposalResult] | None = (
            None
        )
        self._last_result: ExtensionGenerationDisposalResult | None = None

    @property
    def owner(self) -> RegistrationOwner:
        return self._owner

    @property
    def is_published(self) -> bool:
        return self._published

    @property
    def inventory(
        self,
    ) -> tuple[
        tuple[RegistrationOwner, RegistrationIdentity, RegistrationLeaseState], ...
    ]:
        scopes = (self._setup, *self._late)
        return tuple(item for scope in scopes for item in scope.inventory)

    def capture(self, lease: RegistrationLease) -> RegistrationLease:
        if self._dispose_task is not None or self._last_result is not None:
            raise RuntimeError("Extension generation registrations are retiring")
        if lease.owner != self._owner:
            raise ValueError("registration lease owner does not match Extension owner")
        if not self._published:
            return self._setup.add(lease)
        scope = RegistrationScope(self._owner)
        scope.add(lease)
        scope.commit()
        self._late.append(scope)
        return lease

    def commit(self) -> None:
        if self._published:
            return
        self._setup.commit()
        self._published = True

    def rollback_publication(self) -> None:
        if not self._published:
            return
        self._setup.rollback_commit()
        self._published = False

    def rollback_admission(self) -> RegistrationScopeDisposalResult:
        """Discard setup mutations after synchronous initial admission fails."""

        if self._published:
            raise RuntimeError("published Extension admission cannot be rolled back")
        report = self._setup.rollback_admission()
        if not report.has_failures:
            self._setup = RegistrationScope(self._owner)
        return report

    async def dispose(self) -> ExtensionGenerationDisposalResult:
        if self._last_result is not None and not self._last_result.has_failures:
            return self._last_result
        task = self._dispose_task
        if task is None:
            task = asyncio.create_task(self._dispose_all())
            self._dispose_task = task
        return await _join_cleanup(task)

    async def _dispose_all(self) -> ExtensionGenerationDisposalResult:
        reports: list[RegistrationScopeDisposalResult] = []
        for scope in reversed((self._setup, *self._late)):
            reports.append(await scope.dispose())
        result = ExtensionGenerationDisposalResult(scopes=tuple(reports))
        self._last_result = result
        self._dispose_task = None
        return result


async def dispose_extension_generation_registrations(
    registrations: tuple[ExtensionGenerationRegistrations, ...],
) -> tuple[ExtensionGenerationDisposalResult, ...]:
    """Retire Extension owners in reverse admission order without skipped cleanup."""

    async def dispose_all() -> tuple[ExtensionGenerationDisposalResult, ...]:
        reports: list[ExtensionGenerationDisposalResult] = []
        for registration in reversed(registrations):
            reports.append(await registration.dispose())
        return tuple(reports)

    return await _join_cleanup(asyncio.create_task(dispose_all()))


async def _join_cleanup(task: asyncio.Task[T]) -> T:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = exc
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


__all__ = [
    "ExtensionGenerationDisposalResult",
    "ExtensionGenerationRegistrations",
    "dispose_extension_generation_registrations",
]
