from __future__ import annotations

import re
from dataclasses import dataclass, field

from loushang.harnesstui.conversation.source import TranscriptSnapshot, TranscriptSource
from loushang.tui.cell_width import truncate_to_width, wrap_cells
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.input import InputEvent, InputIntent
from loushang.tui.theme import apply_theme_style
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    ErrorRecord,
    StatusRecord,
    ThinkingRecord,
    ThinkingVisibility,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
    render_transcript_records,
)

_MAX_TRANSCRIPT_RENDER_HEIGHT = 1_000_000
_FOOTER_STYLE = {"color": "bright_black", "dim": True}
_SEARCH_HIGHLIGHT_STYLE = {"bold": True, "reverse": True}
_FOOTER_LINES = (
    "↑/↓ scroll   PgUp/Ctrl+B · PgDn/Ctrl+F page   Home/End jump",
    "Ctrl+O/q/Esc close   / search   n/N next   d detail   r raw",
)
_CONSUMED = InputIntent(kind="consumed", note="transcript_reader")


@dataclass(slots=True)
class TranscriptReaderSurface:
    source: TranscriptSource
    focused: bool = False
    raw_mode: bool = False
    detail_mode: bool = False
    search_query: str = ""
    _snapshot: TranscriptSnapshot = field(init=False, repr=False)
    _scroll_offset: int = field(default=0, init=False, repr=False)
    _max_scroll_offset: int = field(default=0, init=False, repr=False)
    _last_body_height: int = field(default=1, init=False, repr=False)
    _follow_tail: bool = field(default=True, init=False, repr=False)
    _search_draft: str = field(default="", init=False, repr=False)
    _search_editing: bool = field(default=False, init=False, repr=False)
    _search_matches: tuple[int, ...] = field(default=(), init=False, repr=False)
    _search_match_index: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._snapshot = self.source.snapshot()

    @property
    def scroll_offset(self) -> int:
        return self._scroll_offset

    @property
    def max_scroll_offset(self) -> int:
        return self._max_scroll_offset

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: InputEvent) -> InputIntent[str]:
        if self._search_editing:
            return self._handle_search_input(event)
        if event.kind == "text":
            if len(event.text) == 1:
                return self.handle_input(InputEvent(kind="key", key=event.text, raw=event.raw))
            return _CONSUMED
        if event.kind != "key":
            return _CONSUMED
        key = event.key
        if key in {"esc", "escape"} and self.search_query:
            self._clear_search()
            return _CONSUMED
        if key in {"q", "esc", "escape", "ctrl+c", "ctrl_c", "ctrl+o", "ctrl_o"}:
            return InputIntent(kind="surface_close")
        if key == "up":
            self._scroll_by(-1)
            return _CONSUMED
        if key == "down":
            self._scroll_by(1)
            return _CONSUMED
        if key in {"pageUp", "ctrl+b", "ctrl_b"}:
            self._scroll_by(-self._last_body_height)
            return _CONSUMED
        if key in {"pageDown", "ctrl+f", "ctrl_f"}:
            self._scroll_by(self._last_body_height)
            return _CONSUMED
        if key == "home":
            self._scroll_to_start()
            return _CONSUMED
        if key == "end":
            self._scroll_to_tail()
            return _CONSUMED
        if key == "/":
            self._begin_search()
            return _CONSUMED
        if key == "n":
            self._move_search_match(1)
            return _CONSUMED
        if key == "N":
            self._move_search_match(-1)
            return _CONSUMED
        if key == "d":
            self.detail_mode = not self.detail_mode
            return _CONSUMED
        if key == "r":
            self.raw_mode = not self.raw_mode
            return _CONSUMED
        return _CONSUMED

    def render(self, constraints: RenderConstraints) -> RenderResult:
        body = self._body_lines(width=constraints.width)
        self._sync_search_matches(body)
        top_chrome = self._top_chrome_lines(constraints.width, constraints.max_height)
        footer = self._footer_lines(constraints.width, max_height=constraints.max_height - len(top_chrome))
        body_height = max(0, constraints.max_height - len(top_chrome) - len(footer))
        self._last_body_height = max(1, body_height)
        self._max_scroll_offset = max(0, len(body) - body_height)
        if self.search_query and self._search_matches:
            self._follow_tail = False
            self._scroll_offset = _clamp(self._search_matches[self._search_match_index], 0, self._max_scroll_offset)
        elif self._follow_tail:
            self._scroll_offset = self._max_scroll_offset
        else:
            self._scroll_offset = _clamp(self._scroll_offset, 0, self._max_scroll_offset)

        visible_body = list(body[self._scroll_offset : self._scroll_offset + body_height]) if body_height else []
        if self.search_query:
            visible_body = [RenderLine(_highlight_search_matches(line.text, self.search_query)) for line in visible_body]
        if body_height and not visible_body:
            visible_body.append(RenderLine(truncate_to_width("No transcript records.", max_width=constraints.width)))
        padding = [RenderLine("") for _ in range(max(0, body_height - len(visible_body)))]
        lines = [*top_chrome, *visible_body, *padding, *footer]
        return RenderResult.from_lines(lines[: constraints.max_height], constraints=constraints)

    def _top_chrome_lines(self, width: int, max_height: int) -> tuple[RenderLine, ...]:
        lines = [
            RenderLine(
                truncate_to_width(
                    _title_text(
                        self._snapshot.source_label,
                        raw=self.raw_mode,
                        detail=self.detail_mode,
                        search_query=self.search_query,
                        search_match_index=self._search_match_index,
                        search_match_count=len(self._search_matches),
                    ),
                    max_width=width,
                )
            )
        ]
        if self._snapshot.evicted_prefix_record_count > 0 and len(lines) < max_height - 1:
            lines.append(RenderLine(truncate_to_width("Earlier transcript records were trimmed.", max_width=width)))
        return tuple(lines[:max_height])

    def _footer_lines(self, width: int, *, max_height: int) -> tuple[RenderLine, ...]:
        if max_height <= 0:
            return ()
        separator = "─" * max(0, width)
        mode_lines = _FOOTER_LINES
        if self._search_editing:
            mode_lines = (_FOOTER_LINES[0], f"Search: {self._search_draft}")
        raw_lines = (separator, *mode_lines)
        selected = raw_lines[-max_height:]
        return tuple(RenderLine(_footer_text(line, width=width)) for line in selected)

    def _body_lines(self, *, width: int) -> tuple[RenderLine, ...]:
        if self.raw_mode:
            return _render_raw_transcript_records(
                self._snapshot.records,
                width=width,
                detail=self.detail_mode,
                max_height=_MAX_TRANSCRIPT_RENDER_HEIGHT,
            )
        return render_transcript_records(
            self._snapshot.records,
            width=width,
            max_height=_MAX_TRANSCRIPT_RENDER_HEIGHT,
            verbose_errors=self.detail_mode,
        )

    def _scroll_by(self, delta: int) -> None:
        self._follow_tail = False
        self._scroll_offset = _clamp(self._scroll_offset + delta, 0, self._max_scroll_offset)
        if self._scroll_offset >= self._max_scroll_offset and delta > 0:
            self._follow_tail = True

    def _scroll_to_start(self) -> None:
        self._follow_tail = False
        self._scroll_offset = 0

    def _scroll_to_tail(self) -> None:
        self._follow_tail = True
        self._scroll_offset = self._max_scroll_offset

    def _begin_search(self) -> None:
        self._search_editing = True
        self._search_draft = ""
        self.search_query = ""
        self._search_matches = ()
        self._search_match_index = 0

    def _handle_search_input(self, event: InputEvent) -> InputIntent[str]:
        if event.kind == "text":
            self._search_draft += event.text
            return _CONSUMED
        if event.kind != "key":
            return _CONSUMED
        key = event.key
        if key in {"esc", "escape"}:
            self._search_editing = False
            self._search_draft = ""
            self._clear_search()
            return _CONSUMED
        if key == "enter":
            self._search_editing = False
            self.search_query = self._search_draft.strip()
            self._search_draft = ""
            self._search_matches = ()
            self._search_match_index = 0
            return _CONSUMED
        if key in {"backspace", "delete"}:
            self._search_draft = self._search_draft[:-1]
            return _CONSUMED
        return _CONSUMED

    def _sync_search_matches(self, body: tuple[RenderLine, ...]) -> None:
        if not self.search_query:
            self._search_matches = ()
            self._search_match_index = 0
            return
        needle = self.search_query.lower()
        matches = tuple(index for index, line in enumerate(body) if needle in line.text.lower())
        self._search_matches = matches
        if matches:
            self._search_match_index = _clamp(self._search_match_index, 0, len(matches) - 1)
        else:
            self._search_match_index = 0

    def _move_search_match(self, delta: int) -> None:
        if not self.search_query:
            return
        if not self._search_matches:
            return
        self._search_match_index = (self._search_match_index + delta) % len(self._search_matches)
        self._follow_tail = False

    def _clear_search(self) -> None:
        self.search_query = ""
        self._search_matches = ()
        self._search_match_index = 0


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _footer_text(text: str, *, width: int) -> str:
    return apply_theme_style(truncate_to_width(text, max_width=width), _FOOTER_STYLE)


