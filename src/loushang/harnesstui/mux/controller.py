"""Hosted Mux controller over an injected transport-neutral AppClient."""

from __future__ import annotations

from loushang.appserver.client import AppClientV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxDetachV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    TurnInterruptV1,
    TurnTextV1,
)

from .model import HarnessWindowState, HostedMuxState
from .reducer import reduce_events, set_active_draft, state_from_attachment


class HostedMuxControllerV1:
    """Coordinate explicit hosted actions; local window actions stay local."""

    __slots__ = ("_client", "_mailbox_capacity", "_selector", "state")

    def __init__(
        self,
        client: AppClientV1,
        *,
        selector: MuxSelectorV1,
        mailbox_capacity: int = 256,
    ) -> None:
        for method in (
            "attach_mux",
            "detach_mux",
            "open_member",
            "close_member",
            "start_turn",
            "steer_turn",
            "follow_up_turn",
            "interrupt_turn",
            "respond_interaction",
            "read_events",
        ):
            if not callable(getattr(client, method, None)):
                raise TypeError("client does not implement AppClientV1")
        self._client = client
        self._selector = selector
        self._mailbox_capacity = mailbox_capacity
        self.state: HostedMuxState | None = None

    async def start(self) -> HostedMuxState:
        if self.state is not None:
            raise RuntimeError("hosted mux controller is already started")
        attachment = await self._client.attach_mux(
            MuxAttachV1(self._selector, self._mailbox_capacity)
        )
        self.state = state_from_attachment(attachment)
        return self.state

    async def poll(self) -> HostedMuxState:
        state = self._require_state()
        try:
            events = await self._client.read_events(
                attachment_id=state.attachment_id,
                controller_generation=state.controller_generation,
            )
        except AppServiceError as error:
            if error.code not in {
                AppErrorCodeV1.ATTACHMENT_LAGGED,
                AppErrorCodeV1.STALE_ATTACHMENT,
            }:
                raise
            state.snapshot_required = True
            state.status_message = "snapshot_required"
            return state
        reduce_events(state, events)
        return state

    async def refresh_snapshot(self) -> HostedMuxState:
        state = self._require_state()
        try:
            await self._client.detach_mux(
                MuxDetachV1(
                    state.attachment_id,
                    state.controller_generation,
                )
            )
        except AppServiceError as error:
            if error.code is not AppErrorCodeV1.STALE_ATTACHMENT:
                raise
        self.state = None
        return await self.start()

    async def open_member(self, request: SessionOpenSpecV1) -> HostedMuxState:
        self._require_state()
        await self._client.open_member(MuxMemberOpenV1(self._selector, request))
        return await self._reattach_after_membership_change()

    async def close_active_member(self, *, close_session: bool = True) -> HostedMuxState:
        state = self._require_state()
        window = state.active_window
        if window is None:
            raise RuntimeError("hosted mux has no active window")
        await self._client.close_member(
            MuxMemberCloseV1(
                self._selector,
                window.member_id,
                close_session=close_session,
            )
        )
        return await self._reattach_after_membership_change()

    async def submit(self, text: str | None = None) -> None:
        state, window = self._active()
        selected = window.draft if text is None else text
        request = TurnTextV1(
            state.attachment_id,
            state.controller_generation,
            window.member_id,
            selected,
        )
        await self._client.start_turn(request)
        set_active_draft(state, "")

    async def steer(self, text: str) -> None:
        state, window = self._active()
        await self._client.steer_turn(
            TurnTextV1(
                state.attachment_id,
                state.controller_generation,
                window.member_id,
                text,
            )
        )

    async def follow_up(self, text: str) -> None:
        state, window = self._active()
        await self._client.follow_up_turn(
            TurnTextV1(
                state.attachment_id,
                state.controller_generation,
                window.member_id,
                text,
            )
        )

    async def interrupt(self) -> None:
        state, window = self._active()
        await self._client.interrupt_turn(
            TurnInterruptV1(
                state.attachment_id,
                state.controller_generation,
                window.member_id,
            )
        )

    async def respond_interaction(
        self,
        interaction_id: str,
        outcome: InteractionOutcomeV1,
    ) -> None:
        state, window = self._active()
        await self._client.respond_interaction(
            InteractionRespondV1(
                state.attachment_id,
                state.controller_generation,
                window.member_id,
                interaction_id,
                outcome,
            )
        )

    async def close(self) -> None:
        state = self.state
        if state is None:
            return
        try:
            await self._client.detach_mux(
                MuxDetachV1(state.attachment_id, state.controller_generation)
            )
        except AppServiceError as error:
            if error.code is not AppErrorCodeV1.STALE_ATTACHMENT:
                raise
        self.state = None

    async def _reattach_after_membership_change(self) -> HostedMuxState:
        self.state = None
        return await self.start()

    def _require_state(self) -> HostedMuxState:
        if self.state is None:
            raise RuntimeError("hosted mux controller is not started")
        return self.state

    def _active(self) -> tuple[HostedMuxState, HarnessWindowState]:
        state = self._require_state()
        window = state.active_window
        if window is None:
            raise RuntimeError("hosted mux has no active window")
        return state, window


__all__ = ["HostedMuxControllerV1"]
