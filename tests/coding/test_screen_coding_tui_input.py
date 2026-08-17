from __future__ import annotations

from loushang.tui import CompletionItem, InputEvent, InputIntent
from loushang.tui.transcript import UserPromptRecord


def test_screen_input_router_idle_enter_starts_prompt_and_clears_composer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.composer.set_text("你好")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="enter")
    )

    assert result.prompt_text == "你好"
    assert app.composer.value == ""
    assert app.state.running is True
    assert isinstance(app.state.records[0], UserPromptRecord)
    assert app.state.records[0].text == "你好"


def test_screen_input_router_running_enter_queues_steer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.start_prompt("当前代码有啥？", started_at=10.0)
    app.composer.set_text("请用中文")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="enter")
    )

    assert result.prompt_text is None
    assert result.steer_text == "请用中文"
    assert app.composer.value == ""
    assert app.state.pending_steers == ["请用中文"]


def test_screen_input_router_idle_escape_submits_pending_steer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.state.pending_steers.append("你好")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="escape")
    )

    assert result.prompt_text is None
    assert result.steer_text == "你好"
    assert app.state.pending_steers == []


def test_screen_input_router_idle_interrupt_message_prefers_pending_steer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.state.pending_steers.append("你好")
    app.state.interruption_message = (
        "Conversation interrupted - tell the model what to do differently."
    )
    app.composer.set_text("草稿")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="escape")
    )

    assert result.steer_text == "你好"
    assert app.state.pending_steers == []
    assert app.composer.value == "草稿"


def test_screen_input_router_running_alt_enter_queues_followup() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.start_prompt("当前代码有啥？", started_at=10.0)
    app.composer.set_text("继续")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="alt+enter")
    )

    assert result.followup_text == "继续"
    assert app.composer.value == ""
    assert app.state.pending_followups == ["继续"]


def test_screen_input_router_escape_closes_completion_before_running_abort() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.start_prompt("当前代码有啥？", started_at=10.0)
    app.composer.set_text("/he")
    app.composer.set_completion_items((CompletionItem(value="/help", label="/help"),))

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="escape")
    )

    assert result.abort_requested is False
    assert app.state.running is True
    assert app.composer.value == "/he"
    assert not app.composer.has_completions


def test_screen_input_router_enter_applies_slash_completion_before_submit() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.composer.set_text("/mo")
    app.composer.set_completion_items((CompletionItem(value="/model", label="/model"),))

    result = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        is_local_command=lambda text: text == "/model",
    ).handle(InputEvent(kind="key", key="enter"))

    assert result.local_text == "/model"
    assert app.composer.value == ""


def test_screen_input_router_restores_queued_messages_to_composer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.queue_steer("先回答")
    app.queue_followup("再继续")

    build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="alt+up")
    )

    assert app.state.pending_steers == []
    assert app.state.pending_followups == []
    assert app.composer.value == "先回答\n再继续"


def test_screen_input_router_uses_configured_editor_keybindings() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.composer.set_text("ab")
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        keybindings={
            "tui.editor.cursorLeft": ("alt+h",),
            "tui.editor.deleteCharForward": ("alt+x",),
        },
    )

    router.handle(InputEvent(kind="key", key="alt+h"))
    router.handle(InputEvent(kind="key", key="alt+x"))

    assert app.composer.value == "a"


def test_screen_input_router_jump_mode_moves_to_next_or_previous_character() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.composer.set_text("abc def abc")
    app.composer.move_to_line_start()
    router = build_screen_input_router(app, should_exit=lambda text: False)

    assert router.handle(InputEvent(kind="key", key="ctrl+]")).render_requested is True
    router.handle(InputEvent(kind="text", text="d"))
    router.handle(InputEvent(kind="key", key="delete"))
    assert app.composer.value == "abc ef abc"

    router.handle(InputEvent(kind="key", key="ctrl+alt+]"))
    router.handle(InputEvent(kind="text", text="a"))
    router.handle(InputEvent(kind="key", key="delete"))
    assert app.composer.value == "bc ef abc"


