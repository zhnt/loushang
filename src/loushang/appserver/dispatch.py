"""Exhaustive typed dispatch onto an injected application service port."""

from __future__ import annotations

from typing import cast

from .client import AppServicePortV1, SessionDiscoveryPortV1
from .protocol import (
    AppErrorCodeV1,
    AppOperationV1,
    AppRequestV1,
    AppResultPayloadV1,
    AppServiceError,
    AttachmentEventsV1,
    AttachmentReadEventsV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    SessionListV1,
    SessionModelSelectV1,
    SessionSnapshotRequestV1,
    TurnInterruptV1,
    TurnTextV1,
)


async def dispatch_request(
    client: AppServicePortV1, request: AppRequestV1,
    *, discovery: SessionDiscoveryPortV1 | None = None,
) -> AppResultPayloadV1:
    service_port = client
    value = request.payload
    match request.operation:
        case AppOperationV1.MUX_CREATE:
            return await service_port.create_mux(cast(MuxCreateV1, value))
        case AppOperationV1.MUX_LIST:
            return await service_port.list_muxes()
        case AppOperationV1.SESSIONS_LIST:
            if discovery is None:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            return await discovery.list_sessions(cast(SessionListV1, value))
        case AppOperationV1.MUX_READ:
            return await service_port.read_mux(cast(MuxReadV1, value))
        case AppOperationV1.MUX_ATTACH:
            return await service_port.attach_mux(cast(MuxAttachV1, value))
        case AppOperationV1.MUX_DETACH:
            return await service_port.detach_mux(cast(MuxDetachV1, value))
        case AppOperationV1.MUX_CLOSE:
            return await service_port.close_mux(cast(MuxCloseV1, value))
        case AppOperationV1.MEMBER_OPEN:
            return await service_port.open_member(cast(MuxMemberOpenV1, value))
        case AppOperationV1.MEMBER_CLOSE:
            return await service_port.close_member(cast(MuxMemberCloseV1, value))
        case AppOperationV1.SESSION_SNAPSHOT:
            return await service_port.snapshot_session(cast(SessionSnapshotRequestV1, value))
        case AppOperationV1.SESSION_MODELS:
            return await service_port.list_session_models(cast(SessionSnapshotRequestV1, value))
        case AppOperationV1.SESSION_MODEL_SELECT:
            return await service_port.select_session_model(cast(SessionModelSelectV1, value))
        case AppOperationV1.TURN_START:
            return await service_port.start_turn(cast(TurnTextV1, value))
        case AppOperationV1.TURN_STEER:
            return await service_port.steer_turn(cast(TurnTextV1, value))
        case AppOperationV1.TURN_FOLLOW_UP:
            return await service_port.follow_up_turn(cast(TurnTextV1, value))
        case AppOperationV1.TURN_INTERRUPT:
            return await service_port.interrupt_turn(cast(TurnInterruptV1, value))
        case AppOperationV1.INTERACTION_RESPOND:
            return await service_port.respond_interaction(cast(InteractionRespondV1, value))
        case AppOperationV1.ATTACHMENT_READ_EVENTS:
            poll = cast(AttachmentReadEventsV1, value)
            # One event per frame avoids multiplying maximum-sized event values.
            return AttachmentEventsV1(
                await service_port.read_events(
                    attachment_id=poll.attachment_id,
                    controller_generation=poll.controller_generation,
                    limit=1,
                )
            )
    raise AssertionError("unhandled app operation")
