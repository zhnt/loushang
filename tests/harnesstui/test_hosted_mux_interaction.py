from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace

import pytest

from loushang.appserver.protocol import (
    AckV1,
    AppErrorCodeV1,
    AppServiceError,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
)
from loushang.harnesstui.mux import (
    HarnessWindowState,
    open_hosted_mux_profile,
    select_next,
    set_active_draft,
)

from .test_hosted_mux_profile import FINGERPRINT, _Client


def test_G16_UI_edit_revision_does_not_shift_existing_positional_window_fields():
    fields = inspect.signature(HarnessWindowState).parameters
    assert fields["draft_revision"].kind is inspect.Parameter.KEYWORD_ONLY
    positional = [
        key
        for key, value in fields.items()
        if value.kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    assert positional[positional.index("draft") + 1] == "assistant_draft"


@pytest.mark.parametrize("switch_window", [False, True])
@pytest.mark.parametrize("new_text", ["new draft", "submitted"])
def test_G16_UI_late_submit_never_erases_new_or_other_window_drafts(
    switch_window, new_text
):
    async def scenario():
        client = _Client()
        controller = await open_hosted_mux_profile(
            client, selector=MuxSelectorV1(name="dev")
        )
        state = controller.state
        entered, release = asyncio.Event(), asyncio.Event()

        async def submit(request):
            entered.set()
            await release.wait()
            return AckV1()

        client.start_turn = submit
        set_active_draft(state, "submitted")
        pending = asyncio.create_task(controller.submit())
        await entered.wait()
        if switch_window:
            select_next(state)
        set_active_draft(state, "")
        set_active_draft(state, new_text)
        release.set()
        await pending
        assert state.active_window.draft == new_text
        if switch_window:
            assert state.windows[0].draft == ""
        await controller.close()

    asyncio.run(scenario())


def test_G16_UI_failed_snapshot_retains_drafts_but_fences_old_actions():
    async def scenario():
        client = _Client()
        controller = await open_hosted_mux_profile(
            client, selector=MuxSelectorV1(name="dev")
        )
        state = controller.state
        set_active_draft(state, "retained draft")

        async def unavailable(request):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

        attach = client.attach_mux
        client.attach_mux = unavailable
        with pytest.raises(AppServiceError, match="operation_unavailable"):
            await controller.refresh_snapshot()
        assert (
            controller.state is state and state.active_window.draft == "retained draft"
        )
        assert state.snapshot_required
        calls = tuple(client.calls)
        with pytest.raises(AppServiceError, match="snapshot_required"):
            await controller.submit()
        with pytest.raises(AppServiceError, match="snapshot_required"):
            await controller.interrupt()
        with pytest.raises(AppServiceError, match="snapshot_required"):
            await controller.close_active_member()
        with pytest.raises(AppServiceError, match="snapshot_required"):
            await controller.open_member(
                SessionOpenSpecV1(
                    "coding", "new", SessionScopeV1.CWD, FINGERPRINT, "new"
                )
            )
        assert tuple(client.calls) == calls
        client.attach_mux = attach
        refreshed = await controller.refresh_snapshot()
        assert refreshed.active_window.draft == "retained draft"
        assert not refreshed.snapshot_required
        await controller.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("edit_after_refresh", [False, True])
def test_G16_UI_late_submit_resolves_against_fresh_member_edit_revision(
    edit_after_refresh,
):
    async def scenario():
        client = _Client()
        controller = await open_hosted_mux_profile(
            client, selector=MuxSelectorV1(name="dev")
        )
        entered, release = asyncio.Event(), asyncio.Event()

        async def submit(request):
            entered.set()
            await release.wait()
            return AckV1()

        client.start_turn = submit
        set_active_draft(controller.state, "submitted")
        pending = asyncio.create_task(controller.submit())
        await entered.wait()
        fresh = await controller.refresh_snapshot()
        if edit_after_refresh:
            set_active_draft(fresh, "")
            set_active_draft(fresh, "submitted")
        release.set()
        await pending
        assert fresh.active_window.draft == ("submitted" if edit_after_refresh else "")
        await controller.close()

    asyncio.run(scenario())


def test_G16_UI_replaced_session_does_not_inherit_another_sessions_draft():
    async def scenario():
        client = _Client()
        controller = await open_hosted_mux_profile(
            client, selector=MuxSelectorV1(name="dev")
        )
        set_active_draft(controller.state, "private old draft")
        fresh = client.attachments[0]
        identity = replace(
            fresh.sessions[0].snapshot.identity, session_id="replacement"
        )
        member = replace(fresh.sessions[0].member, session=identity)
        client.attachments[0] = replace(
            fresh,
            mux_space=replace(
                fresh.mux_space, members=(member, *fresh.mux_space.members[1:])
            ),
            sessions=(
                replace(
                    fresh.sessions[0],
                    member=member,
                    snapshot=replace(fresh.sessions[0].snapshot, identity=identity),
                ),
                *fresh.sessions[1:],
            ),
        )
        refreshed = await controller.refresh_snapshot()
        assert refreshed.active_window.draft == ""
        await controller.close()

    asyncio.run(scenario())


def test_G16_UI_snapshot_reorders_local_state_by_identity_without_reviving_authority():
    async def scenario():
        client = _Client()
        controller = await open_hosted_mux_profile(
            client, selector=MuxSelectorV1(name="dev")
        )
        state = controller.state
        set_active_draft(state, "first draft")
        state.windows[0].scroll_anchor = 2
        select_next(state)
        set_active_draft(state, "second draft")
        state.windows[1].pending_interaction_id = "stale-question"
        state.windows[1].assistant_draft = "stale-stream"
        state.windows[1].running = True
        fresh = client.attachments[0]
        reversed_members = tuple(
            replace(item, position=index)
            for index, item in enumerate(reversed(fresh.mux_space.members), 1)
        )
        client.attachments[0] = replace(
            fresh,
            mux_space=replace(fresh.mux_space, members=reversed_members),
            sessions=tuple(
                replace(item, member=member)
                for item, member in zip(
                    reversed(fresh.sessions), reversed_members, strict=True
                )
            ),
        )
        refreshed = await controller.refresh_snapshot()
        assert [window.draft for window in refreshed.windows] == [
            "second draft",
            "first draft",
        ]
        assert refreshed.active_window.member_id == "member-2"
        assert refreshed.windows[1].scroll_anchor == 2
        assert refreshed.attachment_id != state.attachment_id
        assert all(not window.running for window in refreshed.windows)
        assert all(
            window.pending_interaction_id is None for window in refreshed.windows
        )
        assert all(window.assistant_draft == "" for window in refreshed.windows)
        await controller.close()

    asyncio.run(scenario())
