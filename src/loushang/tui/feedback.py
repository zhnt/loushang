from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from loushang.tui.cell_width import (
    autowrap_safe_width,
    truncate_to_width,
    visible_width,
)
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.input import InputEvent, InputIntent
from loushang.tui.theme import ThemeResolver, ThemeStyle, apply_theme_style

StyleFn = Callable[[str], str]
NowMs = Callable[[], int]

DEFAULT_LOADER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
DEFAULT_LOADER_INTERVAL_MS = 80


@dataclass(slots=True)
class Rule:
    label: str = ""
    character: str = "─"
    style: StyleFn | None = None
    theme: ThemeResolver | None = None
    theme_token: str | None = None

    def invalidate(self) -> None:
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        line = self._line(constraints.width)
        if self.style is not None:
            line = self.style(line)
        line = apply_theme_style(line, _resolve_style(self.theme, self.theme_token))
        return RenderResult.from_lines([RenderLine(line)], constraints=constraints)

    def _line(self, width: int) -> str:
        target_width = autowrap_safe_width(width)
        char = self.character or "─"
        if not self.label:
            return truncate_to_width(char * target_width, max_width=target_width, ellipsis="")
        prefix = f"{char} {self.label} "
        if visible_width(prefix) >= target_width:
            return truncate_to_width(prefix, max_width=target_width, ellipsis="")
        return prefix + (char * (target_width - visible_width(prefix)))


class DynamicBorder(Rule):
    def __init__(
        self,
        style: StyleFn | None = None,
        *,
        theme: ThemeResolver | None = None,
        theme_token: str | None = None,
    ) -> None:
        super().__init__(style=style, theme=theme, theme_token=theme_token)


@dataclass(slots=True)
class Loader:
    message: str = "Loading..."
    frames: tuple[str, ...] = DEFAULT_LOADER_FRAMES
    interval_ms: int = DEFAULT_LOADER_INTERVAL_MS
    now_ms: NowMs = field(default_factory=lambda: _monotonic_ms)
    padding_x: int = 1
    leading_spacer: bool = True
    indicator_style: StyleFn | None = None
    message_style: StyleFn | None = None
    theme: ThemeResolver | None = None
    theme_token: str | None = None
    indicator_theme_token: str | None = None
    message_theme_token: str | None = None
    running: bool = True
    _started_at_ms: int = field(default=0, init=False, repr=False)
    _stopped_frame_index: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.interval_ms <= 0:
            self.interval_ms = DEFAULT_LOADER_INTERVAL_MS
        if self.padding_x < 0:
            raise ValueError("padding_x must be non-negative")
        self.frames = tuple(self.frames)
        self._started_at_ms = self.now_ms()

    def start(self, *, now_ms: int | None = None) -> None:
        self.running = True
        self._started_at_ms = self.now_ms() if now_ms is None else now_ms
        self._stopped_frame_index = 0

    def stop(self) -> None:
        self._stopped_frame_index = self.frame_index()
        self.running = False

    def set_message(self, message: str) -> None:
        self.message = message

    def set_indicator(self, *, frames: tuple[str, ...] | list[str] | None = None, interval_ms: int | None = None) -> None:
        if frames is not None:
            self.frames = tuple(frames)
        if interval_ms is not None and interval_ms > 0:
            self.interval_ms = interval_ms
        self.start()

    def invalidate(self) -> None:
        return None

    def frame_index(self) -> int:
        if not self.frames:
            return 0
        if not self.running:
            return self._stopped_frame_index % len(self.frames)
        elapsed = max(0, self.now_ms() - self._started_at_ms)
        return (elapsed // self.interval_ms) % len(self.frames)

    def next_frame_due_ms(self, *, after_ms: int) -> int | None:
        if not self.running or len(self.frames) <= 1:
            return None
        elapsed = max(0, after_ms - self._started_at_ms)
        next_elapsed = ((elapsed // self.interval_ms) + 1) * self.interval_ms
        return self._started_at_ms + next_elapsed

    def render(self, constraints: RenderConstraints) -> RenderResult:
        raw_lines = []
        if self.leading_spacer:
            raw_lines.append("")
        raw_lines.append(self._line(constraints.width))
        return RenderResult.from_lines(
            [RenderLine(line) for line in raw_lines[: constraints.max_height]],
            constraints=constraints,
        )

    def _line(self, width: int) -> str:
        target_width = autowrap_safe_width(width)
        frame = self.frames[self.frame_index()] if self.frames else ""
        rendered_frame = _style_text(
            frame,
            self.indicator_style,
            theme=self.theme,
            theme_token=self.indicator_theme_token,
        )
        rendered_message = _style_text(
            self.message,
            self.message_style,
            theme=self.theme,
            theme_token=self.message_theme_token,
        )
        indicator = f"{rendered_frame} " if frame else ""
        content_width = max(1, target_width - self.padding_x * 2)
        content = truncate_to_width(f"{indicator}{rendered_message}", max_width=content_width)
        padded = (" " * self.padding_x) + content + (" " * self.padding_x)
        line = truncate_to_width(padded, max_width=target_width, ellipsis="", pad=True)
        return apply_theme_style(line, _resolve_style(self.theme, self.theme_token))


@dataclass(slots=True)
class CancellableLoader(Loader):
    on_abort: Callable[[], None] | None = None
    aborted: bool = False

    def handle_input(self, event: InputEvent) -> InputIntent[str] | None:
        if event.kind != "key" or event.key not in {"esc", "escape", "ctrl_c", "ctrl+c"}:
            return None
        self.abort()
        return InputIntent(kind="abort")

    def abort(self) -> None:
        if self.aborted:
            return
        self.aborted = True
        self.stop()
        if self.on_abort is not None:
            self.on_abort()

    def dispose(self) -> None:
        self.stop()


@dataclass(slots=True)
class WorkedDivider:
    elapsed_seconds: float
    style: StyleFn | None = None
    theme: ThemeResolver | None = None
    theme_token: str | None = None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return Rule(
            label=f"Worked for {_format_elapsed(self.elapsed_seconds)}",
            style=self.style,
            theme=self.theme,
            theme_token=self.theme_token,
        ).render(constraints)

    def invalidate(self) -> None:
        return None


def _apply_style(text: str, style: StyleFn | None) -> str:
    return style(text) if style is not None else text


def _style_text(
    text: str,
    style: StyleFn | None,
    *,
    theme: ThemeResolver | None,
    theme_token: str | None,
) -> str:
    return apply_theme_style(_apply_style(text, style), _resolve_style(theme, theme_token))


def _resolve_style(theme: ThemeResolver | None, token: str | None) -> ThemeStyle | None:
    if theme is None or not token:
        return None
    return theme.resolve(token)


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    remaining = seconds - (minutes * 60)
    return f"{minutes}m {remaining:05.2f}s"


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)
