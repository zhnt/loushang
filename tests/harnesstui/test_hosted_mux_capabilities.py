from __future__ import annotations

import asyncio

import pytest

from loushang.tui.core import RenderConstraints
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import _Client
from .test_hosted_mux_shell import _shell


@pytest.mark.parametrize("changed", ["closing", "snapshot", "membership", "content"])
def test_current_capabilities_replace_same_binding_eligibility_without_transcript_change(changed):
    async def run():
        shell = _shell(_Client())
        await shell.start()
        try:
            window = shell.state.active_window
            window.pending_interaction_id = "interaction"
            window.pending_interaction_text = "Approve this exact action"
            constraints = RenderConstraints(width=160, max_height=100)
            shell.screen.show_approval()
            shell.screen.render(constraints)
            old = shell.current_capabilities()
            assert old.get("approve", binding_key=old.binding_key).availability == "available"
            cursor = window.last_cursor
            shell.screen.show_help()
            if changed == "closing":
                shell._closing = True
            elif changed == "snapshot":
                shell.state.snapshot_required = True
            elif changed == "membership":
                shell._membership_pending = True
            else:
                window.pending_interaction_text = "Changed action"
            rendered = shell.screen.render(constraints)
            current = shell.screen.state.capabilities
            assert current.binding_key == old.binding_key
            assert window.last_cursor == cursor
            assert current.get("approve", binding_key=current.binding_key).availability == "unavailable"
            text = "\n".join(line.text for line in rendered.lines)
            for command in ("lmux new -s NAME", "lmux ls", "lmux attach -t NAME",
                            "lmux close -t NAME", "lmux stop --server NAME",
                            "lmux create --continue"):
                assert command in text
            assert "create/list/attach/close/stop" not in text
            assert "approve: unavailable" in text
            assert "approve: available" not in text
            assert "approve" not in {item.name for item in shell._completion.commands}
            # Reading the old value has no publication path back to the view.
            assert old.get("approve", binding_key=old.binding_key).availability == "available"
            assert shell.current_capabilities() == current
            if changed == "snapshot":
                shell.state.snapshot_required = False
                restored = shell.current_capabilities()
                assert restored.get("approve", binding_key=restored.binding_key).reason == "presentation_required"
        finally:
            await shell.close()
    asyncio.run(run())


def test_unpresented_approval_keeps_deny_and_details_available():
    async def run():
        shell = _shell(_Client())
        await shell.start()
        try:
            window = shell.state.active_window
            window.pending_interaction_id = "interaction"
            window.pending_interaction_text = "Exact action"
            value = shell.current_capabilities()
            assert value.get("deny", binding_key=value.binding_key).availability == "available"
            assert value.get("approval_details", binding_key=value.binding_key).availability == "read_only"
            assert value.get("approve", binding_key=value.binding_key).reason == "presentation_required"
            assert value.get("image_paste", binding_key=value.binding_key).reason == "protocol_unavailable"
            shell.refresh_capability_completions()
            names = {item.name for item in shell._completion.commands}
            assert {"deny", "question"} <= names and "approve" not in names
            assert not shell._completion.complete("/approve")
            assert shell._completion.complete("/deny")
            constraints = RenderConstraints(width=160, max_height=100)
            shell.screen.show_approval()
            shell.screen.render(constraints)
            shell.screen.dismiss_details()
            shell.screen.render(constraints)
            assert "approve" in {item.name for item in shell._completion.commands}
            assert shell._completion.complete("/approve")
            shell.handle(InputEvent(kind="key", key="ctrl+b"))
            shell.handle(InputEvent(kind="text", text="2"))
            current = shell.current_capabilities()
            assert value.get("deny", binding_key=current.binding_key).reason == "binding_changed"
            shell.screen.render(constraints)
            assert "approve" not in {item.name for item in shell._completion.commands}
            assert not shell._completion.complete("/approve")
            shell.handle(InputEvent(kind="key", key="ctrl+b"))
            shell.handle(InputEvent(kind="text", text="1"))
            returned = shell.current_capabilities()
            assert returned.binding_key == value.binding_key
            assert returned.get("approve", binding_key=returned.binding_key).reason == "presentation_required"
            assert shell._completion.complete("/deny")
            assert not shell._completion.complete("/approve")
            calls = len(shell._client.calls)
            shell._command("/approve")
            assert len(shell._client.calls) == calls
            assert "Present all approval details" in shell.notice
        finally:
            await shell.close()
    asyncio.run(run())
