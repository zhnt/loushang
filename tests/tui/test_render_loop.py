from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

import loushang.tui.render_loop as render_loop_module
from loushang.foundation.observability._router import (
    configure_debug_logging,
    reset_observability,
)
from loushang.tui import (
    CURSOR_MARKER,
    CursorDeclaration,
    FakeTerminalPort,
    ProcessTerminalPort,
    RenderConstraints,
    RenderLine,
    RenderLoop,
    RenderResult,
    TerminalOperation,
    TerminalPort,
    TerminalProgressReporter,
    TerminalSize,
    TuiRuntime,
    delete_kitty_image,
    wrap_tmux_passthrough,
)
from loushang.tui.core import (
    RenderLineSegment,
    RenderLineSegmentLike,
    SegmentedRenderLines,
)
from loushang.tui.framework import (
    ScreenRoot as OverlayScreenRoot,
)
from loushang.tui.framework import (
    Surface,
    SurfaceHost,
)
from loushang.tui.render_loop import DEFAULT_STRATEGY_ORDER, RenderPlanStrategyKind

pytestmark = pytest.mark.tui_render_contract


class StaticRoot:
    def __init__(self, lines: tuple[str, ...]) -> None:
        self.lines = lines

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines([RenderLine(line) for line in self.lines], constraints=constraints)


class SegmentedRoot:
    def __init__(
        self,
        segments: tuple[RenderLineSegmentLike, ...],
        *,
        cursor: CursorDeclaration | None = None,
    ) -> None:
        self.segments = segments
        self.cursor = cursor

    def render(self, constraints: RenderConstraints) -> RenderResult:
        del constraints
        return RenderResult(
            lines=SegmentedRenderLines.from_segments(self.segments),
            cursor=self.cursor,
        )


class FlatFrameRoot:
    def __init__(
        self,
        lines: tuple[str, ...],
        *,
        cursor: CursorDeclaration | None = None,
    ) -> None:
        self.lines = lines
        self.cursor = cursor

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            tuple(RenderLine(line) for line in self.lines),
            constraints=constraints,
            cursor=self.cursor,
        )


class TextRoot:
    def __init__(self, text: str) -> None:
        self.text = text

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_text(self.text, constraints=constraints)


class RecordingDebugSink:
    def __init__(self) -> None:
        self.events = []

    def write_log(self, **_kwargs) -> None:
        return None

    def write_problem(self, _record) -> None:
        return None

    def write_debug_event(self, record) -> None:
        self.events.append(record)


def _render_segment(
    *lines: str,
    identity: object | None = None,
    revision: object = 0,
) -> RenderLineSegment:
    return RenderLineSegment(
        tuple(RenderLine(line) for line in lines),
        identity=identity if identity is not None else object(),
        revision=revision,
    )


def test_segmented_render_skips_11748_committed_rows_on_bottom_frame_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committed = _render_segment(
        *(f"history {index}" for index in range(11_748)),
        identity="committed",
        revision=1,
    )
    bottom_identity = object()
    root = SegmentedRoot(
        (committed, _render_segment("Working (1s)", identity=bottom_identity, revision=1))
    )
    loop = RenderLoop(root)
    size = TerminalSize(columns=80, rows=24)
    first = loop.plan(size)
    loop.commit(first, size=size)

    compared_tail_sizes: list[tuple[int, int]] = []
    original_changed_range = render_loop_module._changed_line_range_flat

    def record_changed_range_sizes(
        previous_lines: tuple[str, ...],
        current_lines: tuple[str, ...],
    ) -> tuple[int, int] | None:
        compared_tail_sizes.append((len(previous_lines), len(current_lines)))
        return original_changed_range(previous_lines, current_lines)

    monkeypatch.setattr(
        render_loop_module,
        "_changed_line_range_flat",
        record_changed_range_sizes,
    )
    root.segments = (
        committed,
        _render_segment("Working (2s)", identity=bottom_identity, revision=2),
    )

    tick = loop.plan(size)

    assert tick.changed_line_range == (11_748, 11_748)
    assert compared_tail_sizes == [(1, 1)]
    assert tick.reused_render_segment_count == 1
    assert tick.materialized_logical_line_count == 1
    assert tick.flattened_logical_line_count == 0

    loop.commit(tick, size=size)
    compared_tail_sizes.clear()

    no_op = loop.plan(size)

    assert no_op.operation_class == "noop"
    assert no_op.operations == ()
    assert compared_tail_sizes == []
    assert no_op.reused_render_segment_count == 2
    assert no_op.materialized_logical_line_count == 0
    assert no_op.flattened_logical_line_count == 0


def test_segment_cache_retains_only_the_latest_segmented_frame() -> None:
    committed = _render_segment("history", identity="committed", revision=1)
    root = SegmentedRoot((committed,))
    loop = RenderLoop(root)
    size = TerminalSize(columns=80, rows=24)
    latest_draft: RenderLineSegment | None = None

    for revision in range(600):
        draft_line_count = revision // 100 + 1
        latest_draft = _render_segment(
            *(f"draft revision {revision} line {line}" for line in range(draft_line_count)),
            revision=revision,
        )
        root.segments = (committed, latest_draft)
        frame = loop.plan(size)
        loop.commit(frame, size=size)

        assert len(loop._finalized_segment_cache) == 2
        assert sum(
            len(segment.raw_lines)
            for segment in loop._finalized_segment_cache.values()
        ) == draft_line_count + 1

    assert latest_draft is not None
    assert set(loop._finalized_segment_cache) == {
        (committed.identity_key, committed.revision),
        (latest_draft.identity_key, latest_draft.revision),
    }

    no_op = loop.plan(size)

    assert no_op.reused_render_segment_count == 2
    assert no_op.materialized_logical_line_count == 0

    root.segments = (committed,)
    completed = loop.plan(size)

    assert tuple(completed.current_logical_lines) == ("history",)
    assert set(loop._finalized_segment_cache) == {
        (committed.identity_key, committed.revision)
    }


