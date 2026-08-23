from __future__ import annotations

from dataclasses import dataclass

from loushang.tui import (
    ExtensionHost,
    FakeTerminalPort,
    FooterView,
    InputEvent,
    InputIntent,
    PublicTuiApi,
    RenderConstraints,
    RenderLine,
    RenderResult,
    ScreenLayout,
    SelectionSurface,
    SelectItem,
    StatusField,
    Surface,
    SurfaceHost,
    TerminalOperation,
    TerminalSize,
    Tui,
    strip_control_sequences,
)


@dataclass(slots=True)
class StaticRenderable:
    text: str

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines([RenderLine(self.text)], constraints=constraints)


@dataclass(slots=True)
class ControlConsumer:
    events: list[InputEvent]

    def consume_control_events(self, events: tuple[InputEvent, ...]) -> None:
        self.events.extend(events)


def test_extension_widgets_render_in_named_slots_and_dispose_cleanly() -> None:
    host = ExtensionHost()
    api = PublicTuiApi(extension_id="ext", host=host)

    handle = api.set_widget("hint", StaticRenderable("hint"), placement="above_composer")

    assert host.widgets("above_composer") == (StaticRenderable("hint"),)

    handle.dispose()

    assert host.widgets("above_composer") == ()


def test_screen_layout_can_mount_extension_widgets_around_editor() -> None:
    host = ExtensionHost()
    api = PublicTuiApi(extension_id="ext", host=host)
    api.set_widget("above", StaticRenderable("above"), placement="above_composer")
    api.set_widget("below", StaticRenderable("below"), placement="below_composer")

    layout = ScreenLayout(
        editor=StaticRenderable("editor"),
        widgets_above_editor=host.widgets("above_composer"),
        widgets_below_editor=host.widgets("below_composer"),
    )

    assert tuple(region.name for region in layout.regions()) == (
        "widget_above_editor:0",
        "editor",
        "widget_below_editor:0",
    )
    assert tuple(line.text for line in layout.render(RenderConstraints(width=20, max_height=4)).lines) == (
        "above",
        "editor",
        "below",
    )


def test_extension_status_fields_are_exposed_by_priority_source() -> None:
    host = ExtensionHost()
    api = PublicTuiApi(extension_id="ext", host=host)

    api.set_status("quota", "weekly 72%", priority=20)

    assert host.status_fields() == (StatusField("weekly 72%", priority=20),)


def test_extension_status_fields_can_render_through_footer_view() -> None:
    host = ExtensionHost()
    api = PublicTuiApi(extension_id="ext", host=host)
    api.set_status("task", "Tasks 2/5", priority=100)

    footer = FooterView(primary="model idle", extension_statuses=host.status_fields())

    assert tuple(line.text for line in footer.render(RenderConstraints(width=32, max_height=3)).lines) == (
        "model idle",
        "Tasks 2/5",
    )


def test_extension_surface_is_owned_by_surface_host_and_removed_on_dispose() -> None:
    extension_host = ExtensionHost()
    surface_host = SurfaceHost()
    api = PublicTuiApi(extension_id="ext", host=extension_host, surface_host=surface_host)

    handle = api.open_surface("commands", Surface(SelectionSurface([SelectItem("Help", value="help")])))

    assert len(surface_host.entries) == 1

    handle.dispose()

    assert len(surface_host.entries) == 0


def test_extension_renderable_adapter_receives_constraints_not_terminal_port() -> None:
    seen_widths: list[int] = []
    api = PublicTuiApi(extension_id="ext", host=ExtensionHost())

    def render_plugin(constraints: RenderConstraints) -> list[str]:
        seen_widths.append(constraints.width)
        return ["plugin"]

    renderable = api.adapt_renderable(render_plugin)

    assert not hasattr(renderable, "terminal_port")
    assert tuple(line.text for line in renderable.render(RenderConstraints(width=20, max_height=2)).lines) == ("plugin",)
    assert seen_widths == [20]


def test_extension_input_adapter_receives_normalized_events_only() -> None:
    api = PublicTuiApi(extension_id="ext", host=ExtensionHost())
    renderable = api.adapt_renderable(
        lambda constraints: ["plugin"],
        on_input=lambda event: InputIntent(kind="select", text=event.key),
    )

    assert renderable.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="select", text="enter")
    assert not hasattr(renderable, "handle_raw_input")


def test_extension_input_adapter_preserves_owner_qualified_intent_kind() -> None:
    api = PublicTuiApi(extension_id="example_plugin", host=ExtensionHost())
    expected = InputIntent(
        kind="example_plugin.openArtifact",
        text="artifact-42",
        note="preview",
    )
    renderable = api.adapt_renderable(
        lambda constraints: ["plugin"],
        on_input=lambda event: expected,
    )

    assert renderable.handle_input(InputEvent(kind="key", key="enter")) is expected


