from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from loushang.tui import (
    ApprovalSurface,
    CommandSurface,
    Container,
    CursorDeclaration,
    DialogSurface,
    FakeTerminalPort,
    FocusableMixin,
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderLoop,
    RenderResult,
    ScreenRoot,
    SelectItem,
    Surface,
    SurfaceHost,
    TerminalSize,
    TuiRuntime,
    surface_is_bottom_exclusive,
    surface_is_page_presentation,
)
from loushang.tui.cell_width import strip_control_sequences, visible_width


@dataclass
class TextRenderable:
    lines: tuple[str, ...]
    seen_constraints: list[RenderConstraints]

    def render(self, constraints: RenderConstraints) -> RenderResult:
        self.seen_constraints.append(constraints)
        return RenderResult.from_lines(
            [RenderLine(line) for line in self.lines], constraints=constraints
        )


class FocusTarget(FocusableMixin):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.events: list[Any] = []

    def handle_input(self, event: Any) -> str:
        self.events.append(event)
        return f"{self.name}:{event}"


class ReturningFocusTarget(FocusableMixin):
    def __init__(self, result: Any) -> None:
        super().__init__()
        self.result = result
        self.events: list[Any] = []

    def handle_input(self, event: Any) -> Any:
        self.events.append(event)
        return self.result


class EditorProviderFocusTarget(FocusTarget):
    def __init__(self, name: str, target: object | None) -> None:
        super().__init__(name)
        self.target = target

    def editor_input_target(self) -> object | None:
        return self.target


@dataclass
class BaselineResetRenderable(TextRenderable):
    reset_reason: str | None = None

    def consume_render_baseline_reset_reason(self) -> str | None:
        reason = self.reset_reason
        self.reset_reason = None
        return reason


@dataclass
class CursorRenderable(TextRenderable):
    cursor: CursorDeclaration | None = None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        self.seen_constraints.append(constraints)
        return RenderResult.from_lines(
            [RenderLine(line) for line in self.lines],
            constraints=constraints,
            cursor=self.cursor,
        )


def test_container_renders_children_in_order_and_propagates_remaining_constraints() -> (
    None
):
    first = TextRenderable(("one", "two"), [])
    second = TextRenderable(("three",), [])
    container = Container([first, second])

    result = container.render(RenderConstraints(width=10, max_height=3))

    assert tuple(line.text for line in result.lines) == ("one", "two", "three")
    assert first.seen_constraints == [RenderConstraints(width=10, max_height=3)]
    assert second.seen_constraints == [RenderConstraints(width=10, max_height=1)]


def test_container_propagates_remaining_visible_height_to_children() -> None:
    first = TextRenderable(("one",), [])
    second = TextRenderable(("two",), [])
    container = Container([first, second])

    container.render(RenderConstraints(width=10, max_height=1000, visible_height=4))

    assert first.seen_constraints == [
        RenderConstraints(width=10, max_height=1000, visible_height=4)
    ]
    assert second.seen_constraints == [
        RenderConstraints(width=10, max_height=999, visible_height=3)
    ]


def test_container_offsets_child_cursor_by_previous_children() -> None:
    first = TextRenderable(("one", "two"), [])
    second = CursorRenderable(("edit",), [], cursor=CursorDeclaration(row=0, column=4))
    container = Container([first, second])

    result = container.render(RenderConstraints(width=10, max_height=3))

    assert result.cursor == CursorDeclaration(row=2, column=4)


def test_screen_root_preserves_base_cursor_when_no_surface_is_visible() -> None:
    base = CursorRenderable(
        ("› ", "", "status"), [], cursor=CursorDeclaration(row=0, column=2)
    )
    screen_root = ScreenRoot(base=base, surface_host=SurfaceHost())

    result = screen_root.render(RenderConstraints(width=20, max_height=5))

    assert tuple(line.text for line in result.lines) == ("› ", "", "status")
    assert result.cursor == CursorDeclaration(row=0, column=2)


