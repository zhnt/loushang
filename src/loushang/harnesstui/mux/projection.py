"""Projection from hosted App Contract records to shared conversation state."""

from __future__ import annotations

from loushang.appserver.protocol import TranscriptRecordKindV1
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    StatusRecord,
    UserPromptRecord,
)

from ..conversation.screen_state import ScreenConversationState
from .model import HostedMuxState


def project_active_conversation(state: HostedMuxState) -> ScreenConversationState:
    """Reuse the shared presentation core without retaining Product objects."""

    projected = ScreenConversationState()
    window = state.active_window
    if window is None:
        projected.set_status("No hosted Sessions")
        return projected
    records: list[DisplayRecord] = []
    for record in window.records:
        if record.kind is TranscriptRecordKindV1.USER:
            records.append(UserPromptRecord(record.text))
        elif record.kind is TranscriptRecordKindV1.ASSISTANT:
            records.append(AssistantMessageRecord(record.text, stable=True))
        elif record.kind is TranscriptRecordKindV1.STATUS:
            records.append(StatusRecord(record.text))
        else:
            records.append(ErrorRecord(record.text, ""))
    projected.replace_transcript_window(records)
    projected.session_label = window.title
    if window.running:
        projected.begin_run(started_at=0.0)
    if window.assistant_draft:
        projected.append_assistant_chunk(window.assistant_draft)
    projected.set_status(state.status_message)
    return projected


__all__ = ["project_active_conversation"]
