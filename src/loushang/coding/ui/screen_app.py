from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

from loushang.harness.tools.output_preview import (
    drop_tool_timing_tail_line,
    prefers_tail_tool_output,
)
from loushang.harnesstui.conversation.screen_frame import ScreenFrameCopy
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.conversation.theme import (
    terminal_transcript_theme as _terminal_transcript_theme,
)
from loushang.harnesstui.conversation.transcript_display import (
    TranscriptDisplayProjectionProfile,
    compact_absolute_display_paths,
)
from loushang.harnesstui.conversation.transcript_presentation import (
    ConversationTranscriptCopy,
    ConversationTranscriptPresentationProfile,
    ProfiledScreenConversationApp,
    ScreenConversationPresentationProfile,
)
from loushang.harnesstui.conversation.transcript_style import (
    apply_transcript_style as apply_coding_transcript_style,
)
from loushang.tui import Composer, LoushangWelcomePanel, loushang_welcome_theme
from loushang.tui.cell_width import (
    TAB_WIDTH,
    strip_control_sequences,
    truncate_to_width,
    wrap_cells,
)
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    ToolExecutionRecord,
)
from loushang.tui.ui_parts.transcript import DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT

DEFAULT_ACTIVE_TRANSCRIPT_LINE_BUDGET = 320
DEFAULT_STABLE_RENDER_CACHE_ENTRY_LIMIT = DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT
DEFAULT_TOOL_PREVIEW_SCREEN_ROWS = 7
_TOOL_PREVIEW_HINT = "ctrl + t to view transcript"
_NON_PLAIN_PREVIEW_CHAR = re.compile(r"[^\x20-\x7e\n]")

_CODING_SCREEN_FRAME_COPY = ScreenFrameCopy(
    working_label="Working",
    steer_label="Messages to be submitted after next tool call",
    steer_hint="press esc to interrupt and send immediately",
    followup_label="Queued follow-up inputs",
    followup_hint="alt + ↑ edit last queued message",
)


def _coding_compaction_summary(summary: str) -> str:
    return f"Compacted summary:\n\n{summary.strip()}"


def _project_coding_tool_name(
    record: ToolExecutionRecord,
    *,
    context: str,
    width: int,
) -> str:
    name = (
        record.tool_name
        if _coding_command_needs_block(record, context=context, width=width)
        else record.name
    )
    return compact_absolute_display_paths(name or record.name, cwd=context)


def _project_coding_tool_command(
    record: ToolExecutionRecord,
    *,
    projected_name: str,
    context: str,
    width: int,
) -> str:
    del projected_name
    command = record.expanded_command
    if command is None:
        return record.command.replace("\t", " " * TAB_WIDTH)
    command = compact_absolute_display_paths(command, cwd=context)
    command = command.replace("\t", " " * TAB_WIDTH)
    if record.detail_expanded:
        return command
    if not _coding_command_needs_block(record, context=context, width=width):
        return record.command.replace("\t", " " * TAB_WIDTH)
    return _collapse_coding_tool_preview(
        command,
        width=_tool_preview_content_width(width),
        max_rows=DEFAULT_TOOL_PREVIEW_SCREEN_ROWS,
        tail=True,
    )


def _project_coding_tool_output(
    record: ToolExecutionRecord,
    *,
    projected_name: str,
    context: str,
    width: int,
) -> str:
    del context
    if not record.output:
        return record.output
    output = drop_tool_timing_tail_line(
        record.expanded_output if record.expanded_output is not None else record.output
    )
    if record.detail_expanded:
        return output
    if record.output_kind == "text":
        output = _collapse_coding_tool_preview(
            output,
            width=_tool_output_preview_content_width(width),
            max_rows=DEFAULT_TOOL_PREVIEW_SCREEN_ROWS,
            tail=prefers_tail_tool_output(projected_name),
        )
    return output


def _coding_command_needs_block(
    record: ToolExecutionRecord,
    *,
    context: str,
    width: int,
) -> bool:
    command = record.expanded_command
    if command is None:
        return False
    command = compact_absolute_display_paths(command, cwd=context)
    command = command.replace("\t", " " * TAB_WIDTH)
    return len(wrap_cells(command, width=_tool_preview_content_width(width))) > 1


def _tool_preview_content_width(width: int) -> int:
    # Commands reserve the four-cell rail plus ``$ ``, as well as one terminal
    # autowrap-safety cell.
    return max(1, width - 7)


def _tool_output_preview_content_width(width: int) -> int:
    # Tool output uses the four-cell Product rail plus one autowrap-safety cell.
    return max(1, width - 5)


