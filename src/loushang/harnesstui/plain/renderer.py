from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TextIO

from loushang.harnesstui.conversation.tool_transcript import (
    ToolTranscriptBlock,
    tool_block_to_record,
)
from loushang.harnesstui.status.plain import (
    PlainToolbarSnapshot,
    render_plain_toolbar,
)
from loushang.tui import InfoPanel, RenderConstraints, RenderLine, RenderResult
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.markdown.renderer import CodeHighlighterLike
from loushang.tui.render import (
    MarkdownBlock,
    TerminalBlock,
    TextBlock,
    blocks_to_terminal_text,
)
from loushang.tui.theme import TerminalCapabilities, ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    StatusRecord,
    ThinkingRecord,
    ThinkingVisibility,
    TranscriptBuffer,
    TranscriptView,
    UserPromptRecord,
    WorkedDividerRecord,
)


def _terminal_columns() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def _neutral_line(line: str, record: DisplayRecord) -> str:
    del record
    return strip_control_sequences(line)


@dataclass(frozen=True, slots=True)
class PlainConversationGlyphs:
    """Text markers used by the non-screen conversation presentation."""

    user_prompt: str = "> "
    assistant: str = "* "
    item: str = "- "
    error: str = "! Error: "
    interruption: str = "! "
    # Worked-divider width accounting requires one terminal cell per repetition.
    rule: str = "-"


@dataclass(frozen=True, slots=True)
class PlainConversationProfile:
    """Immutable product presentation policy for the shared renderer."""

    title: str | None = None
    interruption_message: str = "Conversation interrupted."
    glyphs: PlainConversationGlyphs = PlainConversationGlyphs()
    line_mapper: Callable[[str, DisplayRecord], str] = _neutral_line
    tool_block_projector: Callable[[ToolTranscriptBlock], DisplayRecord] = (
        tool_block_to_record
    )
    terminal_columns: Callable[[], int] = _terminal_columns