def test_screen_input_router_visual_up_down_uses_configured_width() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui import RenderConstraints

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.composer.set_text("abcd efgh ij")
    router = build_screen_input_router(app, should_exit=lambda text: False, width=7)

    router.handle(InputEvent(kind="key", key="up"))

    result = app.composer.render(RenderConstraints(width=7, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 4)


def test_screen_input_router_resize_updates_visual_movement_width() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui import RenderConstraints

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    app.composer.set_text("abcd efgh ij")
    router = build_screen_input_router(app, should_exit=lambda text: False)

    router.handle(InputEvent(kind="resize", columns=7, rows=12))
    router.handle(InputEvent(kind="key", key="up"))

    result = app.composer.render(RenderConstraints(width=7, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 4)


def test_screen_input_router_pastes_clipboard_image_as_attachment(tmp_path) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui.clipboard_image import ClipboardImage

    payload = b"fake png bytes"
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=payload, mime_type="image/png"
        ),
        clipboard_image_dir=tmp_path / ".clips",
        clipboard_image_name_factory=lambda: "abc123",
    )

    paste_result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    saved_path = tmp_path / ".clips" / "clipboard-abc123.png"
    assert paste_result.render_requested is True
    assert saved_path.read_bytes() == payload
    assert app.composer.value == "@.clips/clipboard-abc123.png "
    assert (
        app.state.status_message
        == "Attached clipboard image: .clips/clipboard-abc123.png"
    )

    app.composer.insert_text("describe it")
    submit_result = router.handle(InputEvent(kind="key", key="enter"))

    assert submit_result.prompt_text == "@.clips/clipboard-abc123.png describe it"
    assert submit_result.prompt_attachments is not None
    assert submit_result.prompt_attachments[0].mime_type == "image/png"
    assert submit_result.prompt_attachments[0].bytes == payload


def test_screen_input_router_reports_empty_clipboard_image_without_editing(
    tmp_path,
) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=lambda: None,
        clipboard_image_dir=tmp_path / ".clips",
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert result.render_requested is True
    assert app.composer.value == ""
    assert app.state.status_message == "No clipboard image found."
    assert not (tmp_path / ".clips").exists()


def test_screen_input_router_reports_unsupported_clipboard_image_without_writing(
    tmp_path,
) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui.clipboard_image import ClipboardImage

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"svg",
            mime_type=" IMAGE/SVG+XML ",
        ),
        clipboard_image_dir=tmp_path / ".clips",
        clipboard_image_name_factory=lambda: "unused",
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert result.render_requested is True
    assert app.composer.value == ""
    assert app.state.status_message == "Unsupported clipboard image type: image/svg+xml"
    assert not (tmp_path / ".clips").exists()


def test_screen_input_router_reports_clipboard_image_read_failure_without_crashing(
    tmp_path,
) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    def fail_to_read_clipboard_image():
        raise RuntimeError("clipboard command failed")

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=fail_to_read_clipboard_image,
        clipboard_image_dir=tmp_path / ".clips",
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert result.render_requested is True
    assert app.composer.value == ""
    assert (
        app.state.status_message
        == "Unable to read clipboard image: clipboard command failed"
    )
    assert not (tmp_path / ".clips").exists()


def test_screen_input_router_reports_clipboard_image_write_failure_without_crashing(
    tmp_path,
) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui.clipboard_image import ClipboardImage

    blocked_path = tmp_path / "not-a-directory"
    blocked_path.write_text("file", encoding="utf-8")
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"PNG", mime_type="image/png"
        ),
        clipboard_image_dir=blocked_path,
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    assert result.render_requested is True
    assert app.composer.value == ""
    assert app.state.status_message.startswith("Unable to attach clipboard image:")


def test_screen_input_router_sanitizes_clipboard_image_filename_token(tmp_path) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui.clipboard_image import ClipboardImage

    payload = b"PNG"
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=payload, mime_type="image/png"
        ),
        clipboard_image_dir=tmp_path / ".clips",
        clipboard_image_name_factory=lambda: "../bad name:\n",
    )

    result = router.handle(InputEvent(kind="key", key="ctrl+v"))

    saved_path = tmp_path / ".clips" / "clipboard-bad_name.png"
    assert result.render_requested is True
    assert saved_path.read_bytes() == payload
    assert app.composer.value == "@.clips/clipboard-bad_name.png "
    assert (
        app.state.status_message
        == "Attached clipboard image: .clips/clipboard-bad_name.png"
    )


