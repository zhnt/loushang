from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loushang.harnesstui.conversation.attachments import (
    PromptImageAttachment,
    PromptImageAttachmentOutcome,
)
from loushang.harnesstui.conversation.input import (
    ClipboardImageInputProfile,
    ClipboardImageStatusCopy,
    bind_clipboard_image_input_router,
)
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.tui import Composer, InputEvent, SurfaceHost
from loushang.tui.clipboard_image import ClipboardImage


@dataclass(slots=True)
class _ConversationApp:
    cwd: str
    composer: Composer = field(default_factory=Composer)
    state: ScreenConversationState = field(init=False)
    active_surface: object | None = None
    surface_host: SurfaceHost | None = None
    statuses: list[str | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.state = ScreenConversationState(cwd=self.cwd)

    def open_transcript_reader(self) -> bool:
        return False

    def start_prompt(self, text: str) -> None:
        self.state.start_prompt(text, started_at=1.0)
        self.composer.add_history(text)
        self.composer.clear()

    def queue_followup(self, text: str) -> None:
        self.state.queue_followup(text)

    def queue_steer(self, text: str) -> None:
        self.state.queue_steer(text)

    def set_status(self, message: str | None) -> None:
        self.statuses.append(message)


_COPY = ClipboardImageStatusCopy(
    empty="nothing",
    read_error_prefix="read: ",
    unsupported_prefix="unsupported: ",
    write_error_prefix="write: ",
    attached_prefix="attached: ",
    unknown_type="unspecified",
)


def _builder():
    return bind_clipboard_image_input_router(
        ClipboardImageInputProfile(
            directory=lambda app: Path(app.state.cwd) / "images",
            display_root=lambda app: Path(app.state.cwd),
            status_copy=_COPY,
        )
    )


def test_clipboard_image_input_binding_follows_the_replaced_app(
    tmp_path: Path,
) -> None:
    original = _ConversationApp(str(tmp_path / "original"))
    replacement = _ConversationApp(str(tmp_path / "replacement"))
    router = _builder()(
        original,
        should_exit=lambda _text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "sample",
    )

    router.replace_app(replacement)
    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    expected = tmp_path / "replacement" / "images" / "clipboard-sample.png"
    assert expected.read_bytes() == b"png"
    assert not (tmp_path / "original" / "images").exists()
    assert replacement.composer.value == "@images/clipboard-sample.png "
    assert replacement.statuses == ["attached: images/clipboard-sample.png"]
    assert original.statuses == []
    assert result.clipboard_outcome is not None
    assert result.clipboard_outcome.attachment is not None
    assert result.clipboard_outcome.attachment.path == expected


def test_clipboard_image_status_copy_formats_every_neutral_outcome(
    tmp_path: Path,
) -> None:
    attachment = PromptImageAttachment(
        bytes=b"png",
        mime_type="image/png",
        path=tmp_path / "image.png",
        display_path="images/image.png",
        marker="@images/image.png",
    )
    cases = (
        (PromptImageAttachmentOutcome(kind="empty"), "nothing"),
        (
            PromptImageAttachmentOutcome(
                kind="read_error",
                error_message="unavailable",
            ),
            "read: unavailable",
        ),
        (
            PromptImageAttachmentOutcome(
                kind="unsupported",
                mime_type="image/svg+xml",
            ),
            "unsupported: image/svg+xml",
        ),
        (
            PromptImageAttachmentOutcome(kind="unsupported"),
            "unsupported: unspecified",
        ),
        (
            PromptImageAttachmentOutcome(
                kind="write_error",
                error_message="read-only",
            ),
            "write: read-only",
        ),
        (
            PromptImageAttachmentOutcome(
                kind="attached",
                attachment=attachment,
            ),
            "attached: images/image.png",
        ),
    )

    assert tuple(_COPY.message(outcome) for outcome, _expected in cases) == tuple(
        expected for _outcome, expected in cases
    )


def test_clipboard_image_input_binding_forwards_router_policy() -> None:
    app = _ConversationApp("/workspace")
    app.start_prompt("running")
    app.composer.set_text("later")
    router = _builder()(
        app,
        should_exit=lambda _text: False,
        running_submit_mode="follow_up",
    )

    result = router.handle(InputEvent(kind="key", key="enter"))

    assert result.followup_text == "later"
    assert result.steer_text is None
    assert app.state.pending_followups == ["later"]
