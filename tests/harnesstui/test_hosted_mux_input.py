from __future__ import annotations

import asyncio

import pytest

from loushang.harnesstui.conversation.input import ConversationInputRouter
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import _Client
from .test_hosted_mux_requests import settle
from .test_hosted_mux_shell import _shell


def key(shell, value):
    shell.handle(InputEvent(kind="key", key=value))


def test_hosted_uses_shared_input_and_live_running_state_without_render():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        try:
            assert isinstance(shell._router, ConversationInputRouter)
            window = shell.state.active_window
            original_records = list(window.records)
            for running, submit_key, expected in ((False, "enter", "start"),
                    (True, "enter", "steer"), (True, "alt+enter", "follow_up"),
                    (False, "enter", "start")):
                window.running = running
                shell.handle(InputEvent(kind="text", text="hello"))
                key(shell, submit_key)
                assert shell.screen.composer.value == window.draft == ""
                await settle(shell)
                assert client.calls[-1][0] == expected
                assert window.running is running and window.records == original_records
                assert not shell.screen.state.pending_steers
                assert not shell.screen.state.pending_followups
                assert window.request_presentation.state == "acknowledged"
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("modal", ["help", "approval", "picker"])
@pytest.mark.parametrize("pressed", ["tab", "enter", "ctrl+c", "ctrl+d"])
def test_modal_input_cannot_switch_submit_interrupt_or_detach(modal, pressed):
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        try:
            window = shell.state.active_window
            window.running = True
            if modal == "help":
                shell.screen.show_help()
            elif modal == "approval":
                window.pending_interaction_id = "question"
                window.pending_interaction_text = "Sensitive action"
                shell.screen.show_approval()
            else:
                shell.picker.open()
            key(shell, pressed)
            assert shell.state.active_window is window
            assert not shell.exit_requested
            assert shell.pending_actions == 0
            assert [name for name, _ in client.calls] == ["attach"]
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("running", [False, True])
def test_rejected_shared_submission_keeps_draft_and_does_not_add_history(monkeypatch, running):
    async def scenario():
        shell = _shell(_Client())
        await shell.start()
        try:
            shell.state.active_window.running = running
            editor = shell.screen.composer
            history = []
            monkeypatch.setattr(type(editor), "add_history", lambda self, text: history.append(text))
            def refuse(*args, **kwargs):
                raise ValueError("action_queue_full")
            monkeypatch.setattr(shell._actions, "submit", refuse)
            shell.handle(InputEvent(kind="text", text="keep me"))
            key(shell, "enter")
            assert editor.value == shell.state.active_window.draft == "keep me"
            assert history == [] and shell.pending_actions == 0
            assert shell.state.active_window.request_presentation is None
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_shared_completion_consumes_keys_but_never_enables_product_commands():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        try:
            editor, window = shell.screen.composer, shell.state.active_window
            shell.handle(InputEvent(kind="text", text="/he"))
            editor.refresh_completions(force=True)
            assert editor.has_completions
            key(shell, "tab")
            assert shell.state.active_window is window
            assert editor.value.strip() == "/help"
            key(shell, "enter")
            assert shell.screen._detail is not None and not editor.value
            key(shell, "escape")
            for text in ("/model", "/tools", "/bash"):
                editor.set_text(text)
                editor.refresh_completions(force=True)
                assert not editor.has_completions
                key(shell, "enter")
                assert editor.value == text and shell.pending_actions == 0
            editor.clear()
            shell.handle(InputEvent(kind="text", text="//help"))
            key(shell, "enter")
            await settle(shell)
            assert client.calls[-1][0] == "start" and client.calls[-1][1].text == "/help"
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_shared_editor_rebind_clears_context_keeps_cursor_and_has_no_late_submit(monkeypatch):
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        try:
            first = shell.screen.composer
            shell.handle(InputEvent(kind="text", text="abc def"))
            first.move_to_line_start()
            key(shell, "ctrl+]")
            key(shell, "tab")
            shell.handle(InputEvent(kind="text", text="second"))
            assert shell.screen.composer.value == "second"
            key(shell, "shift+tab")
            shell.handle(InputEvent(kind="text", text="X"))
            assert first.value == "Xabc def"
            old_cursor = first._buffer.cursor
            await shell._controller.refresh_snapshot()
            shell._sync_editor()
            assert shell.screen.composer is first and first._buffer.cursor == old_cursor
            assert shell._router._jump_mode is None and not first.has_completions
            shell.handle(InputEvent(kind="key", key="enter", event_type="release"))
            assert shell.pending_actions == 0 and first.value == "Xabc def"
            history = []
            original = type(first).add_history
            def remember(editor, text):
                history.append(text)
                original(editor, text)
            monkeypatch.setattr(type(first), "add_history", remember)
            key(shell, "enter")
            await settle(shell)
            assert history == ["Xabc def"]
            assert first.value == shell.state.active_window.draft == ""
            router = shell._router
        finally:
            await shell.close()
        assert router._disposed

    asyncio.run(scenario())


def test_rejected_completed_command_keeps_one_consistent_draft(monkeypatch):
    async def scenario():
        shell = _shell(_Client())
        await shell.start()
        try:
            shell.handle(InputEvent(kind="text", text="/inter"))
            shell.screen.composer.refresh_completions(force=True)
            assert shell.screen.composer.has_completions
            def refuse(*args, **kwargs):
                raise ValueError("action_queue_full")
            monkeypatch.setattr(shell._actions, "submit", refuse)
            key(shell, "enter")
            completed = shell.screen.composer.value
            assert completed.strip() == "/interrupt"
            assert shell.state.active_window.draft == completed
            assert not shell.screen.composer._history
            assert shell.notice == "action_queue_full"
            assert shell.state.active_window.request_presentation is None
            key(shell, "tab")
            key(shell, "shift+tab")
            assert shell.screen.composer.value == completed
            assert shell.state.active_window.draft == completed
            await shell._controller.refresh_snapshot()
            shell._sync_editor()
            assert shell.screen.composer.value == shell.state.active_window.draft == completed
        finally:
            await shell.close()

    asyncio.run(scenario())
