from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TypedDict, Unpack

from loushang.tui.core import RenderConstraints, RenderResult
from loushang.tui.extensions import ExtensionHandle
from loushang.tui.framework import (
    Container,
    Focusable,
    OverlayAnchor,
    Renderable,
    ScreenRoot,
    SizeValue,
    Surface,
    SurfaceHandle,
    SurfaceHost,
    SurfacePresentation,
)
from loushang.tui.playback import PlaybackStep
from loushang.tui.render_loop import RenderLoop
from loushang.tui.runtime import TuiRuntime
from loushang.tui.scheduler import RenderRequestKind, RenderScheduleDecision
from loushang.tui.terminal import (
    TerminalFrame,
    TerminalOperation,
    TerminalPort,
    TerminalProgressReporter,
    TerminalSize,
)

InputListener = Callable[[object], object]


class _SurfaceOptions(TypedDict, total=False):
    presentation: SurfacePresentation
    captures_focus: bool
    non_capturing: bool
    row: SizeValue | None
    column: SizeValue | None
    col: SizeValue | None
    width: SizeValue | None
    min_width: int | None
    max_height: SizeValue | None
    anchor: OverlayAnchor
    offset_x: int
    offset_y: int
    margin: int | dict[str, int] | None
    visible: Callable[[TerminalSize], bool] | None


@dataclass(slots=True)
class Tui:
    container: Container = field(default_factory=Container)
    surface_host: SurfaceHost = field(default_factory=SurfaceHost)
    terminal: TerminalPort | None = None
    terminal_context: object | None = None
    now_ms: Callable[[], int] | None = None
    _screen_root: ScreenRoot = field(init=False, repr=False)
    _runtime: TuiRuntime | None = field(default=None, init=False, repr=False)
    _progress_reporter: TerminalProgressReporter | None = field(default=None, init=False, repr=False)
    _input_listeners: list[InputListener] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._screen_root = ScreenRoot(base=self.container, surface_host=self.surface_host)

    def add_child(self, renderable: Renderable) -> ExtensionHandle:
        self.container.add_child(renderable)
        return ExtensionHandle(lambda: self._remove_child(renderable))

    def add_input_listener(self, listener: InputListener) -> ExtensionHandle:
        self._input_listeners.append(listener)
        return ExtensionHandle(lambda: self._remove_input_listener(listener))

    def attach_terminal(self, terminal: TerminalPort) -> None:
        self.terminal = terminal
        self._runtime = None
        self._progress_reporter = None

    def show_overlay(
        self,
        renderable: Renderable,
        *,
        focus_target: Focusable | None = None,
        **surface_options: Unpack[_SurfaceOptions],
    ) -> SurfaceHandle:
        target = focus_target or (renderable if isinstance(renderable, Focusable) else None)
        surface = Surface(renderable=renderable, focus_target=target, **surface_options)
        return self.surface_host.open_surface(surface)

    def set_focus(self, focus_target: Focusable | None) -> None:
        self.surface_host.base_focus = focus_target
        if focus_target is not None:
            self.surface_host._set_focus(focus_target)

    def handle_input(self, event: object) -> tuple[object, ...]:
        if getattr(event, "kind", "") == "signal":
            self._consume_terminal_control_event(event)
            return ()
        current = event
        for listener in tuple(self._input_listeners):
            consumed, current = _apply_input_listener_result(current, listener(current))
            if consumed:
                return ()
        return self.surface_host.route_input(current)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self._screen_root.render(constraints)

    def request_render(self, kind: RenderRequestKind = "input") -> RenderScheduleDecision:
        return self._ensure_runtime().request_render(kind)

    def render_now(self) -> PlaybackStep:
        return self._ensure_runtime().render_now()

    def set_title(self, title: str) -> TerminalFrame:
        return self._ensure_terminal().flush((TerminalOperation.set_title(title),))

    def set_progress(self, active: bool) -> bool:
        reporter = self._ensure_progress_reporter()
        return reporter.set_active(active)

    def keep_progress_alive(self) -> bool:
        return self._ensure_progress_reporter().keepalive()

    def _consume_terminal_control_event(self, event: object) -> None:
        consumer = getattr(self.terminal_context, "consume_control_events", None)
        if callable(consumer):
            consumer((event,))

    def _remove_child(self, renderable: Renderable) -> None:
        with suppress(ValueError):
            self.container.remove_child(renderable)

    def _remove_input_listener(self, listener: InputListener) -> None:
        with suppress(ValueError):
            self._input_listeners.remove(listener)

    def _ensure_runtime(self) -> TuiRuntime:
        terminal = self._ensure_terminal()
        if self._runtime is None:
            if self.now_ms is None:
                self._runtime = TuiRuntime(RenderLoop(self._screen_root), terminal)
            else:
                self._runtime = TuiRuntime(RenderLoop(self._screen_root), terminal, now_ms=self.now_ms)
        return self._runtime

    def _ensure_terminal(self) -> TerminalPort:
        if self.terminal is None:
            raise RuntimeError("terminal is required for this Tui operation")
        return self.terminal

    def _ensure_progress_reporter(self) -> TerminalProgressReporter:
        terminal = self._ensure_terminal()
        if self._progress_reporter is None:
            if self.now_ms is None:
                self._progress_reporter = TerminalProgressReporter(terminal)
            else:
                self._progress_reporter = TerminalProgressReporter(terminal, now_ms=self.now_ms)
        return self._progress_reporter


def _apply_input_listener_result(current: object, result: object) -> tuple[bool, object]:
    if result is True:
        return True, current
    if result is None or result is False:
        return False, current
    if isinstance(result, Mapping):
        if result.get("consume") is True:
            return True, current
        for key in ("event", "data"):
            if key in result:
                return _replacement_result(result[key])
        return False, current
    consume = getattr(result, "consume", None)
    if consume is True:
        return True, current
    for attr in ("event", "data"):
        if hasattr(result, attr):
            return _replacement_result(getattr(result, attr))
    return False, current


def _replacement_result(replacement: object) -> tuple[bool, object]:
    if replacement is None or replacement == "":
        return True, replacement
    return False, replacement


__all__ = ["InputListener", "Tui"]