def test_dispose_extension_removes_widgets_status_and_surfaces() -> None:
    extension_host = ExtensionHost()
    surface_host = SurfaceHost()
    api = PublicTuiApi(extension_id="ext", host=extension_host, surface_host=surface_host)

    api.set_widget("hint", StaticRenderable("hint"), placement="above_composer")
    api.set_status("quota", "weekly 72%", priority=20)
    api.set_footer(StaticRenderable("custom footer"))
    api.open_surface("commands", Surface(SelectionSurface([SelectItem("Help", value="help")])))

    extension_host.dispose_extension("ext")

    assert extension_host.widgets("above_composer") == ()
    assert extension_host.status_fields() == ()
    assert extension_host.footer() is None
    assert surface_host.entries == []


def test_tui_facade_composes_children_overlays_focus_and_input() -> None:
    tui = Tui()
    child_handle = tui.add_child(StaticRenderable("base"))
    surface = SelectionSurface([SelectItem("Help", value="help")])
    overlay_handle = tui.show_overlay(surface)

    assert surface.focused is True
    assert tuple(strip_control_sequences(line.text).rstrip() for line in tui.render(RenderConstraints(width=20, max_height=4)).lines) == (
        "> Help",
        "",
        "",
        "",
    )
    assert tui.handle_input(InputEvent(kind="key", key="enter")) == (InputIntent(kind="select", text="help"),)

    overlay_handle.close()
    child_handle.dispose()

    assert tui.render(RenderConstraints(width=20, max_height=4)).lines == ()


def test_tui_facade_routes_terminal_signals_to_terminal_context_before_input_listeners() -> None:
    consumer = ControlConsumer([])
    tui = Tui(terminal_context=consumer)
    seen: list[InputEvent] = []
    tui.add_input_listener(lambda event: seen.append(event) or True)
    event = InputEvent(kind="signal", signal="kitty_protocol", text="7")

    assert tui.handle_input(event) == ()
    assert seen == []
    assert consumer.events == [event]


def test_tui_facade_input_listeners_can_consume_events_before_surface_host() -> None:
    tui = Tui()
    event = InputEvent(kind="key", key="enter")
    seen: list[InputEvent] = []
    tui.show_overlay(SelectionSurface([SelectItem("Help", value="help")]))

    listener_handle = tui.add_input_listener(lambda input_event: seen.append(input_event) or True)

    assert tui.handle_input(event) == ()
    assert seen == [event]

    listener_handle.dispose()

    assert tui.handle_input(event) == (InputIntent(kind="select", text="help"),)


def test_tui_facade_input_listeners_can_rewrite_events_before_routing() -> None:
    tui = Tui()
    original = InputEvent(kind="key", key="tab")
    rewritten = InputEvent(kind="key", key="enter")
    seen: list[InputEvent] = []
    tui.show_overlay(SelectionSurface([SelectItem("Help", value="help")]))

    tui.add_input_listener(lambda event: {"event": rewritten} if event == original else None)
    tui.add_input_listener(lambda event: seen.append(event) or None)

    assert tui.handle_input(original) == (InputIntent(kind="select", text="help"),)
    assert seen == [rewritten]


def test_tui_facade_input_listener_rewrite_can_consume_empty_events() -> None:
    tui = Tui()
    seen: list[InputEvent] = []
    tui.show_overlay(SelectionSurface([SelectItem("Help", value="help")]))

    tui.add_input_listener(lambda _event: {"event": None})
    tui.add_input_listener(lambda event: seen.append(event) or None)

    assert tui.handle_input(InputEvent(kind="key", key="enter")) == ()
    assert seen == []


def test_tui_facade_can_request_render_and_render_now_with_attached_terminal() -> None:
    terminal = FakeTerminalPort(size=TerminalSize(columns=20, rows=4), frame_history_limit=None)
    tui = Tui(terminal=terminal)
    tui.add_child(StaticRenderable("base"))

    decision = tui.request_render("input")
    step = tui.render_now()

    assert decision.render_now is True
    assert step.frame is terminal.frames[-1]
    assert terminal.screen.visible_lines[0] == "base"


def test_tui_facade_title_and_progress_helpers_flush_terminal_operations() -> None:
    now = 0

    def now_ms() -> int:
        return now

    terminal = FakeTerminalPort(frame_history_limit=None)
    tui = Tui(terminal=terminal, now_ms=now_ms)

    title_frame = tui.set_title("Loushang")

    assert title_frame.operations == (TerminalOperation.set_title("Loushang"),)
    assert tui.set_progress(True) is True
    assert terminal.flushes[-1] == (TerminalOperation.set_progress(True),)
    assert tui.keep_progress_alive() is False

    now = 1_000

    assert tui.keep_progress_alive() is True
    assert terminal.flushes[-1] == (TerminalOperation.set_progress(True),)
    assert tui.set_progress(False) is True
    assert terminal.flushes[-1] == (TerminalOperation.set_progress(False),)