def test_screen_input_router_orders_clipboard_images_by_marker_position(
    tmp_path,
) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui.clipboard_image import ClipboardImage

    images = iter(
        [
            ClipboardImage(bytes=b"first", mime_type="image/png"),
            ClipboardImage(bytes=b"second", mime_type="image/png"),
        ]
    )
    names = iter(["first", "second"])
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=lambda: next(images),
        clipboard_image_dir=tmp_path / ".clips",
        clipboard_image_name_factory=lambda: next(names),
    )

    router.handle(InputEvent(kind="key", key="ctrl+v"))
    router.handle(InputEvent(kind="key", key="ctrl+v"))
    app.composer.set_text(
        "@.clips/clipboard-second.png @.clips/clipboard-first.png compare"
    )

    submit_result = router.handle(InputEvent(kind="key", key="enter"))

    assert submit_result.prompt_attachments is not None
    assert [image.bytes for image in submit_result.prompt_attachments] == [
        b"second",
        b"first",
    ]


def test_screen_input_router_uses_default_workspace_clipboard_directory_and_clears_registry(
    tmp_path,
) -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui.clipboard_image import ClipboardImage

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd=str(tmp_path),
        branch="main",
        session_label="abcd",
        now=lambda: 12.0,
    )
    router = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        clipboard_image_reader=lambda: ClipboardImage(
            bytes=b"png",
            mime_type="image/png",
        ),
        clipboard_image_name_factory=lambda: "image",
    )

    router.handle(InputEvent(kind="key", key="ctrl+v"))

    marker = "@.loushang/clipboard/clipboard-image.png"
    saved_path = tmp_path / ".loushang" / "clipboard" / "clipboard-image.png"
    assert saved_path.read_bytes() == b"png"
    assert app.composer.value == f"{marker} "

    first_submit = router.handle(InputEvent(kind="key", key="enter"))
    assert first_submit.prompt_attachments is not None

    app.complete_run(elapsed_seconds=0.1)
    app.composer.set_text(f"reuse {marker}")
    second_submit = router.handle(InputEvent(kind="key", key="enter"))

    assert second_submit.prompt_attachments is None
    assert saved_path.read_bytes() == b"png"


def test_screen_input_router_exit_command_returns_exit_code_without_transcript() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.composer.set_text("/quit")

    result = build_screen_input_router(
        app, should_exit=lambda text: text in {"/quit", "/exit"}
    ).handle(InputEvent(kind="key", key="enter"))

    assert result.exit_code == 0
    assert app.state.records == []


def test_screen_input_router_routes_local_slash_command_without_starting_prompt() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.composer.set_text("/model")

    result = build_screen_input_router(
        app,
        should_exit=lambda text: False,
        is_local_command=lambda text: text == "/model",
    ).handle(InputEvent(kind="key", key="enter"))

    assert result.local_text == "/model"
    assert app.composer.value == ""
    assert app.state.records == []
    assert app.state.running is False


def test_screen_input_router_routes_active_surface_before_composer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router

    class Surface:
        def handle_input(self, event: InputEvent) -> InputIntent | None:
            assert event.key == "enter"
            return InputIntent(kind="select", text="chosen")

        def render(self, _constraints):
            raise AssertionError("not rendered")

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.active_surface = Surface()
    app.composer.set_text("draft")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="enter")
    )

    assert result.surface_intent == InputIntent(kind="select", text="chosen")
    assert app.composer.value == "draft"
    assert app.state.records == []


def test_screen_input_router_routes_runtime_overlay_before_composer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.harnesstui.surface.view import ScreenSurfaceView
    from loushang.tui import CommandSurface, SelectItem, Surface, SurfaceHost

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    view = ScreenSurfaceView(
        title="Commands",
        purpose="command",
        content=CommandSurface([SelectItem("/model", value="/model")]),
    )
    app.surface_host.open_surface(Surface(renderable=view, focus_target=view))
    app.composer.set_text("draft")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="enter")
    )

    assert result.surface_intent == InputIntent(kind="command", text="/model")
    assert app.composer.value == "draft"
    assert app.state.records == []


