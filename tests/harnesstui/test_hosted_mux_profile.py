from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from loushang.appserver.protocol import (
    AckV1,
    AppErrorCodeV1,
    AppServiceError,
    AttachedSessionV1,
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
    MuxSelectorV1,
    MuxSpaceMemberV1,
    MuxSpaceV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
    TurnInterruptV1,
    TurnTextV1,
)
from loushang.harnesstui.mux import (
    open_hosted_mux_profile,
    project_active_conversation,
    reduce_events,
    select_next,
    set_active_draft,
    state_from_attachment,
)
from loushang.tui.transcript import AssistantMessageRecord, UserPromptRecord

FINGERPRINT = "d" * 64


def _run(coroutine: Awaitable[object]) -> object:
    return asyncio.run(coroutine)


def _attachment(
    *,
    attachment_id: str = "attachment-1",
    generation: int = 1,
) -> MuxAttachmentV1:
    identities = (
        SessionIdentityV1(
            "coding",
            "continuity-1",
            "session-1",
            SessionScopeV1.CWD,
            FINGERPRINT,
        ),
        SessionIdentityV1(
            "coding",
            "continuity-2",
            "session-2",
            SessionScopeV1.USER_HOME,
            FINGERPRINT,
        ),
    )
    members = tuple(
        MuxSpaceMemberV1(
            member_id=f"member-{index}",
            session=identity,
            title=f"Session {index}",
            position=index,
        )
        for index, identity in enumerate(identities, 1)
    )
    mux = MuxSpaceV1("mux-1", "dev", 3, members)
    snapshots = tuple(
        SessionSnapshotV1(
            identity=identity,
            title=f"Session {index}",
            cursor=2,
            revision=1,
            running=False,
            records=(
                TranscriptRecordV1(TranscriptRecordKindV1.USER, f"prompt {index}"),
                TranscriptRecordV1(
                    TranscriptRecordKindV1.ASSISTANT,
                    f"answer {index}",
                ),
            ),
        )
        for index, identity in enumerate(identities, 1)
    )
    return MuxAttachmentV1(
        attachment_id,
        mux,
        generation,
        tuple(
            AttachedSessionV1(member, snapshot)
            for member, snapshot in zip(members, snapshots, strict=True)
        ),
    )


class _Client:
    def __init__(self) -> None:
        self.attachments = [_attachment(), _attachment(attachment_id="attachment-2", generation=2)]
        self.events: tuple[AttachmentEventV1, ...] = ()
        self.calls: list[tuple[str, object]] = []
        self.lag_once = False
        self.detach_failure: AppErrorCodeV1 | None = None

    async def create_mux(self, request: MuxCreateV1) -> MuxSpaceV1:
        self.calls.append(("create", request))
        return self.attachments[0].mux_space

    async def list_muxes(self) -> MuxListResultV1:
        return MuxListResultV1((self.attachments[0].mux_space,))

    async def read_mux(self, request: MuxReadV1) -> MuxSpaceV1:
        return self.attachments[0].mux_space

    async def attach_mux(self, request: MuxAttachV1) -> MuxAttachmentV1:
        self.calls.append(("attach", request))
        return self.attachments.pop(0)

    async def detach_mux(self, request: MuxDetachV1) -> AckV1:
        self.calls.append(("detach", request))
        if self.detach_failure is not None:
            raise AppServiceError(self.detach_failure)
        return AckV1()

    async def close_mux(self, request: MuxCloseV1) -> AckV1:
        self.calls.append(("close_mux", request))
        return AckV1()

    async def open_member(self, request: MuxMemberOpenV1) -> MuxSpaceV1:
        self.calls.append(("open_member", request))
        return self.attachments[0].mux_space

    async def close_member(self, request: MuxMemberCloseV1) -> MuxSpaceV1:
        self.calls.append(("close_member", request))
        return self.attachments[0].mux_space

    async def snapshot_session(
        self,
        request: SessionSnapshotRequestV1,
    ) -> SessionSnapshotV1:
        return self.attachments[0].sessions[0].snapshot

    async def start_turn(self, request: TurnTextV1) -> AckV1:
        self.calls.append(("start", request))
        return AckV1()

    async def steer_turn(self, request: TurnTextV1) -> AckV1:
        self.calls.append(("steer", request))
        return AckV1()

    async def follow_up_turn(self, request: TurnTextV1) -> AckV1:
        self.calls.append(("follow_up", request))
        return AckV1()

    async def interrupt_turn(self, request: TurnInterruptV1) -> AckV1:
        self.calls.append(("interrupt", request))
        return AckV1()

    async def respond_interaction(self, request: InteractionRespondV1) -> AckV1:
        self.calls.append(("interaction", request))
        return AckV1()

    async def read_events(
        self,
        *,
        attachment_id: str,
        controller_generation: int,
        limit: int = 64,
    ) -> tuple[AttachmentEventV1, ...]:
        del attachment_id, controller_generation, limit
        if self.lag_once:
            self.lag_once = False
            raise AppServiceError(AppErrorCodeV1.ATTACHMENT_LAGGED)
        events, self.events = self.events, ()
        return events


