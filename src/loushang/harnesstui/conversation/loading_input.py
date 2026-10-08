"""Loading input policy shared by main-loop and borrowed-screen owners."""

from __future__ import annotations

from loushang.harnesstui.conversation.input import (
    ConversationExitResult,
    ConversationInputHandled,
    ConversationInputResult,
    ConversationInputRouter,
)
from loushang.tui.input import InputEvent

LOADING_MESSAGE = "Loading session — you can type; submission is disabled"


class LoadingInputRouter(ConversationInputRouter):
    def handle(self, event: InputEvent) -> ConversationInputResult:
        if event.kind == "key" and event.event_type != "release":
            if event.key in {"ctrl+c", "ctrl+d"}:
                return ConversationExitResult(
                    exit_code=130 if event.key == "ctrl+c" else 0
                )
            if self._keybindings().matches(
                event.key, "tui.input.submit"
            ) or event.key in {"ctrl+v", "alt+v", "tab"}:
                # Gate before submit can clear draft or acquire attachments.
                if not (self.app.state.status_message or "").startswith(
                    "Session unavailable"
                ):
                    self.app.state.status_message = LOADING_MESSAGE
                return ConversationInputHandled()
        return super().handle(event)