def test_screen_input_router_ctrl_o_opens_transcript_reader_overlay() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
    from loushang.tui import SurfaceHost
    from loushang.tui.transcript import AssistantMessageRecord

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.state.records.append(AssistantMessageRecord("answer"))
    app.composer.set_text("draft")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="ctrl+o")
    )

    assert result.render_requested is True
    assert result.surface_intent is None
    assert len(app.surface_host.entries) == 1
    assert isinstance(
        app.surface_host.entries[0].surface.renderable, TranscriptReaderSurface
    )
    assert app.composer.value == "draft"
    assert app.state.records[-1] == AssistantMessageRecord("answer")


def test_screen_input_router_ctrl_o_fallback_reader_includes_streaming_assistant_draft() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
    from loushang.tui import RenderConstraints, SurfaceHost, strip_control_sequences
    from loushang.tui.transcript import AssistantMessageRecord, UserPromptRecord

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
        ),
        reason="test",
    )
    app.begin_run(started_at=3.0)
    app.append_assistant_chunk("streaming fallback draft")

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="ctrl+o")
    )

    assert result.render_requested is True
    assert app.surface_host.entries
    reader = app.surface_host.entries[0].surface.renderable
    assert isinstance(reader, TranscriptReaderSurface)
    reader.raw_mode = True
    rendered = reader.render(RenderConstraints(width=100, max_height=12))
    lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert lines[0] == "Transcript window · raw"
    assert any("streaming fallback draft" in line for line in lines)


def test_screen_input_router_ctrl_o_uses_transcript_source_factory() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
    from loushang.harnesstui.conversation.source import TranscriptSnapshot
    from loushang.tui import SurfaceHost
    from loushang.tui.transcript import AssistantMessageRecord

    class _Source:
        def snapshot(self) -> TranscriptSnapshot:
            return TranscriptSnapshot(
                records=(AssistantMessageRecord("full session answer"),),
                complete=True,
                source_label="Full transcript",
            )

        def recent_assistant_texts(self) -> tuple[str, ...]:
            return ("full session answer",)

    source = _Source()
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.transcript_source_factory = lambda: source
    app.state.records.append(AssistantMessageRecord("active window answer"))

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="ctrl+o")
    )

    assert result.render_requested is True
    assert app.surface_host.entries
    reader = app.surface_host.entries[0].surface.renderable
    assert isinstance(reader, TranscriptReaderSurface)
    assert reader.source is source


def test_screen_input_router_ctrl_o_session_reader_includes_running_tool_record() -> (
    None
):
    from dataclasses import dataclass

    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.harnesstui.conversation.agent_binding import (
        agent_session_history_records,
    )
    from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
    from loushang.harnesstui.conversation.source import MaterializedTranscriptSource
    from loushang.tui import RenderConstraints, SurfaceHost, strip_control_sequences
    from loushang.tui.transcript import (
        AssistantMessageRecord,
        ToolExecutionRecord,
        UserPromptRecord,
    )

    @dataclass(slots=True)
    class _Session:
        messages: list[object]

    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="full question")],
                timestamp=1.0,
            ),
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="full answer")],
                api="openai",
                provider="moonshot",
                model="kimi",
                response_id=None,
                usage=Usage(
                    input=0,
                    output=0,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=0,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            ),
        ]
    )
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
            ToolExecutionRecord(
                name="bash run-tests",
                state="running",
                elapsed_seconds=0.1,
                output="live output",
            ),
        ),
        reason="test",
    )
    app.begin_run(started_at=3.0)
    app.transcript_source_factory = lambda: MaterializedTranscriptSource(
        materialize_records=lambda: agent_session_history_records(session.messages),
        active_window_state=app.state,
    )

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="ctrl+o")
    )

    assert result.render_requested is True
    assert app.surface_host.entries
    reader = app.surface_host.entries[0].surface.renderable
    assert isinstance(reader, TranscriptReaderSurface)
    reader.raw_mode = True
    rendered = reader.render(RenderConstraints(width=100, max_height=12))
    lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert any("Tool: bash run-tests running in 0.10s" in line for line in lines)
    assert any("live output" in line for line in lines)


