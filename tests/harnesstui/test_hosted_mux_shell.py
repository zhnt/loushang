from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol import AckV1, MuxSelectorV1, SessionScopeV1
from loushang.harnesstui.mux.shell import HostedMuxShellV1
from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import FINGERPRINT, _Client


def _shell(client):
    return HostedMuxShellV1(
        client,
        selector=MuxSelectorV1(name="dev"),
        product_id="coding",
        scopes=(
            (SessionScopeV1.CWD, FINGERPRINT),
            (SessionScopeV1.USER_HOME, FINGERPRINT),
        ),
    )


def test_G16_SHELL_captures_member_before_next_input_and_keeps_typing_responsive():
    async def scenario():
        client = _Client()
        entered = asyncio.Event()
        calls = []

        async def turn(request):
            calls.append(request)
            entered.set()
            await asyncio.Event().wait()
            return AckV1()

        client.start_turn = turn
        shell = _shell(client)
        await shell.start()
        shell.handle(InputEvent(kind="text", text="first prompt"))
        shell.handle(InputEvent(kind="key", key="enter"))
        shell.handle(InputEvent(kind="key", key="tab"))
        shell.handle(InputEvent(kind="text", text="second draft"))
        await asyncio.wait_for(entered.wait(), 1)
        assert calls[0].member_id == "member-1"
        assert shell.state.active_window.member_id == "member-2"
        assert shell.state.active_window.draft == "second draft"
        assert shell.pending_actions == 1
        await asyncio.wait_for(shell.close(), 1)
        assert not shell.cleanup_pending
        assert not any(
            name in {"close_mux", "close_member", "interrupt"}
            for name, _ in client.calls
        )

    asyncio.run(scenario())


def test_G16_SHELL_limits_paste_before_editor_effects_and_rejects_image_input():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        shell.handle(InputEvent(kind="text", text="kept"))
        shell.handle(InputEvent(kind="paste", text="中" * 30_000))
        assert shell.state.active_window.draft == "kept"
        assert shell.notice == "draft_limit"
        shell.handle(InputEvent(kind="key", key="ctrl+v"))
        assert shell.notice == "image_paste_unavailable"
        assert len(client.calls) == 1
        await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("width", [8, 30, 80])
def test_G16_SHELL_reuses_conversation_view_with_a_bounded_mux_footer(width):
    async def scenario():
        shell = _shell(_Client())
        await shell.start()
        result = shell.screen.render(
            RenderConstraints(width=width, max_height=24, visible_height=24)
        )
        result.validate(RenderConstraints(width=width, max_height=24))
        assert len(result.lines) <= 24
        text = "\n".join(line.text for line in result.lines)
        assert "dev" in text
        await shell.close()

    asyncio.run(scenario())


def test_G16_SHELL_explicit_detach_does_not_send_stop_or_close():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        shell.handle(InputEvent(kind="text", text="/detach"))
        shell.handle(InputEvent(kind="key", key="enter"))
        assert shell.exit_requested
        await shell.close()
        assert [name for name, _ in client.calls] == ["attach", "detach"]

    asyncio.run(scenario())


def test_G16_SHELL_does_not_invent_remote_permissions_paths_model_or_elapsed_time():
    async def scenario():
        shell = _shell(_Client())
        await shell.start()
        shell.state.active_window.running = True
        shell.state.active_window.last_cursor += 1
        constraints = RenderConstraints(width=240, max_height=24)
        result = shell.screen.render(constraints)
        text = "\n".join(line.text for line in result.lines)
        assert "perm=" not in text
        assert "no-branch" not in text
        assert "Working" not in text  # No remote run timestamp exists in v1.
        assert "running" in text and "Hosted" in text
        await shell.close()

    asyncio.run(scenario())


def test_G16_SHELL_first_member_pending_rejects_unplaced_draft_before_edit():
    async def scenario():
        from dataclasses import replace

        client = _Client()
        client.attachments[0] = replace(
            client.attachments[0],
            mux_space=replace(client.attachments[0].mux_space, members=()),
            sessions=(),
        )
        entered, release = asyncio.Event(), asyncio.Event()
        original = client.open_member

        async def open_member(request):
            entered.set()
            await release.wait()
            return await original(request)

        client.open_member = open_member
        shell = _shell(client)
        await shell.start()
        shell.handle(InputEvent(kind="text", text="/new cwd"))
        shell.handle(InputEvent(kind="key", key="enter"))
        await asyncio.wait_for(entered.wait(), 1)
        shell.handle(InputEvent(kind="text", text="unplaced text"))
        assert shell.screen.composer.value == ""
        assert shell.notice == "member_pending: wait for the first Session"
        release.set()
        await shell.close()

    asyncio.run(scenario())
