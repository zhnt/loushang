from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.harnesstui.conversation.attachments import (
    PromptImageAttachment,
    PromptImageAttachmentOutcome,
)
from loushang.harnesstui.conversation.input import (
    ConversationClipboardResult,
    ConversationExitResult,
    ConversationFollowupResult,
    ConversationInputHandled,
    ConversationInputIgnored,
    ConversationInputRouter,
    ConversationLocalResult,
    ConversationPromptResult,
    ConversationSurfaceResult,
)
from loushang.harnesstui.conversation.input_policy import (
    CONVERSATION_FOLLOW_UP_ACTION,
    CONVERSATION_PASTE_IMAGE_ACTION,
    CONVERSATION_QUEUE_EDIT_LAST_ACTION,
    ConversationInputCapabilities,
    ConversationInputPolicy,
    conversation_keybinding_manager,
)
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


def test_conversation_keybinding_catalog_owns_conversation_actions() -> None:
    manager = conversation_keybinding_manager()

    assert manager.keys_for(CONVERSATION_FOLLOW_UP_ACTION) == ("alt+enter",)
    assert manager.keys_for(CONVERSATION_PASTE_IMAGE_ACTION) == ("ctrl+v",)
    assert manager.keys_for(CONVERSATION_QUEUE_EDIT_LAST_ACTION) == ("alt+up",)
    assert manager.keys_for("app.clipboard.pasteImage") == ()


def test_conversation_keybinding_catalog_is_idempotent_for_bound_managers() -> None:
    manager = conversation_keybinding_manager()

    assert conversation_keybinding_manager(manager) is manager


def _attachment(tmp_path: Path, *, name: str = "image") -> PromptImageAttachment:
    path = tmp_path / f"{name}.png"
    return PromptImageAttachment(
        bytes=name.encode(),
        mime_type="image/png",
        path=path,
        display_path=path.name,
        marker=f"@{path.name}",
    )


def test_conversation_input_results_are_discriminated_and_payload_valid() -> None:
    from loushang.harnesstui.conversation.input import (
        ConversationAbortResult,
        ConversationClipboardResult,
        ConversationExitResult,
        ConversationFollowupResult,
        ConversationInputHandled,
        ConversationInputIgnored,
        ConversationLocalResult,
        ConversationPromptResult,
        ConversationSteerResult,
        ConversationSurfaceResult,
    )

    assert ConversationInputHandled().kind == "handled"
    assert ConversationInputHandled().render_requested is True
    assert ConversationInputIgnored().kind == "ignored"
    assert ConversationInputIgnored().render_requested is False
    assert ConversationPromptResult(text="prompt").kind == "prompt"
    assert ConversationLocalResult(text="/local").kind == "local"
    assert ConversationSteerResult(text="steer").kind == "steer"
    assert ConversationFollowupResult(text="later").kind == "follow_up"
    assert ConversationSurfaceResult(intent=InputIntent(kind="select")).kind == (
        "surface"
    )
    assert ConversationClipboardResult(
        outcome=PromptImageAttachmentOutcome(kind="empty")
    ).kind == "clipboard"
    assert ConversationAbortResult().kind == "abort"
    assert ConversationExitResult(exit_code=7).kind == "exit"

    with pytest.raises(TypeError):
        ConversationPromptResult(text="prompt", exit_code=7)  # type: ignore[call-arg]


def test_conversation_input_result_field_bag_constructor_is_removed() -> None:
    from loushang.harnesstui.conversation.input import ConversationInputResult

    with pytest.raises(TypeError):
        ConversationInputResult(prompt_text="prompt")  # type: ignore[misc]


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

    assert isinstance(paste_result, ConversationClipboardResult)
    assert paste_result.outcome.attachment is attachment
    assert isinstance(submit_result, ConversationPromptResult)
    assert submit_result.text == "@image.png describe"
    assert submit_result.attachments == (attachment,)
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

    assert isinstance(result, ConversationFollowupResult)
    assert result.text == "@image.png later"
    assert result.attachments == (attachment,)
    assert app.state.pending_followups == ["@image.png later"]


def test_conversation_input_router_defaults_running_submit_to_steer() -> None:
    app = _ConversationApp()
    app.start_prompt("question")
    app.composer.set_text("now")
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
    )

    result = router.handle(InputEvent(kind="key", key="enter"))

    assert result.kind == "steer"
    assert app.state.pending_steers == ["now"]


def test_conversation_input_router_falls_back_to_followup_without_steer() -> None:
    app = _ConversationApp()
    app.state.input_capabilities = ConversationInputCapabilities(
        steer=False,
        follow_up=True,
    )
    app.start_prompt("question")
    app.composer.set_text("later")
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
    )

    result = router.handle(InputEvent(kind="key", key="enter"))

    assert result == ConversationFollowupResult(text="later")
    assert app.state.pending_followups == ["later"]


def test_conversation_input_router_uses_configured_followup_action() -> None:
    app = _ConversationApp()
    app.start_prompt("question")
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
        keybindings={"conversation.input.followUp": ("ctrl+enter",)},
    )

    app.composer.set_text("line")
    newline = router.handle(InputEvent(kind="key", key="alt+enter"))
    app.composer.insert_text("later")
    follow_up = router.handle(InputEvent(kind="key", key="ctrl+enter"))

    assert isinstance(newline, ConversationInputHandled)
    assert follow_up == ConversationFollowupResult(text="line\nlater")
    assert app.state.pending_followups == ["line\nlater"]


def test_conversation_input_router_accepts_a_product_primary_submit_override() -> None:
    app = _ConversationApp()
    app.start_prompt("question")
    app.composer.set_text("later")
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
        policy=ConversationInputPolicy(primary_running_submit="follow_up"),
    )

    result = router.handle(InputEvent(kind="key", key="enter"))

    assert result == ConversationFollowupResult(text="later")


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

    assert isinstance(result, ConversationSurfaceResult)
    assert result.intent == InputIntent(kind="select", text="choice")
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

    assert local_result == ConversationLocalResult(text="/model")
    assert exit_result == ConversationExitResult(exit_code=0)
    assert app.state.running is False


def test_conversation_input_router_translates_shared_prompt_editing_to_handled() -> None:
    app = _ConversationApp()
    app.composer.add_history("history")
    app.composer.insert_text("abc def")
    app.composer.move_to_line_start()
    router = ConversationInputRouter(
        app=app,
        should_exit=lambda _text: False,
        width=7,
        height=3,
    )

    jump = router.handle(InputEvent(kind="key", key="ctrl+]"))
    jump_text = router.handle(InputEvent(kind="text", text="d"))
    paste = router.handle(InputEvent(kind="paste", text="!"))
    page = router.handle(InputEvent(kind="key", key="pageDown"))

    app.composer.clear()
    history = router.handle(InputEvent(kind="key", key="up"))

    assert all(
        isinstance(result, ConversationInputHandled)
        for result in (jump, jump_text, paste, page, history)
    )
    assert app.composer.value == "history"


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

    assert result == ConversationLocalResult(text="/agents")
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

    assert isinstance(result, ConversationInputHandled)
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

    assert isinstance(result, ConversationInputIgnored)


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
    assert isinstance(attached, ConversationClipboardResult)
    assert isinstance(empty, ConversationClipboardResult)
    assert attached.outcome is presented[0][0]
    assert empty.outcome is presented[1][0]