def test_segment_cache_retains_every_segment_in_the_latest_frame() -> None:
    stable = tuple(
        _render_segment(
            f"stable group {index}",
            identity=("stable-group", index),
            revision=1,
        )
        for index in range(600)
    )
    frontier_identity = object()
    root = SegmentedRoot(
        (*stable, _render_segment("frontier one", identity=frontier_identity, revision=1))
    )
    loop = RenderLoop(root)
    size = TerminalSize(columns=80, rows=24)
    first = loop.plan(size)
    loop.commit(first, size=size)

    assert len(loop._finalized_segment_cache) == 601

    root.segments = (
        *stable,
        _render_segment("frontier two", identity=frontier_identity, revision=2),
    )
    changed = loop.plan(size)

    assert changed.reused_render_segment_count == 600
    assert changed.materialized_logical_line_count == 1
    loop.commit(changed, size=size)

    no_op = loop.plan(size)

    assert no_op.reused_render_segment_count == 601
    assert no_op.materialized_logical_line_count == 0


def test_segment_cache_replacement_is_atomic_when_finalization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = SegmentedRoot((_render_segment("old", revision=1),))
    loop = RenderLoop(root)
    size = TerminalSize(columns=80, rows=24)
    loop.plan(size)
    previous_cache = loop._finalized_segment_cache
    previous_cache_items = tuple(previous_cache.items())
    root.segments = (
        _render_segment("new one", revision=2),
        _render_segment("new two", revision=2),
    )
    original_finalize = render_loop_module._finalize_render_segment
    finalize_calls = 0

    def fail_second_segment(segment: RenderLineSegmentLike):
        nonlocal finalize_calls
        finalize_calls += 1
        if finalize_calls == 2:
            raise RuntimeError("finalization failed")
        return original_finalize(segment)

    monkeypatch.setattr(
        render_loop_module,
        "_finalize_render_segment",
        fail_second_segment,
    )

    with pytest.raises(RuntimeError, match="finalization failed"):
        loop.plan(size)

    assert loop._finalized_segment_cache is previous_cache
    assert tuple(loop._finalized_segment_cache.items()) == previous_cache_items


def test_segment_cache_sweeps_changed_views_without_changing_flat_output() -> None:
    base = _render_segment(
        "zero",
        "one",
        "two",
        "three",
        identity="shared",
        revision=1,
    )
    first_view = SegmentedRenderLines.from_segments((base,))[0:2]
    second_view = SegmentedRenderLines.from_segments((base,))[1:3]
    root = SegmentedRoot(first_view.segments)
    flat_root = FlatFrameRoot(("zero", "one"))
    loop = RenderLoop(root)
    flat_loop = RenderLoop(flat_root)
    size = TerminalSize(columns=80, rows=24)
    first = loop.plan(size)
    flat_first = flat_loop.plan(size)
    loop.commit(first, size=size)
    flat_loop.commit(flat_first, size=size)
    first_key = (
        first_view.segments[0].identity_key,
        first_view.segments[0].revision,
    )

    root.segments = second_view.segments
    flat_root.lines = ("one", "two")
    changed = loop.plan(size)
    flat_changed = flat_loop.plan(size)
    second_key = (
        second_view.segments[0].identity_key,
        second_view.segments[0].revision,
    )

    assert tuple(changed.current_logical_lines) == tuple(flat_changed.current_logical_lines)
    assert changed.changed_line_range == flat_changed.changed_line_range
    assert changed.operation_class == flat_changed.operation_class
    assert changed.operations == flat_changed.operations
    assert first_key not in loop._finalized_segment_cache
    assert set(loop._finalized_segment_cache) == {second_key}
    loop.commit(changed, size=size)

    no_op = loop.plan(size)

    assert no_op.reused_render_segment_count == 1
    assert no_op.materialized_logical_line_count == 0


def test_failed_segmented_flush_reuses_cache_without_advancing_baseline() -> None:
    identity = object()
    root = SegmentedRoot(
        (_render_segment("first", identity=identity, revision=1),)
    )
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    loop = RenderLoop(root)
    runtime = TuiRuntime(render_loop=loop, terminal=port)
    runtime.render_now()
    committed_revision = loop.committed_frame_revision
    root.segments = (
        _render_segment("second", identity=identity, revision=2),
    )
    port.fail_next_flush(RuntimeError("write failed"))

    with pytest.raises(RuntimeError, match="write failed"):
        runtime.render_now()

    assert loop.committed_frame_revision == committed_revision

    retried = runtime.render_now()

    assert retried.diagnostics.reused_render_segment_count == 1
    assert retried.diagnostics.materialized_logical_line_count == 0
    assert tuple(retried.diagnostics.previous_rendered_lines) == ("first",)
    assert tuple(retried.diagnostics.current_logical_lines) == ("second",)
    assert retried.diagnostics.base_frame_revision == committed_revision


def test_segmented_row_shift_matches_flat_planner_and_repaints_shifted_image() -> None:
    image_line = "\x1b_Gi=123;AAAA\x1b\\"
    committed = _render_segment("history one", "history two", identity="history")
    bottom = _render_segment(image_line, identity="bottom-image")
    segmented_root = SegmentedRoot(
        (committed, _render_segment("draft", identity="draft", revision=1), bottom),
        cursor=CursorDeclaration(row=3, column=0),
    )
    flat_root = FlatFrameRoot(
        ("history one", "history two", "draft", image_line),
        cursor=CursorDeclaration(row=3, column=0),
    )
    segmented_loop = RenderLoop(segmented_root)
    flat_loop = RenderLoop(flat_root)
    size = TerminalSize(columns=80, rows=8)
    segmented_first = segmented_loop.plan(size)
    flat_first = flat_loop.plan(size)
    segmented_loop.commit(segmented_first, size=size)
    flat_loop.commit(flat_first, size=size)

    segmented_root.segments = (
        committed,
        _render_segment("draft", "extra", identity="draft", revision=2),
        bottom,
    )
    segmented_root.cursor = CursorDeclaration(row=4, column=0)
    flat_root.lines = ("history one", "history two", "draft", "extra", image_line)
    flat_root.cursor = CursorDeclaration(row=4, column=0)

    segmented = segmented_loop.plan(size)
    flat = flat_loop.plan(size)

    assert tuple(segmented.current_logical_lines) == tuple(flat.current_logical_lines)
    assert segmented.changed_line_range == flat.changed_line_range == (3, 4)
    assert segmented.operation_class == flat.operation_class
    assert segmented.operations == flat.operations
    assert segmented.viewport_top == flat.viewport_top
    assert segmented.logical_cursor_row == flat.logical_cursor_row
    assert delete_kitty_image(123) in tuple(
        operation.text
        for operation in segmented.operations
        if operation.kind == "write"
    )