def test_G11_HOSTED_PROFILE_builds_windows_and_reuses_conversation_projection() -> None:
    state = state_from_attachment(_attachment())

    conversation = project_active_conversation(state)

    assert state.mux_name == "dev"
    assert [window.title for window in state.windows] == ["Session 1", "Session 2"]
    assert isinstance(conversation.records[0], UserPromptRecord)
    assert isinstance(conversation.records[1], AssistantMessageRecord)
    assert conversation.session_label == "Session 1"


def test_G11_HOSTED_PROFILE_local_window_and_draft_actions_do_not_call_client() -> None:
    async def scenario() -> None:
        client = _Client()
        controller = await open_hosted_mux_profile(
            client,
            selector=MuxSelectorV1(name="dev"),
        )
        state = controller.state
        assert state is not None
        calls_after_attach = tuple(client.calls)

        set_active_draft(state, "draft one")
        select_next(state)
        set_active_draft(state, "draft two")

        assert tuple(client.calls) == calls_after_attach
        assert [window.draft for window in state.windows] == ["draft one", "draft two"]
        await controller.close()

    _run(scenario())


def test_G11_HOSTED_PROFILE_reducer_tracks_unread_deltas_and_rejects_gaps() -> None:
    state = state_from_attachment(_attachment())
    event = AttachmentEventV1(
        state.attachment_id,
        "member-2",
        SessionEventV1(
            "session-2",
            3,
            SessionEventKindV1.ASSISTANT_DELTA,
            "new",
        ),
    )

    reduce_events(state, (event,))

    assert state.windows[1].assistant_draft == "new"
    assert state.windows[1].unread is True
    reduce_events(
        state,
        (
            AttachmentEventV1(
                state.attachment_id,
                "member-2",
                SessionEventV1(
                    "session-2",
                    5,
                    SessionEventKindV1.STATUS,
                    "gap",
                ),
            ),
        ),
    )
    assert state.snapshot_required is True
    assert state.status_message == "snapshot_required"


def test_G11_HOSTED_PROFILE_reducer_retains_interaction_identity() -> None:
    state = state_from_attachment(_attachment())
    requested = AttachmentEventV1(
        state.attachment_id,
        "member-1",
        SessionEventV1(
            "session-1",
            3,
            SessionEventKindV1.INTERACTION_REQUESTED,
            "Approve tool use?",
            "interaction-1",
        ),
    )
    dismissed = AttachmentEventV1(
        state.attachment_id,
        "member-1",
        SessionEventV1(
            "session-1",
            4,
            SessionEventKindV1.INTERACTION_DISMISSED,
            interaction_id="interaction-1",
        ),
    )

    reduce_events(state, (requested,))
    assert state.windows[0].pending_interaction_id == "interaction-1"
    assert state.windows[0].pending_interaction_text == "Approve tool use?"
    reduce_events(state, (dismissed,))
    assert state.windows[0].pending_interaction_id is None
    assert state.windows[0].pending_interaction_text is None


def test_G11_HOSTED_PROFILE_controller_submits_and_recovers_lagged_attachment() -> None:
    async def scenario() -> None:
        client = _Client()
        controller = await open_hosted_mux_profile(
            client,
            selector=MuxSelectorV1(name="dev"),
        )
        state = controller.state
        assert state is not None
        set_active_draft(state, "submit me")

        await controller.submit()
        client.lag_once = True
        await controller.poll()
        assert state.snapshot_required is True
        refreshed = await controller.refresh_snapshot()

        start_request = next(value for name, value in client.calls if name == "start")
        assert isinstance(start_request, TurnTextV1)
        assert start_request.text == "submit me"
        assert refreshed.attachment_id == "attachment-2"
        assert [name for name, _value in client.calls].count("detach") == 1
        await controller.close()

    _run(scenario())


def test_G11_HOSTED_PROFILE_is_explicit_and_has_no_default_entrypoint_effect() -> None:
    import loushang.harnesstui

    assert not hasattr(loushang.harnesstui, "open_hosted_mux_profile")


def test_hosted_controller_close_retains_authority_when_detach_fails() -> None:
    async def scenario() -> None:
        client = _Client()
        controller = await open_hosted_mux_profile(
            client,
            selector=MuxSelectorV1(name="dev"),
        )
        state = controller.state
        client.detach_failure = AppErrorCodeV1.SESSION_UNAVAILABLE

        try:
            await controller.close()
        except AppServiceError as error:
            assert error.code is AppErrorCodeV1.SESSION_UNAVAILABLE
        else:
            raise AssertionError("detach failure must remain visible")

        assert controller.state is state
        client.detach_failure = None
        await controller.close()
        assert controller.state is None

    _run(scenario())
