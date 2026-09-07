"""Hosted presentation through the existing shared conversation and TUI editor."""

from __future__ import annotations

import unicodedata
from dataclasses import replace
from typing import TYPE_CHECKING

from loushang.tui import Composer
from loushang.tui.cell_width import strip_control_sequences, truncate_to_width
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.input import InputEvent
from loushang.tui.ui_parts.text_pager import TextPager

from ..conversation.screen_app import ScreenConversationApp
from ..conversation.screen_frame import ScreenFrameCopy, ScreenFramePresentation
from ..conversation.screen_state import ScreenConversationState
from ..status.line import StatusLineSettings
from .projection import project_active_conversation

if TYPE_CHECKING:
    from .shell import HostedMuxShellV1

_HELP = """Enter sends a turn. // sends text beginning with a literal slash.
Tab / Shift+Tab or Ctrl+B n/p selects another Session window.
Ctrl+B 1..9 selects a window. Each window retains its own local draft.
PageUp / PageDown scrolls history, or the open read-only details.
F1 or /help opens this help. Esc closes details without changing a draft.
F2 or /question opens the current approval details.
/approve requires all current details to have been presented, then an explicit command.
/deny rejects the current approval without requiring a review.
/interrupt or Ctrl+C interrupts the selected Session.
/steer <text> sends steering; /followup <text> sends a follow-up.
/new cwd|user_home [title] creates a scoped Session in this mux.
/resume <scope> <continuity> <session> opens an explicit saved identity.
/refresh reconciles an unknown outcome; it does not retry a mutation.
/close --yes closes this member and its execution, not the application.
/detach or Ctrl+B d disconnects this terminal; accepted work continues.
Ctrl+D with an empty editor also detaches. Image paste is unavailable.
The installed create/list/attach/close/stop commands manage named muxes.
Application restart restores history and membership, not in-flight execution.
"""


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
        self._detail: TextPager | None = None
        self._detail_key: tuple[object, ...] | None = None
        self._reviewed_key: tuple[object, ...] | None = None
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

    def _approval_key(self) -> tuple[object, ...] | None:
        mux, window = self.shell.state, self.shell.state.active_window
        if (
            mux.snapshot_required
            or window is None
            or not window.pending_interaction_id
            or not window.pending_interaction_text
        ):
            return None
        return (
            mux.attachment_id,
            mux.controller_generation,
            window.member_id,
            window.session_id,
            window.pending_interaction_id,
            window.pending_interaction_text,
        )

    def show_help(self) -> None:
        self._detail, self._detail_key = TextPager("Hosted help", _HELP), None

    def show_approval(self) -> None:
        key = self._approval_key()
        if key is None:
            raise ValueError("no current approval details")
        self._detail = TextPager(
            "Approval details — Esc back, then /approve or /deny", str(key[-1])
        )
        self._detail_key = key

    def approval_presented(self) -> bool:
        key = self._approval_key()
        return key is not None and key == self._reviewed_key

    def dismiss_details(self) -> None:
        self._detail, self._detail_key = None, None

    def _sync_details(self) -> None:
        if self._detail_key is not None and self._detail_key != self._approval_key():
            self._detail = TextPager(
                "Approval expired",
                "Authority or pending action changed. Press Esc to return; inspect the current action again.",
            )
            self._detail_key = self._reviewed_key = None

    def handle_details(self, event: InputEvent) -> bool:
        self._sync_details()
        if self._detail is None:
            return False
        if event.kind == "key" and event.key in {"esc", "escape"}:
            self.dismiss_details()
        else:
            self._detail.handle_input(event)
        return True

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
                    "Approval pending: F2 details; /approve /deny"
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
        self._sync_details()
        rendered = self._detail.render(inner) if self._detail else super().render(inner)
        if (
            self._detail is not None
            and self._detail.fully_presented
            and self._detail_key is not None
        ):
            self._reviewed_key = self._detail_key
        return RenderResult.from_lines(
            (*rendered.lines, row), constraints=constraints, cursor=rendered.cursor
        )