def test_first_render_flushes_full_logical_lines_without_clearing_scrollback() -> None:
    runtime = TuiRuntime(
        render_loop=RenderLoop(StaticRoot(("hello", "status"))),
        terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )

    step = runtime.render_now()

    assert step.diagnostics.operation_class == "first_render"
    assert step.diagnostics.current_logical_lines == ("hello", "status")
    assert step.diagnostics.previous_rendered_lines == ()
    assert step.diagnostics.clear_scrollback_emitted is False
    assert step.frame is not None
    assert step.frame.serialized_output == "\x1b[?25l\x1b[?2026hhello\r\nstatus\x1b[?2026l"
    assert step.frame.screen_after.visible_lines[:2] == ("hello", "status")


def test_first_render_without_declared_cursor_hides_hardware_cursor() -> None:
    runtime = TuiRuntime(
        render_loop=RenderLoop(StaticRoot(("hello", "status"))),
        terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )

    step = runtime.render_now()

    assert step.diagnostics.current_logical_lines == ("hello", "status")
    assert TerminalOperation.hide_cursor() in step.diagnostics.operations


def test_runtime_render_now_emits_tui_render_frame_diagnostics() -> None:
    sink = RecordingDebugSink()
    reset_observability()
    configure_debug_logging(debug_sink=sink, debug_scopes=("tui",))
    try:
        runtime = TuiRuntime(
            render_loop=RenderLoop(StaticRoot(("hello", "status"))),
            terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
        )

        runtime.render_now()
    finally:
        reset_observability()

    event = next(event for event in sink.events if event.scope == "tui" and event.name == "render.frame")
    assert event.data["operation_class"] == "first_render"
    assert event.data["logical_line_count"] == 2
    assert event.data["operation_count"] > 0
    assert event.data["plan_ms"] >= 0
    assert event.data["flush_ms"] >= 0
    assert event.data["total_ms"] >= 0


def test_render_plan_context_carries_cursor_and_diff_facts() -> None:
    root = StaticRoot(("alpha",))
    loop = RenderLoop(root)
    size = TerminalSize(columns=20, rows=5)
    first = loop.plan(size)
    loop.commit(first, size=size)

    root.lines = ("alpha", "beta" + CURSOR_MARKER)
    context = loop._build_plan_context(size)

    assert context.raw_current_lines == ("alpha", "beta")
    assert context.current_lines == ("alpha", "beta")
    assert context.declared_cursor == CursorDeclaration(row=1, column=4)
    assert context.cursor == CursorDeclaration(row=1, column=4)
    assert context.changed_range == (1, 1)
    assert context.first_changed == 1
    assert context.last_changed == 1
    assert context.appended_lines == 1
    assert context.append_start == 1


def test_default_render_strategy_order_matches_design() -> None:
    assert DEFAULT_STRATEGY_ORDER == (
        RenderPlanStrategyKind.FIRST_RENDER,
        RenderPlanStrategyKind.TRANSCRIPT_WINDOW_TRIMMED_RESET,
        RenderPlanStrategyKind.BASELINE_RESET,
        RenderPlanStrategyKind.RESIZE_REPAINT,
        RenderPlanStrategyKind.UNSAFE_VIEWPORT,
        RenderPlanStrategyKind.NO_CHANGE,
        RenderPlanStrategyKind.APPEND,
        RenderPlanStrategyKind.PROTECTED_APPEND,
        RenderPlanStrategyKind.SHRINK_VIEWPORT_REPAINT,
        RenderPlanStrategyKind.SHRINK_CLEAR,
        RenderPlanStrategyKind.CHANGED_ABOVE_VIEWPORT,
        RenderPlanStrategyKind.CHANGED_RANGE,
    )


def test_resize_repaint_precedes_changed_range_strategy() -> None:
    root = StaticRoot(("one",))
    loop = RenderLoop(root)
    first = loop.plan(TerminalSize(columns=20, rows=5))
    loop.commit(first, size=TerminalSize(columns=20, rows=5))

    root.lines = ("two",)
    step = loop.plan(TerminalSize(columns=30, rows=5))

    assert step.operation_class == "resize_repaint"


def test_unsafe_viewport_precedes_append_strategy() -> None:
    root = StaticRoot(("one",))
    loop = RenderLoop(root)
    first = loop.plan(TerminalSize(columns=20, rows=5))
    loop.commit(first, size=TerminalSize(columns=20, rows=5))

    root.lines = ("one", "two")
    loop.mark_viewport_unsafe("external_stdout")
    step = loop.plan(TerminalSize(columns=20, rows=5))

    assert step.operation_class == "recovery_repaint"
    assert step.repaint_reason == "external_stdout"


def test_transcript_window_trimmed_reset_precedes_resize_repaint() -> None:
    root = StaticRoot(("one",))
    loop = RenderLoop(root)
    first = loop.plan(TerminalSize(columns=20, rows=5))
    loop.commit(first, size=TerminalSize(columns=20, rows=5))

    root.lines = ("one", "two")
    loop.reset_baseline("transcript_window_trimmed:active_line_budget")
    step = loop.plan(TerminalSize(columns=30, rows=5))

    assert step.operation_class == "managed_viewport_repaint"
    assert step.repaint_reason == "transcript_window_trimmed:active_line_budget"


