"""Small shared surface for renaming the current session."""

from __future__ import annotations

from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import InputEvent, InputIntent, RenderConstraints, RenderResult
from loushang.tui.ui_parts import TextInput


class SessionRenameSurface:
    """Edit a session name without exposing Product persistence details."""

    def __init__(self, *, current_name: str | None = None) -> None:
        self._input = TextInput(
            prompt="Name: ",
            placeholder="Enter a session name",
        )
        self._input.set_text(current_name or "")
        self._input.focus()

    @property
    def value(self) -> str:
        return self._input.value

    def focus(self) -> None:
        self._input.focus()

    def blur(self) -> None:
        self._input.blur()

    def editor_input_target(self) -> object:
        return self._input.editor_input_target()

    def handle_input(self, event: InputEvent) -> InputIntent[str] | None:
        if event.kind == "key" and event.key == "enter":
            return InputIntent(kind="select", text=self.value)
        if event.kind == "key" and event.key in {"esc", "escape"}:
            return None
        if self._input.handle_input(event):
            return InputIntent(kind="consumed", note="rename_input")
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self._input.render(constraints)


def build_session_rename_surface_view(
    *,
    current_name: str | None = None,
) -> ScreenSurfaceView:
    """Build the standard bottom rename prompt."""

    return ScreenSurfaceView(
        title="Rename session",
        subtitle="Set a name shown in the status line and session history",
        purpose="rename",
        content=SessionRenameSurface(current_name=current_name),
        footer="Enter rename · Esc cancel",
        presentation="bottom-exclusive",
        preferred_height=7,
    )


__all__ = ["SessionRenameSurface", "build_session_rename_surface_view"]
