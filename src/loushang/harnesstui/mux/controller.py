"""Hosted Mux controller over an injected transport-neutral AppClient."""

from __future__ import annotations

from secrets import token_hex

from loushang.appserver.client import AppClientV1, AppConnectionClosedError
from loushang.appserver.execution.client import ExecutionClientV1
from loushang.appserver.execution.recovery import (
    PendingSubmissionV1,
    SubmissionDeliveryV1,
    SubmissionRecoveryV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxDetachV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionSnapshotRequestV1,
    SessionSubmissionModeV1,
    TurnInterruptV1,
    TurnTextV1,
)

from .model import HarnessWindowState, HostedMuxState
from .reducer import preserve_local_state, reduce_events, state_from_attachment


class HostedMuxControllerV1:
    """Coordinate explicit hosted actions; local window actions stay local."""

    __slots__ = (
        "_client",
        "_execution_client",
        "_mailbox_capacity",
        "_selector",
        "_submissions",
        "state",
    )

    def __init__(
        self,
        client: AppClientV1,
        *,
        selector: MuxSelectorV1,
        mailbox_capacity: int = 256,
        execution_client: ExecutionClientV1 | None = None,
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
        self._execution_client = execution_client
        self._selector = selector
        self._mailbox_capacity = mailbox_capacity
        self._submissions: dict[tuple[object, str], SubmissionRecoveryV1] = {}
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
        state.snapshot_required = True
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
        return await self._reattach_after_membership_change()

    async def open_member(self, request: SessionOpenSpecV1) -> HostedMuxState:
        self._require_state(current=True)
        await self._client.open_member(MuxMemberOpenV1(self._selector, request))
        return await self._reattach_after_membership_change()

    async def close_active_member(
        self, *, close_session: bool = True
    ) -> HostedMuxState:
        state = self._require_state(current=True)
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
        revision = window.draft_revision
        request = TurnTextV1(
            state.attachment_id,
            state.controller_generation,
            window.member_id,
            selected,
        )
        if window.submission_mode is SessionSubmissionModeV1.LEGACY:
            await self._client.start_turn(request)
        else:
            execution_client = self._execution_client
            if execution_client is None:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            # Keep the v1 validation bound while changing only delivery semantics.
            key = (window.identity, selected)
            recovery = self._submissions.get(key)
            if recovery is not None and recovery.delivery not in {
                SubmissionDeliveryV1.UNKNOWN,
                SubmissionDeliveryV1.NOT_FOUND,
            }:
                recovery = None
            if recovery is None:
                recovery = SubmissionRecoveryV1(
                    PendingSubmissionV1(
                        execution_client.service_instance_id,
                        window.identity,
                        token_hex(16),
                        selected,
                    )
                )
                self._submissions[key] = recovery
            await recovery.submit(
                execution_client,
                SessionSnapshotRequestV1(
                    state.attachment_id,
                    state.controller_generation,
                    window.member_id,
                ),
            )
            record = recovery.record
            if record is None:
                raise RuntimeError("execution submission has no record")
            outcome = record.state.outcome
            if outcome is not None and isinstance(outcome.legacy_result, AppFailureV1):
                raise AppServiceError(outcome.legacy_result.code)
            if self._submissions.get(key) is recovery:
                del self._submissions[key]
        current = self.state
        if current is not None and current.mux_space_id == state.mux_space_id:
            for item in current.windows:
                if (
                    (item.member_id, item.session_id)
                    == (window.member_id, window.session_id)
                    and item.draft_revision == revision
                    and item.draft == selected
                ):
                    item.draft = ""
                    item.draft_revision += 1

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
        except AppConnectionClosedError:
            # The local connection is unusable, so this view cannot retain an
            # attachment. This is not a remote ACK: connection/scope/process
            # owners still prove their own cleanup independently.
            pass
        except AppServiceError as error:
            if error.code is not AppErrorCodeV1.STALE_ATTACHMENT:
                raise
        self.state = None

    async def _reattach_after_membership_change(self) -> HostedMuxState:
        previous = self._require_state()
        previous.snapshot_required = True
        attachment = await self._client.attach_mux(
            MuxAttachV1(self._selector, self._mailbox_capacity)
        )
        fresh = state_from_attachment(attachment)
        preserve_local_state(fresh, previous)
        self.state = fresh
        return fresh

    def _require_state(self, *, current: bool = False) -> HostedMuxState:
        if self.state is None:
            raise RuntimeError("hosted mux controller is not started")
        if current and self.state.snapshot_required:
            raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
        return self.state

    def _active(self) -> tuple[HostedMuxState, HarnessWindowState]:
        state = self._require_state(current=True)
        window = state.active_window
        if window is None:
            raise RuntimeError("hosted mux has no active window")
        return state, window


__all__ = ["HostedMuxControllerV1"]
