from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, cast, runtime_checkable

from loushang.tui.cell_width import (
    autowrap_safe_width,
    slice_by_column,
    truncate_to_width,
    visible_width,
)
from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.terminal import TerminalSize
from loushang.tui.terminal_image import is_terminal_image_line

SurfacePresentation = Literal[
    "inline",
    "overlay",
    "modal",
    "bottom",
    "bottom-exclusive",
    "page",
]
_INLINE_PRESENTATIONS = {"inline", "bottom", "bottom-exclusive"}
_OVERLAY_PRESENTATIONS = {"overlay", "modal"}
_PAGE_PRESENTATIONS = {"page"}
OverlayAnchor = Literal[
    "center",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "top-center",
    "bottom-center",
    "left-center",
    "right-center",
]
SizeValue = int | str


@runtime_checkable
class Renderable(Protocol):
    def render(self, constraints: RenderConstraints) -> RenderResult: ...


@runtime_checkable
class Focusable(Protocol):
    focused: bool

    def focus(self) -> None: ...

    def blur(self) -> None: ...

    def handle_input(self, event: Any) -> Any: ...


@runtime_checkable
class EditorInputTargetProvider(Protocol):
    def editor_input_target(self) -> Any: ...


class FocusableMixin:
    def __init__(self) -> None:
        self.focused = False

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: Any) -> Any:
        return None


@dataclass(slots=True)
class Container:
    children: list[Renderable] = field(default_factory=list)

    def add_child(self, child: Renderable) -> None:
        self.children.append(child)

    def remove_child(self, child: Renderable) -> None:
        self.children.remove(child)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        rendered_lines: list[RenderLine] = []
        cursor: CursorDeclaration | None = None
        for child in self.children:
            remaining_height = constraints.max_height - len(rendered_lines)
            if remaining_height <= 0:
                break
            start_row = len(rendered_lines)
            remaining_visible_height = _remaining_visible_height(
                constraints.visible_height,
                consumed_lines=len(rendered_lines),
            )
            child_result = child.render(
                RenderConstraints(
                    width=constraints.width,
                    max_height=remaining_height,
                    visible_height=remaining_visible_height,
                )
            )
            rendered_lines.extend(child_result.lines)
            if child_result.cursor is not None:
                cursor = CursorDeclaration(
                    row=start_row + child_result.cursor.row,
                    column=child_result.cursor.column,
                )
        return RenderResult.from_lines(
            rendered_lines, constraints=constraints, cursor=cursor
        )


def _remaining_visible_height(
    visible_height: int | None, *, consumed_lines: int
) -> int | None:
    if visible_height is None:
        return None
    remaining = visible_height - consumed_lines
    return remaining if remaining > 0 else None


@dataclass(slots=True)
class Surface:
    renderable: Renderable
    focus_target: Focusable | None = None
    presentation: SurfacePresentation = "overlay"
    captures_focus: bool = True
    non_capturing: bool = False
    row: SizeValue | None = None
    column: SizeValue | None = None
    col: SizeValue | None = None
    width: SizeValue | None = None
    min_width: int | None = None
    max_height: SizeValue | None = None
    anchor: OverlayAnchor = "top-left"
    offset_x: int = 0
    offset_y: int = 0
    margin: int | dict[str, int] | None = None
    visible: Callable[[TerminalSize], bool] | None = None


@dataclass(slots=True)
class SurfaceHandle:
    host: SurfaceHost
    entry: SurfaceEntry
    close_reason: str | None = None

    def close(self, reason: str = "closed") -> None:
        self.close_reason = reason
        self.host.close_surface(self.entry, reason=reason)

    def hide(self) -> None:
        self.close("hidden")

    def set_hidden(self, hidden: bool) -> None:
        self.host.set_hidden(self.entry, hidden)

    def is_hidden(self) -> bool:
        return self.entry.hidden

    def focus(self) -> None:
        self.host.focus_surface(self.entry)

    def unfocus(self) -> None:
        self.host.unfocus_surface(self.entry)

    def is_focused(self) -> bool:
        focus_target = self.entry.surface.focus_target
        return focus_target is not None and focus_target.focused


