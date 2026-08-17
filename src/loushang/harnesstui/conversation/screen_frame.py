"""Product-neutral screen conversation frame presentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.status.line import (
    StatusLinePreviewSnapshot,
    status_line_fields,
    status_line_separator,
    status_line_style_mode,
)
from loushang.tui import (
    BottomFrame,
    Composer,
    PendingQueueView,
    PendingSection,
    StatusBar,
    WorkingLine,
)


@dataclass(frozen=True, slots=True)
class ScreenFrameCopy:
    """Presentation copy supplied by a product screen binding."""

    working_label: str
    steer_label: str
    steer_hint: str
    followup_label: str
    followup_hint: str
    interruption_marker: str = "■"


@dataclass(frozen=True, slots=True)
class ScreenFramePresentation:
    """Build the reusable bottom frame around conversation state."""

    copy: ScreenFrameCopy

    def statusline_preview_snapshot(
        self, state: ScreenConversationState
    ) -> StatusLinePreviewSnapshot:
        return StatusLinePreviewSnapshot(
            model_label=state.model_label,
            cwd=state.cwd,
            branch=state.branch,
            session_label=state.session_label,
            running=state.running,
            permission_profile=state.permission_profile,
            pending_followups=len(state.pending_followups),
            pending_steers=len(state.pending_steers),
            status_message=state.status_message,
        )

    def expanded_bottom_frame(
        self,
        state: ScreenConversationState,
        *,
        active_surface: Any | None,
    ) -> bool:
        return (
            active_surface is not None
            or state.running
            or bool(state.pending_steers)
            or bool(state.pending_followups)
            or bool(state.interruption_message)
        )

    def bottom_frame_height(
        self,
        state: ScreenConversationState,
        *,
        active_surface: Any | None,
        visible_height: int,
    ) -> int:
        height = 12
        if self.expanded_bottom_frame(state, active_surface=active_surface):
            height = 16
            preferred = getattr(active_surface, "preferred_height", None)
            if isinstance(preferred, int) and preferred > 0:
                height = max(height, preferred)
        return max(1, min(height, visible_height))

    def populate_bottom_frame(
        self,
        component: BottomFrame,
        *,
        composer: Composer,
        state: ScreenConversationState,
        active_surface: Any | None,
        elapsed_seconds: float,
    ) -> BottomFrame:
        component.composer = composer
        component.surface = active_surface
        component.working_line = self.working_line(
            state,
            elapsed_seconds=elapsed_seconds,
        )
        component.pending_queue = self.pending_queue(state)
        component.status_bar = (
            self.status_bar(state) if state.statusline_visible else None
        )
        return component

    def working_line(
        self,
        state: ScreenConversationState,
        *,
        elapsed_seconds: float,
    ) -> WorkingLine | None:
        if not state.running:
            return None
        return WorkingLine(
            label=self.copy.working_label,
            elapsed_seconds=elapsed_seconds,
        )

    def pending_queue(self, state: ScreenConversationState) -> PendingQueueView | None:
        sections: list[PendingSection] = []
        if state.interruption_message:
            sections.append(
                PendingSection(
                    label=state.interruption_message,
                    marker=self.copy.interruption_marker,
                    show_when_empty=True,
                )
            )
        if state.pending_steers:
            sections.append(
                PendingSection(
                    label=self.copy.steer_label,
                    items=tuple(state.pending_steers),
                    hint=self.copy.steer_hint,
                    hint_placement="header",
                )
            )
        if state.pending_followups:
            sections.append(
                PendingSection(
                    label=self.copy.followup_label,
                    items=tuple(state.pending_followups),
                    hint=self.copy.followup_hint,
                )
            )
        if not sections:
            return None
        return PendingQueueView(sections=tuple(sections))

    def status_bar(self, state: ScreenConversationState) -> StatusBar:
        settings = state.statusline_settings
        return StatusBar(
            status_line_fields(
                self.statusline_preview_snapshot(state),
                settings,
            ),
            separator=status_line_separator(settings),
            style_mode=status_line_style_mode(settings),
        )


__all__ = ["ScreenFrameCopy", "ScreenFramePresentation"]
