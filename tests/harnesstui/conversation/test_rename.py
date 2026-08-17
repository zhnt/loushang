from __future__ import annotations

from loushang.harnesstui.conversation.rename import (
    SessionRenameSurface,
    build_session_rename_surface_view,
)
from loushang.tui import InputEvent, RenderConstraints


def test_session_rename_surface_edits_and_submits_name() -> None:
    surface = SessionRenameSurface()

    consumed = surface.handle_input(InputEvent(kind="text", text="Project Alpha"))
    selected = surface.handle_input(InputEvent(kind="key", key="enter"))

    assert consumed is not None
    assert consumed.kind == "consumed"
    assert selected is not None
    assert selected.kind == "select"
    assert selected.text == "Project Alpha"


def test_session_rename_view_prefills_current_name() -> None:
    view = build_session_rename_surface_view(current_name="Existing")

    result = view.render(RenderConstraints(width=80, max_height=7))

    assert view.purpose == "rename"
    assert view.presentation == "bottom-exclusive"
    assert "Name: Existing" in "\n".join(line.text for line in result.lines)
