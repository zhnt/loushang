from __future__ import annotations

import subprocess
from io import BytesIO
from pathlib import Path

import pytest


def _tiny_bmp_1x1_red() -> bytes:
    payload = bytearray(58)
    payload[0:2] = b"BM"
    payload[2:6] = (58).to_bytes(4, "little")
    payload[10:14] = (54).to_bytes(4, "little")
    payload[14:18] = (40).to_bytes(4, "little")
    payload[18:22] = (1).to_bytes(4, "little", signed=True)
    payload[22:26] = (1).to_bytes(4, "little", signed=True)
    payload[26:28] = (1).to_bytes(2, "little")
    payload[28:30] = (24).to_bytes(2, "little")
    payload[34:38] = (4).to_bytes(4, "little")
    payload[54] = 0x00
    payload[55] = 0x00
    payload[56] = 0xFF
    return bytes(payload)


def _tiny_tiff_1x1_red() -> bytes:
    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(output, format="TIFF")
    return output.getvalue()


@pytest.mark.parametrize(
    ("platform_name", "env", "expected"),
    [
        ("darwin", {"WAYLAND_DISPLAY": "wayland-0", "WSL_DISTRO_NAME": "Ubuntu"}, "macos"),
        ("linux", {"OS": "Windows_NT", "WSL_DISTRO_NAME": "Ubuntu"}, "wsl"),
        ("win32", {"OS": "Windows_NT"}, "windows"),
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ("linux", {}, "x11"),
    ],
)
def test_clipboard_image_resolves_host_kind(
    platform_name: str,
    env: dict[str, str],
    expected: str,
) -> None:
    from loushang.tui.clipboard_image import _resolve_clipboard_host_kind

    host_kind = _resolve_clipboard_host_kind(
        platform_name=platform_name,
        environment=env,
        probe_proc=False,
    )

    assert host_kind == expected


@pytest.mark.parametrize(
    ("host_kind", "expected"),
    [
        ("macos", ("macos_native", "pngpaste", "injected_reader")),
        ("wsl", ("wl_paste", "xclip", "wsl_powershell", "injected_reader")),
        ("windows", ("windows_powershell", "injected_reader")),
        ("wayland", ("wl_paste", "xclip", "injected_reader")),
        ("x11", ("injected_reader", "xclip")),
    ],
)
def test_clipboard_image_resolves_ordered_backend_plan(
    host_kind: str,
    expected: tuple[str, ...],
) -> None:
    from loushang.tui.clipboard_image import (
        _ClipboardHostKind,
        _resolve_clipboard_image_backends,
    )

    backends = _resolve_clipboard_image_backends(_ClipboardHostKind(host_kind))

    assert tuple(backend.__name__.removeprefix("_read_clipboard_image_via_") for backend in backends) == expected


def test_clipboard_image_reads_wayland_with_xclip_fallback() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    calls: list[tuple[str, tuple[str, ...]]] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append((command, args))
        if command == "wl-paste":
            return CommandResult(ok=False)
        if command == "xclip" and "TARGETS" in args:
            return CommandResult(ok=True, stdout=b"text/plain\nimage/png\n")
        if command == "xclip" and "image/png" in args:
            return CommandResult(ok=True, stdout=b"PNG")
        return CommandResult(ok=False)

    image = read_clipboard_image(
        env={"WAYLAND_DISPLAY": "wayland-0"},
        runner=runner,
        platform_name="linux",
    )

    assert image is not None
    assert image.bytes == b"PNG"
    assert image.mime_type == "image/png"
    assert calls == [
        ("wl-paste", ("--list-types",)),
        ("xclip", ("-selection", "clipboard", "-t", "TARGETS", "-o")),
        ("xclip", ("-selection", "clipboard", "-t", "image/png", "-o")),
    ]


