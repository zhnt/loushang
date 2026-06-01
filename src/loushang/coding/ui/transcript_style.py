import re
from dataclasses import dataclass

from loushang.tui.theme import TerminalCapabilities, ThemeResolver, apply_theme_style
from loushang.tui.transcript import (
    DisplayRecord,
    ErrorRecord,
    ToolExecutionRecord,
    WorkedDividerRecord,
)

_FLAG_RE = re.compile(r"(?<!\S)(-{1,2}[A-Za-z0-9][A-Za-z0-9_-]*)(?=$|[\s=])")
_ELLIPSIS_LINES_RE = re.compile(r"… \+\d+ lines(?: \([^)]*\))?")
_COLLAPSED_LINES_RE = re.compile(r"\.\.\. \(\d+ (?:earlier|more|hidden) lines?\)")
_TIMING_RE = re.compile(r"\b(?:took|Took|Elapsed) \d+(?:\.\d+)?(?:ms|s|m|h)?\b")
_GIT_NOOP_RE = re.compile(r"\bnothing (?:added to commit|to commit)\b.*", re.IGNORECASE)
_TOOL_VERBS = {"Ran", "Explored", "Edited", "Tested"}
_TOOL_ACTIONS = {"Read", "Search"}
_CONNECTORS = frozenset("│└├┌┐┘┤┬┴┼╭╮╰╯")


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    token: str


def apply_coding_transcript_style(
    line: str,
    record: DisplayRecord,
    *,
    theme: ThemeResolver | None,
    capabilities: TerminalCapabilities | None,
) -> str:
    if theme is None:
        return line
    if isinstance(record, WorkedDividerRecord):
        return _style(line, "transcript.divider", theme=theme, capabilities=capabilities)
    if isinstance(record, ErrorRecord):
        return _style(line, "transcript.error", theme=theme, capabilities=capabilities)
    if not isinstance(record, ToolExecutionRecord):
        return line

    spans: list[_Span] = []
    spans.extend(_tool_heading_spans(line))
    spans.extend(_tool_output_spans(line))
    return _apply_spans(line, spans, theme=theme, capabilities=capabilities)


def _tool_heading_spans(line: str) -> list[_Span]:
    spans: list[_Span] = []
    if line.startswith("• "):
        spans.append(_Span(0, 1, "transcript.tool.marker"))
        spans.extend(_verb_span(line, start=2))
        if line.startswith("• Ran "):
            spans.extend(_flag_spans(line))
    elif line.startswith("■ "):
        spans.append(_Span(0, 1, "transcript.tool.error_marker"))
        spans.extend(_verb_span(line, start=2))
        if line.startswith("■ Ran "):
            spans.extend(_flag_spans(line))
    return spans


def _verb_span(line: str, *, start: int) -> list[_Span]:
    end = line.find(" ", start)
    if end == -1:
        end = len(line)
    verb = line[start:end]
    if verb not in _TOOL_VERBS:
        return []
    return [_Span(start, end, "transcript.tool.verb")]


def _flag_spans(line: str) -> list[_Span]:
    return [_Span(match.start(1), match.end(1), "transcript.tool.flag") for match in _FLAG_RE.finditer(line)]


def _tool_output_spans(line: str) -> list[_Span]:
    spans: list[_Span] = []
    first_content = _first_non_space(line)
    if first_content is None:
        return spans
    if line[first_content] in _CONNECTORS:
        spans.append(_Span(first_content, first_content + 1, "transcript.tool.connector"))
    spans.extend(_action_spans(line, first_content=first_content))
    spans.extend(_meta_spans(line))
    return spans


def _first_non_space(line: str) -> int | None:
    for index, char in enumerate(line):
        if char != " ":
            return index
    return None


def _action_spans(line: str, *, first_content: int) -> list[_Span]:
    start = first_content
    if line[start] in _CONNECTORS:
        start += 1
        while start < len(line) and line[start] == " ":
            start += 1
    end = line.find(" ", start)
    if end == -1:
        end = len(line)
    action = line[start:end]
    if action not in _TOOL_ACTIONS:
        return []
    return [_Span(start, end, "transcript.tool.action")]


def _meta_spans(line: str) -> list[_Span]:
    spans: list[_Span] = []
    no_output = line.find("(no output)")
    if no_output != -1:
        spans.append(_Span(no_output, no_output + len("(no output)"), "transcript.tool.meta"))
    spans.extend(_Span(match.start(), match.end(), "transcript.tool.meta") for match in _ELLIPSIS_LINES_RE.finditer(line))
    spans.extend(_Span(match.start(), match.end(), "transcript.tool.meta") for match in _COLLAPSED_LINES_RE.finditer(line))
    spans.extend(_Span(match.start(), match.end(), "transcript.tool.meta") for match in _TIMING_RE.finditer(line))
    spans.extend(_Span(match.start(), match.end(), "transcript.tool.meta") for match in _GIT_NOOP_RE.finditer(line))
    return spans


def _apply_spans(
    line: str,
    spans: list[_Span],
    *,
    theme: ThemeResolver,
    capabilities: TerminalCapabilities | None,
) -> str:
    if not spans:
        return line
    spans = sorted(spans, key=lambda span: (span.start, span.end))
    output: list[str] = []
    cursor = 0
    for span in spans:
        if span.start < cursor or span.end <= span.start:
            continue
        output.append(line[cursor : span.start])
        output.append(_style(line[span.start : span.end], span.token, theme=theme, capabilities=capabilities))
        cursor = span.end
    output.append(line[cursor:])
    return "".join(output)


def _style(
    text: str,
    token: str,
    *,
    theme: ThemeResolver,
    capabilities: TerminalCapabilities | None,
) -> str:
    return apply_theme_style(text, theme.resolve(token, capabilities))


__all__ = ["apply_coding_transcript_style"]
