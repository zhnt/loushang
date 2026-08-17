from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from loushang.foundation.observability import get_log
from loushang.tui.framework import ScreenRoot as OverlayScreenRoot
from loushang.tui.framework import Surface, SurfaceHandle, SurfaceHost
from loushang.tui.playback import PlaybackEvent, PlaybackStep
from loushang.tui.render_loop import RenderLoop
from loushang.tui.scheduler import (
    AnimationFrameSource,
    RenderRequestKind,
    RenderScheduleDecision,
    RenderScheduler,
)
from loushang.tui.terminal import TerminalPort

_log = get_log(__name__).bind(component="TuiRuntime")


@dataclass(slots=True)
class TuiRuntime:
    render_loop: RenderLoop
    terminal: TerminalPort
    scheduler: RenderScheduler = field(default_factory=RenderScheduler)
    now_ms: Callable[[], int] = field(default_factory=lambda: _monotonic_ms)
    _step_index: int = 0
    _pending_render_due_ms: int | None = field(default=None, init=False, repr=False)
    _overlay_host: SurfaceHost | None = field(default=None, init=False, repr=False)

    def render_now(self) -> PlaybackStep:
        render_started = time.perf_counter()
        size = self.terminal.size()
        self._consume_screen_root_baseline_reset()
        plan_started = time.perf_counter()
        diagnostics = self.render_loop.plan(size)
        plan_ms = (time.perf_counter() - plan_started) * 1000
        flush_started = time.perf_counter()
        frame = self.terminal.flush(diagnostics.operations)
        flush_ms = (time.perf_counter() - flush_started) * 1000
        self.render_loop.commit(diagnostics, size=size)
        self._pending_render_due_ms = None
        rendered_at_ms = self.now_ms()
        self.scheduler.mark_rendered(now_ms=rendered_at_ms)
        step = PlaybackStep(
            index=self._step_index,
            event=PlaybackEvent("render"),
            size=size,
            diagnostics=diagnostics,
            frame=frame,
        )
        self._step_index += 1
        changed_start, changed_end = diagnostics.changed_line_range or (None, None)
        _log.debug_event(
            "tui",
            "render.frame",
            operation_class=diagnostics.operation_class,
            logical_line_count=len(diagnostics.current_logical_lines),
            previous_line_count=len(diagnostics.previous_rendered_lines),
            operation_count=len(diagnostics.operations),
            changed_start=changed_start,
            changed_end=changed_end,
            viewport_top=diagnostics.viewport_top,
            previous_viewport_top=diagnostics.previous_viewport_top,
            plan_ms=round(plan_ms, 3),
            flush_ms=round(flush_ms, 3),
            total_ms=round((time.perf_counter() - render_started) * 1000, 3),
        )
        return step

    def overlay_host(self) -> SurfaceHost:
        """Return the runtime-owned overlay host, wrapping plain roots on first use."""
        if self._overlay_host is not None:
            return self._overlay_host
        existing = getattr(self.render_loop.screen_root, "surface_host", None)
        if isinstance(existing, SurfaceHost):
            self._overlay_host = existing
            return existing
        host = SurfaceHost()
        self.render_loop.screen_root = OverlayScreenRoot(
            base=self.render_loop.screen_root,
            surface_host=host,
        )
        self._overlay_host = host
        return host

    def open_surface(self, surface: Surface) -> SurfaceHandle:
        return self.overlay_host().open_surface(surface)

    def route_surface_input(
        self,
        event: Any,
        *,
        close_on_intents: tuple[str, ...] = ("surface_close", "dialog_cancel"),
    ) -> tuple[Any, ...]:
        return self.overlay_host().route_input(event, close_on_intents=close_on_intents)

    def _consume_screen_root_baseline_reset(self) -> None:
        consume = getattr(self.render_loop.screen_root, "consume_render_baseline_reset_reason", None)
        if not callable(consume):
            return
        reason = consume()
        if isinstance(reason, str) and reason:
            self.render_loop.reset_baseline(reason)

    def request_animation_frame(self, source: AnimationFrameSource) -> RenderScheduleDecision:
        return self.scheduler.request_animation_frame(source, now_ms=self.now_ms())

    def request_render(self, kind: RenderRequestKind) -> RenderScheduleDecision:
        now_ms = self.now_ms()
        decision = self.scheduler.request_render(kind, now_ms=now_ms)
        due_ms = now_ms if decision.render_now else now_ms + decision.delay_ms
        if self._pending_render_due_ms is None:
            self._pending_render_due_ms = due_ms
        else:
            self._pending_render_due_ms = min(self._pending_render_due_ms, due_ms)
        return decision

    def animation_sources(self) -> tuple[AnimationFrameSource, ...]:
        return tuple(_collect_animation_sources(self.render_loop.screen_root))

    def request_next_animation_frame(self) -> RenderScheduleDecision:
        now_ms = self.now_ms()
        pending_render = self._pending_render_decision(now_ms=now_ms)
        if pending_render.render_now:
            return pending_render

        sources = self.animation_sources()
        if not sources:
            return pending_render

        decisions = [self.request_animation_frame(source) for source in sources]
        if any(decision.render_now for decision in decisions):
            return RenderScheduleDecision(render_now=True, delay_ms=0, coalesced=False)

        delayed = [decision.delay_ms for decision in decisions if decision.delay_ms > 0]
        if pending_render.delay_ms > 0:
            delayed.append(pending_render.delay_ms)
        if not delayed:
            return RenderScheduleDecision(render_now=False, delay_ms=0, coalesced=False)
        return RenderScheduleDecision(render_now=False, delay_ms=min(delayed), coalesced=True)

    def _pending_render_decision(self, *, now_ms: int) -> RenderScheduleDecision:
        if self._pending_render_due_ms is None:
            return RenderScheduleDecision(render_now=False, delay_ms=0, coalesced=False)
        if self._pending_render_due_ms <= now_ms:
            return RenderScheduleDecision(render_now=True, delay_ms=0, coalesced=False)
        return RenderScheduleDecision(
            render_now=False,
            delay_ms=self._pending_render_due_ms - now_ms,
            coalesced=True,
        )


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _collect_animation_sources(root: object) -> tuple[AnimationFrameSource, ...]:
    sources: list[AnimationFrameSource] = []
    visited: set[int] = set()

    def visit(value: object) -> None:
        if value is None or isinstance(value, (str, bytes, int, float, bool)):
            return
        value_id = id(value)
        if value_id in visited:
            return
        visited.add(value_id)

        if callable(getattr(value, "next_frame_due_ms", None)):
            sources.append(cast(AnimationFrameSource, value))

        custom_sources = getattr(value, "animation_sources", None)
        if callable(custom_sources):
            for source in custom_sources():
                visit(source)

        for attr in ("children", "base", "composer", "surface_host", "entries", "surface", "renderable"):
            if hasattr(value, attr):
                visit_nested(getattr(value, attr))

    def visit_nested(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                visit(item)
            return
        visit(value)

    visit(root)
    return tuple(sources)
