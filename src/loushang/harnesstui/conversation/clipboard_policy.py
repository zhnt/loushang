"""Shared policy for clipboard images attached to conversation prompts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.foundation.runtime_scope import RuntimeScope
from loushang.harnesstui.conversation.attachments import (
    DEFAULT_DRAFT_STORE_POLICY,
    DraftStorePolicy,
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
    quota_exceeded_prefix: str | None = None

    def message(self, outcome: PromptImageAttachmentOutcome) -> str | None:
        if outcome.kind == "empty":
            return self.empty
        if outcome.kind == "read_error":
            return f"{self.read_error_prefix}{outcome.error_message}"
        if outcome.kind == "unsupported":
            return f"{self.unsupported_prefix}{outcome.mime_type or self.unknown_type}"
        if outcome.kind == "write_error":
            return f"{self.write_error_prefix}{outcome.error_message}"
        if outcome.kind == "quota_exceeded":
            prefix = self.quota_exceeded_prefix or self.write_error_prefix
            return f"{prefix}{outcome.error_message}"
        if outcome.attachment is not None:
            return f"{self.attached_prefix}{outcome.attachment.display_path}"
        return None


ClipboardImageAppPath = Callable[[ClipboardImageInputApp], Path | str]
ClipboardImageRuntimePath = Callable[[RuntimeScope], Path | str]


@dataclass(frozen=True, slots=True)
class ClipboardImageRuntimeStorage:
    """Run-scoped storage paths independent of Product application state."""

    directory: ClipboardImageRuntimePath
    display_root: ClipboardImageRuntimePath


@dataclass(frozen=True, slots=True)
class ClipboardImageInputProfile:
    """Workspace and copy policy for shared conversation image input."""

    directory: ClipboardImageAppPath | None
    display_root: ClipboardImageAppPath | None
    status_copy: ClipboardImageStatusCopy
    explicit_directory_display_root: ClipboardImageAppPath | None = None
    draft_policy: DraftStorePolicy = DEFAULT_DRAFT_STORE_POLICY
    runtime_storage: ClipboardImageRuntimeStorage | None = None

    def __post_init__(self) -> None:
        app_scoped = self.directory is not None or self.display_root is not None
        if self.runtime_storage is None:
            if self.directory is None or self.display_root is None:
                raise ValueError(
                    "clipboard profile requires both app-scoped paths"
                )
        elif app_scoped:
            raise ValueError(
                "clipboard profile cannot mix app-scoped and runtime-scoped paths"
            )

    def directory_for(
        self,
        app: ClipboardImageInputApp,
        scope: RuntimeScope | None,
    ) -> Path | str:
        if self.runtime_storage is not None:
            if scope is None:
                raise RuntimeError("clipboard runtime scope is unavailable")
            return self.runtime_storage.directory(scope)
        if self.directory is None:
            raise RuntimeError("clipboard profile directory is unavailable")
        return self.directory(app)

    def display_root_for(
        self,
        app: ClipboardImageInputApp,
        scope: RuntimeScope | None,
    ) -> Path | str:
        if self.runtime_storage is not None:
            if scope is None:
                raise RuntimeError("clipboard runtime scope is unavailable")
            return self.runtime_storage.display_root(scope)
        if self.display_root is None:
            raise RuntimeError("clipboard profile display root is unavailable")
        return self.display_root(app)


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
    quota_exceeded_prefix="Clipboard image limit reached: ",
    attached_prefix="Attached clipboard image: ",
    unknown_type="unknown",
)

STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE = ClipboardImageInputProfile(
    directory=None,
    display_root=None,
    status_copy=STANDARD_CLIPBOARD_IMAGE_STATUS_COPY,
    explicit_directory_display_root=_app_cwd,
    runtime_storage=ClipboardImageRuntimeStorage(
        directory=lambda scope: scope.drafts / "clipboard",
        display_root=lambda scope: scope.drafts,
    ),
)


__all__ = [
    "ClipboardImageAppPath",
    "ClipboardImageInputApp",
    "ClipboardImageInputProfile",
    "ClipboardImageRuntimePath",
    "ClipboardImageRuntimeStorage",
    "ClipboardImageStatusCopy",
    "STANDARD_CLIPBOARD_IMAGE_INPUT_PROFILE",
    "STANDARD_CLIPBOARD_IMAGE_STATUS_COPY",
]