@dataclass(slots=True)
class SurfaceEntry:
    surface: Surface
    previous_focus: Focusable | None
    hidden: bool = False
    close_reason: str | None = None
    focus_order: int = 0
    last_row: int | None = None
    last_column: int | None = None


@dataclass(frozen=True, slots=True)
class SurfaceInputRouteResult:
    intents: tuple[Any, ...]
    consumed: bool


@dataclass(slots=True)
class SurfaceHost:
    base_focus: Focusable | None = None
    entries: list[SurfaceEntry] = field(default_factory=list)
    _focus_order_counter: int = 0
    _last_size: TerminalSize | None = field(default=None, init=False, repr=False)

    def open_surface(self, surface: Surface) -> SurfaceHandle:
        previous_focus = self.current_focus()
        self._focus_order_counter += 1
        entry = SurfaceEntry(
            surface=surface,
            previous_focus=previous_focus,
            focus_order=self._focus_order_counter,
        )
        self.entries.append(entry)
        if (
            surface.visible is None
            and _surface_captures_focus(surface)
            and surface.focus_target is not None
        ):
            self._set_focus(surface.focus_target)
        return SurfaceHandle(host=self, entry=entry)

    def close_surface(self, entry: SurfaceEntry, *, reason: str) -> None:
        if entry not in self.entries:
            return
        was_focused = (
            entry.surface.focus_target is not None
            and entry.surface.focus_target.focused
        )
        if entry.surface.focus_target is not None:
            entry.surface.focus_target.blur()
        entry.close_reason = reason
        self.entries.remove(entry)
        if was_focused:
            self._restore_focus(entry.previous_focus)

    def set_hidden(self, entry: SurfaceEntry, hidden: bool) -> None:
        if entry not in self.entries or entry.hidden == hidden:
            return
        entry.hidden = hidden
        focus_target = entry.surface.focus_target
        if hidden and focus_target is not None and focus_target.focused:
            focus_target.blur()
            self._restore_focus(entry.previous_focus)
            return
        if (
            not hidden
            and entry.surface.visible is None
            and _surface_captures_focus(entry.surface)
            and focus_target is not None
        ):
            self.focus_surface(entry)

    def focus_surface(self, entry: SurfaceEntry) -> None:
        if entry not in self.entries or not self._is_entry_visible(
            entry, self._last_known_size()
        ):
            return
        focus_target = entry.surface.focus_target
        if not _surface_captures_focus(entry.surface) or focus_target is None:
            return
        self._focus_order_counter += 1
        entry.focus_order = self._focus_order_counter
        self._set_focus(focus_target)

    def unfocus_surface(self, entry: SurfaceEntry) -> None:
        focus_target = entry.surface.focus_target
        if focus_target is None or not focus_target.focused:
            return
        focus_target.blur()
        for candidate in sorted(
            self.entries, key=lambda item: item.focus_order, reverse=True
        ):
            if candidate is entry or not _surface_captures_focus(candidate.surface):
                continue
            candidate_focus = candidate.surface.focus_target
            if candidate_focus is not None and not candidate.hidden:
                self._set_focus(candidate_focus)
                return
        self._restore_focus(entry.previous_focus)

    def current_focus(self) -> Focusable | None:
        for entry in reversed(self.entries):
            focus_target = entry.surface.focus_target
            if (
                _surface_captures_focus(entry.surface)
                and focus_target is not None
                and focus_target.focused
            ):
                return focus_target
        if self.base_focus is not None and self.base_focus.focused:
            return self.base_focus
        return None

    def current_editor_target(self) -> Any | None:
        self._sync_focus_for_visible_entries(self._last_known_size())
        entry = self._current_focus_entry()
        if entry is None:
            return None
        focus_target = entry.surface.focus_target
        if not isinstance(focus_target, EditorInputTargetProvider):
            return None
        target = focus_target.editor_input_target()
        return target if target is not None else None

    def handle_input(self, event: Any) -> Any:
        focus_target = self.current_focus()
        if focus_target is None:
            return None
        return focus_target.handle_input(event)

    def route_input(
        self,
        event: Any,
        *,
        close_on_intents: tuple[str, ...] = ("surface_close", "dialog_cancel"),
    ) -> tuple[Any, ...]:
        return self.route_input_result(event, close_on_intents=close_on_intents).intents

    def route_input_result(
        self,
        event: Any,
        *,
        close_on_intents: tuple[str, ...] = ("surface_close", "dialog_cancel"),
    ) -> SurfaceInputRouteResult:
        self._sync_focus_for_visible_entries(self._last_known_size())
        entry = self._current_focus_entry()
        if entry is None:
            result = self.handle_input(event)
        else:
            result = self._handle_entry_input(entry, event)
        intents = _normalize_surface_input_result(result)
        if entry is not None:
            for intent in intents:
                if getattr(intent, "kind", None) in close_on_intents:
                    self.close_surface(entry, reason=getattr(intent, "kind", "closed"))
                    break
        return SurfaceInputRouteResult(
            intents=intents, consumed=_surface_input_consumed(result, intents)
        )

    def compose(
        self, base: RenderResult, constraints: RenderConstraints
    ) -> RenderResult:
        visible_height = constraints.visible_height or constraints.max_height
        size = TerminalSize(columns=constraints.width, rows=visible_height)
        self._last_size = size
        self._sync_focus_for_visible_entries(size)
        for entry in self.entries:
            entry.last_row = None
            entry.last_column = None
        page_entry = self._top_page_entry(size)
        if not any(
            self._is_entry_visible(entry, size)
            and (
                surface_is_inline_presentation(entry.surface)
                or surface_is_overlay_presentation(entry.surface)
                or surface_is_page_presentation(entry.surface)
            )
            for entry in self.entries
        ):
            return base
        first_visible_entry = 0
        if page_entry is None:
            lines = [line.text for line in base.lines]
            cursor = base.cursor
        else:
            page = page_entry.surface.renderable.render(
                _surface_constraints(page_entry.surface, constraints)
            )
            visible_height = constraints.visible_height or constraints.max_height
            lines = [line.text for line in page.lines[:visible_height]]
            lines.extend("" for _ in range(visible_height - len(lines)))
            cursor = page.cursor
            page_entry.last_row = 0
            page_entry.last_column = 0
            first_visible_entry = self.entries.index(page_entry) + 1
        for entry in self.entries[first_visible_entry:]:
            if not self._is_entry_visible(
                entry, size
            ) or not surface_is_inline_presentation(entry.surface):
                continue
            inline = entry.surface.renderable.render(
                _surface_constraints(entry.surface, constraints)
            )
            entry.last_row = len(lines)
            entry.last_column = 0
            cursor = _merge_surface_cursor(
                cursor,
                inline.cursor,
                row_offset=entry.last_row,
                column_offset=entry.last_column,
            )
            lines.extend(line.text for line in inline.lines)
        for entry in sorted(
            self.entries[first_visible_entry:],
            key=lambda item: item.focus_order,
        ):
            if not self._is_entry_visible(
                entry, size
            ) or not surface_is_overlay_presentation(entry.surface):
                continue
            overlay_constraints = _surface_constraints(entry.surface, constraints)
            overlay = entry.surface.renderable.render(overlay_constraints)
            layout = _resolve_overlay_layout(entry.surface, overlay, constraints)
            entry.last_row = layout.row
            entry.last_column = layout.column
            overlay_lines = (
                overlay.lines[: layout.max_height]
                if layout.max_height is not None
                else overlay.lines
            )
            lines = _compose_overlay(
                lines,
                overlay_lines,
                row=layout.row,
                column=layout.column,
                overlay_width=layout.width,
                constraints=constraints,
            )
            cursor = _merge_surface_cursor(
                cursor,
                overlay.cursor,
                row_offset=layout.row,
                column_offset=layout.column,
            )
        return RenderResult.from_lines(
            [RenderLine(line) for line in lines], constraints=constraints, cursor=cursor
        )

    def has_visible_page(self, constraints: RenderConstraints) -> bool:
        visible_height = constraints.visible_height or constraints.max_height
        return (
            self._top_page_entry(
                TerminalSize(columns=constraints.width, rows=visible_height)
            )
            is not None
        )

    def _restore_focus(
        self, preferred: Focusable | None, *, size: TerminalSize | None = None
    ) -> None:
        for entry in reversed(self.entries):
            focus_target = entry.surface.focus_target
            if (
                _surface_captures_focus(entry.surface)
                and focus_target is not None
                and not entry.hidden
                and (size is None or self._is_entry_visible(entry, size))
            ):
                self._set_focus(focus_target)
                return
        if preferred is not None:
            self._set_focus(preferred)
            return
        if self.base_focus is not None:
            self._set_focus(self.base_focus)

    def _set_focus(self, focus_target: Focusable) -> None:
        current = self.current_focus()
        if current is not None and current is not focus_target:
            current.blur()
        focus_target.focus()

    def _handle_entry_input(self, entry: SurfaceEntry, event: Any) -> Any:
        focus_target = entry.surface.focus_target
        if focus_target is None:
            return None
        return focus_target.handle_input(_translate_surface_input_event(entry, event))

    def _current_focus_entry(self) -> SurfaceEntry | None:
        current = self.current_focus()
        if current is None:
            return None
        for entry in reversed(self.entries):
            if entry.surface.focus_target is current:
                return entry
        return None

    def _is_entry_visible(self, entry: SurfaceEntry, size: TerminalSize) -> bool:
        if entry.hidden:
            return False
        if entry.surface.visible is not None:
            return entry.surface.visible(size)
        return True

    def _sync_focus_for_visible_entries(self, size: TerminalSize) -> None:
        current = self.current_focus()
        if current is not None:
            for entry in self.entries:
                if entry.surface.focus_target is current and not self._is_entry_visible(
                    entry, size
                ):
                    current.blur()
                    self._restore_focus(entry.previous_focus, size=size)
                    break
        current = self.current_focus()
        current_entry = None
        if current is not None:
            for entry in self.entries:
                if entry.surface.focus_target is current:
                    current_entry = entry
                    break
        for entry in sorted(
            self.entries, key=lambda item: item.focus_order, reverse=True
        ):
            focus_target = entry.surface.focus_target
            if (
                self._is_entry_visible(entry, size)
                and _surface_captures_focus(entry.surface)
                and focus_target is not None
                and current_entry is None
            ):
                self._set_focus(focus_target)
                return

    def _last_known_size(self) -> TerminalSize:
        return self._last_size or TerminalSize(columns=1_000_000, rows=1_000_000)

    def _top_page_entry(self, size: TerminalSize) -> SurfaceEntry | None:
        return next(
            (
                entry
                for entry in reversed(self.entries)
                if self._is_entry_visible(entry, size)
                and surface_is_page_presentation(entry.surface)
            ),
            None,
        )


