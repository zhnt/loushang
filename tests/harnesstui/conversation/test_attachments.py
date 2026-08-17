from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from loushang.harnesstui.conversation.attachments import (
    PendingPromptImageRegistry,
    PromptImageAttachment,
    persist_clipboard_image,
    stage_clipboard_image,
)
from loushang.tui.clipboard_image import ClipboardImage


def test_persist_clipboard_image_creates_neutral_relative_attachment(tmp_path) -> None:
    payload = b"png bytes"

    attachment = persist_clipboard_image(
        ClipboardImage(bytes=payload, mime_type=" IMAGE/PNG; charset=binary "),
        directory=tmp_path / ".clips",
        display_root=tmp_path,
        name_token="abc123",
    )

    expected_path = tmp_path / ".clips" / "clipboard-abc123.png"
    assert expected_path.read_bytes() == payload
    assert attachment == PromptImageAttachment(
        bytes=payload,
        mime_type="image/png",
        path=expected_path,
        display_path=".clips/clipboard-abc123.png",
        marker="@.clips/clipboard-abc123.png",
    )


def test_persist_clipboard_image_sanitizes_filename_token(tmp_path) -> None:
    attachment = persist_clipboard_image(
        ClipboardImage(bytes=b"jpeg", mime_type="image/jpeg"),
        directory=tmp_path / "images",
        display_root=tmp_path,
        name_token="../bad name:\n",
    )

    assert attachment.path == tmp_path / "images" / "clipboard-bad_name.jpg"
    assert attachment.path.read_bytes() == b"jpeg"
    assert attachment.marker == "@images/clipboard-bad_name.jpg"


def test_persist_clipboard_image_uses_full_path_outside_display_root(tmp_path) -> None:
    directory = tmp_path / "outside"

    attachment = persist_clipboard_image(
        ClipboardImage(bytes=b"gif", mime_type="image/gif"),
        directory=directory,
        display_root=tmp_path / "workspace",
        name_token="image",
    )

    assert attachment.display_path == (directory / "clipboard-image.gif").as_posix()
    assert attachment.marker == f"@{attachment.display_path}"


def test_persist_clipboard_image_rejects_unsupported_mime_before_writing(
    tmp_path,
) -> None:
    directory = tmp_path / "images"

    with pytest.raises(
        ValueError,
        match=r"unsupported clipboard image type: image/svg\+xml",
    ):
        persist_clipboard_image(
            ClipboardImage(bytes=b"svg", mime_type="image/svg+xml"),
            directory=directory,
            display_root=tmp_path,
            name_token="image",
        )

    assert not directory.exists()


def test_prompt_image_attachment_is_immutable(tmp_path) -> None:
    attachment = persist_clipboard_image(
        ClipboardImage(bytes=b"webp", mime_type="image/webp"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="image",
    )

    with pytest.raises(FrozenInstanceError):
        attachment.marker = "@different"  # type: ignore[misc]


def test_pending_registry_selects_images_in_body_marker_order(tmp_path) -> None:
    first = persist_clipboard_image(
        ClipboardImage(bytes=b"first", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="first",
    )
    second = persist_clipboard_image(
        ClipboardImage(bytes=b"second", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="second",
    )
    unused = persist_clipboard_image(
        ClipboardImage(bytes=b"unused", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="unused",
    )
    registry = PendingPromptImageRegistry()
    registry.add(first)
    registry.add(second)
    registry.add(unused)

    selected = registry.select_for_text(
        f"Compare {second.marker} with {first.marker}; ignore the other image."
    )

    assert selected == (second, first)
    assert len(registry) == 3


def test_pending_registry_clear_removes_all_images(tmp_path) -> None:
    attachment = persist_clipboard_image(
        ClipboardImage(bytes=b"png", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="image",
    )
    registry = PendingPromptImageRegistry()
    registry.add(attachment)

    registry.clear()

    assert len(registry) == 0
    assert registry.select_for_text(attachment.marker) == ()


def test_stage_clipboard_image_returns_attached_outcome(tmp_path) -> None:
    outcome = stage_clipboard_image(
        lambda: ClipboardImage(bytes=b"png", mime_type="image/png"),
        directory=tmp_path / "images",
        display_root=tmp_path,
        name_token="image",
    )

    assert outcome.kind == "attached"
    assert outcome.mime_type == "image/png"
    assert outcome.error_message == ""
    assert outcome.attachment is not None
    assert outcome.attachment.marker == "@images/clipboard-image.png"


@pytest.mark.parametrize(
    "image", (None, ClipboardImage(bytes=b"", mime_type="image/png"))
)
def test_stage_clipboard_image_returns_empty_outcome_without_writing(
    tmp_path,
    image: ClipboardImage | None,
) -> None:
    directory = tmp_path / "images"

    outcome = stage_clipboard_image(
        lambda: image,
        directory=directory,
        display_root=tmp_path,
        name_token="image",
    )

    assert outcome.kind == "empty"
    assert outcome.attachment is None
    assert not directory.exists()


def test_stage_clipboard_image_returns_unsupported_outcome_without_writing(
    tmp_path,
) -> None:
    directory = tmp_path / "images"

    outcome = stage_clipboard_image(
        lambda: ClipboardImage(bytes=b"svg", mime_type=" IMAGE/SVG+XML "),
        directory=directory,
        display_root=tmp_path,
        name_token="image",
    )

    assert outcome.kind == "unsupported"
    assert outcome.mime_type == "image/svg+xml"
    assert outcome.attachment is None
    assert not directory.exists()


def test_stage_clipboard_image_returns_read_error_outcome(tmp_path) -> None:
    def fail() -> ClipboardImage | None:
        raise RuntimeError("clipboard unavailable")

    outcome = stage_clipboard_image(
        fail,
        directory=tmp_path / "images",
        display_root=tmp_path,
        name_token="image",
    )

    assert outcome.kind == "read_error"
    assert outcome.error_message == "clipboard unavailable"
    assert outcome.attachment is None


def test_stage_clipboard_image_returns_write_error_outcome(tmp_path) -> None:
    blocked_directory = tmp_path / "not-a-directory"
    blocked_directory.write_text("blocked", encoding="utf-8")

    outcome = stage_clipboard_image(
        lambda: ClipboardImage(bytes=b"png", mime_type="image/png"),
        directory=blocked_directory,
        display_root=tmp_path,
        name_token="image",
    )

    assert outcome.kind == "write_error"
    assert outcome.mime_type == "image/png"
    assert outcome.error_message
    assert outcome.attachment is None
