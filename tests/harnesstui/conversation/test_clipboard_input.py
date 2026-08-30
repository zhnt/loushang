from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import RunLease, resolve_runtime_scope
from loushang.harnesstui.conversation.attachments import (
    DraftStorePolicy,
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
    quota_exceeded_prefix="quota: ",
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setattr("sys.platform", "win32")
    app = _ConversationApp(str(tmp_path))
    assert STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE.status_copy.attached_prefix == (
        "Attached clipboard image: "
    )
    scope = resolve_runtime_scope()
    lease = RunLease.acquire(scope)
    router = bind_clipboard_image_input_router(runtime_scope=scope)(
        app,
        should_exit=lambda _text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "shared",
    )

    result = router.handle(InputEvent(kind="key", key="alt+v"))

    expected = next(
        (runtime_dir / "runs").glob("*/drafts/clipboard/clipboard-shared.png")
    )
    assert expected.read_bytes() == b"png"
    assert isinstance(result, ConversationClipboardResult)
    assert app.composer.value == "@clipboard/clipboard-shared.png "
    assert app.state.status_message == (
        "Attached clipboard image: clipboard/clipboard-shared.png"
    )
    assert expected.parents[2] == scope.run_dir
    assert (scope.run_dir / ".lease").is_file()

    router.dispose()

    assert scope.run_dir.exists()
    assert not expected.exists()
    lease.close()
    assert not scope.run_dir.exists()


def test_standard_clipboard_binding_resolves_runtime_environment_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_runtime = tmp_path / "first-runtime"
    second_runtime = tmp_path / "second-runtime"
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(first_runtime))
    scope = resolve_runtime_scope()
    lease = RunLease.acquire(scope)
    app = _ConversationApp(str(tmp_path))
    router = bind_clipboard_image_input_router(runtime_scope=scope)(
        app,
        should_exit=lambda _text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "once",
    )

    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(second_runtime))
    router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert next(
        (first_runtime / "runs").glob("*/drafts/clipboard/clipboard-once.png")
    ).read_bytes() == b"png"
    assert not second_runtime.exists()
    router.dispose()
    lease.close()


def test_standard_clipboard_binding_accepts_injected_runtime_scope(
    tmp_path: Path,
) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "injected")},
        home=tmp_path / "home",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="a" * 32)
    lease = RunLease.acquire(scope)
    app = _ConversationApp(str(tmp_path))
    router = bind_clipboard_image_input_router()(
        app,
        should_exit=lambda _text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "injected",
        runtime_scope=scope,
    )

    router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert (
        scope.drafts / "clipboard" / "clipboard-injected.png"
    ).read_bytes() == b"png"
    router.dispose()
    assert scope.run_dir.exists()
    lease.close()
    assert not scope.run_dir.exists()


def test_standard_clipboard_binding_rejects_oversized_image_before_disk(
    tmp_path: Path,
) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="b" * 32)
    lease = RunLease.acquire(scope)
    profile = replace(
        STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE,
        draft_policy=DraftStorePolicy(
            max_attachments=2,
            max_attachment_bytes=4,
            max_total_bytes=8,
        ),
    )
    app = _ConversationApp(str(tmp_path))
    router = bind_clipboard_image_input_router(profile)(
        app,
        should_exit=lambda _text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"large",
            mime_type="image/png",
        ),
        runtime_scope=scope,
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert isinstance(result, ConversationClipboardResult)
    assert result.outcome.kind == "quota_exceeded"
    assert app.state.status_message == (
        "Clipboard image limit reached: image is 5 bytes; "
        "per-image limit is 4 bytes"
    )
    assert not scope.drafts.exists()
    router.dispose()
    lease.close()


def test_clipboard_image_uses_the_conversation_action_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.platform", "win32")
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

    ignored_ctrl = router.handle(InputEvent(kind="key", key="ctrl+v"))
    ignored_alt = router.handle(InputEvent(kind="key", key="alt+v"))
    attached = router.handle(InputEvent(kind="key", key="ctrl+p"))

    assert ignored_ctrl.kind == "ignored"
    assert ignored_alt.kind == "ignored"
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
                kind="quota_exceeded",
                error_message="too many bytes",
            ),
            "quota: too many bytes",
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

    fallback = replace(_COPY, quota_exceeded_prefix=None)
    assert fallback.message(cases[-2][0]) == "write: too many bytes"


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