def _highlight_search_matches(text: str, query: str) -> str:
    if not query:
        return text
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    parts: list[str] = []
    last_end = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if start > last_end:
            parts.append(text[last_end:start])
        parts.append(apply_theme_style(text[start:end], _SEARCH_HIGHLIGHT_STYLE))
        last_end = end
    if not parts:
        return text
    parts.append(text[last_end:])
    return "".join(parts)


def _title_text(
    source_label: str,
    *,
    raw: bool,
    detail: bool,
    search_query: str,
    search_match_index: int,
    search_match_count: int,
) -> str:
    suffixes: list[str] = []
    if raw and detail:
        suffixes.append("raw+detail")
    elif raw:
        suffixes.append("raw")
    elif detail:
        suffixes.append("detail")
    if search_query:
        suffixes.append(f"search {search_query} {search_match_index + 1 if search_match_count else 0}/{search_match_count}")
    if not suffixes:
        return source_label
    return f"{source_label} · {' · '.join(suffixes)}"


def _render_raw_transcript_records(
    records: tuple[DisplayRecord, ...],
    *,
    width: int,
    detail: bool,
    max_height: int,
) -> tuple[RenderLine, ...]:
    lines: list[str] = []
    for record in records:
        if lines:
            lines.append("")
        lines.extend(_raw_record_lines(record, width=width, detail=detail))
        if len(lines) >= max_height:
            break
    return tuple(RenderLine(line) for line in lines[:max_height])