@dataclass(slots=True)
class ScreenRoot:
    base: Renderable
    surface_host: SurfaceHost = field(default_factory=SurfaceHost)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        base_result = (
            RenderResult.from_lines((), constraints=constraints)
            if self.surface_host.has_visible_page(constraints)
            else self.base.render(constraints)
        )
        return self.surface_host.compose(base_result, constraints)

    def consume_render_baseline_reset_reason(self) -> str | None:
        consume = getattr(self.base, "consume_render_baseline_reset_reason", None)
        if not callable(consume):
            return None
        reason = consume()
        return reason if isinstance(reason, str) and reason else None


def _merge_surface_cursor(
    current: CursorDeclaration | None,
    surface_cursor: CursorDeclaration | None,
    *,
    row_offset: int,
    column_offset: int,
) -> CursorDeclaration | None:
    if surface_cursor is None:
        return current
    return CursorDeclaration(
        row=row_offset + surface_cursor.row,
        column=column_offset + surface_cursor.column,
    )


def _normalize_surface_input_result(result: Any) -> tuple[Any, ...]:
    if result is None or isinstance(result, bool):
        return ()
    if isinstance(result, tuple):
        return result
    return (result,)


def _surface_input_consumed(result: Any, intents: tuple[Any, ...]) -> bool:
    if isinstance(result, bool):
        return result
    if result is None:
        return False
    if isinstance(result, tuple):
        return bool(result)
    return True


