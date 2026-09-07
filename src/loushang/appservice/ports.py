"""Injected Product Session ports consumed by the G11 AppService."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from loushang.appserver.protocol import (
    InteractionOutcomeV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionSnapshotV1,
)

HostedSessionEventListenerV1 = Callable[
    [SessionEventV1], Awaitable[None] | None
]


class HostedSessionPortV1(Protocol):
    """One independently owned, Product-adapted hosted Session."""

    @property
    def identity(self) -> SessionIdentityV1: ...

    async def snapshot(self) -> SessionSnapshotV1: ...

    def subscribe(
        self,
        listener: HostedSessionEventListenerV1,
    ) -> Callable[[], None]: ...

    async def start_turn(self, text: str) -> None: ...

    def steer_turn(self, text: str) -> None: ...

    def follow_up_turn(self, text: str) -> None: ...

    def interrupt_turn(self) -> bool: ...

    async def respond_interaction(
        self,
        interaction_id: str,
        outcome: InteractionOutcomeV1,
    ) -> bool: ...

    async def close(self) -> None: ...


class HostedSessionResolverV1(Protocol):
    """Product-owned create/resume resolver returning one owned Session."""

    async def open_session(self, request: SessionOpenSpecV1) -> HostedSessionPortV1: ...


__all__ = [
    "HostedSessionEventListenerV1",
    "HostedSessionPortV1",
    "HostedSessionResolverV1",
]
