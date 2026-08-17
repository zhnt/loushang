from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar, Literal, Protocol

from loushang.tui.cell_width import normalize_terminal_output, visible_width
from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLineSegmentLike,
    RenderResult,
    SegmentedRenderLines,
)
from loushang.tui.playback import RenderDiagnostics
from loushang.tui.terminal import TerminalOperation, TerminalSize
from loushang.tui.terminal_image import (
    delete_kitty_image,
    extract_kitty_image_ids,
    is_terminal_image_line,
    wrap_tmux_passthrough,
)

ClearScrollbackPolicy = Literal["disabled", "resize", "explicit"]
SEGMENT_RESET = "\x1b[0m\x1b]8;;\x07"


@dataclass(frozen=True, slots=True, eq=False)
class _LogicalLineSegment:
    raw_lines: tuple[str, ...]
    finalized_lines: tuple[str, ...]
    kitty_images: tuple[tuple[int, int, str], ...] = ()


@dataclass(frozen=True, slots=True, eq=False)
class _SegmentedTextLines(Sequence[str]):
    segments: tuple[_LogicalLineSegment, ...] = ()
    finalized: bool = True
    _segment_ends: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        total = 0
        ends: list[int] = []
        for segment in self.segments:
            total += len(self._segment_lines(segment))
            ends.append(total)
        object.__setattr__(self, "_segment_ends", tuple(ends))

    def __len__(self) -> int:
        return self._segment_ends[-1] if self._segment_ends else 0

    def __iter__(self) -> Iterator[str]:
        for segment in self.segments:
            yield from self._segment_lines(segment)

    def __getitem__(self, index: int | slice) -> str | tuple[str, ...]:
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return tuple(self[row] for row in range(start, stop, step))
        normalized = index + len(self) if index < 0 else index
        if normalized < 0 or normalized >= len(self):
            raise IndexError("logical line index out of range")
        segment_index = bisect_right(self._segment_ends, normalized)
        segment_start = self._segment_ends[segment_index - 1] if segment_index else 0
        return self._segment_lines(self.segments[segment_index])[normalized - segment_start]

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, Sequence):
            return NotImplemented
        if len(self) != len(other):
            return False
        return all(current == candidate for current, candidate in zip(self, other, strict=True))

    def tail_segments(self, start: int) -> _SegmentedTextLines:
        return _SegmentedTextLines(self.segments[start:], finalized=self.finalized)

    def segment_start(self, index: int) -> int:
        return self._segment_ends[index - 1] if index else 0

    def iter_kitty_images(self) -> Iterator[tuple[int, int, str]]:
        row_offset = 0
        for segment in self.segments:
            for row, image_id, delete_sequence in segment.kitty_images:
                yield row_offset + row, image_id, delete_sequence
            row_offset += len(self._segment_lines(segment))

    def _segment_lines(self, segment: _LogicalLineSegment) -> tuple[str, ...]:
        return segment.finalized_lines if self.finalized else segment.raw_lines


class ScreenRoot(Protocol):
    def render(self, constraints: RenderConstraints) -> RenderResult: ...


class RenderPlanStrategyKind(Enum):
    FIRST_RENDER = auto()
    TRANSCRIPT_WINDOW_TRIMMED_RESET = auto()
    BASELINE_RESET = auto()
    RESIZE_REPAINT = auto()
    UNSAFE_VIEWPORT = auto()
    NO_CHANGE = auto()
    APPEND = auto()
    PROTECTED_APPEND = auto()
    SHRINK_VIEWPORT_REPAINT = auto()
    SHRINK_CLEAR = auto()
    CHANGED_ABOVE_VIEWPORT = auto()
    CHANGED_RANGE = auto()


DEFAULT_STRATEGY_ORDER: tuple[RenderPlanStrategyKind, ...] = (
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


@dataclass(frozen=True, slots=True)
class RenderPlanContext:
    size: TerminalSize
    result: RenderResult
    raw_current_lines: tuple[str, ...]
    current_lines: tuple[str, ...]
    previous_lines: tuple[str, ...]
    previous_size: TerminalSize | None
    declared_cursor: CursorDeclaration | None
    cursor: CursorDeclaration
    changed_range: tuple[int, int] | None
    first_changed: int | None
    last_changed: int | None
    appended_lines: int
    append_start: int | None
    viewport_top: int
    differential_viewport_top: int
    width_changed: bool
    height_changed: bool
    previous_kitty_delete_sequences: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RenderPlanRuntime:
    previous_viewport_top: int
    previous_cursor_row: int
    previous_cursor_column: int
    hardware_cursor_row: int
    hardware_cursor_column: int
    working_area_high_water_mark: int
    termux_session: bool
    clear_scrollback_policy: ClearScrollbackPolicy
    baseline_reset_reason: str | None
    unsafe_viewport_reason: str | None
    diagnostics: Callable[..., RenderDiagnostics]
    repaint_diagnostics: Callable[..., RenderDiagnostics]
    managed_viewport_repaint_diagnostics: Callable[..., RenderDiagnostics]


class RenderPlanStrategy(Protocol):
    kind: ClassVar[RenderPlanStrategyKind]
    name: ClassVar[str]

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool: ...

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics: ...


@dataclass(frozen=True, slots=True)
class FirstRenderStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.FIRST_RENDER
    name: ClassVar[str] = "first_render"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return context.previous_size is None

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        return runtime.diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            operation_class="first_render",
            operations=_full_write_operations(
                context.current_lines,
                cursor=context.declared_cursor,
                viewport_top=context.viewport_top,
            ),
            changed_range=context.changed_range,
            viewport_top=context.viewport_top,
            cursor=context.cursor,
            hardware_cursor_row=_hardware_row_after_write(context.current_lines, cursor=context.declared_cursor),
            hardware_cursor_column=context.cursor.column,
        )


@dataclass(frozen=True, slots=True)
class ResizeRepaintStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.RESIZE_REPAINT
    name: ClassVar[str] = "resize_repaint"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return context.width_changed or (context.height_changed and not runtime.termux_session)

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        return runtime.repaint_diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            changed_range=context.changed_range,
            cursor=context.cursor,
            declared_cursor=context.declared_cursor,
            operation_class="resize_repaint",
            repaint_kind="resize",
            repaint_reason="terminal_size_changed",
            width_changed=context.width_changed,
            height_changed=context.height_changed,
            delete_kitty_image_sequences=context.previous_kitty_delete_sequences,
        )


