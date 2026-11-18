"""Bounded request and result values for Workspace previews."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MAX_PREVIEW_PATH = 4096
MAX_PREVIEW_BYTES = 128 * 1024
MAX_PREVIEW_ENTRIES = 128
_UNSAFE_PATH_TEXT = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")


def _path_text(value: str, *, empty: bool = False, limit: int = MAX_PREVIEW_PATH) -> None:
    if (type(value) is not str or not (0 if empty else 1) <= len(value) <= limit
            or _UNSAFE_PATH_TEXT.search(value)):
        raise ValueError("invalid workspace preview path")


@dataclass(frozen=True, slots=True)
class WorkspacePreviewRequestV1:
    reference: str
    base: str
    scope_fingerprint: str

    def __post_init__(self) -> None:
        _path_text(self.reference)
        _path_text(self.base, empty=True)
        if type(self.scope_fingerprint) is not str or not _FINGERPRINT.fullmatch(self.scope_fingerprint):
            raise ValueError("invalid workspace preview scope")


@dataclass(frozen=True, slots=True)
class WorkspacePreviewEntryV1:
    name: str
    kind: Literal["file", "directory"]

    def __post_init__(self) -> None:
        _path_text(self.name, limit=255)
        if self.name in {".", ".."} or any(char in self.name for char in "/\\:"):
            raise ValueError("invalid workspace preview entry")
        if self.kind not in ("file", "directory"):
            raise ValueError("invalid workspace preview entry kind")


@dataclass(frozen=True, slots=True)
class WorkspaceFilePreviewV1:
    path: str
    text: str = field(repr=False)

    def __post_init__(self) -> None:
        _path_text(self.path)
        if type(self.text) is not str or len(self.text.encode("utf-8")) > MAX_PREVIEW_BYTES:
            raise ValueError("invalid workspace preview text")


@dataclass(frozen=True, slots=True)
class WorkspaceDirectoryPreviewV1:
    path: str
    entries: tuple[WorkspacePreviewEntryV1, ...]
    limited: bool

    def __post_init__(self) -> None:
        _path_text(self.path)
        if (type(self.entries) is not tuple or len(self.entries) > MAX_PREVIEW_ENTRIES
                or any(type(item) is not WorkspacePreviewEntryV1 for item in self.entries)
                or type(self.limited) is not bool):
            raise ValueError("invalid workspace preview directory")


WorkspacePreviewV1 = WorkspaceFilePreviewV1 | WorkspaceDirectoryPreviewV1
