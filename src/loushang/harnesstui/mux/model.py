"""Client-owned presentation state for the explicit Hosted Mux Profile."""

from __future__ import annotations

from dataclasses import dataclass, field

from loushang.appserver.protocol import TranscriptRecordV1


@dataclass(slots=True)
class HarnessWindowState:
    """One hosted Session window; none of these fields are AppService state."""

    window_id: str
    member_id: str
    session_id: str
    title: str
    records: list[TranscriptRecordV1] = field(default_factory=list)
    last_cursor: int = 0
    unread: bool = False
    draft: str = ""
    assistant_draft: str = ""
    pending_interaction_id: str | None = None
    pending_interaction_text: str | None = None
    scroll_anchor: int | None = None
    running: bool = False


@dataclass(slots=True)
class HostedMuxState:
    """Mutable Harnesstui state reconstructed from one attachment barrier."""

    mux_space_id: str
    mux_name: str
    membership_revision: int
    attachment_id: str
    controller_generation: int
    windows: list[HarnessWindowState]
    active_index: int = 0
    snapshot_required: bool = False
    status_message: str | None = None

    @property
    def active_window(self) -> HarnessWindowState | None:
        if not self.windows:
            return None
        self.active_index %= len(self.windows)
        return self.windows[self.active_index]


__all__ = ["HarnessWindowState", "HostedMuxState"]
