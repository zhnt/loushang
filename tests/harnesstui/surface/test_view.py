from __future__ import annotations

from types import SimpleNamespace

from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    CursorDeclaration,
    InfoPanel,
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
)


class _Content:
    def __init__(self) -> None:
        self.last_event: InputEvent | None = None

    def handle_input(self, event: InputEvent) -> object:
        self.last_event = event
        return SimpleNamespace(kind="select", text="picked", note="child")

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            [RenderLine("choice")],
            constraints=constraints,
            cursor=CursorDeclaration(row=0, column=3),
        )


def test_screen_surface_view_preserves_content_cursor_and_translates_mouse_row() -> (
    None
):
    content = _Content()
    view = ScreenSurfaceView(
        title="Models", purpose="model", content=content, footer=""
    )

    rendered = view.render(RenderConstraints(width=40, max_height=8))
    intent = view.handle_input(
        InputEvent(kind="mouse", mouse_button=0, mouse_row=3, mouse_action="press")
    )

    assert rendered.cursor == CursorDeclaration(row=2, column=3)
    assert content.last_event is not None
    assert content.last_event.mouse_row == 1
    assert intent == InputIntent(kind="select", text="picked", note="child")


def test_screen_surface_view_scrolls_info_without_changing_copy_or_footer() -> None:
    view = ScreenSurfaceView(
        title="Models",
        purpose="info",
        content=InfoPanel(title="Models", text="one\ntwo\nthree\nfour"),
        footer="Esc to close",
    )

    first = view.render(RenderConstraints(width=40, max_height=6))
    intent = view.handle_input(InputEvent(kind="key", key="down"))
    second = view.render(RenderConstraints(width=40, max_height=6))

    assert tuple(line.text for line in first.lines) == (
        "Models",
        "",
        "one",
        "two",
        "",
        "Up/Down/Page to scroll - Esc to close",
    )
    assert intent == InputIntent(kind="consumed", note="info_scroll")
    assert tuple(line.text for line in second.lines) == (
        "Models",
        "",
        "two",
        "three",
        "",
        "Up/Down/Page to scroll - Esc to close",
    )


def test_screen_surface_view_info_close_keys_keep_existing_contract() -> None:
    view = ScreenSurfaceView(
        title="Info", purpose="info", content=InfoPanel(title="Info", text="body")
    )

    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="surface_close"
    )


def test_screen_surface_view_renders_feedback_inside_exclusive_surface() -> None:
    view = ScreenSurfaceView(
        title="Models",
        purpose="model",
        content=_Content(),
        feedback="Error: selected model does not support image input",
        feedback_hint="Choose another model or press Esc to keep the current model.",
        presentation="bottom-exclusive",
    )

    rendered = view.render(RenderConstraints(width=80, max_height=8))

    assert tuple(line.text for line in rendered.lines)[:6] == (
        "Models",
        "",
        "choice",
        "",
        "Error: selected model does not support image input",
        "Choose another model or press Esc to keep the current model.",
    )
