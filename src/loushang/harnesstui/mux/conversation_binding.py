"""Hosted adapter for the shared conversation action port; no task owner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from secrets import token_hex
from typing import Literal

from loushang.appserver.client import AppClientV1
from loushang.appserver.execution.client import ExecutionClientV1
from loushang.appserver.execution.recovery import (
    PendingSubmissionV1,
    SubmissionDeliveryV1,
    SubmissionRecoveryV1,
)
from loushang.appserver.protocol import (
    AckV1,
    AppErrorCodeV1,
    AppFailureV1,
    AppServiceError,
    SessionSnapshotRequestV1,
    SessionSubmissionModeV1,
    TurnInterruptV1,
    TurnTextV1,
)

from ..conversation.control import ConversationActionHost, ConversationTextAction
from ..conversation.request_presentation import (
    ConversationRequestPresentation,
    RequestDeliveryState,
)
from ._shell_tasks import ShellActions
from .model import HarnessWindowState, HostedMuxState

ConversationMode = Literal["start", "steer", "followup", "interrupt"]
ExecutionSubmissionKey = tuple[object, str]


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


class HostedExecutionSubmitBinding:
    """Submit one stable input through the optional execution profile."""

    def __init__(
        self, client: ExecutionClientV1, recovery: SubmissionRecoveryV1, *,
        control: SessionSnapshotRequestV1, present: Callable[[RequestDeliveryState], None],
        acknowledged: Callable[[], None],
    ) -> None:
        self._client, self._recovery = client, recovery
        self._control, self._present = control, present
        self._acknowledged = acknowledged

    async def submit(self) -> None:
        try:
            await self._recovery.submit(self._client, self._control)
            record = self._recovery.record
            if record is None:
                raise RuntimeError("execution submission has no record")
            outcome = record.state.outcome
            if outcome is not None and isinstance(outcome.legacy_result, AppFailureV1):
                raise AppServiceError(outcome.legacy_result.code)
        except asyncio.CancelledError:
            self._present("unknown")
            raise
        except Exception:
            self._present("unknown")
        else:
            self._present("acknowledged")
            self._acknowledged()


def submit_hosted_conversation_action(
    client: AppClientV1, actions: ShellActions, state: HostedMuxState, window: HarnessWindowState,
    *, current: Callable[[], HostedMuxState | None], request_id: int, text: str, mode: ConversationMode,
    execution_client: ExecutionClientV1 | None = None,
    execution_submissions: dict[ExecutionSubmissionKey, SubmissionRecoveryV1] | None = None,
    execution_acknowledged: Callable[[SubmissionRecoveryV1], None] | None = None,
) -> bool:
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
    deferred_clear = False
    if mode == "interrupt":
        actions.submit(port.abort, control=True)
    elif mode == "start" and window.submission_mode is (
        SessionSubmissionModeV1.EXECUTION
    ):
        if execution_client is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        if execution_submissions is None or execution_acknowledged is None:
            raise ValueError("execution submission ownership is unavailable")
        action = ConversationTextAction(text)
        binding.validate_text(action)
        key: ExecutionSubmissionKey = (window.identity, text)
        recovery = execution_submissions.get(key)
        if recovery is not None and recovery.delivery not in {
            SubmissionDeliveryV1.UNKNOWN,
            SubmissionDeliveryV1.NOT_FOUND,
        }:
            recovery = None
        created = recovery is None
        if recovery is None:
            recovery = SubmissionRecoveryV1(
                PendingSubmissionV1(
                    execution_client.service_instance_id,
                    window.identity,
                    token_hex(16),
                    text,
                )
            )
        execution = HostedExecutionSubmitBinding(
            execution_client,
            recovery,
            control=SessionSnapshotRequestV1(attachment, generation, member),
            present=present,
            acknowledged=lambda: execution_acknowledged(recovery),
        )
        actions.submit(execution.submit)
        if created:
            execution_submissions[key] = recovery
        deferred_clear = True
    else:
        action = ConversationTextAction(text)
        binding.validate_text(action)
        operation = {"start": port.submit, "steer": port.steer, "followup": port.follow_up}[mode]
        actions.submit(lambda: operation(action))
    # The original publication-gated task is now retained. Rejected validation
    # or capacity leaves the draft and previous presentation untouched.
    window.request_id, window.request_presentation = request_id, pending
    return deferred_clear


__all__ = [
    "ExecutionSubmissionKey",
    "HostedConversationActionBinding",
    "HostedExecutionSubmitBinding",
    "submit_hosted_conversation_action",
]