@pytest.mark.tui_render_contract
def test_surface_host_preserves_base_result_identity_without_visible_surfaces() -> None:
    composer = FocusTarget("composer")
    hidden_focus = FocusTarget("hidden")
    composer.focus()
    host = SurfaceHost(base_focus=composer)
    handle = host.open_surface(
        Surface(
            renderable=TextRenderable(("hidden",), []),
            focus_target=hidden_focus,
            visible=lambda size: size.columns > 20,
        )
    )
    handle.focus()
    handle.entry.last_row = 3
    handle.entry.last_column = 4
    base = RenderResult(
        lines=(RenderLine("base"),),
        cursor=CursorDeclaration(row=0, column=4),
    )

    result = host.compose(base, RenderConstraints(width=20, max_height=5))

    assert result is base
    assert host._last_size == TerminalSize(columns=20, rows=5)
    assert composer.focused is True
    assert hidden_focus.focused is False
    assert handle.entry.last_row is None
    assert handle.entry.last_column is None


def test_surface_host_captures_and_restores_focus() -> None:
    composer = FocusTarget("composer")
    dialog_focus = FocusTarget("dialog")
    composer.focus()
    host = SurfaceHost(base_focus=composer)

    handle = host.open_surface(
        Surface(renderable=TextRenderable(("dialog",), []), focus_target=dialog_focus)
    )

    assert composer.focused is False
    assert dialog_focus.focused is True
    assert host.handle_input("enter") == "dialog:enter"
    assert dialog_focus.events == ["enter"]

    handle.close("escape")

    assert handle.close_reason == "escape"
    assert dialog_focus.focused is False
    assert composer.focused is True


def test_stacked_surface_close_restores_next_surface_focus() -> None:
    composer = FocusTarget("composer")
    first_focus = FocusTarget("first")
    second_focus = FocusTarget("second")
    composer.focus()
    host = SurfaceHost(base_focus=composer)

    host.open_surface(
        Surface(renderable=TextRenderable(("first",), []), focus_target=first_focus)
    )
    second = host.open_surface(
        Surface(renderable=TextRenderable(("second",), []), focus_target=second_focus)
    )

    assert first_focus.focused is False
    assert second_focus.focused is True

    second.close("cancel")

    assert first_focus.focused is True
    assert second_focus.focused is False
    assert composer.focused is False


def test_surface_host_routes_close_intent_and_restores_base_focus() -> None:
    composer = FocusTarget("composer")
    command = CommandSurface([SelectItem("/model", value="/model")])
    composer.focus()
    host = SurfaceHost(base_focus=composer)
    handle = host.open_surface(Surface(renderable=command, focus_target=command))

    intents = host.route_input(InputEvent(kind="key", key="escape"))

    assert intents == (InputIntent(kind="surface_close"),)
    assert host.entries == []
    assert command.focused is False
    assert composer.focused is True
    assert handle.entry.close_reason == "surface_close"


def test_surface_host_route_input_result_preserves_consumption_without_changing_route_input() -> (
    None
):
    cases: tuple[tuple[Any, tuple[Any, ...], bool], ...] = (
        (None, (), False),
        (False, (), False),
        (True, (), True),
        ("handled", ("handled",), True),
        (("handled",), ("handled",), True),
    )
    for result, expected_intents, expected_consumed in cases:
        target = ReturningFocusTarget(result)
        host = SurfaceHost()
        host.open_surface(
            Surface(renderable=TextRenderable(("surface",), []), focus_target=target)
        )

        routed = host.route_input_result("x")

        assert routed.intents == expected_intents
        assert routed.consumed is expected_consumed
        assert host.route_input("x") == expected_intents


def test_surface_host_route_input_result_closes_on_close_intent() -> None:
    target = ReturningFocusTarget(InputIntent(kind="surface_close"))
    host = SurfaceHost()
    handle = host.open_surface(
        Surface(renderable=TextRenderable(("surface",), []), focus_target=target)
    )

    routed = host.route_input_result(InputEvent(kind="key", key="escape"))

    assert routed.intents == (InputIntent(kind="surface_close"),)
    assert routed.consumed is True
    assert host.entries == []
    assert handle.entry.close_reason == "surface_close"


def test_surface_host_returns_current_visible_surface_editor_target() -> None:
    editor_target = object()
    focus = EditorProviderFocusTarget("editor", editor_target)
    host = SurfaceHost()
    host.open_surface(
        Surface(renderable=TextRenderable(("editor",), []), focus_target=focus)
    )

    assert host.current_editor_target() is editor_target


