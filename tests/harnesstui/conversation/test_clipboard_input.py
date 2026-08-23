from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loushang.harnesstui.conversation.attachments import (
    PromptImageAttachment,
    PromptImageAttachmentOutcome,
)
from loushang.harnesstui.conversation.clipboard_policy import (
    STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE,
)
from loushang.harnesstui.conversation.input import (
    ClipboardImageInputProfile,
    ClipboardImageStatusCopy,
    ConversationClipboardResult,
    ConversationFollowupResult,
    ConversationInputRouterFactoryPort,
    bind_clipboard_image_input_router,
)
from loushang.harnesstui.conversation.input_policy import ConversationInputPolicy
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


def _standard_factory(
    factory: ConversationInputRouterFactoryPort,
) -> ConversationInputRouterFactoryPort:
    return factory


def test_clipboard_builder_satisfies_standard_router_factory_contract() -> None:
    app = _ConversationApp("/repo")
    factory = _standard_factory(_builder())

    router = factory(
        app=app,
        should_exit=lambda _text: False,
        is_local_command=lambda _text: False,
        keybindings=None,
        width=80,
        height=12,
    )

    result = router.handle(InputEvent(kind="text", text="hello"))
    assert result.kind == "handled"
    assert app.composer.value == "hello"


def test_standard_clipboard_image_profile_is_harnesstui_owned(
    tmp_path: Path,
) -> None:
    app = _ConversationApp(str(tmp_path))
    assert STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE.status_copy.attached_prefix == (
        "Attached clipboard image: "
    )
    router = bind_clipboard_image_input_router()(
        app,
        should_exit=lambda _text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "shared",
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    expected = tmp_path / ".loushang" / "clipboard" / "clipboard-shared.png"
    assert expected.read_bytes() == b"png"
    assert isinstance(result, ConversationClipboardResult)
    assert app.composer.value == "@.loushang/clipboard/clipboard-shared.png "
    assert app.state.status_message == (
        "Attached clipboard image: .loushang/clipboard/clipboard-shared.png"
    )


def test_clipboard_image_uses_the_conversation_action_override(
    tmp_path: Path,
) -> None:
    app = _ConversationApp(str(tmp_path))
    router = _builder()(
        app,
        should_exit=lambda _text: False,
        keybindings={"conversation.input.pasteImage": ("ctrl+p",)},
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "override",
    )

    ignored = router.handle(InputEvent(kind="key", key="ctrl+v"))
    attached = router.handle(InputEvent(kind="key", key="ctrl+p"))

    assert ignored.kind == "ignored"
    assert isinstance(attached, ConversationClipboardResult)


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
    assert replacement.state.status_message == "attached: images/clipboard-sample.png"
    assert original.state.status_message is None
    assert isinstance(result, ConversationClipboardResult)
    assert result.outcome.attachment is not None
    assert result.outcome.attachment.path == expected


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


def test_clipboard_image_input_binding_closes_over_router_policy() -> None:
    app = _ConversationApp("/workspace")
    app.start_prompt("running")
    app.composer.set_text("later")
    router = bind_clipboard_image_input_router(
        ClipboardImageInputProfile(
            directory=lambda current: Path(current.state.cwd) / "images",
            display_root=lambda current: Path(current.state.cwd),
            status_copy=_COPY,
        ),
        policy=ConversationInputPolicy(primary_running_submit="follow_up"),
    )(
        app,
        should_exit=lambda _text: False,
    )

    result = router.handle(InputEvent(kind="key", key="enter"))

    assert result == ConversationFollowupResult(text="later")
    assert app.state.pending_followups == ["later"]
