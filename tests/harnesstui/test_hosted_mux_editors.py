from __future__ import annotations

import asyncio
from dataclasses import replace

from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import _Client
from .test_hosted_mux_shell import _shell


def _key(shell, key):
    shell.handle(InputEvent(kind="key", key=key))


def test_G17_EDITOR_switch_preserves_selection_cursor_undo_and_router_target():
    async def scenario():
        shell = _shell(_Client())
        await shell.start()
        try:
            shell.handle(InputEvent(kind="text", text="first draft"))
            first = shell.screen.composer
            first.set_selection(1, 4)
            _key(shell, "tab")
            second = shell.screen.composer
            assert second is not first
            shell.handle(InputEvent(kind="text", text="second draft"))
            _key(shell, "shift+tab")
            assert shell.screen.composer is first
            assert first.selected_range == (1, 4)
            shell.handle(InputEvent(kind="text", text="X"))
            assert first.value == "fXt draft"
            assert second.value == "second draft"
            _key(shell, "alt+u")
            assert first.value == "first draft"
            _key(shell, "alt+u")
            assert first.value == ""
            assert shell.state.active_window.draft == ""
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_EDITOR_refresh_preserves_identity_not_position_or_attachment():
    async def scenario():
        client = _Client()
        fresh = client.attachments[1]
        members = tuple(
            replace(member, position=index)
            for index, member in enumerate(fresh.mux_space.members[::-1], 1)
        )
        client.attachments[1] = replace(
            fresh,
            mux_space=replace(fresh.mux_space, members=members),
            sessions=tuple(
                replace(item, member=member)
                for item, member in zip(fresh.sessions[::-1], members, strict=True)
            ),
        )
        shell = _shell(client)
        await shell.start()
        try:
            shell.handle(InputEvent(kind="text", text="kept"))
            first = shell.screen.composer
            first.move_left()
            shell.state.active_window.scroll_anchor = 1
            await shell._controller.refresh_snapshot()
            shell._sync_editor()
            assert shell.state.attachment_id == "attachment-2"
            assert shell.screen.composer is first
            assert shell.state.active_window.scroll_anchor == 1
            shell.handle(InputEvent(kind="text", text="!"))
            assert first.value == "kep!t"
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_G17_EDITOR_removed_or_replaced_identity_is_pruned_and_close_releases_cache():
    async def scenario():
        shell = _shell(_Client())
        await shell.start()
        first = shell.screen.composer
        _key(shell, "tab")
        second = shell.screen.composer
        shell.state.windows.pop(0)
        shell._sync_editor()
        assert list(shell._editors.values()) == [second]
        shell.state.active_window.session_id = "replacement"
        shell.state.active_window.draft = ""
        shell._sync_editor()
        assert shell.screen.composer is not second
        assert all(editor is not first for editor in shell._editors.values())
        assert all(editor is not second for editor in shell._editors.values())
        active = shell.screen.composer
        _key(shell, "end")
        shell.handle(InputEvent(kind="text", text="private draft"))
        _key(shell, "ctrl+u")
        assert active.kill_ring
        shell.screen.render(RenderConstraints(width=80, max_height=24))
        assert shell.screen._bottom_frame_component.composer is active
        await shell.close()
        assert not shell._editors
        assert shell.screen.composer is not active
        assert shell.screen._bottom_frame_component.composer is shell.screen.composer
        assert (
            shell.screen.composer is not first and shell.screen.composer is not second
        )
        assert not shell.screen.composer.kill_ring

    asyncio.run(scenario())