def test_surface_host_ignores_base_hidden_and_closed_editor_targets() -> None:
    base_target = object()
    base = EditorProviderFocusTarget("base", base_target)
    base.focus()
    focus = EditorProviderFocusTarget("editor", object())
    host = SurfaceHost(base_focus=base)

    assert host.current_editor_target() is None

    handle = host.open_surface(
        Surface(renderable=TextRenderable(("editor",), []), focus_target=focus)
    )
    assert host.current_editor_target() is focus.target

    handle.set_hidden(True)
    assert host.current_editor_target() is None

    handle.set_hidden(False)
    assert host.current_editor_target() is focus.target

    handle.close("done")
    assert host.current_editor_target() is None


def test_surface_host_translates_overlay_mouse_coordinates_to_focus_target() -> None:
    target = FocusTarget("overlay")
    host = SurfaceHost()
    host.open_surface(
        Surface(
            renderable=TextRenderable(("one", "two"), []),
            focus_target=target,
            presentation="overlay",
            row=2,
            column=3,
        )
    )

    host.compose(
        RenderResult.from_lines(
            (RenderLine("base"),), constraints=RenderConstraints(width=12, max_height=6)
        ),
        RenderConstraints(width=12, max_height=6),
    )

    host.route_input(
        InputEvent(
            kind="mouse",
            mouse_button=0,
            mouse_column=5,
            mouse_row=3,
            mouse_action="press",
        )
    )

    assert isinstance(target.events[-1], InputEvent)
    assert target.events[-1].mouse_row == 1
    assert target.events[-1].mouse_column == 2


def test_surface_host_can_close_on_call_site_intent_policy() -> None:
    composer = FocusTarget("composer")
    composer.focus()
    host = SurfaceHost(base_focus=composer)

    command = CommandSurface([SelectItem("/model", value="/model")])
    host.open_surface(Surface(renderable=command, focus_target=command))
    command_intents = host.route_input(
        InputEvent(kind="key", key="enter"), close_on_intents=("command",)
    )

    settings_target = ReturningFocusTarget(
        InputIntent(kind="setting", text="statusline", note="true")
    )
    host.open_surface(
        Surface(
            renderable=TextRenderable(("statusline",), []),
            focus_target=settings_target,
        )
    )
    setting_intents = host.route_input(
        InputEvent(kind="key", key="enter"), close_on_intents=("setting",)
    )

    approval = ApprovalSurface(action="Run command")
    host.open_surface(Surface(renderable=approval, focus_target=approval))
    approval_intents = host.route_input(
        InputEvent(kind="key", key="y"),
        close_on_intents=("approval_decision",),
    )

    dialog = DialogSurface(title="Confirm")
    host.open_surface(Surface(renderable=dialog, focus_target=dialog))
    dialog_intents = host.route_input(
        InputEvent(kind="key", key="enter"),
        close_on_intents=("dialog_confirm", "dialog_cancel"),
    )

    assert command_intents == (InputIntent(kind="command", text="/model"),)
    assert setting_intents == (
        InputIntent(kind="setting", text="statusline", note="true"),
    )
    assert approval_intents == (
        InputIntent(kind="approval_decision", text="allow_once"),
    )
    assert dialog_intents == (InputIntent(kind="dialog_confirm"),)
    assert host.entries == []
    assert composer.focused is True


def test_non_capturing_overlay_does_not_steal_base_focus() -> None:
    composer = FocusTarget("composer")
    overlay_focus = FocusTarget("overlay")
    composer.focus()
    host = SurfaceHost(base_focus=composer)

    host.open_surface(
        Surface(
            renderable=TextRenderable(("overlay",), []),
            focus_target=overlay_focus,
            captures_focus=False,
        )
    )

    assert composer.focused is True
    assert overlay_focus.focused is False
    assert host.handle_input("x") == "composer:x"


def test_screen_root_composes_overlay_surfaces_before_render_loop_diffing() -> None:
    base = TextRenderable(("one", "two"), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)
    runtime = TuiRuntime(
        render_loop=RenderLoop(screen_root),
        terminal=FakeTerminalPort(size=TerminalSize(columns=10, rows=5)),
    )
    runtime.render_now()

    host.open_surface(
        Surface(
            renderable=TextRenderable(("XX",), []),
            presentation="overlay",
            row=1,
            column=0,
            captures_focus=False,
        )
    )
    step = runtime.render_now()

    step.assert_operation_class("changed_range_update")
    assert step.diagnostics.current_logical_lines == ("one", "XXo", "", "", "")
    assert step.diagnostics.changed_line_range == (1, 1)