def _translate_surface_input_event(entry: SurfaceEntry, event: Any) -> Any:
    if getattr(event, "kind", None) != "mouse":
        return event
    mouse_row = getattr(event, "mouse_row", None)
    mouse_column = getattr(event, "mouse_column", None)
    if mouse_row is None or entry.last_row is None:
        return event
    updates: dict[str, int] = {"mouse_row": mouse_row - entry.last_row}
    if mouse_column is not None and entry.last_column is not None:
        updates["mouse_column"] = mouse_column - entry.last_column
    try:
        return replace(event, **updates)
    except TypeError:
        return event


def _surface_constraints(
    surface: Surface, constraints: RenderConstraints
) -> RenderConstraints:
    visible_height = constraints.visible_height or constraints.max_height
    margins = _parse_margin(surface.margin)
    available_width = max(1, constraints.width - margins.left - margins.right)
    available_height = max(1, visible_height - margins.top - margins.bottom)
    width = _parse_size_value(surface.width, constraints.width)
    if width is None:
        width = (
            constraints.width if surface.presentation == "inline" else available_width
        )
    elif surface.presentation == "overlay":
        width = max(width, constraints.width)
    if surface.min_width is not None:
        width = max(width, surface.min_width)
    width = max(1, min(width, available_width))
    max_height = _parse_size_value(surface.max_height, visible_height)
    if max_height is not None:
        max_height = max(1, min(max_height, available_height))
    return RenderConstraints(
        width=width,
        max_height=max_height or constraints.max_height,
        visible_height=constraints.visible_height,
    )