def test_screen_input_router_ctrl_o_session_reader_includes_streaming_assistant_draft() -> (
    None
):
    from dataclasses import dataclass

    from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.harnesstui.conversation.agent_binding import (
        agent_session_history_records,
    )
    from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
    from loushang.harnesstui.conversation.source import MaterializedTranscriptSource
    from loushang.tui import RenderConstraints, SurfaceHost, strip_control_sequences
    from loushang.tui.transcript import AssistantMessageRecord, UserPromptRecord

    @dataclass(slots=True)
    class _Session:
        messages: list[object]

    session = _Session(
        messages=[
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="full question")],
                timestamp=1.0,
            ),
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="full answer")],
                api="openai",
                provider="moonshot",
                model="kimi",
                response_id=None,
                usage=Usage(
                    input=0,
                    output=0,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=0,
                    cost={},
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=2.0,
            ),
        ]
    )
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.replace_transcript_window(
        (
            UserPromptRecord("full question"),
            AssistantMessageRecord("full answer", stable=True),
        ),
        reason="test",
    )
    app.begin_run(started_at=3.0)
    app.append_assistant_chunk("streaming draft")
    app.transcript_source_factory = lambda: MaterializedTranscriptSource(
        materialize_records=lambda: agent_session_history_records(session.messages),
        active_window_state=app.state,
    )

    result = build_screen_input_router(app, should_exit=lambda text: False).handle(
        InputEvent(kind="key", key="ctrl+o")
    )

    assert result.render_requested is True
    assert app.surface_host.entries
    reader = app.surface_host.entries[0].surface.renderable
    assert isinstance(reader, TranscriptReaderSurface)
    reader.raw_mode = True
    rendered = reader.render(RenderConstraints(width=100, max_height=12))
    lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)
    assert lines[0] == "Full transcript + live window · raw"
    assert any("streaming draft" in line for line in lines)


def test_screen_input_router_reader_strict_modal_consumes_tab_without_completion() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui import SurfaceHost
    from loushang.tui.transcript import AssistantMessageRecord

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.state.records.append(AssistantMessageRecord("answer"))
    app.composer.set_text("/mo")
    app.composer.set_completion_items((CompletionItem(value="/model", label="/model"),))
    router = build_screen_input_router(app, should_exit=lambda text: False)

    router.handle(InputEvent(kind="key", key="ctrl+o"))
    result = router.handle(InputEvent(kind="key", key="tab"))

    assert result.render_requested is True
    assert result.surface_intent is None
    assert len(app.surface_host.entries) == 1
    assert app.composer.value == "/mo"
    assert app.composer.has_completions


def test_screen_input_router_reader_ctrl_c_closes_then_text_routes_to_composer() -> (
    None
):
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.tui import SurfaceHost
    from loushang.tui.transcript import AssistantMessageRecord

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.state.records.append(AssistantMessageRecord("answer"))
    router = build_screen_input_router(app, should_exit=lambda text: False)

    router.handle(InputEvent(kind="key", key="ctrl+o"))
    close_result = router.handle(InputEvent(kind="key", key="ctrl+c"))
    text_result = router.handle(InputEvent(kind="text", text="x"))

    assert close_result.surface_intent == InputIntent(kind="surface_close")
    assert app.surface_host.entries == []
    assert text_result.render_requested is True
    assert app.composer.value == "x"


def test_screen_input_router_reader_page_up_scrolls_without_moving_composer() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp
    from loushang.coding.ui.screen_input import build_screen_input_router
    from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
    from loushang.tui import RenderConstraints, SurfaceHost
    from loushang.tui.transcript import AssistantMessageRecord

    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        now=lambda: 10.0,
    )
    app.surface_host = SurfaceHost()
    app.state.records.append(
        AssistantMessageRecord("\n".join(f"line {index}" for index in range(12)))
    )
    app.composer.set_text("one\ntwo\nthree")
    app.composer.move_to_line_start()
    cursor_before = app.composer.render(
        RenderConstraints(width=20, max_height=5)
    ).cursor
    router = build_screen_input_router(
        app, should_exit=lambda text: False, width=20, height=5
    )

    router.handle(InputEvent(kind="key", key="ctrl+o"))
    assert app.surface_host.entries
    reader = app.surface_host.entries[0].surface.renderable
    assert isinstance(reader, TranscriptReaderSurface)
    reader.render(RenderConstraints(width=40, max_height=5))
    tail_offset = reader.scroll_offset

    result = router.handle(InputEvent(kind="key", key="pageUp"))

    assert result.render_requested is True
    assert reader.scroll_offset < tail_offset
    assert app.composer.value == "one\ntwo\nthree"
    assert (
        app.composer.render(RenderConstraints(width=20, max_height=5)).cursor
        == cursor_before
    )