def test_runtime_can_open_overlay_for_plain_screen_root() -> None:
    base = TextRenderable(("one", "two"), [])
    runtime = TuiRuntime(
        render_loop=RenderLoop(base),
        terminal=FakeTerminalPort(size=TerminalSize(columns=10, rows=5)),
    )

    runtime.open_surface(
        Surface(
            renderable=TextRenderable(("XX",), []),
            presentation="overlay",
            row=1,
            column=0,
            captures_focus=False,
        )
    )
    step = runtime.render_now()

    assert step.diagnostics.current_logical_lines == ("one", "XXo", "", "", "")


def test_runtime_reuses_existing_screen_root_surface_host() -> None:
    base = TextRenderable(("base",), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)
    runtime = TuiRuntime(
        render_loop=RenderLoop(screen_root),
        terminal=FakeTerminalPort(size=TerminalSize(columns=10, rows=3)),
    )

    runtime.open_surface(
        Surface(
            renderable=TextRenderable(("OV",), []),
            row=0,
            column=0,
            captures_focus=False,
        )
    )

    assert runtime.overlay_host() is host
    assert len(host.entries) == 1


def test_runtime_routes_input_to_overlay_surface_host() -> None:
    composer = FocusTarget("composer")
    command = CommandSurface([SelectItem("/model", value="/model")])
    composer.focus()
    runtime = TuiRuntime(
        render_loop=RenderLoop(TextRenderable(("base",), [])),
        terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=4)),
    )
    runtime.overlay_host().base_focus = composer
    runtime.open_surface(Surface(renderable=command, focus_target=command))

    intents = runtime.route_surface_input(
        InputEvent(kind="key", key="enter"), close_on_intents=("command",)
    )

    assert intents == (InputIntent(kind="command", text="/model"),)
    assert runtime.overlay_host().entries == []
    assert composer.focused is True


def test_runtime_overlay_wrapper_preserves_base_baseline_reset_signal() -> None:
    base = BaselineResetRenderable(("base",), [])
    runtime = TuiRuntime(
        render_loop=RenderLoop(base),
        terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=4)),
    )
    runtime.open_surface(
        Surface(
            renderable=TextRenderable(("OV",), []),
            row=0,
            column=0,
            captures_focus=False,
        )
    )
    runtime.render_now()

    base.reset_reason = "test_reset"
    step = runtime.render_now()

    step.assert_operation_class("baseline_repaint")


def test_surface_host_treats_modal_presentation_as_overlay() -> None:
    base = TextRenderable(("base", "line"), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)

    host.open_surface(
        Surface(
            renderable=TextRenderable(("MODAL",), []),
            presentation="modal",
            row=1,
            column=0,
            captures_focus=False,
        )
    )

    result = screen_root.render(RenderConstraints(width=10, max_height=4))

    assert tuple(line.text for line in result.lines) == ("base", "MODAL", "", "")


def test_surface_bottom_exclusive_presentation_is_a_formal_helper() -> None:
    surface = Surface(
        renderable=TextRenderable(("Select Model",), []),
        presentation="bottom-exclusive",
    )

    assert surface_is_bottom_exclusive(surface) is True


def test_page_surface_replaces_base_and_receives_the_full_viewport() -> None:
    base_renders: list[RenderConstraints] = []
    page_renders: list[RenderConstraints] = []
    base = TextRenderable(("base",), base_renders)
    page = TextRenderable(("Resume", "row"), page_renders)
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)
    surface = Surface(
        renderable=page,
        presentation="page",
        captures_focus=False,
    )
    host.open_surface(surface)

    result = screen_root.render(
        RenderConstraints(width=20, max_height=5, visible_height=5)
    )

    assert base_renders == []
    assert page_renders == [RenderConstraints(width=20, max_height=5, visible_height=5)]
    assert tuple(line.text for line in result.lines) == (
        "Resume",
        "row",
        "",
        "",
        "",
    )
    assert surface_is_page_presentation(surface) is True


def test_newer_overlay_renders_above_page_but_older_overlay_stays_below() -> None:
    host = SurfaceHost()
    host.open_surface(
        Surface(
            renderable=TextRenderable(("OLD",), []),
            presentation="overlay",
            row=0,
            column=0,
            captures_focus=False,
        )
    )
    host.open_surface(
        Surface(
            renderable=TextRenderable(("PAGE",), []),
            presentation="page",
            captures_focus=False,
        )
    )
    host.open_surface(
        Surface(
            renderable=TextRenderable(("NEW",), []),
            presentation="overlay",
            row=1,
            column=0,
            captures_focus=False,
        )
    )

    result = host.compose(
        RenderResult.from_text(
            "base",
            constraints=RenderConstraints(width=10, max_height=3),
        ),
        RenderConstraints(width=10, max_height=3),
    )

    assert tuple(line.text for line in result.lines) == ("PAGE", "NEW", "")


