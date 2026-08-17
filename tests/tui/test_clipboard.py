from __future__ import annotations

from loushang.tui.clipboard import ClipboardCopyResult, copy_to_clipboard


def test_copy_to_clipboard_uses_platform_command_with_text_stdin() -> None:
    calls: list[tuple[str, tuple[str, ...], str]] = []

    def runner(
        command: str,
        args: tuple[str, ...],
        *,
        input_text: str,
        timeout_seconds: float,
    ) -> ClipboardCopyResult:
        del timeout_seconds
        calls.append((command, args, input_text))
        return ClipboardCopyResult(ok=True, command=command)

    result = copy_to_clipboard(
        "hello",
        env={"WAYLAND_DISPLAY": "wayland-1"},
        runner=runner,
        platform="linux",
    )

    assert result.ok is True
    assert result.command == "wl-copy"
    assert calls == [("wl-copy", tuple(), "hello")]


def test_text_clipboard_is_owned_by_tui() -> None:
    assert ClipboardCopyResult.__module__ == "loushang.tui.clipboard"
    assert copy_to_clipboard.__module__ == "loushang.tui.clipboard"
