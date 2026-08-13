from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loushang.harnesstui.conversation.attachments import (
    PromptImageAttachment,
    PromptImageAttachmentOutcome,
)
from loushang.harnesstui.conversation.input import ConversationInputRouter
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.tui import Composer, InputEvent, InputIntent, SurfaceHost


@dataclass(slots=True)
class _ConversationApp:
    composer: Composer = field(default_factory=Composer)
    state: ScreenConversationState = field(default_factory=ScreenConversationState)
    active_surface: object | None = None
    surface_host: SurfaceHost | None = None
    transcript_opened: bool = False

    def open_transcript_reader(self) -> bool:
        self.transcript_opened = True
        return True

    def start_prompt(self, text: str) -> None:
        self.state.start_prompt(text, started_at=1.0)
        self.composer.add_history(text)
        self.composer.clear()

    def queue_followup(self, text: str) -> None:
        self.state.queue_followup(text)

    def queue_steer(self, text: str) -> None:
        self.state.queue_steer(text)


def _attachment(tmp_path: Path, *, name: str = "image") -> PromptImageAttachment:
    path = tmp_path / f"{name}.png"
    return PromptImageAttachment(
        bytes=name.encode(),
        mime_type="image/png",
        path=path,
        display_path=path.name,
        marker=f"@{path.name}",
    )


def test_conversation_input_router_submits_neutral_prompt_attachments(
    tmp_path: Path,
) -> None:
    app = _ConversationApp()
    attachment = _attachment(tmp_path)
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
        prompt_image_stager=lambda: PromptImageAttachmentOutcome(
            kind="attached",
            attachment=attachment,
            mime_type=attachment.mime_type,
        ),
    )

    paste_result = router.handle(InputEvent(kind="key", key="ctrl+v"))
    app.composer.insert_text("describe")
    submit_result = router.handle(InputEvent(kind="key", key="enter"))

    assert paste_result.clipboard_outcome is not None
    assert paste_result.clipboard_outcome.attachment is attachment
    assert submit_result.prompt_text == "@image.png describe"
    assert submit_result.prompt_attachments == (attachment,)
    assert app.state.running is True
    assert app.composer.value == ""


def test_conversation_input_router_preserves_running_followup_priority(
    tmp_path: Path,
) -> None:
    app = _ConversationApp()
    app.start_prompt("question")
    attachment = _attachment(tmp_path)
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
        prompt_image_stager=lambda: PromptImageAttachmentOutcome(
            kind="attached",
            attachment=attachment,
            mime_type=attachment.mime_type,
        ),
    )
    router.handle(InputEvent(kind="key", key="ctrl+v"))
    app.composer.insert_text("later")

    result = router.handle(InputEvent(kind="key", key="alt+enter"))

    assert result.followup_text == "@image.png later"
    assert result.followup_attachments == (attachment,)
    assert result.steer_text is None
    assert app.state.pending_followups == ["@image.png later"]


def test_conversation_input_router_routes_active_surface_before_composer() -> None:
    class _Surface:
        def handle_input(self, event: InputEvent) -> InputIntent:
            assert event.key == "enter"
            return InputIntent(kind="select", text="choice")

    app = _ConversationApp(active_surface=_Surface())
    app.composer.set_text("draft")
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
    )

    result = router.handle(InputEvent(kind="key", key="enter"))

    assert result.surface_intent == InputIntent(kind="select", text="choice")
    assert app.composer.value == "draft"
    assert app.state.running is False


def test_conversation_input_router_keeps_exit_and_local_policy_injected() -> None:
    app = _ConversationApp()
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda text: text == "/quit",
        is_local_command=lambda text: text == "/model",
    )

    app.composer.set_text("/model")
    local_result = router.handle(InputEvent(kind="key", key="enter"))
    app.composer.set_text("/quit")
    exit_result = router.handle(InputEvent(kind="key", key="enter"))

    assert local_result.local_text == "/model"
    assert exit_result.exit_code == 0
    assert app.state.running is False


def test_conversation_input_router_handles_local_command_while_run_is_active() -> None:
    app = _ConversationApp()
    app.start_prompt("question")
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
        is_local_command=lambda text: text == "/agents",
    )
    app.composer.set_text("/agents")

    result = router.handle(InputEvent(kind="key", key="enter"))

    assert result.local_text == "/agents"
    assert result.steer_text is None
    assert result.followup_text is None
    assert app.state.running is True
    assert app.state.pending_steers == []
    assert app.state.pending_followups == []
    assert app.composer.value == ""


def test_conversation_input_router_restores_pending_messages() -> None:
    app = _ConversationApp()
    app.state.queue_steer("first")
    app.state.queue_followup("second")
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
    )

    result = router.handle(InputEvent(kind="key", key="alt+up"))

    assert result.render_requested is True
    assert app.composer.value == "first\nsecond"
    assert app.state.pending_steers == []
    assert app.state.pending_followups == []


def test_conversation_input_router_reports_unconfigured_clipboard_as_unhandled() -> (
    None
):
    app = _ConversationApp()
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert result.render_requested is False
    assert result.clipboard_outcome is None


def test_conversation_input_router_presents_each_clipboard_outcome_once(
    tmp_path: Path,
) -> None:
    app = _ConversationApp()
    attachment = _attachment(tmp_path)
    outcomes = iter(
        (
            PromptImageAttachmentOutcome(
                kind="attached",
                attachment=attachment,
                mime_type=attachment.mime_type,
            ),
            PromptImageAttachmentOutcome(kind="empty"),
        )
    )
    presented: list[tuple[PromptImageAttachmentOutcome, str]] = []
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
        prompt_image_stager=lambda: next(outcomes),
        clipboard_outcome_presenter=lambda outcome: presented.append(
            (outcome, app.composer.value)
        ),
    )

    attached = router.handle(InputEvent(kind="key", key="ctrl+v"))
    empty = router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert [outcome.kind for outcome, _text in presented] == ["attached", "empty"]
    assert presented[0][1] == "@image.png "
    assert attached.clipboard_outcome is presented[0][0]
    assert empty.clipboard_outcome is presented[1][0]
