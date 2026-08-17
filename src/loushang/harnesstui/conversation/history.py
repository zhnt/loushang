"""Product-neutral dispatch from conversation records to transcript records."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from loushang.harness.conversation.types import ConversationRecord
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    ToolExecutionRecord,
    UserPromptRecord,
)

HistoryRecordDisposition = Literal[
    "render",
    "state-only",
    "hidden",
    "metadata-only",
]
HistoryPayloadProjector = Callable[[object], DisplayRecord | None]
ToolMessageProjector = Callable[[object], ToolExecutionRecord | None]


@dataclass(frozen=True, slots=True)
class ConversationHistoryProjector:
    """Filter and dispatch ordered conversation items to display records."""

    dispositions: Mapping[str, HistoryRecordDisposition]
    payload_projectors: Mapping[str, HistoryPayloadProjector]
    fallback_projector: HistoryPayloadProjector

    def project_item(self, item: object) -> DisplayRecord | None:
        if not isinstance(item, ConversationRecord):
            return self.fallback_projector(item)
        if self.dispositions.get(item.kind) != "render":
            return None
        projector = self.payload_projectors.get(item.kind)
        return projector(item.payload) if projector is not None else None

    def project_items(
        self,
        items: Iterable[object],
    ) -> tuple[DisplayRecord, ...]:
        """Project renderable items in source order, omitting empty sections."""

        records: list[DisplayRecord] = []
        for item in items:
            record = self.project_item(item)
            if record is not None:
                records.append(record)
        return tuple(records)


def project_context_compaction_payload(
    payload: object,
) -> ContextCompactionRecord | None:
    """Project the neutral summary/token shape of a compaction checkpoint."""

    summary = getattr(payload, "summary", None)
    tokens_before = getattr(payload, "tokens_before", None)
    if not isinstance(summary, str):
        return None
    if tokens_before is not None and not isinstance(tokens_before, int):
        return None
    return ContextCompactionRecord(
        summary=summary,
        tokens_before=tokens_before,
    )


def project_context_branch_summary_payload(
    payload: object,
) -> ContextCompactionRecord | None:
    """Project the neutral summary shape of a branch context section."""

    summary = getattr(payload, "summary", None)
    if not isinstance(summary, str):
        return None
    return ContextCompactionRecord(summary=summary)


def project_agent_message_payload(
    message: object,
    *,
    tool_result_projector: ToolMessageProjector,
) -> DisplayRecord | None:
    """Project a structurally typed Agent message without importing Agent or AI."""

    role = getattr(message, "role", None)
    if role == "user":
        text = structural_message_text(getattr(message, "content", None)).strip()
        return UserPromptRecord(text) if text else None
    if role == "assistant":
        text = structural_message_text(getattr(message, "content", None)).strip()
        return AssistantMessageRecord(text, stable=True) if text else None
    if role == "toolResult":
        return tool_result_projector(message)
    if role == "application" and getattr(message, "display", False) is True:
        text = structural_message_text(getattr(message, "content", None)).strip()
        return AssistantMessageRecord(text, stable=True) if text else None
    return None


def project_command_execution_payload(
    payload: object,
) -> ToolExecutionRecord | None:
    """Project the standard command-execution payload shape."""

    command = getattr(payload, "command", None)
    output = getattr(payload, "output", None)
    cancelled = getattr(payload, "cancelled", None)
    exit_code = getattr(payload, "exit_code", None)
    if not isinstance(command, str) or not isinstance(output, str):
        return None
    if type(cancelled) is not bool:
        return None
    if exit_code is not None and not isinstance(exit_code, int):
        return None
    return ToolExecutionRecord(
        name=f"bash {command}".strip(),
        state=(
            "cancelled"
            if cancelled
            else "failed"
            if exit_code not in (None, 0)
            else "completed"
        ),
        elapsed_seconds=0.0,
        output=output,
        command=command,
        exit_code=exit_code,
        stderr="cancelled" if cancelled else "",
    )


def structural_message_text(content: object) -> str:
    """Return visible text from a structural string-or-parts message content."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


__all__ = [
    "ConversationHistoryProjector",
    "HistoryPayloadProjector",
    "HistoryRecordDisposition",
    "ToolMessageProjector",
    "project_agent_message_payload",
    "project_command_execution_payload",
    "project_context_branch_summary_payload",
    "project_context_compaction_payload",
    "structural_message_text",
]
