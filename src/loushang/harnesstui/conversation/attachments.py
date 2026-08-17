from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.tui.clipboard_image import (
    ClipboardImage,
    extension_for_image_mime_type,
)


@dataclass(frozen=True, slots=True)
class PromptImageAttachment:
    """Product-neutral image data staged for one prompt."""

    bytes: bytes
    mime_type: str
    path: Path
    display_path: str
    marker: str


PromptImageAttachmentOutcomeKind = Literal[
    "attached",
    "empty",
    "unsupported",
    "read_error",
    "write_error",
]


@dataclass(frozen=True, slots=True)
class PromptImageAttachmentOutcome:
    """Neutral result of reading and staging one clipboard image."""

    kind: PromptImageAttachmentOutcomeKind
    attachment: PromptImageAttachment | None = None
    mime_type: str = ""
    error_message: str = ""


ClipboardImageReader = Callable[[], ClipboardImage | None]
ClipboardImageNameFactory = Callable[[], str]


def new_prompt_image_name_token() -> str:
    """Return an opaque filename token for a newly staged prompt image."""

    return uuid.uuid4().hex


@dataclass(slots=True)
class PendingPromptImageRegistry:
    """Track staged images until a product submits or clears its prompt."""

    _attachments: list[PromptImageAttachment] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def add(self, attachment: PromptImageAttachment) -> None:
        self._attachments.append(attachment)

    def select_for_text(self, text: str) -> tuple[PromptImageAttachment, ...]:
        positioned = (
            (position, insertion_index, attachment)
            for insertion_index, attachment in enumerate(self._attachments)
            if (position := text.find(attachment.marker)) >= 0
        )
        return tuple(
            attachment
            for _position, _insertion_index, attachment in sorted(positioned)
        )

    def clear(self) -> None:
        self._attachments.clear()

    def __len__(self) -> int:
        return len(self._attachments)


def persist_clipboard_image(
    image: ClipboardImage,
    *,
    directory: Path | str,
    display_root: Path | str,
    name_token: str | None = None,
) -> PromptImageAttachment:
    """Persist clipboard bytes and return their neutral prompt attachment."""

    mime_type = _base_mime_type(image.mime_type)
    extension = extension_for_image_mime_type(mime_type)
    if extension is None:
        raise ValueError(f"unsupported clipboard image type: {mime_type or 'unknown'}")

    target_directory = Path(directory)
    target_directory.mkdir(parents=True, exist_ok=True)
    token = _safe_filename_token(name_token)
    path = target_directory / f"clipboard-{token}.{extension}"
    path.write_bytes(image.bytes)

    display_path = _display_path(
        path,
        relative_to=Path(display_root),
    )
    return PromptImageAttachment(
        bytes=image.bytes,
        mime_type=mime_type,
        path=path,
        display_path=display_path,
        marker=f"@{display_path}",
    )


def stage_clipboard_image(
    reader: ClipboardImageReader,
    *,
    directory: Path | str,
    display_root: Path | str,
    name_token: str | None = None,
    name_factory: ClipboardImageNameFactory | None = None,
) -> PromptImageAttachmentOutcome:
    """Read and persist one clipboard image without applying product copy."""

    try:
        image = reader()
    except Exception as error:
        return PromptImageAttachmentOutcome(
            kind="read_error",
            error_message=_exception_message(error),
        )
    if image is None or not image.bytes:
        return PromptImageAttachmentOutcome(kind="empty")

    mime_type = _base_mime_type(image.mime_type)
    if extension_for_image_mime_type(mime_type) is None:
        return PromptImageAttachmentOutcome(
            kind="unsupported",
            mime_type=mime_type,
        )

    try:
        if name_factory is not None:
            name_token = name_factory()
        attachment = persist_clipboard_image(
            image,
            directory=directory,
            display_root=display_root,
            name_token=name_token,
        )
    except OSError as error:
        return PromptImageAttachmentOutcome(
            kind="write_error",
            mime_type=mime_type,
            error_message=_exception_message(error),
        )
    return PromptImageAttachmentOutcome(
        kind="attached",
        attachment=attachment,
        mime_type=attachment.mime_type,
    )


def _display_path(path: Path, *, relative_to: Path | None) -> str:
    if relative_to is not None:
        try:
            return path.relative_to(relative_to).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _safe_filename_token(value: str | None) -> str:
    token = value.strip() if value is not None else ""
    if not token:
        token = new_prompt_image_name_token()
    safe = "".join(
        character if _is_safe_filename_character(character) else "_"
        for character in token
    )
    safe = safe.strip("._")
    return safe or new_prompt_image_name_token()


def _is_safe_filename_character(character: str) -> bool:
    return character.isascii() and (
        character.isalnum() or character in {"-", "_", "."}
    )


def _base_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def _exception_message(error: BaseException) -> str:
    return str(error) or error.__class__.__name__


__all__ = [
    "ClipboardImageNameFactory",
    "ClipboardImageReader",
    "PendingPromptImageRegistry",
    "PromptImageAttachment",
    "PromptImageAttachmentOutcome",
    "PromptImageAttachmentOutcomeKind",
    "new_prompt_image_name_token",
    "persist_clipboard_image",
    "stage_clipboard_image",
]
