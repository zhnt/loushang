"""Transport-neutral client contract for the G11 hosted application."""

from __future__ import annotations

from typing import Protocol

from .protocol import (
    AckV1,
    AttachmentEventV1,
    InteractionRespondV1,
    MuxAttachmentV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxListResultV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSpaceV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TurnInterruptV1,
    TurnTextV1,
)


class AppClientV1(Protocol):
    """Semantic client API shared by in-process and future transports."""

    async def create_mux(self, request: MuxCreateV1) -> MuxSpaceV1: ...

    async def list_muxes(self) -> MuxListResultV1: ...

    async def read_mux(self, request: MuxReadV1) -> MuxSpaceV1: ...

    async def attach_mux(self, request: MuxAttachV1) -> MuxAttachmentV1: ...

    async def detach_mux(self, request: MuxDetachV1) -> AckV1: ...

    async def close_mux(self, request: MuxCloseV1) -> AckV1: ...

    async def open_member(self, request: MuxMemberOpenV1) -> MuxSpaceV1: ...

    async def close_member(self, request: MuxMemberCloseV1) -> MuxSpaceV1: ...

    async def snapshot_session(
        self, request: SessionSnapshotRequestV1
    ) -> SessionSnapshotV1: ...

    async def start_turn(self, request: TurnTextV1) -> AckV1: ...

    async def steer_turn(self, request: TurnTextV1) -> AckV1: ...

    async def follow_up_turn(self, request: TurnTextV1) -> AckV1: ...

    async def interrupt_turn(self, request: TurnInterruptV1) -> AckV1: ...

    async def respond_interaction(self, request: InteractionRespondV1) -> AckV1: ...

    async def read_events(
        self,
        *,
        attachment_id: str,
        controller_generation: int,
        limit: int = 64,
    ) -> tuple[AttachmentEventV1, ...]: ...


__all__ = ["AppClientV1"]
