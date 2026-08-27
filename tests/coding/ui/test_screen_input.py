from __future__ import annotations

from pathlib import Path

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import (
    CODING_SCREEN_RUN_PROFILE,
    build_runtime_screen_input_router,
    build_screen_input_router,
)
from loushang.foundation.runtime_scope import RunLease, resolve_runtime_scope
from loushang.harnesstui.conversation.agent_binding import (
    agent_image_parts_from_prompt_attachments,
)
from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.tui import InputEvent
from loushang.tui.clipboard_image import ClipboardImage


def _app(*, cwd: str = "/repo") -> ScreenCodingTuiApp:
    return ScreenCodingTuiApp(
        model_label="kimi",
        cwd=cwd,
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )


def test_coding_screen_profile_uses_the_standard_input_factory_contract() -> None:
    factory = CODING_SCREEN_RUN_PROFILE.input_router_factory
    assert factory is build_screen_input_router

    router = factory(
        app=_app(),
        should_exit=lambda _text: False,
        is_local_command=lambda _text: False,
        keybindings=None,
        width=80,
        height=24,
    )

    assert router.handle(InputEvent(kind="text", text="hello")).kind == "handled"
    assert CODING_SCREEN_RUN_PROFILE.runtime is not None
    assert (
        CODING_SCREEN_RUN_PROFILE.runtime.input_router_factory
        is build_runtime_screen_input_router
    )


def test_prompt_image_attachments_convert_at_the_agent_boundary() -> None:
    attachment = PromptImageAttachment(
        bytes=b"png",
        mime_type="image/png",
        path=Path("/repo/.loushang/clipboard/image.png"),
        display_path=".loushang/clipboard/image.png",
        marker="@.loushang/clipboard/image.png",
    )

    images = agent_image_parts_from_prompt_attachments((attachment,))

    assert images is not None
    assert images[0].mime_type == "image/png"
    assert images[0].data == "cG5n"


def test_coding_input_binding_follows_a_replaced_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(runtime_dir))
    first_app = _app()
    replacement_app = _app(cwd=str(tmp_path))
    scope = resolve_runtime_scope()
    lease = RunLease.acquire(scope)
    router = build_runtime_screen_input_router(scope)(
        first_app,
        should_exit=lambda _text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "image",
    )
    router.replace_app(replacement_app)

    router.handle(InputEvent(kind="key", key="ctrl+v"))

    expected = next(
        (runtime_dir / "runs").glob("*/drafts/clipboard/clipboard-image.png")
    )
    assert expected.read_bytes() == b"png"
    assert replacement_app.state.status_message == (
        "Attached clipboard image: clipboard/clipboard-image.png"
    )
    router.dispose()
    lease.close()


def test_coding_input_binding_uses_shared_clipboard_status_copy(
    tmp_path: Path,
) -> None:
    def fail_to_read():
        raise RuntimeError("clipboard unavailable")

    cases = (
        (lambda: None, "No clipboard image found."),
        (
            fail_to_read,
            "Unable to read clipboard image: clipboard unavailable",
        ),
        (
            lambda: ClipboardImage(bytes=b"svg", mime_type="image/svg+xml"),
            "Unsupported clipboard image type: image/svg+xml",
        ),
    )

    for index, (reader, expected) in enumerate(cases):
        app = _app(cwd=str(tmp_path / str(index)))
        router = build_screen_input_router(
            app,
            should_exit=lambda _text: False,
            clipboard_image_reader=reader,
            clipboard_image_dir=tmp_path / str(index) / "clips",
        )

        router.handle(InputEvent(kind="key", key="ctrl+v"))

        assert app.state.status_message == expected
