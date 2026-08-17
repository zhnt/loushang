from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, TypeAlias

from loushang.tui.cell_width import (
    autowrap_safe_width,
    truncate_to_width,
    visible_width,
    wrap_cells,
)
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.markdown.renderer import (
    CodeBlock,
    CodeHighlighterLike,
    DiffBlock,
    MarkdownRenderCache,
    MarkdownRenderer,
    MarkdownSegmentedRenderResult,
)
from loushang.tui.theme import TerminalCapabilities, ThemeResolver

ToolState = Literal["running", "completed", "failed", "cancelled", "truncated"]
ToolOutputKind = Literal["text", "markdown", "code", "diff"]


class ThinkingVisibility(Enum):
    VISIBLE = "visible"
    COLLAPSED = "collapsed"
    HIDDEN = "hidden"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class UserPromptRecord:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantMessageRecord:
    text: str
    stable: bool = True


@dataclass(slots=True)
class StreamingTextBuffer:
    _chunks: list[str] = field(default_factory=list)
    _closed_lines: list[str] = field(default_factory=list)
    _open_line: str = ""
    version: int = 0
    _text_cache: str | None = field(default=None, init=False, repr=False)
    _materialize_count: int = field(default=0, init=False, repr=False)

    @classmethod
    def from_text(cls, text: str) -> StreamingTextBuffer:
        buffer = cls()
        if text:
            buffer.append(text)
        return buffer

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def materialize_count(self) -> int:
        return self._materialize_count

    @property
    def text(self) -> str:
        if self._text_cache is None:
            self._text_cache = "".join(self._chunks)
            self._materialize_count += 1
        return self._text_cache

    def logical_lines(self) -> tuple[str, ...]:
        if not self._chunks:
            return ()
        if self._open_line:
            return (*self._closed_lines, self._open_line)
        return tuple(self._closed_lines)

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        self._chunks.append(chunk)
        parts = (self._open_line + chunk).split("\n")
        self._closed_lines.extend(parts[:-1])
        self._open_line = parts[-1]
        self.version += 1
        self._text_cache = None

    def clear(self) -> None:
        self._chunks.clear()
        self._closed_lines.clear()
        self._open_line = ""
        self.version += 1
        self._text_cache = None


@dataclass(frozen=True, slots=True)
class ToolExecutionRecord:
    name: str
    state: ToolState
    elapsed_seconds: float
    output: str = ""
    output_kind: ToolOutputKind = "text"
    language: str = ""
    command: str = ""
    stderr: str = ""
    exit_code: int | None = None
    show_stats: bool = False


@dataclass(frozen=True, slots=True)
class ThinkingRecord:
    text: str
    visibility: ThinkingVisibility


@dataclass(frozen=True, slots=True)
class StatusRecord:
    text: str


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    summary: str
    diagnostics: str = ""


@dataclass(frozen=True, slots=True)
class ContextCompactionRecord:
    summary: str = ""
    tokens_before: int | None = None


@dataclass(frozen=True, slots=True)
class WorkedDividerRecord:
    elapsed_seconds: float


DisplayRecord: TypeAlias = (
    UserPromptRecord
    | AssistantMessageRecord
    | ToolExecutionRecord
    | ThinkingRecord
    | StatusRecord
    | ErrorRecord
    | ContextCompactionRecord
    | WorkedDividerRecord
)


@dataclass(slots=True)
class TranscriptBuffer:
    _records: list[DisplayRecord] = field(default_factory=list)
    _assistant_draft_buffer: StreamingTextBuffer | None = field(default=None, init=False, repr=False)

    @property
    def records(self) -> tuple[DisplayRecord, ...]:
        return tuple(self._records)

    @property
    def assistant_draft(self) -> AssistantMessageRecord | None:
        if self._assistant_draft_buffer is None:
            return None
        return AssistantMessageRecord(text=self._assistant_draft_buffer.text, stable=False)

    @assistant_draft.setter
    def assistant_draft(self, value: AssistantMessageRecord | None) -> None:
        if value is None:
            self._assistant_draft_buffer = None
            return
        self._assistant_draft_buffer = StreamingTextBuffer.from_text(value.text)

    def append(self, record: DisplayRecord) -> None:
        self._records.append(record)

    def append_assistant_chunk(self, chunk: str) -> None:
        if not chunk:
            return
        if self._assistant_draft_buffer is None:
            self._assistant_draft_buffer = StreamingTextBuffer()
        self._assistant_draft_buffer.append(chunk)

    def commit_assistant(self) -> None:
        if self._assistant_draft_buffer is None:
            return
        self._records.append(AssistantMessageRecord(text=self._assistant_draft_buffer.text, stable=True))
        self._assistant_draft_buffer = None