def test_clipboard_image_converts_wayland_bmp_to_png() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        if command == "wl-paste" and "--list-types" in args:
            return CommandResult(ok=True, stdout=b"image/bmp\n")
        if command == "wl-paste" and "image/bmp" in args:
            return CommandResult(ok=True, stdout=_tiny_bmp_1x1_red())
        return CommandResult(ok=False)

    image = read_clipboard_image(
        env={"WAYLAND_DISPLAY": "wayland-0"},
        runner=runner,
        platform_name="linux",
    )

    assert image is not None
    assert image.mime_type == "image/png"
    assert image.bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_clipboard_image_xclip_tries_supported_mimes_when_targets_fail() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    calls: list[tuple[str, tuple[str, ...]]] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append((command, args))
        if command == "xclip" and "TARGETS" in args:
            return CommandResult(ok=False)
        if command == "xclip" and "image/png" in args:
            return CommandResult(ok=True, stdout=b"PNG")
        return CommandResult(ok=False)

    image = read_clipboard_image(env={}, runner=runner, platform_name="linux")

    assert image is not None
    assert image.bytes == b"PNG"
    assert image.mime_type == "image/png"
    assert calls[:2] == [
        ("xclip", ("-selection", "clipboard", "-t", "TARGETS", "-o")),
        ("xclip", ("-selection", "clipboard", "-t", "image/png", "-o")),
    ]


def test_clipboard_image_uses_wsl_powershell_fallback(tmp_path) -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    png_payload = b"\x89PNG\r\n\x1a\npayload"
    calls: list[tuple[str, tuple[str, ...]]] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append((command, args))
        if command in {"wl-paste", "xclip"}:
            return CommandResult(ok=False)
        if command == "wslpath":
            return CommandResult(ok=True, stdout=args[1])
        if command == "powershell.exe":
            env = kwargs.get("env") or {}
            Path(env["LOUSHANG_WSL_CLIPBOARD_IMAGE_PATH"]).write_bytes(png_payload)
            return CommandResult(ok=True, stdout=b"ok\n")
        return CommandResult(ok=False)

    image = read_clipboard_image(
        env={"WSL_DISTRO_NAME": "Ubuntu"},
        runner=runner,
        platform_name="linux",
    )

    assert image is not None
    assert image.bytes == png_payload
    assert image.mime_type == "image/png"
    assert calls[-2][0] == "wslpath"
    assert calls[-1][0] == "powershell.exe"


def test_clipboard_image_prefers_macos_native_png() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    payload = b"\x89PNG\r\n\x1a\nnative"
    calls: list[tuple[str, tuple[str, ...]]] = []
    temporary_directory: Path | None = None

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        nonlocal temporary_directory
        calls.append((command, args))
        if command == "/usr/bin/osascript":
            assert args[:5] == ("-l", "JavaScript", "-s", "he", "-e")
            assert "dataForType" in args[-2]
            assert "availableTypeFromArray" not in args[-2]
            assert args[-2].index('"public.png"') < args[-2].index('"public.tiff"')
            output_path = Path(args[-1])
            temporary_directory = output_path.parent
            output_path.write_bytes(payload)
            return CommandResult(ok=True, stdout=b"LSCB1:OK:PNG\n")
        return CommandResult(ok=False)

    image = read_clipboard_image(env={}, runner=runner, platform_name="darwin")

    assert image is not None
    assert image.bytes == payload
    assert image.mime_type == "image/png"
    assert [command for command, _args in calls] == ["/usr/bin/osascript"]
    assert temporary_directory is not None
    assert not temporary_directory.exists()


def test_clipboard_image_normalizes_macos_native_tiff_to_png() -> None:
    from PIL import Image

    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    tiff_payload = _tiny_tiff_1x1_red()
    calls: list[str] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append(command)
        if command == "/usr/bin/osascript":
            Path(args[-1]).write_bytes(tiff_payload)
            return CommandResult(ok=True, stdout=b"LSCB1:OK:TIFF\n")
        return CommandResult(ok=False)

    image = read_clipboard_image(env={}, runner=runner, platform_name="darwin")

    assert image is not None
    assert image.mime_type == "image/png"
    assert image.bytes.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(image.bytes)) as decoded:
        assert decoded.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    assert calls == ["/usr/bin/osascript"]