@dataclass(frozen=True, slots=True)
class UnsafeViewportStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.UNSAFE_VIEWPORT
    name: ClassVar[str] = "unsafe_viewport"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return runtime.unsafe_viewport_reason is not None

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if runtime.unsafe_viewport_reason is None:
            raise AssertionError("unsafe viewport strategy planned without a reason")
        return runtime.repaint_diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            changed_range=context.changed_range,
            cursor=context.cursor,
            declared_cursor=context.declared_cursor,
            operation_class="recovery_repaint",
            repaint_kind="recovery",
            repaint_reason=runtime.unsafe_viewport_reason,
            delete_kitty_image_sequences=context.previous_kitty_delete_sequences,
        )


@dataclass(frozen=True, slots=True)
class NoChangeStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.NO_CHANGE
    name: ClassVar[str] = "no_change"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return context.changed_range is None

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if (context.cursor.row, context.cursor.column) != (
            runtime.previous_cursor_row,
            runtime.previous_cursor_column,
        ):
            return runtime.diagnostics(
                current_lines=context.current_lines,
                previous_lines=context.previous_lines,
                size=context.size,
                operation_class="cursor_update",
                operations=_cursor_update_operations(
                    context.cursor,
                    viewport_top=context.viewport_top,
                    hardware_cursor_row=runtime.hardware_cursor_row,
                ),
                viewport_top=context.viewport_top,
                width_changed=context.width_changed,
                height_changed=context.height_changed,
                cursor=context.cursor,
                hardware_cursor_row=context.cursor.row,
                hardware_cursor_column=context.cursor.column,
            )
        return runtime.diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            operation_class="noop",
            operations=(),
            viewport_top=context.viewport_top,
            width_changed=context.width_changed,
            height_changed=context.height_changed,
            cursor=context.cursor,
            hardware_cursor_row=runtime.hardware_cursor_row,
            hardware_cursor_column=runtime.hardware_cursor_column,
        )


@dataclass(frozen=True, slots=True)
class TranscriptWindowTrimmedResetStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.TRANSCRIPT_WINDOW_TRIMMED_RESET
    name: ClassVar[str] = "transcript_window_trimmed_reset"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return bool(
            runtime.baseline_reset_reason is not None
            and runtime.baseline_reset_reason.startswith("transcript_window_trimmed:")
        )

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if runtime.baseline_reset_reason is None:
            raise AssertionError("trimmed transcript reset strategy planned without a reason")
        return runtime.managed_viewport_repaint_diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            changed_range=context.changed_range,
            cursor=context.cursor,
            declared_cursor=context.declared_cursor,
            repaint_reason=runtime.baseline_reset_reason,
            delete_kitty_image_sequences=context.previous_kitty_delete_sequences,
        )


@dataclass(frozen=True, slots=True)
class BaselineResetStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.BASELINE_RESET
    name: ClassVar[str] = "baseline_reset"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return bool(
            runtime.baseline_reset_reason is not None
            and not runtime.baseline_reset_reason.startswith("transcript_window_trimmed:")
        )

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if runtime.baseline_reset_reason is None:
            raise AssertionError("baseline reset strategy planned without a reason")
        return runtime.repaint_diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            changed_range=context.changed_range,
            cursor=context.cursor,
            declared_cursor=context.declared_cursor,
            operation_class="baseline_repaint",
            repaint_kind="recovery",
            repaint_reason=runtime.baseline_reset_reason,
            delete_kitty_image_sequences=context.previous_kitty_delete_sequences,
        )


@dataclass(frozen=True, slots=True)
class AppendStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.APPEND
    name: ClassVar[str] = "append"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return context.append_start is not None

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if context.append_start is None or context.last_changed is None:
            raise AssertionError("append strategy planned without append facts")
        return runtime.diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            operation_class="append_update",
            operations=_append_operations(
                context.current_lines[context.append_start :],
                append_start=context.append_start,
                hardware_cursor_row=runtime.hardware_cursor_row,
                cursor=context.declared_cursor,
                viewport_top=context.viewport_top,
            ),
            changed_range=context.changed_range,
            viewport_top=context.viewport_top,
            append_start=context.append_start,
            appended_lines=context.appended_lines,
            render_end=context.last_changed,
            cursor=context.cursor,
            hardware_cursor_row=_hardware_row_after_write(context.current_lines, cursor=context.declared_cursor),
            hardware_cursor_column=context.cursor.column,
        )


@dataclass(frozen=True, slots=True)
class ProtectedAppendStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.PROTECTED_APPEND
    name: ClassVar[str] = "protected_append"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        if context.first_changed is None:
            return False
        return (
            _protected_append_candidate(
                current_lines=context.current_lines,
                previous_lines=context.previous_lines,
                first_changed=context.first_changed,
                appended_lines=context.appended_lines,
                cursor=context.declared_cursor,
                size=context.size,
            )
            is not None
        )

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if context.first_changed is None:
            raise AssertionError("protected append strategy planned without changed range facts")
        protected_append = _protected_append_plan(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            first_changed=context.first_changed,
            appended_lines=context.appended_lines,
            cursor=context.declared_cursor,
            size=context.size,
        )
        if protected_append is None:
            return runtime.managed_viewport_repaint_diagnostics(
                current_lines=context.current_lines,
                previous_lines=context.previous_lines,
                size=context.size,
                changed_range=context.changed_range,
                cursor=context.cursor,
                declared_cursor=context.declared_cursor,
                repaint_reason="non_pure_protected_append",
                delete_kitty_image_sequences=context.previous_kitty_delete_sequences,
            )
        inserted_start, _inserted_end, _protected_start = protected_append
        return runtime.managed_viewport_repaint_diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            changed_range=context.changed_range,
            cursor=context.cursor,
            declared_cursor=context.declared_cursor,
            repaint_reason=None,
            operation_class="protected_append_update",
            repaint_kind=None,
            append_start=inserted_start,
            delete_kitty_image_sequences=_kitty_delete_sequences(
                context.previous_lines[inserted_start:]
            ),
        )