def _raw_record_lines(record: DisplayRecord, *, width: int, detail: bool) -> list[str]:
    if isinstance(record, UserPromptRecord):
        return _raw_labeled_text("User", record.text, width=width)
    if isinstance(record, AssistantMessageRecord):
        return _raw_labeled_text("Assistant", record.text, width=width)
    if isinstance(record, ToolExecutionRecord):
        return _raw_tool_lines(record, width=width)
    if isinstance(record, ThinkingRecord):
        return _raw_thinking_lines(record, width=width)
    if isinstance(record, StatusRecord):
        return _raw_wrapped_lines(record.text, width=width)
    if isinstance(record, ErrorRecord):
        text = record.summary
        if detail and record.diagnostics:
            text = f"{text}\n{record.diagnostics}"
        return _raw_labeled_text("Error", text, width=width)
    if isinstance(record, ContextCompactionRecord):
        summary = record.summary.strip()
        text = summary or "Context compacted"
        if record.tokens_before is not None:
            text = f"{text}\n{record.tokens_before} tokens before compaction"
        return _raw_labeled_text("Context", text, width=width)
    if isinstance(record, WorkedDividerRecord):
        return _raw_wrapped_lines(f"Worked for {record.elapsed_seconds:.2f}s", width=width)
    return []


def _raw_tool_lines(record: ToolExecutionRecord, *, width: int) -> list[str]:
    elapsed = f"{record.elapsed_seconds:.2f}s"
    lines = _raw_wrapped_lines(f"Tool: {record.name} {record.state} in {elapsed}", width=width)
    if record.command:
        lines.extend(_raw_wrapped_lines(f"command: {record.command}", width=width))
    if record.output:
        lines.extend(_raw_wrapped_lines(record.output, width=width))
    if record.stderr:
        lines.extend(_raw_wrapped_lines(f"stderr: {record.stderr}", width=width))
    if record.exit_code is not None:
        lines.extend(_raw_wrapped_lines(f"exit code: {record.exit_code}", width=width))
    return lines


def _raw_thinking_lines(record: ThinkingRecord, *, width: int) -> list[str]:
    if record.visibility is ThinkingVisibility.HIDDEN:
        return []
    if record.visibility is ThinkingVisibility.UNAVAILABLE:
        return _raw_wrapped_lines("Thinking unavailable", width=width)
    if record.visibility is ThinkingVisibility.COLLAPSED:
        return _raw_wrapped_lines("Thinking collapsed", width=width)
    return _raw_labeled_text("Thinking", record.text, width=width)


def _raw_labeled_text(label: str, text: str, *, width: int) -> list[str]:
    lines = _raw_wrapped_lines(label, width=width)
    if text:
        lines.extend(_raw_wrapped_lines(text, width=width))
    return lines


def _raw_wrapped_lines(text: str, *, width: int) -> list[str]:
    target_width = max(1, width)
    lines: list[str] = []
    for logical_line in text.splitlines() or [""]:
        lines.extend(wrap_cells(logical_line, width=target_width) or [""])
    return [truncate_to_width(line, max_width=target_width) for line in lines]


__all__ = ["TranscriptReaderSurface"]
