from __future__ import annotations

import os
import stat
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
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
    path: Path | None
    display_path: str
    marker: str
    _cleanup_identity: tuple[int, int] | None = field(
        default=None,
        repr=False,
        compare=False,
    )


PromptImageAttachmentOutcomeKind = Literal[
    "attached",
    "empty",
    "unsupported",
    "read_error",
    "write_error",
    "quota_exceeded",
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


class DraftStoreQuotaExceeded(ValueError):
    """Raised when a draft cannot safely retain another attachment."""


@dataclass(frozen=True, slots=True)
class DraftStorePolicy:
    """Hard bounds for one in-memory and on-disk prompt draft."""

    max_attachments: int = 16
    max_attachment_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_attachments < 1:
            raise ValueError("max_attachments must be positive")
        if self.max_attachment_bytes < 1:
            raise ValueError("max_attachment_bytes must be positive")
        if self.max_total_bytes < self.max_attachment_bytes:
            raise ValueError(
                "max_total_bytes must be at least max_attachment_bytes"
            )


DEFAULT_DRAFT_STORE_POLICY = DraftStorePolicy()


@dataclass(slots=True)
class DraftStore:
    """Own bounded staged files until their bytes leave the current draft."""

    policy: DraftStorePolicy = DEFAULT_DRAFT_STORE_POLICY

    _attachments: list[PromptImageAttachment] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def add(self, attachment: PromptImageAttachment) -> None:
        reason = self._capacity_error(attachment)
        if reason is not None:
            _dispose_owned_attachment_file(attachment)
            raise DraftStoreQuotaExceeded(reason)
        self._attachments.append(attachment)

    def discard(self, attachment: PromptImageAttachment) -> None:
        """Dispose one registered file without disturbing the rest of the draft."""

        for index, registered in enumerate(self._attachments):
            if registered is attachment:
                self._attachments.pop(index)
                _dispose_owned_attachment_file(registered)
                return

    def select_for_text(self, text: str) -> tuple[PromptImageAttachment, ...]:
        positioned = (
            (position, insertion_index, attachment)
            for insertion_index, attachment in enumerate(self._attachments)
            if (position := text.find(attachment.marker)) >= 0
        )
        return tuple(
            attachment for _position, _insertion_index, attachment in sorted(positioned)
        )

    def take_for_text(self, text: str) -> tuple[PromptImageAttachment, ...]:
        """Transfer selected bytes and dispose every file owned by this draft."""

        selected = tuple(
            replace(
                attachment,
                path=None,
                _cleanup_identity=None,
            )
            for attachment in self.select_for_text(text)
        )
        self.clear()
        return selected

    def clear(self) -> None:
        attachments = tuple(self._attachments)
        self._attachments.clear()
        for attachment in attachments:
            _dispose_owned_attachment_file(attachment)

    def __len__(self) -> int:
        return len(self._attachments)

    @property
    def total_bytes(self) -> int:
        return sum(len(attachment.bytes) for attachment in self._attachments)

    def _capacity_error(self, attachment: PromptImageAttachment) -> str | None:
        size = len(attachment.bytes)
        if size > self.policy.max_attachment_bytes:
            return (
                f"image is {size} bytes; per-image limit is "
                f"{self.policy.max_attachment_bytes} bytes"
            )
        if len(self._attachments) >= self.policy.max_attachments:
            return f"draft attachment limit is {self.policy.max_attachments}"
        if self.total_bytes + size > self.policy.max_total_bytes:
            return f"draft byte limit is {self.policy.max_total_bytes} bytes"
        return None


# Pre-1.0 compatibility: DraftStore is the lifecycle-complete replacement,
# while existing callers may still import the former public registry name.
PendingPromptImageRegistry = DraftStore


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
    _prepare_private_directory(target_directory)
    token = _safe_filename_token(name_token)
    path = target_directory / f"clipboard-{token}.{extension}"
    _write_private_file(path, image.bytes)
    metadata = path.stat()

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
        _cleanup_identity=(metadata.st_dev, metadata.st_ino),
    )


def stage_clipboard_image(
    reader: ClipboardImageReader,
    *,
    directory: Path | str,
    display_root: Path | str,
    name_token: str | None = None,
    name_factory: ClipboardImageNameFactory | None = None,
    max_bytes: int | None = None,
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
    if max_bytes is not None and len(image.bytes) > max_bytes:
        return PromptImageAttachmentOutcome(
            kind="quota_exceeded",
            mime_type=mime_type,
            error_message=(
                f"image is {len(image.bytes)} bytes; per-image limit is "
                f"{max_bytes} bytes"
            ),
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


def _write_private_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(
        path,
        flags,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(OSError):
            path.unlink(missing_ok=True)
        raise


def _prepare_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise NotADirectoryError(str(path))
    getuid = getattr(os, "getuid", None)
    if os.name == "posix" and callable(getuid):
        if metadata.st_uid != getuid():
            raise PermissionError(
                f"clipboard directory is not owned by this user: {path}"
            )
        path.chmod(0o700)


def _dispose_owned_attachment_file(attachment: PromptImageAttachment) -> None:
    path = attachment.path
    expected = attachment._cleanup_identity
    if path is None or expected is None:
        return
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return
        if (metadata.st_dev, metadata.st_ino) != expected:
            return
        path.unlink()
    except OSError:
        # Draft cleanup is best effort; failure must not break prompt, cancel,
        # EOF, or shutdown paths. Run-scoped sweeping belongs to DraftStore.
        return


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
    return character.isascii() and (character.isalnum() or character in {"-", "_", "."})


def _base_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def _exception_message(error: BaseException) -> str:
    return str(error) or error.__class__.__name__


__all__ = [
    "ClipboardImageNameFactory",
    "ClipboardImageReader",
    "DEFAULT_DRAFT_STORE_POLICY",
    "DraftStore",
    "DraftStorePolicy",
    "DraftStoreQuotaExceeded",
    "PendingPromptImageRegistry",
    "PromptImageAttachment",
    "PromptImageAttachmentOutcome",
    "PromptImageAttachmentOutcomeKind",
    "new_prompt_image_name_token",
    "persist_clipboard_image",
    "stage_clipboard_image",
]
