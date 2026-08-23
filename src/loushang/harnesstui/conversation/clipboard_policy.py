"""Shared policy for clipboard images attached to conversation prompts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.harnesstui.conversation.attachments import (
    PromptImageAttachmentOutcome,
)


class ClipboardImageInputApp(Protocol):
    @property
    def state(self) -> object: ...


@dataclass(frozen=True, slots=True)
class ClipboardImageStatusCopy:
    """User-facing copy for neutral clipboard attachment outcomes."""

    empty: str
    read_error_prefix: str
    unsupported_prefix: str
    write_error_prefix: str
    attached_prefix: str
    unknown_type: str

    def message(self, outcome: PromptImageAttachmentOutcome) -> str | None:
        if outcome.kind == "empty":
            return self.empty
        if outcome.kind == "read_error":
            return f"{self.read_error_prefix}{outcome.error_message}"
        if outcome.kind == "unsupported":
            return f"{self.unsupported_prefix}{outcome.mime_type or self.unknown_type}"
        if outcome.kind == "write_error":
            return f"{self.write_error_prefix}{outcome.error_message}"
        if outcome.attachment is not None:
            return f"{self.attached_prefix}{outcome.attachment.display_path}"
        return None


ClipboardImageAppPath = Callable[[ClipboardImageInputApp], Path | str]


@dataclass(frozen=True, slots=True)
class ClipboardImageInputProfile:
    """Workspace and copy policy for shared conversation image input."""

    directory: ClipboardImageAppPath
    display_root: ClipboardImageAppPath
    status_copy: ClipboardImageStatusCopy


def _app_cwd(app: ClipboardImageInputApp) -> Path:
    cwd = getattr(app.state, "cwd", None)
    if not isinstance(cwd, str) or not cwd:
        raise TypeError("Clipboard image input requires app.state.cwd")
    return Path(cwd)


STANDARD_CLIPBOARD_IMAGE_STATUS_COPY = ClipboardImageStatusCopy(
    empty="No clipboard image found.",
    read_error_prefix="Unable to read clipboard image: ",
    unsupported_prefix="Unsupported clipboard image type: ",
    write_error_prefix="Unable to attach clipboard image: ",
    attached_prefix="Attached clipboard image: ",
    unknown_type="unknown",
)

STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE = ClipboardImageInputProfile(
    directory=lambda app: _app_cwd(app) / ".loushang" / "clipboard",
    display_root=_app_cwd,
    status_copy=STANDARD_CLIPBOARD_IMAGE_STATUS_COPY,
)


__all__ = [
    "ClipboardImageAppPath",
    "ClipboardImageInputApp",
    "ClipboardImageInputProfile",
    "ClipboardImageStatusCopy",
    "STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE",
    "STANDARD_CLIPBOARD_IMAGE_STATUS_COPY",
]