def test_ordinary_baseline_reset_precedes_resize_repaint() -> None:
    root = StaticRoot(("one",))
    loop = RenderLoop(root)
    first = loop.plan(TerminalSize(columns=20, rows=5))
    loop.commit(first, size=TerminalSize(columns=20, rows=5))

    root.lines = ("one", "two")
    loop.reset_baseline("transcript_window_replaced:resume")
    step = loop.plan(TerminalSize(columns=30, rows=5))

    assert step.operation_class == "baseline_repaint"
    assert step.repaint_reason == "transcript_window_replaced:resume"


def test_runtime_render_now_does_not_emit_tui_render_frame_when_scope_is_disabled() -> None:
    sink = RecordingDebugSink()
    reset_observability()
    try:
        configure_debug_logging(debug_sink=sink, debug_scopes=set())
        runtime = TuiRuntime(
            render_loop=RenderLoop(StaticRoot(("hello", "status"))),
            terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
        )

        runtime.render_now()

        assert not sink.events

        configure_debug_logging(debug_sink=sink, debug_scopes={"tui"})
        runtime.render_now()
        assert any(event.scope == "tui" and event.name == "render.frame" for event in sink.events)
    finally:
        reset_observability()


def test_fake_terminal_port_implements_terminal_port_boundary() -> None:
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=5))

    assert isinstance(port, TerminalPort)


def test_append_update_writes_only_appended_lines_and_preserves_previous_snapshot() -> None:
    root = StaticRoot(("one",))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))
    runtime.render_now()
    root.lines = ("one", "two")

    step = runtime.render_now()

    step.assert_operation_class("append_update")
    assert step.diagnostics.previous_rendered_lines == ("one",)
    assert step.diagnostics.changed_line_range == (1, 1)
    assert step.diagnostics.append_start == 1
    assert step.diagnostics.appended_lines == 1
    assert step.diagnostics.operations == (
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.newline(),
        TerminalOperation.write("two"),
        TerminalOperation.end_synchronized_update(),
    )
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines[:2] == ("one", "two")


def test_append_update_scrolls_below_visible_viewport_without_repaint() -> None:
    root = StaticRoot(tuple(f"line {index}" for index in range(5)))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=3)))
    first = runtime.render_now()
    root.lines = (*root.lines, "line 5")

    step = runtime.render_now()

    assert first.diagnostics.viewport_top == 2
    step.assert_operation_class("append_update")
    assert step.diagnostics.previous_viewport_top == 2
    assert step.diagnostics.viewport_top == 3
    assert step.diagnostics.operations == (
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.newline(),
        TerminalOperation.write("line 5"),
        TerminalOperation.end_synchronized_update(),
    )
    assert TerminalOperation.clear_screen() not in step.diagnostics.operations
    assert TerminalOperation.clear_scrollback() not in step.diagnostics.operations
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines == ("line 3", "line 4", "line 5")


def test_protected_append_update_commits_departing_history_once() -> None:
    previous_lines = (
        "line 1",
        "line 2",
        "",
        "working 1.00s",
        "",
        f"› {CURSOR_MARKER}",
        "",
        "status running",
    )
    current_lines = (
        "line 1",
        "line 2",
        "line 3",
        "line 4",
        "",
        "working 1.00s",
        "",
        f"› {CURSOR_MARKER}",
        "",
        "status running",
    )
    root = TextRoot("\n".join(previous_lines))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=30, rows=8)))
    runtime.render_now()
    root.text = "\n".join(current_lines)

    step = runtime.render_now()

    step.assert_operation_class("protected_append_update")
    assert all(
        operation.kind not in {"set_scroll_region", "reset_scroll_region"}
        for operation in step.diagnostics.operations
    )
    assert step.diagnostics.append_start == 2
    assert step.diagnostics.appended_lines == 2
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines == (
        "line 3",
        "line 4",
        "",
        "working 1.00s",
        "",
        "›",
        "",
        "status running",
    )
    assert step.frame.screen_after.cursor_row == 5
    assert step.frame.screen_after.cursor_column == 2
    assert (
        step.frame.screen_after.scrollback_lines
        + step.frame.screen_after.visible_lines
    ) == (
        "line 1",
        "line 2",
        "line 3",
        "line 4",
        "",
        "working 1.00s",
        "",
        "›",
        "",
        "status running",
    )


def test_non_pure_protected_append_repaints_instead_of_replaying_changed_turn() -> None:
    previous_lines = (
        "› calculate",
        "• Ran wait_agent 0.00s",
        "",
        "working 1.00s",
        "",
        f"› {CURSOR_MARKER}",
        "",
        "status running",
    )
    current_lines = (
        "› calculate",
        "• Ran wait_agent took 1.32s",
        "• First result: 91",
        "• Ran wait_agent 0.00s",
        "",
        "working 2.00s",
        "",
        f"› {CURSOR_MARKER}",
        "",
        "status running",
    )
    root = TextRoot("\n".join(previous_lines))
    runtime = TuiRuntime(
        render_loop=RenderLoop(root),
        terminal=FakeTerminalPort(size=TerminalSize(columns=40, rows=8)),
    )
    runtime.render_now()
    root.text = "\n".join(current_lines)

    step = runtime.render_now()

    step.assert_operation_class("managed_viewport_repaint")
    assert step.diagnostics.repaint_reason == "non_pure_protected_append"
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines == (
        "• First result: 91",
        "• Ran wait_agent 0.00s",
        "",
        "working 2.00s",
        "",
        "›",
        "",
        "status running",
    )
    assert step.frame.screen_after.visible_lines.count("• Ran wait_agent 0.00s") == 1
    assert (
        step.frame.screen_after.scrollback_lines
        + step.frame.screen_after.visible_lines
    ) == (
        "› calculate",
        "• Ran wait_agent took 1.32s",
        "• First result: 91",
        "• Ran wait_agent 0.00s",
        "",
        "working 2.00s",
        "",
        "›",
        "",
        "status running",
    )


