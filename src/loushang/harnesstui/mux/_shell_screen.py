"""Hosted presentation through the existing shared conversation and TUI editor."""

from __future__ import annotations

import unicodedata
from dataclasses import replace
from typing import TYPE_CHECKING

from loushang.tui import Composer
from loushang.tui.cell_width import strip_control_sequences, truncate_to_width
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult

from ..conversation.screen_app import ScreenConversationApp
from ..conversation.screen_frame import ScreenFrameCopy, ScreenFramePresentation
from ..conversation.screen_state import ScreenConversationState
from ..status.line import StatusLineSettings
from .projection import project_active_conversation

if TYPE_CHECKING:
    from .shell import HostedMuxShellV1


def safe_text(text: str) -> str:
    return "".join(
        char
        for char in strip_control_sequences(text)
        if char in "\n\t" or unicodedata.category(char) != "Cc"
    )


class _HostedFramePresentation(ScreenFramePresentation):
    def working_line(
        self, state: ScreenConversationState, *, elapsed_seconds: float
    ) -> None:
        # v1 does not carry a remote start timestamp. The footer/status render
        # authoritative running state without inventing an elapsed duration.
        return None


class HostedMuxScreenV1(ScreenConversationApp):
    def __init__(self, shell: HostedMuxShellV1) -> None:
        self.shell = shell
        self._view_key: object = None
        self._view_revision = 0
        super().__init__(
            model_label="Hosted",
            cwd="",
            branch=None,
            session_label=None,
            composer=Composer(max_undo_depth=16),
        )

    def _create_frame_presentation(self) -> ScreenFramePresentation:
        return _HostedFramePresentation(
            ScreenFrameCopy("Working", "Steer", "", "Follow-up", "")
        )

    def render(self, constraints: RenderConstraints) -> RenderResult:
        mux = self.shell.state
        window = mux.active_window
        key = (
            mux.attachment_id,
            self.shell.notice,
            mux.active_index,
            None
            if window is None
            else (window.last_cursor, window.scroll_anchor, window.title),
        )
        if key != self._view_key:
            self._view_key = key
            self._view_revision += 1
            # Sanitize the terminal copy, never the authoritative transcript.
            windows = []
            for item in mux.windows:
                if item is window:
                    records = (
                        item.records[: item.scroll_anchor]
                        if item.scroll_anchor is not None
                        else item.records
                    )
                    windows.append(
                        replace(
                            item,
                            title=safe_text(item.title),
                            records=[
                                replace(record, text=safe_text(record.text))
                                for record in records
                            ],
                            assistant_draft=safe_text(item.assistant_draft)
                            if item.scroll_anchor is None
                            else "",
                        )
                    )
                else:
                    windows.append(item)
            self.state = project_active_conversation(replace(mux, windows=windows))
            self.state.records_revision = self._view_revision
            self.state.model_label = "Hosted"
            self.state.permission_profile = None
            self.state.statusline_settings = StatusLineSettings(
                workspace=False,
                branch=False,
                permissions=False,
            )
            self.state.status_message = safe_text(self.shell.notice)
            if window is not None and window.pending_interaction_text:
                self.state.status_message = (
                    safe_text(window.pending_interaction_text) + " (/approve /deny)"
                )
        footer = (
            safe_text(mux.mux_name)
            + " | "
            + " ".join(
                f"{'*' if index == mux.active_index else ''}{index + 1}"
                f"{'!' if item.pending_interaction_id else '+' if item.unread else '~' if item.running else ''}"
                for index, item in enumerate(mux.windows)
            )
        )
        footer += " | /help /detach"
        row = RenderLine(
            truncate_to_width(footer, max_width=max(1, constraints.width - 1))
        )
        if constraints.max_height == 1:
            return RenderResult.from_lines((row,), constraints=constraints)
        inner = replace(
            constraints,
            max_height=constraints.max_height - 1,
            visible_height=max(
                1, (constraints.visible_height or constraints.max_height) - 1
            ),
        )
        rendered = super().render(inner)
        return RenderResult.from_lines(
            (*rendered.lines, row), constraints=constraints, cursor=rendered.cursor
        )