def test_clipboard_image_falls_back_to_pngpaste_on_macos() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    calls: list[tuple[str, tuple[str, ...]]] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append((command, args))
        if command == "pngpaste":
            return CommandResult(ok=True, stdout=b"\x89PNG\r\n\x1a\nmac")
        return CommandResult(ok=False)

    image = read_clipboard_image(env={}, runner=runner, platform_name="darwin")

    assert image is not None
    assert image.bytes == b"\x89PNG\r\n\x1a\nmac"
    assert image.mime_type == "image/png"
    assert [command for command, _args in calls] == ["/usr/bin/osascript", "pngpaste"]


def test_clipboard_image_falls_back_to_pngpaste_after_native_empty_result() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    calls: list[str] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append(command)
        if command == "/usr/bin/osascript":
            return CommandResult(ok=True, stdout=b"LSCB1:EMPTY\n")
        if command == "pngpaste":
            return CommandResult(ok=True, stdout=b"\x89PNG\r\n\x1a\nfallback")
        return CommandResult(ok=False)

    image = read_clipboard_image(env={}, runner=runner, platform_name="darwin")

    assert image is not None
    assert image.bytes == b"\x89PNG\r\n\x1a\nfallback"
    assert calls == ["/usr/bin/osascript", "pngpaste"]


def test_clipboard_image_does_not_probe_non_macos_backends_on_macos() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    calls: list[str] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append(command)
        if command == "/usr/bin/osascript":
            return CommandResult(ok=True, stdout=b"LSCB1:EMPTY\n")
        return CommandResult(ok=False)

    image = read_clipboard_image(
        env={"WAYLAND_DISPLAY": "wayland-0", "WSL_DISTRO_NAME": "Ubuntu", "OS": "Windows_NT"},
        runner=runner,
        platform_name="darwin",
    )

    assert image is None
    assert calls == ["/usr/bin/osascript", "pngpaste"]


def test_clipboard_image_rejects_incomplete_macos_native_result_before_fallback() -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    calls: list[str] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append(command)
        if command == "/usr/bin/osascript":
            return CommandResult(ok=True, stdout=b"LSCB1:OK:PNG\n")
        if command == "pngpaste":
            return CommandResult(ok=True, stdout=b"\x89PNG\r\n\x1a\nfallback")
        return CommandResult(ok=False)

    image = read_clipboard_image(env={}, runner=runner, platform_name="darwin")

    assert image is not None
    assert image.bytes == b"\x89PNG\r\n\x1a\nfallback"
    assert calls == ["/usr/bin/osascript", "pngpaste"]


def test_clipboard_image_uses_native_windows_powershell_without_wslpath(tmp_path) -> None:
    from loushang.tui.clipboard_image import CommandResult, read_clipboard_image

    png_payload = b"\x89PNG\r\n\x1a\nwin"
    calls: list[tuple[str, tuple[str, ...]]] = []

    def runner(command: str, args: tuple[str, ...], **kwargs) -> CommandResult:
        calls.append((command, args))
        if command == "powershell.exe":
            env = kwargs.get("env") or {}
            Path(env["LOUSHANG_CLIPBOARD_IMAGE_PATH"]).write_bytes(png_payload)
            return CommandResult(ok=True, stdout=b"ok\n")
        return CommandResult(ok=False)

    image = read_clipboard_image(
        env={"OS": "Windows_NT"},
        runner=runner,
        platform_name="win32",
    )

    assert image is not None
    assert image.bytes == png_payload
    assert image.mime_type == "image/png"
    assert len(calls) == 1
    assert calls[0][0] == "powershell.exe"
    assert calls[0][1][:2] == ("-NoProfile", "-Command")


def test_clipboard_command_runner_forwards_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from loushang.tui import clipboard_image

    captured_environment: dict[str, str] | None = None

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
        nonlocal captured_environment
        captured_environment = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout=b"ok")

    monkeypatch.setattr(clipboard_image.subprocess, "run", fake_run)

    result = clipboard_image._run_command("helper", ("arg",), env={"CLIPBOARD_PATH": "value"})

    assert result == clipboard_image.CommandResult(ok=True, stdout=b"ok")
    assert captured_environment == {"CLIPBOARD_PATH": "value"}