def test_page_surface_round_trip_does_not_replay_base_into_scrollback() -> None:
    base_lines = tuple(f"base-{index}" for index in range(10))
    host = SurfaceHost()
    root = OverlayScreenRoot(base=StaticRoot(base_lines), surface_host=host)
    port = FakeTerminalPort(size=TerminalSize(columns=30, rows=5))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=port)
    runtime.render_now()

    handle = host.open_surface(
        Surface(
            renderable=StaticRoot(
                tuple(f"agents-page-{index}" for index in range(5))
            ),
            presentation="page",
        )
    )
    runtime.render_now()
    handle.close()
    runtime.render_now()

    assert port.screen.scrollback_lines + port.screen.visible_lines == base_lines


def test_protected_append_update_waits_until_logical_screen_is_full() -> None:
    previous_lines = (
        "line 1",
        "line 2",
        "",
        "working 1.00s",
        "",
        f"› {CURSOR_MARKER}",
        "",
        "status running",
    )
    current_lines = (
        "line 1",
        "line 2",
        "line 3",
        "line 4",
        "",
        "working 1.10s",
        "",
        f"› {CURSOR_MARKER}",
        "",
        "status running",
    )
    root = TextRoot("\n".join(previous_lines))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=30, rows=12)))
    runtime.render_now()
    root.text = "\n".join(current_lines)

    step = runtime.render_now()

    step.assert_operation_class("changed_range_update")
    assert all(operation.kind != "set_scroll_region" for operation in step.diagnostics.operations)


def test_changed_range_update_rewrites_only_visible_changed_rows() -> None:
    root = StaticRoot(("one", "two", "three"))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))
    runtime.render_now()
    root.lines = ("one", "TWO", "three")

    step = runtime.render_now()

    step.assert_operation_class("changed_range_update")
    assert step.diagnostics.changed_line_range == (1, 1)
    assert step.diagnostics.operations == (
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.move_relative(lines=-1),
        TerminalOperation.carriage_return(),
        TerminalOperation.clear_line(),
        TerminalOperation.write("TWO"),
        TerminalOperation.end_synchronized_update(),
    )
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines[:3] == ("one", "TWO", "three")


def test_changed_range_update_without_declared_cursor_reports_actual_hardware_cursor() -> None:
    root = StaticRoot(("one", "two", "three"))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))
    runtime.render_now()
    root.lines = ("one", "TWO", "three")

    step = runtime.render_now()

    step.assert_operation_class("changed_range_update")
    assert step.frame is not None
    assert step.frame.screen_after.cursor_row == 1
    assert step.frame.screen_after.cursor_column == 3
    assert step.diagnostics.hardware_cursor_row == 1
    assert step.diagnostics.hardware_cursor_column == 3


def test_changed_range_update_uses_pi_style_relative_cursor_movement_inside_viewport() -> None:
    root = StaticRoot(("one", "two", "three", "four", "five"))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=3)))
    first = runtime.render_now()
    root.lines = ("one", "two", "three", "FOUR", "five")

    step = runtime.render_now()

    assert first.diagnostics.viewport_top == 2
    assert first.diagnostics.hardware_cursor_row == 4
    step.assert_operation_class("changed_range_update")
    assert step.diagnostics.previous_viewport_top == 2
    assert step.diagnostics.operations[:5] == (
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.move_relative(lines=-1),
        TerminalOperation.carriage_return(),
        TerminalOperation.clear_line(),
    )
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines == ("three", "FOUR", "five")


def test_changed_range_shrink_rewrites_viewport_when_anchor_would_move_up() -> None:
    previous_lines = tuple(f"line {index}" for index in range(36)) + (f"› draft{CURSOR_MARKER}", "", "status running")
    root = TextRoot("\n".join(previous_lines))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=40, rows=28)))
    first = runtime.render_now()
    current_lines = (
        *tuple(f"line {index}" for index in range(31)),
        "assistant final",
        "",
        "worked divider",
        "",
        f"› draft{CURSOR_MARKER}",
        "",
        "status idle",
    )

    root.text = "\n".join(current_lines)
    step = runtime.render_now()

    assert first.diagnostics.viewport_top == 11
    step.assert_operation_class("managed_viewport_repaint")
    assert step.diagnostics.repaint_reason == "viewport_top_decreased_after_shrink"
    assert step.diagnostics.viewport_top == 10
    step.assert_no_clear_scrollback()
    assert TerminalOperation.clear_screen() not in step.diagnostics.operations
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines[-4:] == ("", "› draft", "", "status idle")
    assert step.frame.screen_after.cursor_row == 25
    assert step.frame.screen_after.cursor_column == 7


def test_shrinking_content_clears_stale_rows_without_scrolling() -> None:
    root = StaticRoot(("one", "two", "three"))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))
    runtime.render_now()
    root.lines = ("one",)

    step = runtime.render_now()

    step.assert_operation_class("shrink_clear")
    assert step.diagnostics.changed_line_range == (1, 2)
    assert step.diagnostics.operations == (
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.move_relative(lines=-2),
        TerminalOperation.carriage_return(),
        TerminalOperation.newline(),
        TerminalOperation.clear_line(),
        TerminalOperation.newline(),
        TerminalOperation.clear_line(),
        TerminalOperation.move_relative(lines=-2),
        TerminalOperation.end_synchronized_update(),
    )
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines[:3] == ("one", "", "")


