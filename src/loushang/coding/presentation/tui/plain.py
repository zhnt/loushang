from __future__ import annotations

import shutil
from dataclasses import dataclass, field

from loushang.harnesstui.conversation.agent_binding import (
    agent_tool_block_to_record,
)
from loushang.harnesstui.plain.renderer import (
    PlainConversationGlyphs,
    PlainConversationProfile,
    PlainConversationRenderer,
)
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.render import MarkdownBlock as MarkdownBlock
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)

_INTERRUPTION_MESSAGE = (
    "Conversation interrupted - tell the model what to do differently. "
    "Something went wrong? Hit `/feedback` to report the issue."
)


def _coding_terminal_columns() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def _coding_line(line: str, record: DisplayRecord) -> str:
    line = strip_control_sequences(line)
    if isinstance(record, UserPromptRecord) and line.startswith("> "):
        return "› " + line[2:]
    if isinstance(record, AssistantMessageRecord) and line.startswith("* "):
        return "• " + line[2:]
    if isinstance(record, ErrorRecord) and line.startswith("! Error: "):
        return "■ Error: " + line[len("! Error: ") :]
    if isinstance(record, ToolExecutionRecord):
        if line.startswith("- Ran "):
            return "• Ran " + line[len("- Ran ") :]
        if line.startswith("! Ran "):
            return "■ Ran " + line[len("! Ran ") :]
    if isinstance(record, WorkedDividerRecord) and line.startswith("- Worked for "):
        return line.replace("-", "─", 1).replace("-", "─")
    return line


_CODING_PLAIN_CONVERSATION_PROFILE = PlainConversationProfile(
    title="Loushang TUI",
    interruption_message=_INTERRUPTION_MESSAGE,
    glyphs=PlainConversationGlyphs(
        user_prompt="› ",
        assistant="• ",
        item="• ",
        error="■ Error: ",
        interruption="■ ",
        rule="─",
    ),
    line_mapper=_coding_line,
    tool_block_projector=agent_tool_block_to_record,
    terminal_columns=_coding_terminal_columns,
)


@dataclass
class PlainCodingUiRenderer(PlainConversationRenderer):
    """Coding presentation profile over the shared plain renderer."""

    profile: PlainConversationProfile = field(
        default=_CODING_PLAIN_CONVERSATION_PROFILE,
        init=False,
        repr=False,
    )

__all__ = ["PlainCodingUiRenderer"]
