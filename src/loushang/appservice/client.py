"""In-process AppClient adapter over one injected G11 AppService."""

from __future__ import annotations

from loushang.appserver.protocol import (
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

from .runtime import AppServiceV1


class InProcessAppClientV1:
    """Thin semantic adapter; it owns no serializer or service lifetime."""

    __slots__ = ("_service",)

    def __init__(self, service: AppServiceV1) -> None:
        if type(service) is not AppServiceV1:
            raise TypeError("service must be AppServiceV1")
        self._service = service

    async def create_mux(self, request: MuxCreateV1) -> MuxSpaceV1:
        return await self._service.create_mux(request)

    async def list_muxes(self) -> MuxListResultV1:
        return await self._service.list_muxes()

    async def read_mux(self, request: MuxReadV1) -> MuxSpaceV1:
        return await self._service.read_mux(request)

    async def attach_mux(self, request: MuxAttachV1) -> MuxAttachmentV1:
        return await self._service.attach_mux(request)

    async def detach_mux(self, request: MuxDetachV1) -> AckV1:
        return await self._service.detach_mux(request)

    async def close_mux(self, request: MuxCloseV1) -> AckV1:
        return await self._service.close_mux(request)

    async def open_member(self, request: MuxMemberOpenV1) -> MuxSpaceV1:
        return await self._service.open_member(request)

    async def close_member(self, request: MuxMemberCloseV1) -> MuxSpaceV1:
        return await self._service.close_member(request)

    async def snapshot_session(
        self,
        request: SessionSnapshotRequestV1,
    ) -> SessionSnapshotV1:
        return await self._service.snapshot_session(request)

    async def start_turn(self, request: TurnTextV1) -> AckV1:
        return await self._service.start_turn(request)

    async def steer_turn(self, request: TurnTextV1) -> AckV1:
        return await self._service.steer_turn(request)

    async def follow_up_turn(self, request: TurnTextV1) -> AckV1:
        return await self._service.follow_up_turn(request)

    async def interrupt_turn(self, request: TurnInterruptV1) -> AckV1:
        return await self._service.interrupt_turn(request)

    async def respond_interaction(self, request: InteractionRespondV1) -> AckV1:
        return await self._service.respond_interaction(request)

    async def read_events(
        self,
        *,
        attachment_id: str,
        controller_generation: int,
        limit: int = 64,
    ) -> tuple[AttachmentEventV1, ...]:
        return await self._service.read_events(
            attachment_id=attachment_id,
            controller_generation=controller_generation,
            limit=limit,
        )


__all__ = ["InProcessAppClientV1"]