def test_changed_range_shrink_keeps_hardware_cursor_in_sync_after_clearing_stale_rows() -> None:
    previous_lines = (
        "› 你好",
        "",
        "• 你好！有什么我可以帮你的吗？",
        "",
        "─ Worked for 1.93s ─",
        "",
        f"› /{CURSOR_MARKER}",
        "",
        "  /help  Show help",
        "  /quit  Quit",
    )
    root = TextRoot("\n".join(previous_lines))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=40, rows=12)))
    runtime.render_now()
    current_lines = (
        "› 你好",
        "",
        "• 你好！有什么我可以帮你的吗？",
        "",
        "─ Worked for 1.93s ─",
        "",
        f"› {CURSOR_MARKER}",
        "",
        "moonshot/kimi | repo | main | idle",
    )

    root.text = "\n".join(current_lines)
    step = runtime.render_now()

    step.assert_operation_class("changed_range_update")
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines[:10] == (
        "› 你好",
        "",
        "• 你好！有什么我可以帮你的吗？",
        "",
        "─ Worked for 1.93s ─",
        "",
        "›",
        "",
        "moonshot/kimi | repo | main | idle",
        "",
    )
    assert step.frame.screen_after.cursor_row == 6
    assert step.frame.screen_after.cursor_column == 2
    assert step.diagnostics.hardware_cursor_row == 6
    assert step.diagnostics.hardware_cursor_column == 2


def test_cursor_marker_is_stripped_and_positions_hardware_cursor() -> None:
    root = TextRoot(f"ab{CURSOR_MARKER}c")
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))

    step = runtime.render_now()

    assert step.diagnostics.current_logical_lines == ("abc",)
    assert step.diagnostics.logical_cursor_row == 0
    assert step.diagnostics.logical_cursor_column == 2
    assert CURSOR_MARKER not in step.frame.serialized_output if step.frame is not None else False
    assert step.diagnostics.operations == (
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.write("abc"),
        TerminalOperation.end_synchronized_update(),
        TerminalOperation.move_column(column=2),
        TerminalOperation.show_cursor(),
    )
    assert step.frame is not None
    assert step.frame.screen_after.cursor_row == 0
    assert step.frame.screen_after.cursor_column == 2


def test_cursor_marker_in_render_lines_is_stripped_and_positions_hardware_cursor() -> None:
    root = StaticRoot((f"ab{CURSOR_MARKER}c",))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))

    step = runtime.render_now()

    assert step.diagnostics.current_logical_lines == ("abc",)
    assert step.diagnostics.logical_cursor_row == 0
    assert step.diagnostics.logical_cursor_column == 2
    assert step.frame is not None
    assert CURSOR_MARKER not in step.frame.serialized_output
    assert step.frame.screen_after.cursor_row == 0
    assert step.frame.screen_after.cursor_column == 2


def test_render_finalization_adds_reset_and_osc8_close_after_styled_lines() -> None:
    root = StaticRoot(("\x1b[31mred", "plain"))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))

    step = runtime.render_now()

    assert step.diagnostics.current_logical_lines == ("\x1b[31mred\x1b[0m\x1b]8;;\x07", "plain")
    assert step.frame is not None
    assert step.frame.serialized_output == "\x1b[?25l\x1b[?2026h\x1b[31mred\x1b[0m\x1b]8;;\x07\r\nplain\x1b[?2026l"
    assert step.frame.screen_after.cell_style(row=1, column=0).foreground is None


def test_render_finalization_preserves_terminal_image_lines_without_reset_suffix() -> None:
    image_line = "\x1b_Gi=1;AAAA\x1b\\"
    root = StaticRoot((image_line,))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=5)))

    step = runtime.render_now()

    assert step.diagnostics.current_logical_lines == (image_line,)
    assert step.frame is not None
    assert step.frame.serialized_output == f"\x1b[?25l\x1b[?2026h{image_line}\x1b[?2026l"


def test_changed_range_update_deletes_previous_kitty_image_id_before_replacing_line() -> None:
    image_line = "\x1b_Ga=T,f=100,t=d,i=42;AAAA\x1b\\"
    root = StaticRoot((image_line,))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=5)))
    runtime.render_now()
    root.lines = ("plain",)

    step = runtime.render_now()

    step.assert_operation_class("changed_range_update")
    assert step.frame is not None
    assert delete_kitty_image(42) in step.frame.serialized_output
    assert step.frame.serialized_output.index(delete_kitty_image(42)) < step.frame.serialized_output.index("plain")


def test_changed_range_update_wraps_kitty_delete_for_tmux_passthrough_image() -> None:
    image_line = wrap_tmux_passthrough("\x1b_Ga=T,f=100,t=d,i=42;AAAA\x1b\\")
    root = StaticRoot((image_line,))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=5)))
    runtime.render_now()
    root.lines = ("plain",)

    step = runtime.render_now()

    expected_delete = wrap_tmux_passthrough(delete_kitty_image(42))
    step.assert_operation_class("changed_range_update")
    assert step.frame is not None
    assert expected_delete in step.frame.serialized_output
    assert delete_kitty_image(42) not in step.frame.serialized_output.replace(expected_delete, "")


def test_changed_range_expands_to_unchanged_kitty_images_below_first_change() -> None:
    image_line = "\x1b_Ga=T,f=100,t=d,i=43;BBBB\x1b\\"
    root = StaticRoot(("top", image_line))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=5)))
    runtime.render_now()
    root.lines = ("changed", image_line)

    step = runtime.render_now()

    step.assert_operation_class("changed_range_update")
    assert step.diagnostics.changed_line_range == (0, 1)
    assert step.frame is not None
    assert delete_kitty_image(43) in step.frame.serialized_output
    assert image_line in step.frame.serialized_output


def test_resize_repaint_deletes_previous_kitty_image_ids_before_clearing_screen() -> None:
    image_line = "\x1b_Ga=T,f=100,t=d,i=44;CCCC\x1b\\"
    port = FakeTerminalPort(size=TerminalSize(columns=80, rows=5))
    root = StaticRoot((image_line,))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=port)
    runtime.render_now()
    port.resize(TerminalSize(columns=40, rows=5))

    step = runtime.render_now()

    step.assert_operation_class("resize_repaint")
    assert step.frame is not None
    assert delete_kitty_image(44) in step.frame.serialized_output
    assert step.frame.serialized_output.index(delete_kitty_image(44)) < step.frame.serialized_output.index("\x1b[2J")