def test_surface_handle_can_hide_show_focus_and_unfocus_overlay() -> None:
    composer = FocusTarget("composer")
    first_focus = FocusTarget("first")
    second_focus = FocusTarget("second")
    composer.focus()
    host = SurfaceHost(base_focus=composer)
    host.open_surface(
        Surface(renderable=TextRenderable(("first",), []), focus_target=first_focus)
    )
    second = host.open_surface(
        Surface(renderable=TextRenderable(("second",), []), focus_target=second_focus)
    )

    assert second.is_focused() is True

    second.set_hidden(True)

    assert second.is_hidden() is True
    assert first_focus.focused is True
    assert second_focus.focused is False

    second.set_hidden(False)

    assert second.is_hidden() is False
    assert second_focus.focused is True
    assert first_focus.focused is False

    second.unfocus()

    assert first_focus.focused is True
    assert second_focus.focused is False

    second.focus()

    assert second_focus.focused is True
    assert second.is_focused() is True


def test_overlay_visibility_callback_controls_render_and_focus() -> None:
    focus = FocusTarget("dialog")
    host = SurfaceHost()
    handle = host.open_surface(
        Surface(
            renderable=TextRenderable(("dialog",), []),
            focus_target=focus,
            visible=lambda size: size.columns >= 20,
        )
    )

    hidden_result = host.compose(
        RenderResult.from_text(
            "base", constraints=RenderConstraints(width=10, max_height=5)
        ),
        RenderConstraints(width=10, max_height=5),
    )

    assert tuple(line.text for line in hidden_result.lines) == ("base",)
    assert focus.focused is False
    assert handle.is_focused() is False

    visible_result = host.compose(
        RenderResult.from_text(
            "base", constraints=RenderConstraints(width=30, max_height=5)
        ),
        RenderConstraints(width=30, max_height=5),
    )

    assert tuple(line.text for line in visible_result.lines)[0] == "dialog"
    assert focus.focused is True


def test_surface_host_syncs_overlay_visibility_before_routing_input() -> None:
    visible = True
    base_focus = FocusTarget("base")
    overlay_focus = FocusTarget("overlay")
    base_focus.focus()
    host = SurfaceHost(base_focus=base_focus)
    handle = host.open_surface(
        Surface(
            renderable=TextRenderable(("dialog",), []),
            focus_target=overlay_focus,
            visible=lambda _size: visible,
        )
    )
    host.compose(
        RenderResult.from_text(
            "base", constraints=RenderConstraints(width=30, max_height=5)
        ),
        RenderConstraints(width=30, max_height=5),
    )
    handle.focus()

    assert overlay_focus.focused is True

    visible = False

    assert host.route_input("x") == ("base:x",)
    assert base_focus.focused is True
    assert overlay_focus.focused is False


def test_overlay_composition_pads_to_visible_height_and_clips_to_width() -> None:
    base = TextRenderable(("base",), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)

    host.open_surface(
        Surface(
            renderable=TextRenderable(("abcdef",), []),
            row=4,
            column=3,
            width=4,
            captures_focus=False,
        )
    )

    result = screen_root.render(RenderConstraints(width=8, max_height=5))

    assert tuple(line.text for line in result.lines) == ("base", "", "", "", "   abcd")


def test_overlay_anchor_percentage_size_and_margin_follow_pi_layout_rules() -> None:
    base = TextRenderable(("base",), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)

    host.open_surface(
        Surface(
            renderable=TextRenderable(("abcdef", "ghijkl"), []),
            anchor="bottom-right",
            width="50%",
            max_height="50%",
            margin=1,
            offset_x=-1,
            offset_y=-1,
            captures_focus=False,
        )
    )

    result = screen_root.render(RenderConstraints(width=12, max_height=6))

    assert tuple(line.text for line in result.lines) == (
        "base",
        "",
        "    abcdef",
        "    ghijkl",
        "",
        "",
    )