@dataclass(slots=True)
class TranscriptView:
    records: tuple[DisplayRecord, ...] | list[DisplayRecord]
    draft: AssistantMessageRecord | None = None
    verbose_errors: bool = False
    theme: ThemeResolver | None = None
    capabilities: TerminalCapabilities | None = None
    code_highlighter: CodeHighlighterLike | None = None
    markdown_cache: MarkdownRenderCache | None = None
    markdown_streaming_key: object | None = None
    _render_cache_key: tuple[object, ...] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _render_cache_lines: tuple[str, ...] | None = field(default=None, init=False, repr=False)
    _record_line_cache: dict[tuple[DisplayRecord, bool, int, tuple[object, ...]], tuple[str, ...]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def render(self, constraints: RenderConstraints) -> RenderResult:
        records = tuple(self.records)
        style_signature = _transcript_style_signature(self.theme, self.capabilities, self.code_highlighter)
        cache_key = (
            records,
            self.draft,
            self.verbose_errors,
            constraints.width,
            constraints.max_height,
            style_signature,
        )
        if cache_key == self._render_cache_key and self._render_cache_lines is not None:
            return RenderResult.from_lines(
                [RenderLine(line) for line in self._render_cache_lines],
                constraints=constraints,
            )

        lines: list[str] = []
        for record in [*records, *([self.draft] if self.draft is not None else [])]:
            lines.extend(self._render_record(record, width=constraints.width, style_signature=style_signature))
            if len(lines) >= constraints.max_height:
                break
        lines = lines[: constraints.max_height]
        self._render_cache_key = cache_key
        self._render_cache_lines = tuple(lines)
        return RenderResult.from_lines([RenderLine(line) for line in lines], constraints=constraints)

    def _render_record(
        self,
        record: DisplayRecord,
        *,
        width: int,
        style_signature: tuple[object, ...],
    ) -> tuple[str, ...]:
        if _record_is_transient(record):
            return tuple(
                _render_record(
                    record,
                    width=width,
                    verbose_errors=self.verbose_errors,
                    theme=self.theme,
                    capabilities=self.capabilities,
                    code_highlighter=self.code_highlighter,
                    markdown_cache=self.markdown_cache,
                    markdown_streaming_key=self.markdown_streaming_key,
                )
            )

        key = (record, self.verbose_errors, width, style_signature)
        cached = self._record_line_cache.get(key)
        if cached is not None:
            return cached
        rendered = tuple(
            _render_record(
                record,
                width=width,
                verbose_errors=self.verbose_errors,
                theme=self.theme,
                capabilities=self.capabilities,
                code_highlighter=self.code_highlighter,
                markdown_cache=self.markdown_cache,
                markdown_streaming_key=None,
            )
        )
        self._record_line_cache[key] = rendered
        return rendered


def render_transcript_records(
    records: tuple[DisplayRecord, ...] | list[DisplayRecord],
    *,
    width: int,
    max_height: int,
    draft: AssistantMessageRecord | None = None,
    verbose_errors: bool = False,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
    code_highlighter: CodeHighlighterLike | None = None,
    markdown_cache: MarkdownRenderCache | None = None,
    markdown_streaming_key: object | None = None,
) -> tuple[RenderLine, ...]:
    view = TranscriptView(
        records,
        draft=draft,
        verbose_errors=verbose_errors,
        theme=theme,
        capabilities=capabilities,
        code_highlighter=code_highlighter,
        markdown_cache=markdown_cache,
        markdown_streaming_key=markdown_streaming_key,
    )
    rendered = view.render(RenderConstraints(width=width, max_height=max_height))
    return rendered.lines


def _record_is_transient(record: DisplayRecord) -> bool:
    return isinstance(record, AssistantMessageRecord) and not record.stable


def _render_record(
    record: DisplayRecord,
    *,
    width: int,
    verbose_errors: bool,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
    code_highlighter: CodeHighlighterLike | None = None,
    markdown_cache: MarkdownRenderCache | None = None,
    markdown_streaming_key: object | None = None,
) -> list[str]:
    target_width = autowrap_safe_width(width)
    if isinstance(record, UserPromptRecord):
        return _prefixed_block("> ", record.text, width=target_width)
    if isinstance(record, AssistantMessageRecord):
        if theme is not None:
            return _prefixed_rendered_lines(
                "* ",
                "  ",
                _render_markdown_content(
                    record.text,
                    width=target_width - visible_width("* "),
                    theme=theme,
                    capabilities=capabilities,
                    code_highlighter=code_highlighter,
                    markdown_cache=markdown_cache,
                    markdown_streaming_key=markdown_streaming_key,
                ),
                width=target_width,
            )
        return _prefixed_block("* ", record.text, width=target_width)
    if isinstance(record, ToolExecutionRecord):
        return _render_tool(
            record,
            width=target_width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
            markdown_cache=markdown_cache,
        )
    if isinstance(record, ThinkingRecord):
        return _render_thinking(record, width=target_width)
    if isinstance(record, StatusRecord):
        return _prefixed_block("", record.text, width=target_width)
    if isinstance(record, ErrorRecord):
        lines = _prefixed_block("! Error: ", record.summary, width=target_width)
        if verbose_errors and record.diagnostics:
            lines.extend(_prefixed_block("  ", record.diagnostics, width=target_width))
        return lines
    if isinstance(record, ContextCompactionRecord):
        return [truncate_to_width(_context_compaction_line(record), max_width=target_width)]
    if isinstance(record, WorkedDividerRecord):
        prefix = f"- Worked for {_format_elapsed(record.elapsed_seconds)} "
        filler_width = max(0, target_width - visible_width(prefix))
        return [truncate_to_width(prefix + ("-" * filler_width), max_width=target_width)]
    return []


def _render_tool(
    record: ToolExecutionRecord,
    *,
    width: int,
    theme: ThemeResolver | None = None,
    capabilities: TerminalCapabilities | None = None,
    code_highlighter: CodeHighlighterLike | None = None,
    markdown_cache: MarkdownRenderCache | None = None,
) -> list[str]:
    first = _tool_heading(record)
    lines = [truncate_to_width(first, max_width=width)]
    if record.command:
        lines.extend(_prefixed_block("  $ ", record.command, width=width))
    if record.output:
        if record.output_kind == "text":
            lines.extend(_prefixed_block("  ", record.output, width=width))
        else:
            lines.extend(
                _prefixed_rendered_lines(
                    "  ",
                    "  ",
                    _render_tool_output_content(
                        record,
                        width=width - 2,
                        theme=theme,
                        capabilities=capabilities,
                        code_highlighter=code_highlighter,
                        markdown_cache=markdown_cache,
                    ),
                    width=width,
                )
            )
    if record.stderr:
        lines.extend(_prefixed_block("  stderr: ", record.stderr, width=width))
    if record.exit_code is not None:
        lines.append(truncate_to_width(f"  exit code: {record.exit_code}", max_width=width))
    return lines


def _tool_heading(record: ToolExecutionRecord) -> str:
    elapsed = _format_elapsed(record.elapsed_seconds)
    if record.state == "running":
        return f"- Ran {record.name} {elapsed}"
    if record.state == "completed":
        return f"- Ran {record.name} took {elapsed}"
    if record.state == "failed":
        return f"! Ran {record.name} failed after {elapsed}"
    if record.state == "cancelled":
        return f"! Ran {record.name} cancelled after {elapsed}"
    if record.state == "truncated":
        return f"- Ran {record.name} truncated after {elapsed}"
    return f"- Ran {record.name} took {elapsed}"


def _render_tool_output_content(
    record: ToolExecutionRecord,
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    markdown_cache: MarkdownRenderCache | None = None,
) -> tuple[str, ...]:
    if record.output_kind == "markdown":
        return _render_markdown_content(
            record.output,
            width=width,
            theme=theme,
            capabilities=capabilities,
            code_highlighter=code_highlighter,
            markdown_cache=markdown_cache,
        )
    constraints = _inner_constraints(width)
    if record.output_kind == "code":
        rendered = CodeBlock(
            record.output,
            language=record.language,
            highlighter=code_highlighter,
            theme=theme,
            capabilities=capabilities,
        ).render(constraints)
        return tuple(line.text for line in rendered.lines)
    if record.output_kind == "diff":
        rendered = DiffBlock(
            record.output,
            theme=theme,
            capabilities=capabilities,
            show_stats=record.show_stats,
        ).render(constraints)
        return tuple(line.text for line in rendered.lines)
    return tuple(record.output.split("\n"))


def _render_markdown_content(
    text: str,
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    markdown_cache: MarkdownRenderCache | None = None,
    markdown_streaming_key: object | None = None,
) -> tuple[str, ...]:
    rendered = MarkdownRenderer(
        text,
        theme=theme,
        capabilities=capabilities,
        code_highlighter=code_highlighter,
        render_cache=markdown_cache,
        streaming_key=markdown_streaming_key,
    ).render(_inner_constraints(width))
    return tuple(line.text for line in rendered.lines)


def _render_streaming_assistant_markdown_segments(
    text: str,
    *,
    width: int,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
    markdown_cache: MarkdownRenderCache,
    markdown_streaming_key: object,
) -> MarkdownSegmentedRenderResult | None:
    if theme is None:
        return None
    target_width = autowrap_safe_width(width)
    return MarkdownRenderer(
        text,
        theme=theme,
        capabilities=capabilities,
        code_highlighter=code_highlighter,
        render_cache=markdown_cache,
        streaming_key=markdown_streaming_key,
    ).render_streaming_segments(
        _inner_constraints(target_width - visible_width("* "))
    )


def _prefix_streaming_assistant_segment(
    lines: tuple[str, ...],
    *,
    width: int,
    use_first_prefix: bool,
) -> tuple[str, ...]:
    target_width = autowrap_safe_width(width)
    return tuple(
        _prefixed_rendered_lines(
            "* " if use_first_prefix else "  ",
            "  ",
            lines,
            width=target_width,
        )
    )


def _inner_constraints(width: int) -> RenderConstraints:
    return RenderConstraints(width=max(1, width) + 1, max_height=1_000_000)


def _prefixed_rendered_lines(
    first_prefix: str,
    continuation_prefix: str,
    lines: tuple[str, ...],
    *,
    width: int,
) -> list[str]:
    prefixed: list[str] = []
    used_first = False
    for line in lines:
        if line == "":
            prefixed.append("")
            continue
        prefix = first_prefix if not used_first else continuation_prefix
        used_first = True
        prefixed.append(truncate_to_width(prefix + line, max_width=width))
    return prefixed


def _transcript_style_signature(
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
    code_highlighter: CodeHighlighterLike | None,
) -> tuple[object, ...]:
    theme_signature: tuple[object, ...] | None = None
    if theme is not None:
        theme_signature = (id(theme), theme.version)
    capabilities_signature: tuple[bool, bool] | None = None
    if capabilities is not None:
        capabilities_signature = (capabilities.truecolor, capabilities.hyperlinks)
    return (theme_signature, capabilities_signature, id(code_highlighter) if code_highlighter is not None else None)


def _render_thinking(record: ThinkingRecord, *, width: int) -> list[str]:
    if record.visibility is ThinkingVisibility.HIDDEN:
        return []
    if record.visibility is ThinkingVisibility.UNAVAILABLE:
        return [truncate_to_width("? thinking unavailable", max_width=width)]
    if record.visibility is ThinkingVisibility.COLLAPSED:
        return [truncate_to_width("? thinking collapsed", max_width=width)]
    return _prefixed_block("? thinking: ", record.text, width=width)


def _context_compaction_line(record: ContextCompactionRecord) -> str:
    line = "* Context compacted"
    if record.tokens_before is not None:
        line += f" ({record.tokens_before} tokens before)"
    return line


def _prefixed_block(prefix: str, text: str, *, width: int) -> list[str]:
    continuation = "  "
    available = max(1, width - visible_width(prefix))
    continuation_available = max(1, width - visible_width(continuation))
    lines: list[str] = []
    for logical_index, logical_line in enumerate(text.split("\n")):
        wrapped = wrap_cells(logical_line, width=available if logical_index == 0 and not lines else continuation_available)
        for wrap_index, chunk in enumerate(wrapped):
            line_prefix = prefix if not lines and logical_index == 0 and wrap_index == 0 else continuation
            lines.append(truncate_to_width(line_prefix + chunk, max_width=width))
    return lines or [truncate_to_width(prefix, max_width=width)]


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    remaining = seconds - (minutes * 60)
    return f"{minutes}m {remaining:05.2f}s"
