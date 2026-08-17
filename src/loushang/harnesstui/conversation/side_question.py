"""Transient screen surface for one-shot side questions."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal, Protocol

from loushang.harness.runtime import SideQuestionAnswer, SideQuestionUpdate
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    InputEvent,
    InputIntent,
    MarkdownRenderCache,
    MarkdownRenderer,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.theme import ThemeResolver, apply_theme_style

SideQuestionStatus = Literal["answering", "answered", "failed", "closed"]
_PROGRESS_GLYPHS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

SIDE_QUESTION_PAGE_THEME = ThemeResolver(
    defaults={
        "surface.title": {"bold": True, "color": "yellow"},
        "surface.subtitle": {"bold": True, "color": "bright_cyan"},
        "surface.footer": {"color": "bright_black", "dim": True},
        "side_question.progress": {"color": "yellow"},
        "side_question.error": {"color": "red"},
        "markdown.heading": {"color": "yellow"},
        "markdown.link": {"color": "blue"},
        "markdown.link.url": {"color": "bright_black"},
        "markdown.code.inline": {"color": "cyan"},
        "markdown.code.block": {"color": "green"},
        "markdown.code.block.border": {"color": "bright_black"},
        "markdown.quote.text": {"color": "bright_black"},
        "markdown.quote.border": {"color": "bright_black"},
        "markdown.hr": {"color": "bright_black"},
        "markdown.list.bullet": {"color": "green"},
        "markdown.strong": {"bold": True},
        "markdown.emphasis": {"italic": True},
    }
)


class SideQuestionRunner(Protocol):
    async def __call__(
        self,
        question: str,
        *,
        on_update: SideQuestionUpdate | None = None,
    ) -> SideQuestionAnswer: ...


@dataclass(slots=True)
class SideQuestionSurface:
    """Render and cancel a transient side-question request."""

    question: str
    ask: SideQuestionRunner
    cancel: Callable[[], object]
    request_render: Callable[[], object]
    theme: ThemeResolver = field(default_factory=lambda: SIDE_QUESTION_PAGE_THEME)
    status: SideQuestionStatus = field(default="answering", init=False)
    answer: str = field(default="", init=False)
    error: str = field(default="", init=False)
    _scroll_offset: int = field(default=0, init=False, repr=False)
    _last_body_height: int = field(default=1, init=False, repr=False)
    _last_line_count: int = field(default=0, init=False, repr=False)
    _progress_frame: int = field(default=0, init=False, repr=False)
    _started_at: float = field(default_factory=time.monotonic, init=False, repr=False)
    _follow_output: bool = field(default=True, init=False, repr=False)
    _markdown_cache: MarkdownRenderCache = field(
        default_factory=MarkdownRenderCache,
        init=False,
        repr=False,
    )

    async def start(self) -> None:
        progress_task = asyncio.create_task(self._animate_progress())
        try:
            result = await self.ask(
                self.question,
                on_update=self._accept_answer_update,
            )
        except asyncio.CancelledError:
            self.status = "closed"
            raise
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc).strip() or exc.__class__.__name__
        else:
            self.status = "answered"
            self.answer = result.text
        finally:
            progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await progress_task
        self.request_render()

    def close(self) -> None:
        if self.status == "answering":
            self.cancel()
        self.status = "closed"

    @property
    def footer_help(self) -> str:
        if self.status == "answering":
            if self._max_scroll_offset() > 0:
                return "Up/Down/Page scroll · Esc cancel · Main task continues"
            return "Esc cancel · Main task continues"
        if self._max_scroll_offset() > 0:
            return "Up/Down/Page scroll · Enter/Esc close"
        return "Enter/Esc close"

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if event.kind != "key":
            return None
        if event.key in {"escape", "esc"}:
            return InputIntent(kind="surface_close")
        if event.key in {"enter", "space"} and self.status != "answering":
            return InputIntent(kind="surface_close")
        page = max(1, self._last_body_height)
        deltas = {
            "down": 1,
            "up": -1,
            "pageDown": page,
            "pageUp": -page,
        }
        if event.key in deltas:
            return self._scroll(deltas[event.key])
        if event.key == "home":
            return self._set_scroll(0)
        if event.key == "end":
            return self._set_scroll(self._max_scroll_offset())
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        lines: list[str] = []
        if self.answer:
            rendered = MarkdownRenderer(
                self.answer,
                theme=self.theme,
                render_cache=self._markdown_cache,
                streaming_key=self.question if self.status == "answering" else None,
            ).render(
                RenderConstraints(width=constraints.width, max_height=100_000)
            )
            lines.extend(line.text for line in rendered.lines)
        if self.status == "answering":
            if lines:
                lines.append("")
            elapsed = max(0, int(time.monotonic() - self._started_at))
            glyph = _PROGRESS_GLYPHS[self._progress_frame % len(_PROGRESS_GLYPHS)]
            lines.append(
                apply_theme_style(
                    f"{glyph} Answering… {elapsed}s",
                    self.theme.resolve("side_question.progress"),
                )
            )
        elif self.status == "failed":
            lines.append(
                apply_theme_style(
                    f"Error: {self.error}",
                    self.theme.resolve("side_question.error"),
                )
            )

        self._last_body_height = constraints.max_height
        self._last_line_count = len(lines)
        max_offset = self._max_scroll_offset()
        self._scroll_offset = (
            max_offset
            if self.status == "answering" and self._follow_output
            else min(self._scroll_offset, max_offset)
        )
        visible = lines[
            self._scroll_offset : self._scroll_offset + constraints.max_height
        ]
        return RenderResult.from_lines(
            [RenderLine(line) for line in visible],
            constraints=constraints,
        )

    def _scroll(self, delta: int) -> InputIntent | None:
        return self._set_scroll(self._scroll_offset + delta)

    def _set_scroll(self, offset: int) -> InputIntent | None:
        max_offset = self._max_scroll_offset()
        next_offset = max(0, min(offset, max_offset))
        if next_offset == self._scroll_offset:
            return None
        self._scroll_offset = next_offset
        self._follow_output = next_offset == max_offset
        return InputIntent(kind="consumed", note="side_question_scroll")

    def _max_scroll_offset(self) -> int:
        return max(0, self._last_line_count - self._last_body_height)

    async def _animate_progress(self) -> None:
        while self.status == "answering":
            await asyncio.sleep(0.12)
            self._progress_frame += 1
            self.request_render()

    def _accept_answer_update(self, text: str) -> None:
        if self.status != "answering" or text == self.answer:
            return
        self.answer = text
        self.request_render()


def build_side_question_surface_view(
    *,
    question: str,
    ask: SideQuestionRunner,
    cancel: Callable[[], object],
    request_render: Callable[[], object],
) -> ScreenSurfaceView:
    """Build the standard framed BTW surface."""

    return ScreenSurfaceView(
        title="/btw",
        subtitle=question,
        purpose="dialog",
        content=SideQuestionSurface(
            question=question,
            ask=ask,
            cancel=cancel,
            request_render=request_render,
            theme=SIDE_QUESTION_PAGE_THEME,
        ),
        footer="",
        presentation="page",
        theme=SIDE_QUESTION_PAGE_THEME,
    )


__all__ = [
    "SideQuestionRunner",
    "SideQuestionStatus",
    "SideQuestionSurface",
    "SIDE_QUESTION_PAGE_THEME",
    "build_side_question_surface_view",
]
