from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from loushang.tui.cell_width import (
    autowrap_safe_width,
    truncate_to_width,
    visible_width,
)
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.theme import ThemeResolver, ThemeStyle, apply_theme_style

from .layout import RegionRenderable

StatusBarStyleMode = Literal["plain", "muted", "codex-like"]

_MODE_TOKEN_PREFIX = {
    "codex-like": "codexLike",
    "muted": "muted",
}

_CODEX_LIKE_DEFAULTS: dict[str, ThemeStyle] = {
    "model": {"foreground": "cyan"},
    "workspace": {"foreground": "green"},
    "branch": {"foreground": "yellow"},
    "session": {"foreground": "bright_black"},
    "permissions": {"foreground": "magenta"},
    "runtime.running": {"foreground": "green"},
    "runtime.idle": {"dim": True},
    "queue": {"foreground": "magenta"},
    "message": {"foreground": "bright_white"},
    "separator": {"dim": True},
}

_MUTED_DEFAULTS: dict[str, ThemeStyle] = {
    "field": {"dim": True},
    "separator": {"dim": True},
}


@dataclass(frozen=True, slots=True)
class StatusField:
    text: str
    priority: int = 0
    token: str = ""


@dataclass(slots=True)
class StatusBar:
    fields: list[StatusField] | tuple[StatusField, ...] = field(default_factory=list)
    separator: str = " | "
    style_mode: StatusBarStyleMode = "plain"
    theme: ThemeResolver | None = None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        ordered = sorted(self.fields, key=lambda status_field: status_field.priority, reverse=True)
        selected: list[StatusField] = []
        for status_field in ordered:
            candidate = selected + [status_field]
            text = _join_status(candidate, separator=self.separator)
            if visible_width(text) <= target_width:
                selected = candidate
        text = _join_status(selected, separator=self.separator)
        if text:
            line = _render_status_segments(
                selected,
                separator=self.separator,
                style_mode=self.style_mode,
                theme=self.theme,
            )
        elif ordered:
            line = _style_status_text(
                truncate_to_width(ordered[0].text, max_width=target_width),
                self.theme,
                self.style_mode,
                ordered[0].token,
            )
        else:
            line = ""
        return RenderResult.from_lines([RenderLine(line)], constraints=constraints)


@dataclass(frozen=True, slots=True)
class FooterField:
    text: str
    side: Literal["left", "right"] = "left"
    priority: int = 0


@dataclass(slots=True)
class FooterStatusLine:
    fields: list[FooterField] | tuple[FooterField, ...] = field(default_factory=list)
    separator: str = " | "
    min_gap: int = 2

    def __post_init__(self) -> None:
        if self.min_gap < 1:
            raise ValueError("min_gap must be positive")

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        selected: list[FooterField] = []
        for footer_field in sorted(self.fields, key=lambda field: field.priority, reverse=True):
            candidate = [*selected, footer_field]
            if _footer_fields_fit(candidate, width=target_width, separator=self.separator, min_gap=self.min_gap):
                selected = candidate
        if not selected and self.fields:
            selected = [max(self.fields, key=lambda field: field.priority)]
        line = _render_footer_fields(selected, width=target_width, separator=self.separator)
        return RenderResult.from_lines([RenderLine(line)], constraints=constraints)


@dataclass(slots=True)
class FooterView:
    primary: RegionRenderable | str | None = None
    secondary: RegionRenderable | str | None = None
    extension_statuses: list[StatusField] | tuple[StatusField, ...] = field(default_factory=list)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        rendered: list[str] = []
        for part in (self.primary, self.secondary):
            if part is None or len(rendered) >= constraints.max_height:
                continue
            rendered.extend(
                _render_footer_part(
                    part,
                    RenderConstraints(
                        width=constraints.width,
                        max_height=constraints.max_height - len(rendered),
                        visible_height=constraints.visible_height,
                    ),
                )
            )
        if self.extension_statuses and len(rendered) < constraints.max_height:
            rendered.extend(
                _render_extension_statuses(
                    self.extension_statuses,
                    RenderConstraints(
                        width=constraints.width,
                        max_height=constraints.max_height - len(rendered),
                        visible_height=constraints.visible_height,
                    ),
                )
            )
        return RenderResult.from_lines(
            [RenderLine(line) for line in rendered[: constraints.max_height]],
            constraints=constraints,
        )


@dataclass(slots=True)
class WorkingLine:
    label: str
    elapsed_seconds: float

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        prefix = f"- {self.label} {_format_elapsed(self.elapsed_seconds)} "
        filler_width = max(0, target_width - visible_width(prefix))
        line = truncate_to_width(prefix + ("-" * filler_width), max_width=target_width)
        return RenderResult.from_lines([RenderLine(line)], constraints=constraints)


def _join_status(fields: list[StatusField], *, separator: str) -> str:
    return separator.join(field.text for field in fields)


def _render_status_segments(
    fields: list[StatusField],
    *,
    separator: str,
    style_mode: StatusBarStyleMode,
    theme: ThemeResolver | None,
) -> str:
    rendered: list[str] = []
    for index, status_field in enumerate(fields):
        if index:
            rendered.append(_style_status_text(separator, theme, style_mode, "separator", separator=True))
        rendered.append(_style_status_text(status_field.text, theme, style_mode, status_field.token))
    return "".join(rendered)