def test_overlay_explicit_percentage_position_is_clamped_inside_margins() -> None:
    base = TextRenderable(("base",), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)

    host.open_surface(
        Surface(
            renderable=TextRenderable(("OV",), []),
            row="100%",
            col="100%",
            width=4,
            margin={"right": 2, "bottom": 1},
            captures_focus=False,
        )
    )

    result = screen_root.render(RenderConstraints(width=10, max_height=4))

    assert tuple(line.text for line in result.lines) == ("base", "", "    OV  ", "")


def test_non_capturing_alias_matches_pi_overlay_option() -> None:
    composer = FocusTarget("composer")
    overlay_focus = FocusTarget("overlay")
    composer.focus()
    host = SurfaceHost(base_focus=composer)

    host.open_surface(
        Surface(
            renderable=TextRenderable(("overlay",), []),
            focus_target=overlay_focus,
            non_capturing=True,
        )
    )

    assert composer.focused is True
    assert overlay_focus.focused is False
    assert host.handle_input("x") == "composer:x"


def test_focus_order_controls_overlay_z_order() -> None:
    first_focus = FocusTarget("first")
    second_focus = FocusTarget("second")
    host = SurfaceHost()
    first = host.open_surface(
        Surface(
            renderable=TextRenderable(("111",), []),
            focus_target=first_focus,
            row=0,
            column=0,
        )
    )
    host.open_surface(
        Surface(
            renderable=TextRenderable(("222",), []),
            focus_target=second_focus,
            row=0,
            column=0,
        )
    )

    before = host.compose(
        RenderResult.from_text(
            "base", constraints=RenderConstraints(width=10, max_height=3)
        ),
        RenderConstraints(width=10, max_height=3),
    )
    first.focus()
    after = host.compose(
        RenderResult.from_text(
            "base", constraints=RenderConstraints(width=10, max_height=3)
        ),
        RenderConstraints(width=10, max_height=3),
    )

    assert tuple(line.text for line in before.lines)[0] == "222e"
    assert tuple(line.text for line in after.lines)[0] == "111e"


def test_inline_surface_renders_after_base_before_overlays() -> None:
    base = TextRenderable(("base",), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)
    host.open_surface(
        Surface(
            renderable=TextRenderable(("inline",), []),
            presentation="inline",
            captures_focus=False,
        )
    )
    host.open_surface(
        Surface(
            renderable=TextRenderable(("OV",), []),
            row=1,
            column=0,
            captures_focus=False,
        )
    )

    result = screen_root.render(RenderConstraints(width=10, max_height=5))

    assert tuple(line.text for line in result.lines) == ("base", "OVline", "", "", "")


def test_overlay_row_is_relative_to_visible_viewport_when_base_exceeds_screen_height() -> (
    None
):
    base = TextRenderable(("line0", "line1", "line2", "line3", "line4"), [])
    host = SurfaceHost()
    screen_root = ScreenRoot(base=base, surface_host=host)
    host.open_surface(
        Surface(
            renderable=TextRenderable(("OV",), []),
            row=1,
            column=0,
            captures_focus=False,
        )
    )

    result = screen_root.render(
        RenderConstraints(width=10, max_height=10, visible_height=3)
    )

    assert tuple(line.text for line in result.lines) == (
        "line0",
        "line1",
        "line2",
        "OVne3",
        "line4",
    )


def test_overlay_composition_skips_terminal_image_base_lines() -> None:
    from loushang.tui.framework import _overlay_text

    image_line = "\x1b_Gi=1;AAAA\x1b\\"

    assert (
        _overlay_text(image_line, "OV", column=0, overlay_width=2, total_width=20)
        == image_line
    )


def test_overlay_composition_slices_by_terminal_columns_not_python_indexes() -> None:
    from loushang.tui.framework import _overlay_text

    result = _overlay_text("中ABCD", "XY", column=2, overlay_width=2, total_width=12)

    assert result == "中XYCD"
    assert visible_width(result) == 6


def test_overlay_composition_clips_wide_overlay_by_cell_width() -> None:
    from loushang.tui.framework import _overlay_text

    result = _overlay_text("abcdef", "中Z", column=1, overlay_width=2, total_width=12)

    assert result == "a中def"
    assert visible_width(result) == 6


def test_overlay_composition_preserves_ansi_suffix_style_after_overlay() -> None:
    from loushang.tui.framework import _overlay_text

    result = _overlay_text(
        "\x1b[31m中ABCD\x1b[39m", "XY", column=2, overlay_width=2, total_width=12
    )

    assert strip_control_sequences(result) == "中XYCD"
    assert "\x1b[31mCD" in result
