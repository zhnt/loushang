from __future__ import annotations

import asyncio

from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import _Client
from .test_hosted_mux_shell import _shell


def _command(shell, text):
    shell.handle(InputEvent(kind="text", text=text))
    shell.handle(InputEvent(kind="key", key="enter"))


def _render(shell):
    constraints = RenderConstraints(width=60, max_height=12)
    result = shell.screen.render(constraints)
    result.validate(constraints)
    return strip_control_sequences("\n".join(line.text for line in result.lines))


def test_G16_DETAILS_approval_requires_current_full_presentation_and_explicit_command():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        window = shell.state.active_window
        window.pending_interaction_id = "question-1"
        window.pending_interaction_text = "\n".join(
            f"argument-{index:03}" for index in range(80)
        )
        _command(shell, "/approve")
        assert "Approval details" in _render(shell)
        assert shell.pending_actions == 0
        shell.handle(InputEvent(kind="key", key="end"))
        assert "argument-079" in _render(shell)
        shell.handle(InputEvent(kind="key", key="escape"))
        _command(shell, "/approve")
        assert shell.pending_actions == 0  # Unseen middle pages cannot authorize.
        seen = ""
        for _ in range(100):
            seen += _render(shell)
            shell.handle(InputEvent(kind="key", key="pageDown"))
        assert all(f"argument-{index:03}" in seen for index in range(80))
        shell.handle(InputEvent(kind="key", key="escape"))
        _command(shell, "/approve")
        assert shell.pending_actions == 1
        await asyncio.sleep(0)
        await shell.close()
        requests = [request for name, request in client.calls if name == "interaction"]
        assert len(requests) == 1 and requests[0].interaction_id == "question-1"

    asyncio.run(scenario())


def test_G16_DETAILS_generation_change_invalidates_presented_approval_but_deny_is_available():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        window = shell.state.active_window
        window.pending_interaction_id = "question"
        window.pending_interaction_text = "Current action"
        shell.handle(InputEvent(kind="key", key="f2"))
        assert "Current action" in _render(shell)
        assert shell.screen.approval_presented()
        shell.handle(InputEvent(kind="key", key="escape"))
        shell.state.controller_generation += 1
        _command(shell, "/approve")
        assert shell.pending_actions == 0
        assert not shell.screen.approval_presented()
        shell.handle(InputEvent(kind="key", key="escape"))
        _command(shell, "/deny")
        await asyncio.sleep(0)
        await shell.close()
        requests = [request for name, request in client.calls if name == "interaction"]
        assert len(requests) == 1
        assert requests[0].outcome.value == "deny"

    asyncio.run(scenario())


def test_G16_DETAILS_help_preserves_draft_and_approval_view_never_moves_to_new_authority():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        shell.handle(InputEvent(kind="text", text="unfinished draft"))
        shell.handle(InputEvent(kind="key", key="f1"))
        seen = ""
        for _ in range(30):
            seen += _render(shell)
            shell.handle(InputEvent(kind="key", key="pageDown"))
        assert "/new" in seen and "/resume" in seen and "/close --yes" in seen
        shell.handle(InputEvent(kind="key", key="escape"))
        assert shell.state.active_window.draft == "unfinished draft"
        assert shell.screen.composer.value == "unfinished draft"
        window = shell.state.active_window
        window.pending_interaction_id, window.pending_interaction_text = (
            "old",
            "Review old action",
        )
        shell.handle(InputEvent(kind="key", key="f2"))
        assert "Review old action" in _render(shell)
        window.pending_interaction_id, window.pending_interaction_text = (
            "new",
            "Review replacement",
        )
        shell.handle(InputEvent(kind="paste", text="/approve\r"))
        assert shell.pending_actions == 0
        assert shell.screen.composer.value == "unfinished draft"
        assert "Review old action" not in _render(shell)
        await shell.close()
        assert [name for name, _ in client.calls] == ["attach", "detach"]

    asyncio.run(scenario())
