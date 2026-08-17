from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderLineSegment,
    RenderLineSegmentLike,
    RenderResult,
    SegmentedRenderLines,
)


class RegionRenderable(Protocol):
    def render(self, constraints: RenderConstraints) -> RenderResult: ...


@dataclass(frozen=True, slots=True)
class CappedRenderable:
    """Render another region within a fixed height cap."""

    renderable: RegionRenderable
    max_height: int

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self.renderable.render(
            RenderConstraints(
                width=constraints.width,
                max_height=max(1, min(self.max_height, constraints.max_height)),
                visible_height=constraints.visible_height,
            )
        )


@dataclass(frozen=True, slots=True)
class ScreenRegion:
    name: str
    renderable: RegionRenderable
    required: bool = False
    min_height: int = 0
    max_height: int | None = None
    gap_before: int = 0
    gap_after: int = 0

    def __post_init__(self) -> None:
        if self.min_height < 0:
            raise ValueError("min_height must be non-negative")
        if self.max_height is not None and self.max_height <= 0:
            raise ValueError("max_height must be positive")
        if self.gap_before < 0:
            raise ValueError("gap_before must be non-negative")
        if self.gap_after < 0:
            raise ValueError("gap_after must be non-negative")

    @property
    def reserved_height(self) -> int:
        if self.required:
            return max(1, self.min_height)
        return self.min_height


@dataclass(slots=True)
class ScreenRegionStack:
    regions: tuple[ScreenRegion, ...] | list[ScreenRegion]

    def render(self, constraints: RenderConstraints) -> RenderResult:
        regions = tuple(self.regions)
        segments: list[RenderLineSegmentLike] = []
        line_count = 0
        cursor: CursorDeclaration | None = None
        remaining = constraints.max_height
        for index, region in enumerate(regions):
            if remaining <= 0:
                break
            future_required_height = _reserved_height(regions[index + 1 :])
            before_gap = _allowed_gap(
                region.gap_before,
                remaining,
                future_required_height,
                region.reserved_height,
            )
            if before_gap:
                segments.append(
                    _ephemeral_segment(tuple(RenderLine("") for _ in range(before_gap)))
                )
                line_count += before_gap
                remaining -= before_gap
            available = remaining - future_required_height
            if available <= 0 and not region.required:
                continue
            budget = max(0, available)
            if region.max_height is not None:
                budget = min(budget, region.max_height)
            if budget <= 0:
                continue
            result = region.renderable.render(
                RenderConstraints(
                    width=constraints.width,
                    max_height=budget,
                    visible_height=constraints.visible_height,
                )
            )
            rendered_count = len(result.lines)
            if rendered_count == 0 and not region.required:
                continue
            if result.cursor is not None:
                if cursor is not None:
                    raise ValueError("screen region stack contains multiple cursors")
                cursor = CursorDeclaration(
                    row=line_count + result.cursor.row, column=result.cursor.column
                )
            _extend_segments(segments, result.lines)
            line_count += rendered_count
            remaining -= rendered_count
            future_required_height = _reserved_height(regions[index + 1 :])
            after_gap = _allowed_gap(
                region.gap_after, remaining, future_required_height, 0
            )
            if after_gap:
                segments.append(
                    _ephemeral_segment(tuple(RenderLine("") for _ in range(after_gap)))
                )
                line_count += after_gap
                remaining -= after_gap

        lines = SegmentedRenderLines.from_segments(tuple(segments))
        if len(lines) > constraints.max_height:
            lines = lines.tail(constraints.max_height)
            cursor = None
        return RenderResult(lines=lines, cursor=cursor)


@dataclass(slots=True)
class ScreenLayout:
    editor: RegionRenderable
    header: RegionRenderable | None = None
    transcript: RegionRenderable | None = None
    pending: RegionRenderable | None = None
    status: RegionRenderable | None = None
    widgets_above_editor: tuple[RegionRenderable, ...] | list[RegionRenderable] = field(
        default_factory=tuple
    )
    widgets_below_editor: tuple[RegionRenderable, ...] | list[RegionRenderable] = field(
        default_factory=tuple
    )
    footer: RegionRenderable | None = None
    status_min_height: int = 1
    editor_min_height: int = 1
    footer_min_height: int = 1

    def __post_init__(self) -> None:
        if self.status_min_height < 0:
            raise ValueError("status_min_height must be non-negative")
        if self.editor_min_height < 0:
            raise ValueError("editor_min_height must be non-negative")
        if self.footer_min_height < 0:
            raise ValueError("footer_min_height must be non-negative")

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return ScreenRegionStack(self.regions()).render(constraints)

    def regions(self) -> tuple[ScreenRegion, ...]:
        regions: list[ScreenRegion] = []
        _append_optional_region(regions, "header", self.header)
        _append_optional_region(regions, "transcript", self.transcript)
        _append_optional_region(regions, "pending", self.pending)
        _append_optional_region(
            regions,
            "status",
            self.status,
            required=True,
            min_height=self.status_min_height,
        )
        for index, widget in enumerate(self.widgets_above_editor):
            _append_optional_region(regions, f"widget_above_editor:{index}", widget)
        regions.append(
            ScreenRegion(
                "editor", self.editor, required=True, min_height=self.editor_min_height
            )
        )
        for index, widget in enumerate(self.widgets_below_editor):
            _append_optional_region(regions, f"widget_below_editor:{index}", widget)
        _append_optional_region(
            regions,
            "footer",
            self.footer,
            required=True,
            min_height=self.footer_min_height,
        )
        return tuple(regions)


def _part_has_content(part: Any) -> bool:
    has_content = getattr(part, "has_content", None)
    if isinstance(has_content, bool):
        return has_content
    if callable(has_content):
        return bool(has_content())
    return True


def _append_optional_region(
    regions: list[ScreenRegion],
    name: str,
    renderable: RegionRenderable | None,
    *,
    required: bool = False,
    min_height: int = 0,
    max_height: int | None = None,
) -> None:
    if renderable is None or not _part_has_content(renderable):
        return
    regions.append(
        ScreenRegion(
            name,
            renderable,
            required=required,
            min_height=min_height,
            max_height=max_height,
        )
    )


def _reserved_height(regions: tuple[ScreenRegion, ...]) -> int:
    return sum(region.reserved_height for region in regions if region.required)


def _allowed_gap(
    requested: int,
    remaining: int,
    future_required_height: int,
    current_reserved_height: int,
) -> int:
    if requested <= 0:
        return 0
    spare = remaining - future_required_height - current_reserved_height
    if spare <= 0:
        return 0
    return min(requested, spare)


def _extend_segments(
    segments: list[RenderLineSegmentLike], lines: Sequence[RenderLine]
) -> None:
    if isinstance(lines, SegmentedRenderLines):
        segments.extend(lines.segments)
        return
    segments.append(_ephemeral_segment(tuple(lines)))


def _ephemeral_segment(lines: tuple[RenderLine, ...]) -> RenderLineSegment:
    return RenderLineSegment(lines=lines, cacheable=False)


__all__ = [
    "CappedRenderable",
    "RegionRenderable",
    "ScreenLayout",
    "ScreenRegion",
    "ScreenRegionStack",
]