@dataclass(frozen=True, slots=True)
class ShrinkViewportRepaintStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.SHRINK_VIEWPORT_REPAINT
    name: ClassVar[str] = "shrink_viewport_repaint"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return (
            len(context.current_lines) < len(context.previous_lines)
            and context.viewport_top < runtime.previous_viewport_top
        )

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        return runtime.managed_viewport_repaint_diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            changed_range=context.changed_range,
            cursor=context.cursor,
            declared_cursor=context.declared_cursor,
            repaint_reason="viewport_top_decreased_after_shrink",
            delete_kitty_image_sequences=context.previous_kitty_delete_sequences,
        )


@dataclass(frozen=True, slots=True)
class ShrinkClearStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.SHRINK_CLEAR
    name: ClassVar[str] = "shrink_clear"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return bool(
            context.first_changed is not None
            and context.first_changed >= len(context.current_lines)
            and len(context.previous_lines) > len(context.current_lines)
        )

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if context.first_changed is None or context.last_changed is None:
            raise AssertionError("shrink clear strategy planned without changed range facts")
        target_row = max(0, len(context.current_lines) - 1)
        return runtime.diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            operation_class="shrink_clear",
            operations=_shrink_clear_operations(
                previous_lines=context.previous_lines,
                current_lines=context.current_lines,
                target_row=target_row,
                hardware_cursor_row=runtime.hardware_cursor_row,
                delete_kitty_image_sequences=_kitty_delete_sequences_in_range(
                    context.previous_lines,
                    context.first_changed,
                    context.last_changed,
                ),
            ),
            changed_range=context.changed_range,
            viewport_top=context.differential_viewport_top,
            render_end=target_row,
            cursor=context.cursor,
            hardware_cursor_row=target_row,
            hardware_cursor_column=context.cursor.column,
        )


@dataclass(frozen=True, slots=True)
class ChangedAboveViewportStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.CHANGED_ABOVE_VIEWPORT
    name: ClassVar[str] = "changed_above_viewport"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return bool(
            context.first_changed is not None
            and context.first_changed
            < max(runtime.previous_viewport_top, context.viewport_top)
        )

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        return runtime.managed_viewport_repaint_diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            changed_range=context.changed_range,
            cursor=context.cursor,
            declared_cursor=context.declared_cursor,
            repaint_reason="changed_range_above_viewport",
            delete_kitty_image_sequences=context.previous_kitty_delete_sequences,
        )