@dataclass(frozen=True, slots=True)
class _ResolvedOverlayLayout:
    row: int
    column: int
    width: int
    max_height: int | None


@dataclass(frozen=True, slots=True)
class _Margins:
    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0


def _resolve_overlay_layout(
    surface: Surface,
    overlay: RenderResult,
    constraints: RenderConstraints,
) -> _ResolvedOverlayLayout:
    visible_height = constraints.visible_height or constraints.max_height
    margins = _parse_margin(surface.margin)
    available_width = max(1, constraints.width - margins.left - margins.right)
    available_height = max(1, visible_height - margins.top - margins.bottom)
    parsed_width = _parse_size_value(surface.width, constraints.width)
    rendered_width = max(
        (visible_width(line.text) for line in overlay.lines), default=1
    )
    width = parsed_width if parsed_width is not None else rendered_width
    if surface.min_width is not None:
        width = max(width, surface.min_width)
    width = max(1, min(width, available_width))
    max_height = _parse_size_value(surface.max_height, visible_height)
    if max_height is not None:
        max_height = max(1, min(max_height, available_height))
    overlay_height = len(overlay.lines)
    effective_height = (
        min(overlay_height, max_height) if max_height is not None else overlay_height
    )
    effective_height = max(0, effective_height)
    row = _resolve_overlay_axis(
        value=surface.row,
        anchor=surface.anchor,
        size=effective_height,
        available=available_height,
        margin_start=margins.top,
        margin_end=margins.bottom,
        total=visible_height,
        axis="row",
    )
    column = _resolve_overlay_axis(
        value=surface.col if surface.col is not None else surface.column,
        anchor=surface.anchor,
        size=width,
        available=available_width,
        margin_start=margins.left,
        margin_end=margins.right,
        total=constraints.width,
        axis="column",
    )
    row += surface.offset_y
    column += surface.offset_x
    row = max(
        margins.top,
        min(row, max(margins.top, visible_height - margins.bottom - effective_height)),
    )
    column = max(
        margins.left,
        min(column, max(margins.left, constraints.width - margins.right - width)),
    )
    return _ResolvedOverlayLayout(
        row=row, column=column, width=width, max_height=max_height
    )


def _resolve_overlay_axis(
    *,
    value: SizeValue | None,
    anchor: OverlayAnchor,
    size: int,
    available: int,
    margin_start: int,
    margin_end: int,
    total: int,
    axis: Literal["row", "column"],
) -> int:
    if value is not None:
        parsed = _parse_position_value(
            value, available=max(0, available - size), margin_start=margin_start
        )
        if parsed is not None:
            return parsed
    if axis == "row":
        if anchor.startswith("bottom"):
            return margin_start + available - size
        if anchor in {"center", "left-center", "right-center"}:
            return margin_start + (available - size) // 2
        return margin_start
    if anchor.endswith("right"):
        return total - margin_end - size
    if anchor in {"center", "top-center", "bottom-center"}:
        return margin_start + (available - size) // 2
    return margin_start