def _style_status_text(
    text: str,
    theme: ThemeResolver | None,
    style_mode: StatusBarStyleMode,
    token: str,
    *,
    separator: bool = False,
) -> str:
    style = _style_for_status_part(theme=theme, style_mode=style_mode, token=token, separator=separator)
    return apply_theme_style(text, style)


def _style_for_status_part(
    *,
    theme: ThemeResolver | None,
    style_mode: StatusBarStyleMode,
    token: str,
    separator: bool = False,
) -> ThemeStyle | None:
    if style_mode == "plain":
        return None
    semantic_token, exact_tokens = _normalize_status_token(token, style_mode=style_mode)
    for candidate in _status_token_candidates(
        semantic_token,
        style_mode=style_mode,
        exact_tokens=exact_tokens,
        separator=separator,
    ):
        style = theme.resolve(candidate) if theme is not None else {}
        if style:
            return style
    return _builtin_status_style(style_mode, semantic_token, separator=separator)


def _normalize_status_token(token: str, *, style_mode: StatusBarStyleMode) -> tuple[str, tuple[str, ...]]:
    normalized = token.strip()
    if not normalized:
        return "field", ()
    mode_prefix = _MODE_TOKEN_PREFIX.get(style_mode, "")
    if mode_prefix and normalized.startswith(f"statusBar.{mode_prefix}."):
        semantic = normalized[len(f"statusBar.{mode_prefix}.") :]
        return semantic or "field", (normalized,)
    if normalized.startswith("statusBar."):
        semantic = normalized[len("statusBar.") :]
        return semantic or "field", ()
    return normalized, ()


def _status_token_candidates(
    semantic_token: str,
    *,
    style_mode: StatusBarStyleMode,
    exact_tokens: tuple[str, ...],
    separator: bool,
) -> tuple[str, ...]:
    mode_prefix = _MODE_TOKEN_PREFIX[style_mode]
    token = "separator" if separator else semantic_token
    if separator:
        candidates = [*exact_tokens, f"statusBar.{mode_prefix}.{token}", f"statusBar.{token}"]
    else:
        candidates = [
            *exact_tokens,
            f"statusBar.{mode_prefix}.{token}",
            f"statusBar.{token}",
            f"statusBar.{mode_prefix}.field",
            "statusBar.field",
        ]
    return tuple(dict.fromkeys(candidates))


def _builtin_status_style(
    style_mode: StatusBarStyleMode,
    semantic_token: str,
    *,
    separator: bool,
) -> ThemeStyle | None:
    if style_mode == "codex-like":
        return _CODEX_LIKE_DEFAULTS.get("separator" if separator else semantic_token)
    if style_mode == "muted":
        return _MUTED_DEFAULTS.get("separator" if separator else "field")
    return None


def _footer_fields_fit(fields: list[FooterField], *, width: int, separator: str, min_gap: int) -> bool:
    left = _join_footer_fields(fields, side="left", separator=separator)
    right = _join_footer_fields(fields, side="right", separator=separator)
    if left and right:
        return visible_width(left) + min_gap + visible_width(right) <= width
    return visible_width(left or right) <= width


def _render_footer_fields(fields: list[FooterField], *, width: int, separator: str) -> str:
    left = _join_footer_fields(fields, side="left", separator=separator)
    right = _join_footer_fields(fields, side="right", separator=separator)
    if left and right:
        left_width = visible_width(left)
        right_width = visible_width(right)
        if left_width + right_width >= width:
            return truncate_to_width(f"{left}  {right}", max_width=width)
        return f"{left}{' ' * (width - left_width - right_width)}{right}"
    if right:
        padding = max(0, width - visible_width(right))
        return (" " * padding) + truncate_to_width(right, max_width=width)
    return truncate_to_width(left, max_width=width)


def _join_footer_fields(fields: list[FooterField], *, side: Literal["left", "right"], separator: str) -> str:
    selected = [field for field in fields if field.side == side]
    selected.sort(key=lambda field: field.priority, reverse=True)
    return separator.join(_sanitize_footer_text(field.text) for field in selected if _sanitize_footer_text(field.text))


def _render_footer_part(part: RegionRenderable | str, constraints: RenderConstraints) -> list[str]:
    target_width = autowrap_safe_width(constraints.width)
    if isinstance(part, str):
        text = _sanitize_footer_text(part)
        if not text:
            return []
        return [truncate_to_width(text, max_width=target_width)]
    result = part.render(constraints)
    return [truncate_to_width(line.text, max_width=target_width) for line in result.lines]


def _render_extension_statuses(
    statuses: list[StatusField] | tuple[StatusField, ...],
    constraints: RenderConstraints,
    *,
    separator: str = " | ",
    style_mode: StatusBarStyleMode = "plain",
    theme: ThemeResolver | None = None,
) -> list[str]:
    sanitized = [
        StatusField(_sanitize_footer_text(status.text), priority=status.priority, token=status.token)
        for status in statuses
        if _sanitize_footer_text(status.text)
    ]
    if not sanitized:
        return []
    return [
        line.text
        for line in StatusBar(
            sanitized,
            separator=separator,
            style_mode=style_mode,
            theme=theme,
        )
        .render(constraints)
        .lines
    ]


def _sanitize_footer_text(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").replace("\t", " ").split())


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    remaining = seconds - (minutes * 60)
    return f"{minutes}m {remaining:05.2f}s"


__all__ = [
    "FooterField",
    "FooterStatusLine",
    "FooterView",
    "StatusBar",
    "StatusField",
    "WorkingLine",
]