@dataclass(frozen=True, slots=True)
class ChangedRangeStrategy:
    kind: ClassVar[RenderPlanStrategyKind] = RenderPlanStrategyKind.CHANGED_RANGE
    name: ClassVar[str] = "changed_range"

    def match(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> bool:
        return context.changed_range is not None

    def plan(self, context: RenderPlanContext, *, runtime: RenderPlanRuntime) -> RenderDiagnostics:
        if context.changed_range is None or context.last_changed is None or context.first_changed is None:
            raise AssertionError("changed range strategy planned without changed range facts")
        render_end = min(context.last_changed, len(context.current_lines) - 1)
        hardware_cursor_row, hardware_cursor_column = _changed_range_hardware_cursor(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            render_end=render_end,
            declared_cursor=context.declared_cursor,
            size=context.size,
        )
        return runtime.diagnostics(
            current_lines=context.current_lines,
            previous_lines=context.previous_lines,
            size=context.size,
            operation_class="changed_range_update",
            operations=_changed_range_operations(
                current_lines=context.current_lines,
                previous_lines=context.previous_lines,
                changed_range=context.changed_range,
                previous_viewport_top=runtime.previous_viewport_top,
                hardware_cursor_row=runtime.hardware_cursor_row,
                cursor=context.declared_cursor,
                viewport_top=context.differential_viewport_top,
                delete_kitty_image_sequences=_kitty_delete_sequences_in_range(
                    context.previous_lines,
                    context.first_changed,
                    context.last_changed,
                ),
            ),
            changed_range=context.changed_range,
            viewport_top=context.differential_viewport_top,
            render_end=render_end,
            cursor=context.cursor,
            hardware_cursor_row=hardware_cursor_row,
            hardware_cursor_column=hardware_cursor_column,
        )


DEFAULT_STRATEGIES: dict[RenderPlanStrategyKind, RenderPlanStrategy] = {
    RenderPlanStrategyKind.FIRST_RENDER: FirstRenderStrategy(),
    RenderPlanStrategyKind.TRANSCRIPT_WINDOW_TRIMMED_RESET: TranscriptWindowTrimmedResetStrategy(),
    RenderPlanStrategyKind.BASELINE_RESET: BaselineResetStrategy(),
    RenderPlanStrategyKind.RESIZE_REPAINT: ResizeRepaintStrategy(),
    RenderPlanStrategyKind.UNSAFE_VIEWPORT: UnsafeViewportStrategy(),
    RenderPlanStrategyKind.NO_CHANGE: NoChangeStrategy(),
    RenderPlanStrategyKind.APPEND: AppendStrategy(),
    RenderPlanStrategyKind.PROTECTED_APPEND: ProtectedAppendStrategy(),
    RenderPlanStrategyKind.SHRINK_VIEWPORT_REPAINT: ShrinkViewportRepaintStrategy(),
    RenderPlanStrategyKind.SHRINK_CLEAR: ShrinkClearStrategy(),
    RenderPlanStrategyKind.CHANGED_ABOVE_VIEWPORT: ChangedAboveViewportStrategy(),
    RenderPlanStrategyKind.CHANGED_RANGE: ChangedRangeStrategy(),
}


@dataclass(slots=True)
class RenderLoop:
    screen_root: ScreenRoot
    clear_scrollback_policy: ClearScrollbackPolicy = "resize"
    termux_session: bool = False
    previous_rendered_lines: Sequence[str] = ()
    previous_raw_lines: Sequence[str] = ()
    previous_size: TerminalSize | None = None
    previous_viewport_top: int = 0
    scrollback_viewport_top: int = 0
    hardware_cursor_row: int = 0
    hardware_cursor_column: int = 0
    working_area_high_water_mark: int = 0
    previous_cursor_row: int = 0
    previous_cursor_column: int = 0
    _unsafe_viewport_reason: str | None = None
    _baseline_reset_reason: str | None = None
    _planned_raw_lines: Sequence[str] = ()
    _finalized_segment_cache: dict[tuple[object, object], _LogicalLineSegment] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _planned_reused_segment_count: int = field(default=0, init=False, repr=False)
    _planned_materialized_line_count: int = field(default=0, init=False, repr=False)
    _planned_flattened_line_count: int = field(default=0, init=False, repr=False)
    committed_frame_revision: int = field(default=0, init=False)
    _next_frame_revision: int = field(default=0, init=False, repr=False)
    _planned_base_frame_revision: int = field(default=0, init=False, repr=False)
    _planned_frame_revision: int = field(default=0, init=False, repr=False)

    def mark_viewport_unsafe(self, reason: str) -> None:
        self._unsafe_viewport_reason = reason

    def reset_baseline(self, reason: str = "baseline_reset") -> None:
        self._baseline_reset_reason = reason

    def _build_plan_context(self, size: TerminalSize) -> RenderPlanContext:
        self._planned_base_frame_revision = self.committed_frame_revision
        self._next_frame_revision += 1
        self._planned_frame_revision = self._next_frame_revision
        result = self.screen_root.render(
            RenderConstraints(width=size.columns, max_height=1_000_000, visible_height=size.rows)
        )
        raw_current_lines, current_lines = self._logical_lines(result)
        self._planned_raw_lines = raw_current_lines
        cursor = _cursor_or_line_end(result.cursor, current_lines)
        previous_lines = self.previous_rendered_lines
        previous_size = self.previous_size
        width_changed = previous_size is not None and previous_size.columns != size.columns
        height_changed = previous_size is not None and previous_size.rows != size.rows
        changed_range = _expand_changed_range_for_kitty_images(
            previous_lines,
            _changed_line_range(previous_lines, current_lines),
        )
        first_changed: int | None = None
        last_changed: int | None = None
        appended_lines = max(0, len(current_lines) - len(previous_lines))
        append_start: int | None = None
        if changed_range is not None:
            first_changed, last_changed = changed_range
            append_start = (
                first_changed
                if appended_lines > 0 and first_changed == len(previous_lines) and first_changed > 0
                else None
            )
        viewport_top = _viewport_top(current_lines, size)
        differential_viewport_top = _differential_viewport_top(
            previous_viewport_top=self.previous_viewport_top,
            natural_viewport_top=viewport_top,
            previous_line_count=len(previous_lines),
            current_line_count=len(current_lines),
        )
        previous_kitty_delete_sequences = _kitty_delete_sequences(previous_lines)
        return RenderPlanContext(
            size=size,
            result=result,
            raw_current_lines=raw_current_lines,
            current_lines=current_lines,
            previous_lines=previous_lines,
            previous_size=previous_size,
            declared_cursor=result.cursor,
            cursor=cursor,
            changed_range=changed_range,
            first_changed=first_changed,
            last_changed=last_changed,
            appended_lines=appended_lines,
            append_start=append_start,
            viewport_top=viewport_top,
            differential_viewport_top=differential_viewport_top,
            width_changed=width_changed,
            height_changed=height_changed,
            previous_kitty_delete_sequences=previous_kitty_delete_sequences,
        )

    def _logical_lines(self, result: RenderResult) -> tuple[Sequence[str], Sequence[str]]:
        self._planned_reused_segment_count = 0
        self._planned_materialized_line_count = 0
        self._planned_flattened_line_count = 0
        if not isinstance(result.lines, SegmentedRenderLines):
            raw_lines = tuple(line.text for line in result.lines)
            self._planned_flattened_line_count = len(raw_lines)
            self._planned_materialized_line_count = len(raw_lines)
            return raw_lines, _finalize_rendered_lines(
                raw_lines,
                previous_raw_lines=self.previous_raw_lines,
                previous_finalized_lines=self.previous_rendered_lines,
            )

        # Retain only segments from the latest complete segmented materialization.
        # Building off to the side keeps the previous cache intact if finalization fails.
        previous_segment_cache = self._finalized_segment_cache
        current_segment_cache: dict[tuple[object, object], _LogicalLineSegment] = {}
        segments: list[_LogicalLineSegment] = []
        for rendered_segment in result.lines.segments:
            cache_key = _render_segment_cache_key(rendered_segment)
            logical_segment = (
                current_segment_cache.get(cache_key) if cache_key is not None else None
            )
            if logical_segment is None and cache_key is not None:
                logical_segment = previous_segment_cache.get(cache_key)
            if logical_segment is not None:
                self._planned_reused_segment_count += 1
            else:
                logical_segment = _finalize_render_segment(rendered_segment)
                self._planned_materialized_line_count += len(logical_segment.raw_lines)
            segments.append(logical_segment)
            if cache_key is not None:
                current_segment_cache[cache_key] = logical_segment
        logical_segments = tuple(segments)
        raw_lines = _SegmentedTextLines(logical_segments, finalized=False)
        finalized_lines = _SegmentedTextLines(logical_segments, finalized=True)
        self._finalized_segment_cache = current_segment_cache
        return raw_lines, finalized_lines

    def _plan_runtime(self) -> RenderPlanRuntime:
        return RenderPlanRuntime(
            previous_viewport_top=self.previous_viewport_top,
            previous_cursor_row=self.previous_cursor_row,
            previous_cursor_column=self.previous_cursor_column,
            hardware_cursor_row=self.hardware_cursor_row,
            hardware_cursor_column=self.hardware_cursor_column,
            working_area_high_water_mark=self.working_area_high_water_mark,
            termux_session=self.termux_session,
            clear_scrollback_policy=self.clear_scrollback_policy,
            baseline_reset_reason=self._baseline_reset_reason,
            unsafe_viewport_reason=self._unsafe_viewport_reason,
            diagnostics=self._diagnostics,
            repaint_diagnostics=self._repaint_diagnostics,
            managed_viewport_repaint_diagnostics=self._managed_viewport_repaint_diagnostics,
        )

    def plan(self, size: TerminalSize) -> RenderDiagnostics:
        context = self._build_plan_context(size)
        runtime = self._plan_runtime()
        for kind in DEFAULT_STRATEGY_ORDER:
            strategy = DEFAULT_STRATEGIES[kind]
            if strategy.match(context, runtime=runtime):
                return strategy.plan(context, runtime=runtime)
        raise AssertionError("no render strategy matched")

    def _managed_viewport_repaint_diagnostics(
        self,
        *,
        current_lines: tuple[str, ...],
        previous_lines: tuple[str, ...],
        size: TerminalSize,
        changed_range: tuple[int, int] | None,
        cursor: CursorDeclaration,
        declared_cursor: CursorDeclaration | None,
        repaint_reason: str | None,
        operation_class: str = "managed_viewport_repaint",
        repaint_kind: str | None = "recovery",
        append_start: int | None = None,
        delete_kitty_image_sequences: tuple[str, ...] = (),
    ) -> RenderDiagnostics:
        viewport_top = _viewport_top(current_lines, size)
        return self._diagnostics(
            current_lines=current_lines,
            previous_lines=previous_lines,
            size=size,
            operation_class=operation_class,
            operations=_managed_viewport_repaint_operations(
                current_lines,
                previous_lines=previous_lines,
                cursor=declared_cursor,
                viewport_top=viewport_top,
                previous_viewport_top=self.previous_viewport_top,
                scrollback_viewport_top=self.scrollback_viewport_top,
                size=size,
                hardware_cursor_row=self.hardware_cursor_row,
                delete_kitty_image_sequences=delete_kitty_image_sequences,
            ),
            changed_range=changed_range,
            viewport_top=viewport_top,
            append_start=append_start,
            appended_lines=max(0, len(current_lines) - len(previous_lines)),
            repaint_kind=repaint_kind,
            repaint_reason=repaint_reason,
            cursor=cursor,
            hardware_cursor_row=_hardware_row_after_write(current_lines, cursor=declared_cursor),
            hardware_cursor_column=cursor.column,
        )

    def commit(self, diagnostics: RenderDiagnostics, *, size: TerminalSize) -> None:
        if diagnostics.base_frame_revision != self.committed_frame_revision:
            raise RuntimeError("render plan base revision no longer matches the committed frame")
        self.previous_rendered_lines = diagnostics.current_logical_lines
        self.previous_raw_lines = diagnostics.raw_logical_lines
        self.previous_size = size
        self.previous_viewport_top = diagnostics.viewport_top
        if diagnostics.clear_scrollback_emitted:
            self.scrollback_viewport_top = diagnostics.viewport_top
        else:
            self.scrollback_viewport_top = max(
                self.scrollback_viewport_top,
                diagnostics.viewport_top,
            )
        self.hardware_cursor_row = diagnostics.hardware_cursor_row
        self.hardware_cursor_column = diagnostics.hardware_cursor_column
        self.previous_cursor_row = diagnostics.logical_cursor_row
        self.previous_cursor_column = diagnostics.logical_cursor_column
        self.working_area_high_water_mark = max(
            self.working_area_high_water_mark, len(diagnostics.current_logical_lines)
        )
        self.committed_frame_revision = diagnostics.frame_revision
        self._unsafe_viewport_reason = None
        self._baseline_reset_reason = None

    def _repaint_diagnostics(
        self,
        *,
        current_lines: tuple[str, ...],
        previous_lines: tuple[str, ...],
        size: TerminalSize,
        changed_range: tuple[int, int] | None,
        cursor: CursorDeclaration,
        declared_cursor: CursorDeclaration | None = None,
        operation_class: str,
        repaint_kind: str,
        repaint_reason: str,
        width_changed: bool = False,
        height_changed: bool = False,
        delete_kitty_image_sequences: tuple[str, ...] = (),
    ) -> RenderDiagnostics:
        return self._diagnostics(
            current_lines=current_lines,
            previous_lines=previous_lines,
            size=size,
            operation_class=operation_class,
            operations=_repaint_operations(
                current_lines,
                clear_scrollback=_should_clear_scrollback(
                    policy=self.clear_scrollback_policy,
                    repaint_kind=repaint_kind,
                ),
                cursor=declared_cursor,
                viewport_top=_viewport_top(current_lines, size),
                delete_kitty_image_sequences=delete_kitty_image_sequences,
            ),
            changed_range=changed_range,
            viewport_top=_viewport_top(current_lines, size),
            repaint_kind=repaint_kind,
            repaint_reason=repaint_reason,
            width_changed=width_changed,
            height_changed=height_changed,
            cursor=cursor,
            hardware_cursor_row=_hardware_row_after_write(current_lines, cursor=declared_cursor),
            hardware_cursor_column=cursor.column,
        )

    def _diagnostics(
        self,
        *,
        current_lines: tuple[str, ...],
        previous_lines: tuple[str, ...],
        size: TerminalSize,
        operation_class: str,
        operations: tuple[TerminalOperation, ...],
        changed_range: tuple[int, int] | None = None,
        viewport_top: int = 0,
        append_start: int | None = None,
        appended_lines: int = 0,
        render_end: int | None = None,
        repaint_kind: str | None = None,
        repaint_reason: str | None = None,
        width_changed: bool = False,
        height_changed: bool = False,
        cursor: CursorDeclaration | None = None,
        hardware_cursor_row: int | None = None,
        hardware_cursor_column: int | None = None,
    ) -> RenderDiagnostics:
        clear_scrollback_emitted = any(operation.kind == "clear_scrollback" for operation in operations)
        logical_cursor = cursor if cursor is not None else _cursor_or_line_end(None, current_lines)
        terminal_cursor_row = logical_cursor.row if hardware_cursor_row is None else hardware_cursor_row
        terminal_cursor_column = logical_cursor.column if hardware_cursor_column is None else hardware_cursor_column
        return RenderDiagnostics(
            current_logical_lines=current_lines,
            raw_logical_lines=self._planned_raw_lines,
            previous_rendered_lines=previous_lines,
            changed_line_range=changed_range,
            operation_class=operation_class,
            append_start=append_start,
            appended_lines=appended_lines,
            render_end=render_end,
            viewport_top=viewport_top,
            previous_viewport_top=self.previous_viewport_top,
            logical_cursor_row=logical_cursor.row,
            logical_cursor_column=logical_cursor.column,
            hardware_cursor_row=terminal_cursor_row,
            hardware_cursor_column=terminal_cursor_column,
            working_area_high_water_mark=max(self.working_area_high_water_mark, len(current_lines)),
            width_changed=width_changed,
            height_changed=height_changed,
            operations=operations,
            repaint_kind=repaint_kind,
            repaint_reason=repaint_reason,
            clear_scrollback_policy=self.clear_scrollback_policy,
            clear_scrollback_emitted=clear_scrollback_emitted,
            reused_render_segment_count=self._planned_reused_segment_count,
            materialized_logical_line_count=self._planned_materialized_line_count,
            flattened_logical_line_count=self._planned_flattened_line_count,
            base_frame_revision=self._planned_base_frame_revision,
            frame_revision=self._planned_frame_revision,
        )


def _changed_line_range(previous_lines: Sequence[str], current_lines: Sequence[str]) -> tuple[int, int] | None:
    if isinstance(previous_lines, _SegmentedTextLines) and isinstance(current_lines, _SegmentedTextLines):
        common_segments = 0
        common_limit = min(len(previous_lines.segments), len(current_lines.segments))
        while (
            common_segments < common_limit
            and previous_lines.segments[common_segments] is current_lines.segments[common_segments]
        ):
            common_segments += 1
        if common_segments == len(previous_lines.segments) == len(current_lines.segments):
            return None
        prefix_rows = previous_lines.segment_start(common_segments)
        if prefix_rows != current_lines.segment_start(common_segments):
            return _changed_line_range_flat(previous_lines, current_lines)
        local = _changed_line_range_flat(
            previous_lines.tail_segments(common_segments),
            current_lines.tail_segments(common_segments),
        )
        if local is None:
            return None
        return prefix_rows + local[0], prefix_rows + local[1]
    return _changed_line_range_flat(previous_lines, current_lines)


def _changed_line_range_flat(
    previous_lines: Sequence[str],
    current_lines: Sequence[str],
) -> tuple[int, int] | None:
    first_changed = -1
    last_changed = -1
    for index in range(max(len(previous_lines), len(current_lines))):
        old_line = previous_lines[index] if index < len(previous_lines) else ""
        new_line = current_lines[index] if index < len(current_lines) else ""
        if old_line == new_line:
            continue
        if first_changed == -1:
            first_changed = index
        last_changed = index
    if first_changed == -1:
        return None
    return first_changed, last_changed


def _expand_changed_range_for_kitty_images(
    previous_lines: Sequence[str],
    changed_range: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if changed_range is None:
        return None
    first_changed, last_changed = changed_range
    if isinstance(previous_lines, _SegmentedTextLines):
        for row, _image_id, _delete_sequence in previous_lines.iter_kitty_images():
            if row >= first_changed:
                last_changed = max(last_changed, row)
        return first_changed, last_changed
    for index in range(first_changed, len(previous_lines)):
        if extract_kitty_image_ids(previous_lines[index]):
            last_changed = max(last_changed, index)
    return first_changed, last_changed


def _kitty_delete_sequences(lines: Sequence[str]) -> tuple[str, ...]:
    if isinstance(lines, _SegmentedTextLines):
        deletes: list[str] = []
        seen: set[int] = set()
        for _row, image_id, delete_sequence in lines.iter_kitty_images():
            if image_id in seen:
                continue
            seen.add(image_id)
            deletes.append(delete_sequence)
        return tuple(deletes)
    deletes: list[str] = []
    seen: set[int] = set()
    for line in lines:
        tmux_passthrough = _line_uses_tmux_passthrough(line)
        for image_id in extract_kitty_image_ids(line):
            if image_id in seen:
                continue
            seen.add(image_id)
            delete_sequence = delete_kitty_image(image_id)
            if tmux_passthrough:
                delete_sequence = wrap_tmux_passthrough(delete_sequence)
            deletes.append(delete_sequence)
    return tuple(deletes)


def _kitty_delete_sequences_in_range(lines: Sequence[str], first: int, last: int) -> tuple[str, ...]:
    if last < first or first >= len(lines):
        return ()
    if isinstance(lines, _SegmentedTextLines):
        deletes: list[str] = []
        seen: set[int] = set()
        for row, image_id, delete_sequence in lines.iter_kitty_images():
            if row < first or row > last or image_id in seen:
                continue
            seen.add(image_id)
            deletes.append(delete_sequence)
        return tuple(deletes)
    return _kitty_delete_sequences(lines[max(0, first) : min(last + 1, len(lines))])


def _kitty_delete_operations(delete_sequences: tuple[str, ...]) -> tuple[TerminalOperation, ...]:
    return tuple(TerminalOperation.write(sequence) for sequence in delete_sequences)


def _line_uses_tmux_passthrough(line: str) -> bool:
    return "\x1bPtmux;" in line


def _finalize_rendered_lines(
    lines: tuple[str, ...],
    *,
    previous_raw_lines: tuple[str, ...] = (),
    previous_finalized_lines: tuple[str, ...] = (),
) -> tuple[str, ...]:
    finalized: list[str] = []
    reusable_count = min(len(lines), len(previous_raw_lines), len(previous_finalized_lines))
    for index, line in enumerate(lines):
        if index < reusable_count and line == previous_raw_lines[index]:
            finalized.append(previous_finalized_lines[index])
            continue
        finalized.append(_finalize_rendered_line(line))
    return tuple(finalized)


def _finalize_rendered_line(line: str) -> str:
    if is_terminal_image_line(line):
        return line
    normalized = normalize_terminal_output(line)
    if "\x1b" not in normalized:
        return normalized
    if normalized.endswith(SEGMENT_RESET):
        return normalized
    return normalized + SEGMENT_RESET


def _render_segment_cache_key(segment: RenderLineSegmentLike) -> tuple[object, object] | None:
    if not segment.cacheable:
        return None
    key = (segment.identity_key, segment.revision)
    try:
        hash(key)
    except TypeError:
        return None
    return key


def _finalize_render_segment(segment: RenderLineSegmentLike) -> _LogicalLineSegment:
    raw_lines = tuple(line.text for line in segment.iter_lines())
    finalized_lines = tuple(_finalize_rendered_line(line) for line in raw_lines)
    kitty_images: list[tuple[int, int, str]] = []
    for row, line in enumerate(finalized_lines):
        tmux_passthrough = _line_uses_tmux_passthrough(line)
        for image_id in extract_kitty_image_ids(line):
            delete_sequence = delete_kitty_image(image_id)
            if tmux_passthrough:
                delete_sequence = wrap_tmux_passthrough(delete_sequence)
            kitty_images.append((row, image_id, delete_sequence))
    return _LogicalLineSegment(
        raw_lines=raw_lines,
        finalized_lines=finalized_lines,
        kitty_images=tuple(kitty_images),
    )


def _viewport_top(lines: tuple[str, ...], size: TerminalSize) -> int:
    return max(0, len(lines) - size.rows)


def _differential_viewport_top(
    *,
    previous_viewport_top: int,
    natural_viewport_top: int,
    previous_line_count: int,
    current_line_count: int,
) -> int:
    if current_line_count < previous_line_count:
        return max(previous_viewport_top, natural_viewport_top)
    return natural_viewport_top


def _full_write_operations(
    lines: tuple[str, ...], *, cursor: CursorDeclaration | None, viewport_top: int
) -> tuple[TerminalOperation, ...]:
    return _render_then_position_cursor(
        _write_lines(lines),
        cursor=cursor,
        viewport_top=viewport_top,
        current_row=max(0, len(lines) - 1),
    )


def _repaint_operations(
    lines: tuple[str, ...],
    *,
    clear_scrollback: bool,
    cursor: CursorDeclaration | None,
    viewport_top: int,
    delete_kitty_image_sequences: tuple[str, ...] = (),
) -> tuple[TerminalOperation, ...]:
    render_lines = lines if clear_scrollback else lines[viewport_top:]
    operations: list[TerminalOperation] = [
        *_kitty_delete_operations(delete_kitty_image_sequences),
        TerminalOperation.clear_screen(),
    ]
    if clear_scrollback:
        operations.append(TerminalOperation.clear_scrollback())
    operations.extend(_write_lines(render_lines))
    return _render_then_position_cursor(
        tuple(operations),
        cursor=cursor,
        viewport_top=viewport_top,
        current_row=viewport_top + max(0, len(render_lines) - 1),
    )


def _managed_viewport_repaint_operations(
    lines: tuple[str, ...],
    *,
    previous_lines: tuple[str, ...],
    cursor: CursorDeclaration | None,
    viewport_top: int,
    previous_viewport_top: int,
    scrollback_viewport_top: int,
    size: TerminalSize,
    hardware_cursor_row: int,
    delete_kitty_image_sequences: tuple[str, ...] = (),
) -> tuple[TerminalOperation, ...]:
    visible_lines = lines[viewport_top : viewport_top + size.rows]
    full_viewport = (
        len(lines) >= size.rows
        or len(previous_lines) >= size.rows
    )
    scroll_start = min(
        viewport_top,
        max(previous_viewport_top, scrollback_viewport_top),
    )
    scroll_count = viewport_top - scroll_start
    operations: list[TerminalOperation] = [
        TerminalOperation.hide_cursor(),
        TerminalOperation.begin_synchronized_update(),
        *_kitty_delete_operations(delete_kitty_image_sequences),
    ]

    current_physical_row = max(0, hardware_cursor_row - previous_viewport_top)

    def move_to(row: int) -> None:
        nonlocal current_physical_row
        if full_viewport:
            operations.append(TerminalOperation.move_cursor(row=row, column=0))
        else:
            line_delta = row - current_physical_row
            if line_delta:
                operations.append(TerminalOperation.move_relative(lines=line_delta))
            operations.append(TerminalOperation.carriage_return())
        current_physical_row = row

    # A terminal cannot edit a line after it enters scrollback. Refresh the
    # logical rows that are about to leave the viewport before scrolling them.
    for offset in range(scroll_count):
        move_to(offset)
        operations.append(TerminalOperation.clear_line())
        line_index = scroll_start + offset
        if line_index < len(lines):
            operations.append(TerminalOperation.write(lines[line_index]))

    if scroll_count:
        move_to(size.rows - 1)
        operations.extend(
            TerminalOperation.newline()
            for _ in range(scroll_count)
        )
        current_physical_row = size.rows - 1

    # Clear once, then paint at most one screen. The final visible line does
    # not emit a newline, so this phase cannot submit anything to scrollback.
    move_to(0)
    operations.append(TerminalOperation.clear_from_cursor())
    operations.extend(_write_lines(visible_lines))
    current_physical_row = max(0, len(visible_lines) - 1)

    operations.append(TerminalOperation.end_synchronized_update())
    if cursor is not None:
        cursor_row = max(0, min(cursor.row - viewport_top, size.rows - 1))
        if full_viewport:
            operations.append(
                TerminalOperation.move_cursor(
                    row=cursor_row,
                    column=cursor.column,
                )
            )
        else:
            line_delta = cursor_row - current_physical_row
            if line_delta:
                operations.append(TerminalOperation.move_relative(lines=line_delta))
            operations.append(TerminalOperation.move_column(column=cursor.column))
    operations.append(TerminalOperation.show_cursor())
    return tuple(operations)


def _append_operations(
    lines: tuple[str, ...],
    *,
    append_start: int,
    hardware_cursor_row: int,
    cursor: CursorDeclaration | None,
    viewport_top: int,
) -> tuple[TerminalOperation, ...]:
    move_target_row = append_start - 1
    operations: list[TerminalOperation] = []
    line_delta = move_target_row - hardware_cursor_row
    if line_delta != 0:
        operations.append(TerminalOperation.move_relative(lines=line_delta))
    operations.append(TerminalOperation.newline())
    for index, line in enumerate(lines):
        if index > 0:
            operations.append(TerminalOperation.newline())
        operations.append(TerminalOperation.write(line))
    return _render_then_position_cursor(
        tuple(operations),
        cursor=cursor,
        viewport_top=viewport_top,
        current_row=append_start + len(lines) - 1,
    )


def _protected_append_plan(
    *,
    current_lines: tuple[str, ...],
    previous_lines: tuple[str, ...],
    first_changed: int,
    appended_lines: int,
    cursor: CursorDeclaration | None,
    size: TerminalSize,
) -> tuple[int, int, int] | None:
    candidate = _protected_append_candidate(
        current_lines=current_lines,
        previous_lines=previous_lines,
        first_changed=first_changed,
        appended_lines=appended_lines,
        cursor=cursor,
        size=size,
    )
    if candidate is None:
        return None
    inserted_start, inserted_end, protected_start = candidate
    if previous_lines[inserted_start:] != current_lines[inserted_end:]:
        return None
    return inserted_start, inserted_end, protected_start


def _protected_append_candidate(
    *,
    current_lines: tuple[str, ...],
    previous_lines: tuple[str, ...],
    first_changed: int,
    appended_lines: int,
    cursor: CursorDeclaration | None,
    size: TerminalSize,
) -> tuple[int, int, int] | None:
    if cursor is None or appended_lines <= 0:
        return None
    if len(current_lines) < size.rows:
        return None
    inserted_start = first_changed
    inserted_end = inserted_start + appended_lines
    if inserted_start <= 0 or inserted_end >= len(current_lines):
        return None
    if inserted_start > len(previous_lines):
        return None
    protected_start = inserted_end
    protected_height = len(current_lines) - protected_start
    if protected_height <= 0 or protected_height >= size.rows:
        return None
    if cursor.row < protected_start:
        return None
    return inserted_start, inserted_end, protected_start


def _cursor_update_operations(
    cursor: CursorDeclaration,
    *,
    viewport_top: int,
    hardware_cursor_row: int,
) -> tuple[TerminalOperation, ...]:
    return _hide_position_and_show_cursor(
        cursor=cursor,
        viewport_top=viewport_top,
        current_row=hardware_cursor_row,
    )


def _shrink_clear_operations(
    *,
    previous_lines: tuple[str, ...],
    current_lines: tuple[str, ...],
    target_row: int,
    hardware_cursor_row: int,
    delete_kitty_image_sequences: tuple[str, ...] = (),
) -> tuple[TerminalOperation, ...]:
    extra_lines = len(previous_lines) - len(current_lines)
    operations: list[TerminalOperation] = list(_kitty_delete_operations(delete_kitty_image_sequences))
    line_delta = target_row - hardware_cursor_row
    if line_delta != 0:
        operations.append(TerminalOperation.move_relative(lines=line_delta))
    operations.append(TerminalOperation.carriage_return())
    if extra_lines > 0:
        operations.append(TerminalOperation.newline())
    for index in range(extra_lines):
        operations.append(TerminalOperation.clear_line())
        if index < extra_lines - 1:
            operations.append(TerminalOperation.newline())
    if extra_lines > 0:
        operations.append(TerminalOperation.move_relative(lines=-extra_lines))
    return _wrap_synchronized(tuple(operations))


def _changed_range_operations(
    *,
    current_lines: tuple[str, ...],
    previous_lines: tuple[str, ...],
    changed_range: tuple[int, int],
    previous_viewport_top: int,
    hardware_cursor_row: int,
    cursor: CursorDeclaration | None,
    viewport_top: int,
    delete_kitty_image_sequences: tuple[str, ...] = (),
) -> tuple[TerminalOperation, ...]:
    first_changed, last_changed = changed_range
    line_delta = first_changed - hardware_cursor_row
    operations: list[TerminalOperation] = list(_kitty_delete_operations(delete_kitty_image_sequences))
    if line_delta != 0:
        operations.append(TerminalOperation.move_relative(lines=line_delta))
    operations.append(TerminalOperation.carriage_return())
    render_end = min(last_changed, len(current_lines) - 1)
    for line_index in range(first_changed, render_end + 1):
        if line_index > first_changed:
            operations.append(TerminalOperation.newline())
        operations.append(TerminalOperation.clear_line())
        operations.append(TerminalOperation.write(current_lines[line_index]))
    cleared_extra_lines = max(0, len(previous_lines) - len(current_lines))
    if len(previous_lines) > len(current_lines):
        for _ in range(cleared_extra_lines):
            operations.append(TerminalOperation.newline())
            operations.append(TerminalOperation.clear_line())
    return _render_then_position_cursor(
        tuple(operations),
        cursor=cursor,
        viewport_top=viewport_top,
        current_row=render_end + cleared_extra_lines,
    )


def _write_lines(lines: tuple[str, ...]) -> tuple[TerminalOperation, ...]:
    operations: list[TerminalOperation] = []
    for index, line in enumerate(lines):
        if index > 0:
            operations.append(TerminalOperation.newline())
        operations.append(TerminalOperation.write(line))
    return tuple(operations)


def _wrap_synchronized(operations: tuple[TerminalOperation, ...]) -> tuple[TerminalOperation, ...]:
    return (
        TerminalOperation.begin_synchronized_update(),
        *operations,
        TerminalOperation.end_synchronized_update(),
    )


def _render_then_position_cursor(
    operations: tuple[TerminalOperation, ...],
    *,
    cursor: CursorDeclaration | None,
    viewport_top: int,
    current_row: int,
) -> tuple[TerminalOperation, ...]:
    render_operations = _wrap_synchronized(operations)
    if cursor is None:
        return (TerminalOperation.hide_cursor(), *render_operations)
    return (
        TerminalOperation.hide_cursor(),
        *render_operations,
        *_cursor_position_operations(cursor=cursor, viewport_top=viewport_top, current_row=current_row),
        TerminalOperation.show_cursor(),
    )


def _hide_position_and_show_cursor(
    *,
    cursor: CursorDeclaration,
    viewport_top: int,
    current_row: int,
) -> tuple[TerminalOperation, ...]:
    return (
        TerminalOperation.hide_cursor(),
        *_cursor_position_operations(cursor=cursor, viewport_top=viewport_top, current_row=current_row),
        TerminalOperation.show_cursor(),
    )


def _cursor_position_operations(
    *,
    cursor: CursorDeclaration,
    viewport_top: int,
    current_row: int,
) -> tuple[TerminalOperation, ...]:
    del viewport_top
    line_delta = cursor.row - current_row
    operations: list[TerminalOperation] = []
    if line_delta != 0:
        operations.append(TerminalOperation.move_relative(lines=line_delta))
    operations.append(TerminalOperation.move_column(column=cursor.column))
    return tuple(operations)


def _cursor_or_line_end(cursor: CursorDeclaration | None, lines: tuple[str, ...]) -> CursorDeclaration:
    if cursor is not None:
        return cursor
    row = max(0, len(lines) - 1)
    column = visible_width(lines[row]) if lines else 0
    return CursorDeclaration(row=row, column=column)


def _changed_range_hardware_cursor(
    *,
    current_lines: tuple[str, ...],
    previous_lines: tuple[str, ...],
    render_end: int,
    declared_cursor: CursorDeclaration | None,
    size: TerminalSize,
) -> tuple[int, int]:
    if declared_cursor is not None:
        return declared_cursor.row, declared_cursor.column
    cleared_extra_lines = max(0, len(previous_lines) - len(current_lines))
    if cleared_extra_lines:
        return render_end + cleared_extra_lines, 0
    if not current_lines:
        return 0, 0
    return render_end, min(visible_width(current_lines[render_end]), size.columns - 1)


def _should_clear_scrollback(*, policy: ClearScrollbackPolicy, repaint_kind: str) -> bool:
    if policy == "explicit":
        return True
    if policy == "resize":
        return repaint_kind == "resize"
    return False


def _hardware_row_after_write(lines: tuple[str, ...], *, cursor: CursorDeclaration | None) -> int:
    if cursor is not None:
        return cursor.row
    return max(0, len(lines) - 1)
