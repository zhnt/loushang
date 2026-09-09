"""Exhaustive typed dispatch onto an injected semantic AppClient."""

from __future__ import annotations

from typing import cast

from .client import AppClientV1, SessionDiscoveryClientV1
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
    SessionSnapshotRequestV1,
    TurnInterruptV1,
    TurnTextV1,
)


async def dispatch_request(
    client: AppClientV1, request: AppRequestV1,
    *, discovery: SessionDiscoveryClientV1 | None = None,
) -> AppResultPayloadV1:
    value = request.payload
    match request.operation:
        case AppOperationV1.MUX_CREATE:
            return await client.create_mux(cast(MuxCreateV1, value))
        case AppOperationV1.MUX_LIST:
            return await client.list_muxes()
        case AppOperationV1.SESSIONS_LIST:
            if discovery is None:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            return await discovery.list_sessions(cast(SessionListV1, value))
        case AppOperationV1.MUX_READ:
            return await client.read_mux(cast(MuxReadV1, value))
        case AppOperationV1.MUX_ATTACH:
            return await client.attach_mux(cast(MuxAttachV1, value))
        case AppOperationV1.MUX_DETACH:
            return await client.detach_mux(cast(MuxDetachV1, value))
        case AppOperationV1.MUX_CLOSE:
            return await client.close_mux(cast(MuxCloseV1, value))
        case AppOperationV1.MEMBER_OPEN:
            return await client.open_member(cast(MuxMemberOpenV1, value))
        case AppOperationV1.MEMBER_CLOSE:
            return await client.close_member(cast(MuxMemberCloseV1, value))
        case AppOperationV1.SESSION_SNAPSHOT:
            return await client.snapshot_session(cast(SessionSnapshotRequestV1, value))
        case AppOperationV1.TURN_START:
            return await client.start_turn(cast(TurnTextV1, value))
        case AppOperationV1.TURN_STEER:
            return await client.steer_turn(cast(TurnTextV1, value))
        case AppOperationV1.TURN_FOLLOW_UP:
            return await client.follow_up_turn(cast(TurnTextV1, value))
        case AppOperationV1.TURN_INTERRUPT:
            return await client.interrupt_turn(cast(TurnInterruptV1, value))
        case AppOperationV1.INTERACTION_RESPOND:
            return await client.respond_interaction(cast(InteractionRespondV1, value))
        case AppOperationV1.ATTACHMENT_READ_EVENTS:
            poll = cast(AttachmentReadEventsV1, value)
            # One event per frame avoids multiplying maximum-sized event values.
            return AttachmentEventsV1(
                await client.read_events(
                    attachment_id=poll.attachment_id,
                    controller_generation=poll.controller_generation,
                    limit=1,
                )
            )
    raise AssertionError("unhandled app operation")
