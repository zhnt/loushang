from __future__ import annotations

import os
import stat
from dataclasses import FrozenInstanceError

import pytest

from loushang.harnesstui.conversation.attachments import (
    DraftStore,
    DraftStorePolicy,
    DraftStoreQuotaExceeded,
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
    if os.name == "posix":
        assert stat.S_IMODE(expected_path.stat().st_mode) == 0o600


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


def test_pending_registry_name_remains_a_compatibility_alias() -> None:
    assert PendingPromptImageRegistry is DraftStore


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
    registry = DraftStore()
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
    registry = DraftStore()
    registry.add(attachment)

    registry.clear()

    assert len(registry) == 0
    assert registry.select_for_text(attachment.marker) == ()
    assert attachment.path.exists() is False


def test_pending_registry_take_transfers_bytes_and_disposes_all_draft_files(
    tmp_path,
) -> None:
    selected = persist_clipboard_image(
        ClipboardImage(bytes=b"selected", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="selected",
    )
    unused = persist_clipboard_image(
        ClipboardImage(bytes=b"unused", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="unused",
    )
    registry = DraftStore()
    registry.add(selected)
    registry.add(unused)

    transferred = registry.take_for_text(f"inspect {selected.marker}")

    assert len(transferred) == 1
    assert transferred[0].path is None
    assert transferred[0].bytes == selected.bytes
    assert transferred[0].bytes == b"selected"
    assert selected.path.exists() is False
    assert unused.path.exists() is False


def test_pending_registry_does_not_delete_unowned_attachment_path(tmp_path) -> None:
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    registry = DraftStore()
    registry.add(
        PromptImageAttachment(
            bytes=b"not-owned",
            mime_type="image/png",
            path=unrelated,
            display_path=unrelated.name,
            marker=f"@{unrelated.name}",
        )
    )

    registry.clear()

    assert unrelated.read_text(encoding="utf-8") == "keep"


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


def test_stage_clipboard_image_enforces_per_image_limit_before_writing(
    tmp_path,
) -> None:
    directory = tmp_path / "images"

    outcome = stage_clipboard_image(
        lambda: ClipboardImage(bytes=b"large", mime_type="image/png"),
        directory=directory,
        display_root=tmp_path,
        max_bytes=4,
    )

    assert outcome.kind == "quota_exceeded"
    assert "per-image limit is 4 bytes" in outcome.error_message
    assert not directory.exists()


def test_draft_store_enforces_count_and_total_bytes_and_disposes_rejected_file(
    tmp_path,
) -> None:
    store = DraftStore(
        policy=DraftStorePolicy(
            max_attachments=2,
            max_attachment_bytes=4,
            max_total_bytes=5,
        )
    )
    first = persist_clipboard_image(
        ClipboardImage(bytes=b"123", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="first",
    )
    second = persist_clipboard_image(
        ClipboardImage(bytes=b"456", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="second",
    )
    store.add(first)

    with pytest.raises(DraftStoreQuotaExceeded, match="draft byte limit"):
        store.add(second)

    assert store.total_bytes == 3
    assert first.path is not None and first.path.exists()
    assert second.path is not None and not second.path.exists()
    store.clear()


def test_draft_store_accepts_exact_limits_then_enforces_attachment_count(
    tmp_path,
) -> None:
    store = DraftStore(
        policy=DraftStorePolicy(
            max_attachments=1,
            max_attachment_bytes=4,
            max_total_bytes=4,
        )
    )
    accepted = persist_clipboard_image(
        ClipboardImage(bytes=b"1234", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="accepted",
    )
    rejected = persist_clipboard_image(
        ClipboardImage(bytes=b"1", mime_type="image/png"),
        directory=tmp_path,
        display_root=tmp_path,
        name_token="rejected",
    )

    store.add(accepted)
    with pytest.raises(DraftStoreQuotaExceeded, match="attachment limit"):
        store.add(rejected)

    assert store.total_bytes == 4
    assert accepted.path is not None and accepted.path.exists()
    assert rejected.path is not None and not rejected.path.exists()
    store.clear()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"max_attachments": 0}, "max_attachments"),
        ({"max_attachment_bytes": 0}, "max_attachment_bytes"),
        (
            {"max_attachment_bytes": 2, "max_total_bytes": 1},
            "max_total_bytes",
        ),
    ),
)
def test_draft_store_policy_rejects_invalid_limits(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        DraftStorePolicy(**kwargs)
