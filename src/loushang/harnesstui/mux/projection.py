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

from ..conversation.input_policy import (
    CapabilityReason,
    ConversationCapabilities,
    ConversationCapability,
    ConversationOperation,
)
from ..conversation.screen_state import ScreenConversationState
from .model import HostedMuxState


def project_capabilities(state: HostedMuxState, *, closing: bool = False,
                         membership_pending: bool = False,
                         approval_presented: bool = False) -> ConversationCapabilities:
    """Synchronously observe current eligibility; never retain authorization."""
    window = state.active_window
    key = (state.attachment_id, str(state.controller_generation),
           window.member_id if window else "", window.session_id if window else "")
    unavailable: CapabilityReason | None = (
        "closing" if closing else "snapshot_required" if state.snapshot_required else
        "membership_pending" if membership_pending else "no_member" if window is None else None
    )
    def action(operation: ConversationOperation) -> ConversationCapability:
        return ConversationCapability(operation, "unavailable" if unavailable else "available",
                                      unavailable or "supported")
    def approval(operation: ConversationOperation) -> ConversationCapability:
        if unavailable:
            return action(operation)
        if window is None or window.pending_interaction_id is None:
            return ConversationCapability(operation, "unavailable", "no_interaction")
        if operation == "approval_details":
            return ConversationCapability(operation, "read_only" if window.pending_interaction_text else "unavailable",
                                          "read_only" if window.pending_interaction_text else "no_interaction")
        if operation == "approve" and not approval_presented:
            return ConversationCapability(operation, "unavailable", "presentation_required")
        return action(operation)
    return ConversationCapabilities(key, (
        ConversationCapability("transcript", "read_only" if window else "unavailable",
                               "read_only" if window else "no_member"),
        action("submit"), action("steer"), action("follow_up"), action("interrupt"),
        approval("approval_details"), approval("approve"), approval("deny"),
        ConversationCapability("image_paste", "unavailable", "protocol_unavailable"),
        ConversationCapability("product_commands", "unavailable", "protocol_unavailable"),
    ))


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
    projected.request_presentation = window.request_presentation
    if window.running:
        projected.begin_run(started_at=0.0)
    if window.assistant_draft:
        projected.append_assistant_chunk(window.assistant_draft)
    projected.set_status(state.status_message)
    return projected


__all__ = ["project_active_conversation"]