def _parse_size_value(value: SizeValue | None, reference: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if value.endswith("%"):
        try:
            return int(reference * (float(value[:-1]) / 100))
        except ValueError:
            return None
    return None


def _parse_position_value(
    value: SizeValue, *, available: int, margin_start: int
) -> int | None:
    if isinstance(value, int):
        return value
    if value.endswith("%"):
        try:
            return margin_start + int(available * (float(value[:-1]) / 100))
        except ValueError:
            return None
    return None


def _parse_margin(margin: int | dict[str, int] | None) -> _Margins:
    if margin is None:
        return _Margins()
    if isinstance(margin, int):
        value = max(0, margin)
        return _Margins(top=value, right=value, bottom=value, left=value)
    return _Margins(
        top=max(0, margin.get("top", 0)),
        right=max(0, margin.get("right", 0)),
        bottom=max(0, margin.get("bottom", 0)),
        left=max(0, margin.get("left", 0)),
    )


def _surface_captures_focus(surface: Surface) -> bool:
    return surface.captures_focus and not surface.non_capturing


def surface_presentation(
    surface: object, *, default: SurfacePresentation = "inline"
) -> SurfacePresentation:
    raw = getattr(surface, "presentation", default)
    if (
        raw in _INLINE_PRESENTATIONS
        or raw in _OVERLAY_PRESENTATIONS
        or raw in _PAGE_PRESENTATIONS
    ):
        return cast(SurfacePresentation, raw)
    return default


def surface_is_inline_presentation(surface: object) -> bool:
    return surface_presentation(surface) in _INLINE_PRESENTATIONS


def surface_is_overlay_presentation(surface: object) -> bool:
    return surface_presentation(surface) in _OVERLAY_PRESENTATIONS


def surface_is_page_presentation(surface: object) -> bool:
    return surface_presentation(surface) in _PAGE_PRESENTATIONS


def surface_is_bottom_exclusive(surface: object) -> bool:
    if surface_presentation(surface) == "bottom-exclusive":
        return True
    return bool(getattr(surface, "exclusive_bottom", False))


def _compose_overlay(
    base_lines: list[str],
    overlay_lines: Sequence[RenderLine],
    *,
    row: int,
    column: int,
    overlay_width: int,
    constraints: RenderConstraints,
) -> list[str]:
    lines = list(base_lines)
    visible_height = constraints.visible_height or constraints.max_height
    needed_height = max(visible_height, row + len(overlay_lines))
    while len(lines) < needed_height:
        lines.append("")
    viewport_start = max(0, len(lines) - visible_height)
    for offset, overlay_line in enumerate(overlay_lines):
        target_row = viewport_start + row + offset
        if target_row < 0 or target_row >= len(lines):
            continue
        lines[target_row] = _overlay_text(
            lines[target_row],
            overlay_line.text,
            column=column,
            overlay_width=overlay_width,
            total_width=constraints.width,
        )
    return lines


def _overlay_text(
    base: str, overlay: str, *, column: int, overlay_width: int, total_width: int
) -> str:
    if column < 0:
        raise ValueError("overlay column must be non-negative")
    if is_terminal_image_line(base):
        return base
    target_width = autowrap_safe_width(total_width)
    if overlay_width <= 0:
        return truncate_to_width(base, max_width=target_width, ellipsis="")
    if column >= target_width:
        return truncate_to_width(base, max_width=target_width, ellipsis="")
    clipped_width = max(0, min(overlay_width, target_width - column))
    prefix_slice = slice_by_column(base, start=0, length=column, strict=True)
    prefix = prefix_slice.text + (" " * max(0, column - prefix_slice.width))
    clipped_overlay = slice_by_column(
        overlay, start=0, length=clipped_width, strict=True
    ).text
    overlay_cells = visible_width(clipped_overlay)
    suffix_start = column + clipped_width
    suffix_length = max(0, target_width - suffix_start)
    suffix = slice_by_column(
        base, start=suffix_start, length=suffix_length, strict=True
    ).text
    padded_overlay = clipped_overlay + (" " * max(0, clipped_width - overlay_cells))
    return truncate_to_width(
        f"{prefix}{padded_overlay}{suffix}", max_width=target_width, ellipsis=""
    )