def _collapse_coding_tool_preview(
    text: str,
    *,
    width: int,
    max_rows: int,
    tail: bool,
) -> str:
    if max_rows < 1:
        return ""
    text = text.replace("\t", " " * TAB_WIDTH)
    row_count, head_rows, tail_rows = _preview_wrapped_rows(
        text, width=width, limit=max_rows
    )
    if row_count <= max_rows:
        return "\n".join(head_rows)

    marker_rows = 1
    while True:
        visible_budget = max(0, max_rows - marker_rows)
        head_budget = visible_budget if not tail else visible_budget // 2
        tail_budget = 0 if not tail else visible_budget - head_budget
        hidden_rows = max(0, row_count - head_budget - tail_budget)
        marker = f"… +{hidden_rows} lines ({_TOOL_PREVIEW_HINT})"
        updated_marker_rows = len(wrap_cells(marker, width=width))
        if updated_marker_rows <= marker_rows:
            break
        marker_rows = updated_marker_rows

    if marker_rows > max_rows:
        compact_marker = truncate_to_width(
            f"ctrl+t · +{row_count}",
            max_width=width * max_rows,
            ellipsis="…",
        )
        return "\n".join(wrap_cells(compact_marker, width=width))
    if marker_rows == max_rows:
        return "\n".join(wrap_cells(marker, width=width))
    head = head_rows[:head_budget]
    tail_lines = tail_rows[-tail_budget:] if tail_budget else []
    return "\n".join([*head, *wrap_cells(marker, width=width), *tail_lines])


def _preview_wrapped_rows(
    text: str, *, width: int, limit: int
) -> tuple[int, list[str], list[str]]:
    """Count wrapped rows while retaining only the rows a preview can show."""

    if width <= 0:
        raise ValueError("width must be positive")
    # Most command output consists of short printable lines. Count those in C
    # and retain only the visible ends instead of visiting every line in Python.
    if (
        limit > 0
        and re.search(rf"[^\n]{{{width + 1}}}", text) is None
        and _NON_PLAIN_PREVIEW_CHAR.search(text) is None
    ):
        count = text.count("\n") + 1
        return (
            count,
            text.split("\n", limit)[:limit],
            text.rsplit("\n", limit)[-limit:],
        )
    head: list[str] = []
    tail: deque[str] = deque(maxlen=limit)
    count = 0
    for line in strip_control_sequences(text).split("\n"):
        if line.isascii() and line.isprintable():
            rows = max(1, (len(line) + width - 1) // width)
            if rows == 1:
                if len(head) < limit:
                    head.append(line)
                tail.append(line)
            else:
                missing = max(0, limit - len(head))
                for index in range(min(rows, missing)):
                    head.append(line[index * width : (index + 1) * width])
                for index in range(max(0, rows - limit), rows):
                    tail.append(line[index * width : (index + 1) * width])
        else:
            wrapped = wrap_cells(line, width=width)
            rows = len(wrapped)
            head.extend(wrapped[: max(0, limit - len(head))])
            tail.extend(wrapped[-limit:])
        count += rows
    return count, head, list(tail)


def _coding_welcome_panel(
    state: ScreenConversationState,
    *,
    theme: ThemeResolver | None,
) -> LoushangWelcomePanel:
    return LoushangWelcomePanel(
        directory=state.cwd,
        session=state.session_label or "",
        model=state.model_label or "",
        theme=theme,
    )


_CODING_TRANSCRIPT_DISPLAY_PROJECTION = TranscriptDisplayProjectionProfile[str](
    project_tool_name=_project_coding_tool_name,
    project_tool_output=_project_coding_tool_output,
    suppress_duplicate_tool_command=True,
    tool_record_width_inset=2,
    project_tool_command=_project_coding_tool_command,
)

_CODING_TRANSCRIPT_PRESENTATION_PROFILE = ConversationTranscriptPresentationProfile[
    str
](
    copy=ConversationTranscriptCopy(
        user_prompt_prefix="› ",
        assistant_prefix="• ",
        error_prefix="■ Error: ",
        context_compaction_prefix="• ",
        tool_success_prefix="• Ran ",
        tool_error_prefix="■ Ran ",
        worked_divider="─",
        tool_command_prefix="  │ ",
        tool_first_output_prefix="  └ ",
        tool_continuation_prefix="    ",
    ),
    project_record=_CODING_TRANSCRIPT_DISPLAY_PROJECTION.project_record,
    record_render_width=_CODING_TRANSCRIPT_DISPLAY_PROJECTION.record_render_width,
    style_line=apply_coding_transcript_style,
)

_CODING_SCREEN_PRESENTATION_PROFILE = ScreenConversationPresentationProfile[str](
    transcript=_CODING_TRANSCRIPT_PRESENTATION_PROFILE,
    transcript_context=lambda state: state.cwd,
    frame_copy=_CODING_SCREEN_FRAME_COPY,
    welcome_panel=_coding_welcome_panel,
)


@dataclass(slots=True)
class ScreenCodingTuiApp(ProfiledScreenConversationApp):
    """Coding product binding over the shared profiled conversation screen."""

    screen_presentation_profile: ClassVar[
        ScreenConversationPresentationProfile[str]
    ] = _CODING_SCREEN_PRESENTATION_PROFILE
    composer: Composer = field(
        default_factory=lambda: Composer(prompt="› ", continuation_prompt="  ")
    )
    transcript_theme: ThemeResolver = field(default_factory=_terminal_transcript_theme)
    welcome_theme: ThemeResolver | None = field(default_factory=loushang_welcome_theme)
    active_transcript_line_budget: int = DEFAULT_ACTIVE_TRANSCRIPT_LINE_BUDGET
    compaction_summary_formatter: Callable[[str], str] = field(
        default=_coding_compaction_summary,
        repr=False,
    )


__all__ = ["ScreenCodingTuiApp"]
