"""Pure reducer from App Contract snapshots/events to hosted window state."""

from __future__ import annotations

from loushang.appserver.protocol import (
    AttachmentEventV1,
    MuxAttachmentV1,
    SessionEventKindV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)

from .model import HarnessWindowState, HostedMuxState


def state_from_attachment(attachment: MuxAttachmentV1) -> HostedMuxState:
    """Build one complete client state from an atomic attachment value."""

    if type(attachment) is not MuxAttachmentV1:
        raise TypeError("attachment must be MuxAttachmentV1")
    windows = [
        HarnessWindowState(
            window_id=item.member.member_id,
            member_id=item.member.member_id,
            session_id=item.member.session.session_id,
            title=item.member.title,
            records=list(item.snapshot.records),
            last_cursor=item.snapshot.cursor,
            running=item.snapshot.running,
        )
        for item in attachment.sessions
    ]
    return HostedMuxState(
        mux_space_id=attachment.mux_space.mux_space_id,
        mux_name=attachment.mux_space.name,
        membership_revision=attachment.mux_space.revision,
        attachment_id=attachment.attachment_id,
        controller_generation=attachment.controller_generation,
        windows=windows,
    )


def reduce_events(
    state: HostedMuxState,
    events: tuple[AttachmentEventV1, ...],
) -> None:
    """Apply ordered delivery; gaps stop mutation until a fresh snapshot."""

    if state.snapshot_required:
        return
    by_member = {window.member_id: window for window in state.windows}
    for item in events:
        if item.attachment_id != state.attachment_id:
            state.snapshot_required = True
            state.status_message = "attachment_changed"
            return
        window = by_member.get(item.member_id)
        if window is None or item.event.session_id != window.session_id:
            state.snapshot_required = True
            state.status_message = "membership_changed"
            return
        cursor = item.event.cursor
        if cursor <= window.last_cursor:
            continue
        if cursor != window.last_cursor + 1:
            state.snapshot_required = True
            state.status_message = "snapshot_required"
            return
        _apply_event(
            window,
            item.event.kind,
            item.event.text,
            item.event.interaction_id,
        )
        window.last_cursor = cursor
        if window is not state.active_window:
            window.unread = True


def select_next(state: HostedMuxState) -> None:
    if not state.windows:
        return
    state.active_index = (state.active_index + 1) % len(state.windows)
    _mark_active_read(state)


def select_previous(state: HostedMuxState) -> None:
    if not state.windows:
        return
    state.active_index = (state.active_index - 1) % len(state.windows)
    _mark_active_read(state)


def select_window(state: HostedMuxState, index: int) -> None:
    if type(index) is not int or not 0 <= index < len(state.windows):
        raise IndexError("hosted mux window index is out of range")
    state.active_index = index
    _mark_active_read(state)


def set_active_draft(state: HostedMuxState, text: str) -> None:
    window = state.active_window
    if window is None:
        raise RuntimeError("hosted mux has no active window")
    window.draft = text


def _mark_active_read(state: HostedMuxState) -> None:
    window = state.active_window
    if window is not None:
        window.unread = False


def _apply_event(
    window: HarnessWindowState,
    kind: SessionEventKindV1,
    text: str | None,
    interaction_id: str | None,
) -> None:
    if kind is SessionEventKindV1.TURN_STARTED:
        window.running = True
    elif kind is SessionEventKindV1.USER_MESSAGE:
        _append(window, TranscriptRecordKindV1.USER, text)
    elif kind is SessionEventKindV1.ASSISTANT_DELTA:
        window.assistant_draft += text or ""
    elif kind is SessionEventKindV1.ASSISTANT_MESSAGE:
        _append(
            window,
            TranscriptRecordKindV1.ASSISTANT,
            text if text is not None else window.assistant_draft,
        )
        window.assistant_draft = ""
    elif kind is SessionEventKindV1.STATUS:
        _append(window, TranscriptRecordKindV1.STATUS, text)
    elif kind is SessionEventKindV1.ERROR:
        _append(window, TranscriptRecordKindV1.ERROR, text)
    elif kind in {
        SessionEventKindV1.TURN_COMPLETED,
        SessionEventKindV1.TURN_INTERRUPTED,
    }:
        window.running = False
    elif kind is SessionEventKindV1.INTERACTION_REQUESTED:
        window.pending_interaction_id = interaction_id
        window.pending_interaction_text = text
    elif (
        kind is SessionEventKindV1.INTERACTION_DISMISSED
        and window.pending_interaction_id == interaction_id
    ):
        window.pending_interaction_id = None
        window.pending_interaction_text = None


def _append(
    window: HarnessWindowState,
    kind: TranscriptRecordKindV1,
    text: str | None,
) -> None:
    if text is not None:
        window.records.append(TranscriptRecordV1(kind, text))


__all__ = [
    "reduce_events",
    "select_next",
    "select_previous",
    "select_window",
    "set_active_draft",
    "state_from_attachment",
]