@dataclass
class PlainConversationRenderer:
    """Render a projected conversation to plain terminal output or a buffer."""

    stdout: TextIO
    stderr: TextIO | None = None
    max_payload_chars: int = 1200
    verbose: bool = False
    use_transcript_view: bool = False
    transcript_theme: ThemeResolver | None = None
    transcript_capabilities: TerminalCapabilities | None = None
    code_highlighter: CodeHighlighterLike | None = None
    transcript_buffer: TranscriptBuffer | None = None
    _assistant_deltas: list[str] | None = None
    profile: PlainConversationProfile = field(
        default_factory=PlainConversationProfile,
        kw_only=True,
    )

    def render_header(
        self,
        *,
        project_label: str,
        cwd: str,
        branch: str | None,
        session_label: str | None,
        model_label: str | None,
    ) -> None:
        self._write_line(self.profile.title or project_label)
        self._write_line(
            render_plain_toolbar(
                PlainToolbarSnapshot(
                    model=model_label,
                    cwd=cwd,
                    branch=branch,
                    session=session_label,
                )
            )
        )
        self._write_line()

    def render_user(self, text: str) -> None:
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(UserPromptRecord(text))
            return
        if self.use_transcript_view:
            self.render_display_record(UserPromptRecord(text))
            return
        self._write_block(self.profile.glyphs.user_prompt, text)

    def begin_assistant(self) -> None:
        if self.transcript_buffer is not None:
            self.transcript_buffer.assistant_draft = None
        self._assistant_deltas = []

    def write_assistant_delta(self, text: str) -> None:
        if not text:
            return
        if self.transcript_buffer is not None:
            self.transcript_buffer.append_assistant_chunk(text)
            return
        if self._assistant_deltas is None:
            self._assistant_deltas = []
        self._assistant_deltas.append(text)

    def end_assistant(self, final_text: str | None = None) -> None:
        if self.transcript_buffer is not None:
            text = final_text
            if text is None and self.transcript_buffer.assistant_draft is not None:
                text = self.transcript_buffer.assistant_draft.text
            if text is None:
                text = "".join(self._assistant_deltas or [])
            self.transcript_buffer.assistant_draft = None
            self._assistant_deltas = None
            if text:
                self.transcript_buffer.append(AssistantMessageRecord(text))
            return
        text = final_text or "".join(self._assistant_deltas or [])
        self._assistant_deltas = None
        self.render_assistant(text)

    def render_assistant(self, text: str) -> None:
        if text:
            if self.transcript_buffer is not None:
                self.transcript_buffer.append(AssistantMessageRecord(text))
                return
            if self.use_transcript_view:
                self.render_display_record(AssistantMessageRecord(text))
                return
            self.render_terminal_blocks(
                [MarkdownBlock(text)], prefix=self.profile.glyphs.assistant
            )

    def render_tool_start(self, tool_name: str, args: object) -> None:
        payload = _format_payload(args, self.max_payload_chars)
        self._write_line(f"[tool:start] {tool_name} {payload}")

    def render_tool_update(self, tool_name: str, text: str) -> None:
        if text:
            self._write_line(
                f"[tool:update] {tool_name} {_truncate(text, self.max_payload_chars)}"
            )

    def render_tool_end(self, tool_name: str, text: str, *, is_error: bool) -> None:
        status = "tool:error" if is_error else "tool:done"
        suffix = f" {text}" if text else ""
        self._write_line(f"[{status}] {tool_name}{suffix}")

    def render_tool_summary(self, label: str, detail: str | None = None) -> None:
        suffix = f" {detail}" if detail else ""
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(
                ThinkingRecord(f"{label}{suffix}", ThinkingVisibility.VISIBLE)
            )
            return
        self._write_line(f"{self.profile.glyphs.item}{label}{suffix}")

    def render_tool_block(self, block: ToolTranscriptBlock) -> None:
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(self.profile.tool_block_projector(block))
            return
        if self.use_transcript_view:
            self.render_display_record(self.profile.tool_block_projector(block))
            return
        headline = f"{block.verb} {block.title}".strip()
        if block.detail and not block.body:
            headline = f"{headline} {block.detail}"
        lines = [headline, *(block.body or "").splitlines()]
        if block.detail and block.body:
            lines.append(block.detail)
        self.render_terminal_blocks(
            [TextBlock("\n".join(lines))], prefix=self.profile.glyphs.item
        )

    def render_terminal_blocks(
        self,
        blocks: Sequence[TerminalBlock],
        *,
        prefix: str = "",
        separator: str = "\n\n",
        width: int | None = None,
    ) -> None:
        rendered = blocks_to_terminal_text(
            tuple(blocks),
            width=self._content_width() if width is None else width,
            separator=separator,
        )
        if not rendered:
            return
        if prefix:
            self._write_block(prefix, rendered)
            return
        for line in rendered.splitlines():
            self._write_line(line)

    def render_status(self, text: str) -> None:
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(StatusRecord(text))
            return
        self._write_line(text)

    def render_info_panel(self, panel: InfoPanel) -> None:
        self.render_status(panel.plain_text())

    def render_display_record(self, record: DisplayRecord) -> None:
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(record)
            return
        view = TranscriptView(
            [record],
            verbose_errors=self.verbose,
            theme=self.transcript_theme or ThemeResolver(),
            capabilities=self.transcript_capabilities,
            code_highlighter=self.code_highlighter,
        )
        rendered = view.render(
            RenderConstraints(width=self._content_width(), max_height=1_000)
        )
        for line in rendered.lines:
            self._write_line(self.profile.line_mapper(line.text, record))

    def render_error(self, text: str) -> None:
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(ErrorRecord(text))
            return
        if self.use_transcript_view:
            self.render_display_record(ErrorRecord(text))
            return
        self._write_line(f"{self.profile.glyphs.error}{text}")

    def render_interruption(self) -> None:
        message = self.profile.interruption_message
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(ErrorRecord(message))
            return
        self._write_line(f"{self.profile.glyphs.interruption}{message}")

    def render_worked(self, elapsed_seconds: float) -> None:
        if self.transcript_buffer is not None:
            self.transcript_buffer.append(WorkedDividerRecord(elapsed_seconds))
            return
        if self.use_transcript_view:
            self.render_display_record(WorkedDividerRecord(elapsed_seconds))
            return
        width = max(1, self.profile.terminal_columns())
        rule = self.profile.glyphs.rule
        label = f"{rule} Worked for {elapsed_seconds:.1f}s "
        self._write_line()
        if len(label) >= width:
            self._write_line(label[:width])
            self._write_line()
            return
        self._write_line(label + (rule * (width - len(label))))
        self._write_line()

    def _write(self, text: str) -> None:
        self.stdout.write(text)
        self.stdout.flush()

    def _write_line(self, text: str = "") -> None:
        self.stdout.write(f"{text}\n")
        self.stdout.flush()

    def _write_block(self, prefix: str, text: str) -> None:
        lines = text.splitlines() or [""]
        self._write_line(f"{prefix}{lines[0]}")
        for line in lines[1:]:
            self._write_line(f"  {line}")

    def _content_width(self) -> int:
        return max(20, self.profile.terminal_columns() - 2)

    def render_transcript(self, constraints: RenderConstraints) -> RenderResult:
        if self.transcript_buffer is None:
            return TranscriptView(()).render(constraints)
        lines: list[str] = []
        records = [*self.transcript_buffer.records]
        if self.transcript_buffer.assistant_draft is not None:
            records.append(self.transcript_buffer.assistant_draft)
        for record in records:
            view = TranscriptView(
                [record],
                verbose_errors=self.verbose,
                theme=self.transcript_theme or ThemeResolver(),
                capabilities=self.transcript_capabilities,
                code_highlighter=self.code_highlighter,
            )
            rendered = view.render(
                RenderConstraints(
                    width=constraints.width,
                    max_height=constraints.max_height,
                )
            )
            lines.extend(
                self.profile.line_mapper(line.text, record) for line in rendered.lines
            )
            if len(lines) >= constraints.max_height:
                break
        return RenderResult.from_lines(
            [RenderLine(line) for line in lines[: constraints.max_height]],
            constraints=constraints,
        )

    def transcript_renderable(self) -> _PlainConversationTranscriptRenderable | None:
        if self.transcript_buffer is None:
            return None
        return _PlainConversationTranscriptRenderable(self)


@dataclass(frozen=True, slots=True)
class _PlainConversationTranscriptRenderable:
    renderer: PlainConversationRenderer

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self.renderer.render_transcript(constraints)


def _format_payload(value: object, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return _truncate(text, limit)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


__all__ = [
    "PlainConversationGlyphs",
    "PlainConversationProfile",
    "PlainConversationRenderer",
]