def test_noop_with_cursor_change_moves_only_hardware_cursor() -> None:
    root = TextRoot(f"a{CURSOR_MARKER}bc")
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))
    runtime.render_now()
    root.text = f"ab{CURSOR_MARKER}c"

    step = runtime.render_now()

    step.assert_operation_class("cursor_update")
    assert step.diagnostics.changed_line_range is None
    assert step.diagnostics.current_logical_lines == ("abc",)
    assert step.diagnostics.operations == (
        TerminalOperation.hide_cursor(),
        TerminalOperation.move_column(column=2),
        TerminalOperation.show_cursor(),
    )
    assert step.frame is not None
    assert step.frame.screen_after.visible_lines[0] == "abc"
    assert step.frame.screen_after.cursor_column == 2


def test_cursor_position_uses_pi_style_relative_row_inside_visible_viewport() -> None:
    root = TextRoot(f"one\ntwo\nthree\nfour\nfi{CURSOR_MARKER}ve")
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=3)))

    step = runtime.render_now()

    assert step.diagnostics.viewport_top == 2
    assert step.diagnostics.operations[-2:] == (
        TerminalOperation.move_column(column=2),
        TerminalOperation.show_cursor(),
    )
    assert step.frame is not None
    assert step.frame.screen_after.cursor_row == 2
    assert step.frame.screen_after.cursor_column == 2


def test_first_render_positions_cursor_relative_to_content_when_terminal_not_home() -> None:
    root = TextRoot(f"one\ntwo\nthr{CURSOR_MARKER}ee\nfour")
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=10))
    port.screen = port.screen.apply((TerminalOperation.move_cursor(row=4, column=0),))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=port)

    step = runtime.render_now()

    assert step.frame is not None
    assert step.frame.screen_after.visible_lines[4:8] == ("one", "two", "three", "four")
    assert step.frame.screen_after.cursor_row == 6
    assert step.frame.screen_after.cursor_column == 3


def test_width_or_height_change_uses_pi_style_resize_repaint_with_clear_scrollback() -> None:
    root = StaticRoot(("one", "two"))
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    runtime = TuiRuntime(render_loop=RenderLoop(root), terminal=port)
    runtime.render_now()
    port.resize(TerminalSize(columns=30, rows=6))

    step = runtime.render_now()

    step.assert_operation_class("resize_repaint")
    step.assert_has_clear_scrollback()
    assert step.diagnostics.width_changed is True
    assert step.diagnostics.height_changed is True
    assert step.diagnostics.repaint_kind == "resize"
    assert step.diagnostics.operations[:4] == (
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        TerminalOperation.clear_screen(),
        TerminalOperation.clear_scrollback(),
    )


def test_termux_height_only_resize_does_not_force_resize_repaint() -> None:
    root = StaticRoot(("one", "two"))
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    runtime = TuiRuntime(render_loop=RenderLoop(root, termux_session=True), terminal=port)
    runtime.render_now()
    port.resize(TerminalSize(columns=20, rows=4))

    step = runtime.render_now()

    step.assert_operation_class("noop")
    step.assert_no_clear_scrollback()
    assert step.diagnostics.width_changed is False
    assert step.diagnostics.height_changed is True


def test_termux_width_resize_still_forces_resize_repaint() -> None:
    root = StaticRoot(("one", "two"))
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    runtime = TuiRuntime(render_loop=RenderLoop(root, termux_session=True), terminal=port)
    runtime.render_now()
    port.resize(TerminalSize(columns=21, rows=5))

    step = runtime.render_now()

    step.assert_operation_class("resize_repaint")
    assert step.diagnostics.width_changed is True
    assert step.diagnostics.height_changed is False


def test_disabled_clear_scrollback_policy_can_preserve_scrollback_on_resize_repaint() -> None:
    root = StaticRoot(("one",))
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    runtime = TuiRuntime(render_loop=RenderLoop(root, clear_scrollback_policy="disabled"), terminal=port)
    runtime.render_now()
    port.resize(TerminalSize(columns=21, rows=5))

    step = runtime.render_now()

    step.assert_operation_class("resize_repaint")
    step.assert_no_clear_scrollback()
    assert TerminalOperation.clear_scrollback() not in step.diagnostics.operations


def test_unsafe_viewport_forces_recovery_repaint_instead_of_changed_range_update() -> None:
    root = StaticRoot(("one", "two"))
    render_loop = RenderLoop(root)
    runtime = TuiRuntime(render_loop=render_loop, terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)))
    runtime.render_now()
    render_loop.mark_viewport_unsafe("external_stdout")
    root.lines = ("one", "TWO")

    step = runtime.render_now()

    step.assert_operation_class("recovery_repaint")
    step.assert_no_clear_scrollback()
    assert step.diagnostics.repaint_kind == "recovery"
    assert step.diagnostics.repaint_reason == "external_stdout"
    assert step.diagnostics.changed_line_range == (1, 1)


def test_recovery_repaint_does_not_replay_existing_history_into_scrollback() -> None:
    lines = tuple(f"history-{index}" for index in range(10))
    root = StaticRoot(lines)
    port = FakeTerminalPort(size=TerminalSize(columns=30, rows=5))
    render_loop = RenderLoop(root)
    runtime = TuiRuntime(render_loop=render_loop, terminal=port)
    runtime.render_now()

    render_loop.mark_viewport_unsafe("external_stdout")
    runtime.render_now()

    assert port.screen.scrollback_lines + port.screen.visible_lines == lines


