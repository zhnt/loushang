"""Hosted adapter for the shared conversation action port; no task owner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from loushang.appserver.client import AppClientV1
from loushang.appserver.protocol import AckV1, TurnInterruptV1, TurnTextV1

from ..conversation.control import ConversationActionHost, ConversationTextAction
from ..conversation.request_presentation import (
    ConversationRequestPresentation,
    RequestDeliveryState,
)
from ._shell_tasks import ShellActions
from .model import HarnessWindowState, HostedMuxState

ConversationMode = Literal["start", "steer", "followup", "interrupt"]


class HostedConversationActionBinding:
    """Borrow one exact target captured by the outer attachment owner.

    Implements ConversationActionHost; the shell keeps its original bounded
    action tasks. Report only delivery, never infer execution from Ack or idle.
    The callback must reject results for a replaced target or newer request.
    """

    def __init__(self, client: AppClientV1, *, attachment_id: str, generation: int,
                 member_id: str, present: Callable[[RequestDeliveryState], None]) -> None:
        self._client = client
        self._attachment_id, self._generation, self._member_id = attachment_id, generation, member_id
        self._present = present
        self._interrupt = TurnInterruptV1(attachment_id, generation, member_id)

    async def _request(self, operation: Callable[[], Awaitable[AckV1]]) -> None:
        try:
            result = await operation()
            if type(result) is not AckV1:
                raise ValueError("invalid request acknowledgement")
        except asyncio.CancelledError:
            self._present("unknown")
            raise
        except Exception:
            # Do not forward unscoped errors to the shell's global callback:
            # even an old failure must respect the captured presentation key.
            self._present("unknown")
        else:
            self._present("acknowledged")

    def _text(self, action: ConversationTextAction) -> TurnTextV1:
        if action.attachments:
            raise ValueError("image_paste_unavailable")
        return TurnTextV1(self._attachment_id, self._generation, self._member_id, action.text)

    def validate_text(self, action: ConversationTextAction) -> None:
        """Reject unsupported/invalid input before the caller publishes a task."""
        self._text(action)

    async def submit(self, action: ConversationTextAction) -> int | None:
        request = self._text(action)
        await self._request(lambda: self._client.start_turn(request))
        return None

    async def steer(self, action: ConversationTextAction) -> int | None:
        request = self._text(action)
        await self._request(lambda: self._client.steer_turn(request))
        return None

    async def follow_up(self, action: ConversationTextAction) -> int | None:
        request = self._text(action)
        await self._request(lambda: self._client.follow_up_turn(request))
        return None

    async def abort(self) -> None:
        await self._request(lambda: self._client.interrupt_turn(self._interrupt))


def submit_hosted_conversation_action(
    client: AppClientV1, actions: ShellActions, state: HostedMuxState, window: HarnessWindowState,
    *, current: Callable[[], HostedMuxState | None], request_id: int, text: str, mode: ConversationMode,
) -> None:
    """Capture a view binding and borrow the shell's original action capacity."""
    attachment, generation = state.attachment_id, state.controller_generation
    member, session = window.member_id, window.session_id
    pending = ConversationRequestPresentation(
        "interrupt" if mode == "interrupt" else "submit" if mode == "start"
        else "steer" if mode == "steer" else "follow_up", "pending",
    )

    def present(delivery: RequestDeliveryState) -> None:
        active = current()
        if (active is None or active.snapshot_required or active.attachment_id != attachment
                or active.controller_generation != generation):
            return
        target = next((item for item in active.windows
                       if item.member_id == member and item.session_id == session), None)
        if target is not None and target.request_id == request_id:
            target.request_presentation = ConversationRequestPresentation(pending.operation, delivery)

    binding = HostedConversationActionBinding(client, attachment_id=attachment, generation=generation,
                                              member_id=member, present=present)
    port: ConversationActionHost = binding
    if mode == "interrupt":
        actions.submit(port.abort, control=True)
    else:
        action = ConversationTextAction(text)
        binding.validate_text(action)
        operation = {"start": port.submit, "steer": port.steer, "followup": port.follow_up}[mode]
        actions.submit(lambda: operation(action))
    # The original publication-gated task is now retained. Rejected validation
    # or capacity leaves the draft and previous presentation untouched.
    window.request_id, window.request_presentation = request_id, pending


__all__ = ["HostedConversationActionBinding", "submit_hosted_conversation_action"]