def test_changed_range_above_viewport_rewrites_managed_viewport_without_clearing_screen() -> None:
    root = StaticRoot(tuple(f"line {index}" for index in range(20)))
    runtime = TuiRuntime(
        render_loop=RenderLoop(root, clear_scrollback_policy="disabled"),
        terminal=FakeTerminalPort(size=TerminalSize(columns=20, rows=5)),
    )
    runtime.render_now()
    root.lines = ("LINE 0", *tuple(f"line {index}" for index in range(1, 20)))

    step = runtime.render_now()

    step.assert_operation_class("managed_viewport_repaint")
    step.assert_no_clear_scrollback()
    assert TerminalOperation.clear_screen() not in step.diagnostics.operations
    assert step.diagnostics.repaint_reason == "changed_range_above_viewport"


def test_baseline_reset_repaints_active_screen_without_diffing_against_old_lines() -> None:
    root = StaticRoot(("old transcript", "status"))
    render_loop = RenderLoop(root, clear_scrollback_policy="disabled")
    runtime = TuiRuntime(render_loop=render_loop, terminal=FakeTerminalPort(size=TerminalSize(columns=30, rows=5)))
    runtime.render_now()

    root.lines = ("compacted summary", "recent suffix", "status")
    render_loop.reset_baseline("transcript_window_replaced")
    step = runtime.render_now()

    step.assert_operation_class("baseline_repaint")
    step.assert_no_clear_scrollback()
    assert step.diagnostics.repaint_kind == "recovery"
    assert step.diagnostics.repaint_reason == "transcript_window_replaced"
    assert step.diagnostics.previous_rendered_lines == ("old transcript", "status")
    assert step.diagnostics.current_logical_lines == ("compacted summary", "recent suffix", "status")


def test_failed_runtime_flush_does_not_advance_render_loop_snapshot() -> None:
    root = StaticRoot(("first",))
    port = FakeTerminalPort(size=TerminalSize(columns=20, rows=5))
    render_loop = RenderLoop(root)
    runtime = TuiRuntime(render_loop=render_loop, terminal=port)
    runtime.render_now()
    committed_revision = render_loop.committed_frame_revision
    root.lines = ("second",)
    port.fail_next_flush(RuntimeError("write failed"))

    with pytest.raises(RuntimeError, match="write failed"):
        runtime.render_now()

    assert render_loop.committed_frame_revision == committed_revision
    root.lines = ("third",)
    step = runtime.render_now()

    assert step.diagnostics.previous_rendered_lines == ("first",)
    assert step.diagnostics.changed_line_range == (0, 0)
    assert step.diagnostics.base_frame_revision == committed_revision


def test_render_loop_rejects_plan_from_a_stale_committed_frame() -> None:
    loop = RenderLoop(StaticRoot(("line",)))
    size = TerminalSize(columns=20, rows=5)
    first = loop.plan(size)
    stale = loop.plan(size)

    loop.commit(first, size=size)

    with pytest.raises(RuntimeError, match="base revision"):
        loop.commit(stale, size=size)


def test_process_terminal_port_writes_serialized_frame_to_output() -> None:
    output = StringIO()
    port = ProcessTerminalPort(output=output, size_provider=lambda: TerminalSize(columns=20, rows=5))

    frame = port.flush(
        (
            TerminalOperation.begin_synchronized_update(),
            TerminalOperation.write("hello"),
            TerminalOperation.end_synchronized_update(),
        )
    )

    assert output.getvalue() == "\x1b[?2026hhello\x1b[?2026l"
    assert frame.serialized_output == output.getvalue()
    assert frame.screen_after.visible_lines[0] == "hello"
    assert port.frames == (frame,)

    second = port.flush((TerminalOperation.write("!"),))

    assert port.frames == (second,)


def test_process_terminal_port_can_skip_screen_tracking_for_live_output() -> None:
    output = StringIO()
    port = ProcessTerminalPort(
        output=output,
        size_provider=lambda: TerminalSize(columns=20, rows=5),
        track_screen=False,
    )

    frame = port.flush((TerminalOperation.write("hello"), TerminalOperation.newline(), TerminalOperation.write("world")))

    assert output.getvalue() == "hello\r\nworld"
    assert frame.serialized_output == output.getvalue()
    assert frame.screen_before is frame.screen_after
    assert port.screen.visible_lines == ("", "", "", "", "")
    assert port.frames == (frame,)


def test_process_terminal_port_can_write_serialized_output_to_log(tmp_path: Path) -> None:
    output = StringIO()
    log_path = tmp_path / "tui.log"
    port = ProcessTerminalPort(
        output=output,
        size_provider=lambda: TerminalSize(columns=20, rows=5),
        write_log_path=log_path,
    )

    port.flush((TerminalOperation.write("hello"),))
    port.flush((TerminalOperation.newline(), TerminalOperation.write("world")))

    assert log_path.read_bytes() == b"hello\r\nworld"


def test_terminal_progress_reporter_sends_keepalive_frames() -> None:
    now = 0

    def now_ms() -> int:
        return now

    port = FakeTerminalPort(frame_history_limit=None)
    reporter = TerminalProgressReporter(port, now_ms=now_ms)

    assert reporter.set_active(True) is True
    assert reporter.keepalive() is False

    now = 1_000

    assert reporter.keepalive() is True
    assert reporter.stop() is True
    assert port.flushes == (
        (TerminalOperation.set_progress(True),),
        (TerminalOperation.set_progress(True),),
        (TerminalOperation.set_progress(False),),
    )


def test_process_terminal_port_uses_environment_size_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    output = StringIO()
    monkeypatch.setenv("COLUMNS", "132")
    monkeypatch.setenv("LINES", "43")

    def unavailable_size() -> TerminalSize:
        raise OSError("not a tty")

    port = ProcessTerminalPort(output=output, size_provider=unavailable_size)

    assert port.size() == TerminalSize(columns=132, rows=43)
    assert port.screen.size == TerminalSize(columns=132, rows=43)


def test_process_terminal_port_defaults_size_when_provider_and_environment_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.delenv("LINES", raising=False)

    def unavailable_size() -> TerminalSize:
        raise OSError("not a tty")

    port = ProcessTerminalPort(output=output, size_provider=unavailable_size)

    assert port.size() == TerminalSize(columns=80, rows=24)
