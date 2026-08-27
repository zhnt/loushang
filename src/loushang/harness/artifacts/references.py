"""Portable references for resources crossing runtime lifetime boundaries."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import TypeAlias, cast

from loushang.foundation.json import JSONValue, require_json_mapping

from .store import ArtifactDisclosure, ArtifactRef

RunArtifactRef: TypeAlias = ArtifactRef

_PORTABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def require_portable_artifact_id(value: str, *, name: str) -> str:
    """Validate an identifier before it can influence durable layout."""

    _require_portable_id(value, name=name)
    return value


def session_blob_authority_id(conversation_id: str) -> str:
    """Return the safe physical authority key for one logical conversation.

    Conversation identity predates the portable artifact layout and historically
    accepted any non-empty string.  Portable identities remain readable as-is;
    legacy identities are mapped deterministically without weakening path safety.
    """

    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError("conversation id must be a non-empty string")
    if _PORTABLE_ID.fullmatch(conversation_id) is not None:
        return conversation_id
    digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()
    return f"legacy-{digest}"


@dataclass(frozen=True, slots=True)
class SessionBlobRef:
    """Portable reference to immutable bytes owned by one durable session."""

    session_id: str
    blob_id: str
    logical_name: str
    kind: str
    media_type: str
    disclosure: ArtifactDisclosure
    size_bytes: int
    sha256: str
    created_at: float
    source: str | None = None

    def __post_init__(self) -> None:
        _require_portable_id(self.session_id, name="session id")
        _require_portable_id(self.blob_id, name="blob id")
        _require_logical_name(self.logical_name)
        _require_portable_id(self.kind, name="blob kind")
        _require_media_type(self.media_type)
        _require_disclosure(self.disclosure)
        _require_size(self.size_bytes)
        _require_digest(self.sha256)
        if self.blob_id != self.sha256:
            raise ValueError("blob id must equal its sha256 content digest")
        _require_timestamp(self.created_at)
        _require_optional_label(self.source, name="blob source")

    def manifest_entry(self) -> dict[str, JSONValue]:
        """Encode portable metadata without exposing storage authority."""

        return {
            "sessionId": self.session_id,
            "blobId": self.blob_id,
            "logicalName": self.logical_name,
            "kind": self.kind,
            "mediaType": self.media_type,
            "disclosure": self.disclosure,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
            "createdAt": self.created_at,
            "source": self.source,
        }

    @classmethod
    def from_manifest_entry(cls, value: Mapping[str, object]) -> SessionBlobRef:
        """Decode one strict manifest entry."""

        entry = require_json_mapping(value, name="session blob reference")
        _require_exact_keys(
            entry,
            required={
                "sessionId",
                "blobId",
                "logicalName",
                "kind",
                "mediaType",
                "disclosure",
                "sizeBytes",
                "sha256",
                "createdAt",
                "source",
            },
            name="session blob reference",
        )
        return cls(
            session_id=_text(entry, "sessionId"),
            blob_id=_text(entry, "blobId"),
            logical_name=_text(entry, "logicalName"),
            kind=_text(entry, "kind"),
            media_type=_text(entry, "mediaType"),
            disclosure=_disclosure(entry, "disclosure"),
            size_bytes=_integer(entry, "sizeBytes"),
            sha256=_text(entry, "sha256"),
            created_at=_number(entry, "createdAt"),
            source=_optional_text(entry, "source"),
        )


@dataclass(frozen=True, slots=True)
class UserExportRef:
    """Portable receipt for bytes explicitly exported into user authority."""

    export_id: str
    logical_name: str
    kind: str
    media_type: str
    disclosure: ArtifactDisclosure
    size_bytes: int
    sha256: str
    created_at: float
    source_artifact_id: str

    def __post_init__(self) -> None:
        _require_portable_id(self.export_id, name="export id")
        _require_logical_name(self.logical_name)
        _require_portable_id(self.kind, name="export kind")
        _require_media_type(self.media_type)
        _require_disclosure(self.disclosure)
        _require_size(self.size_bytes)
        _require_digest(self.sha256)
        _require_timestamp(self.created_at)
        _require_portable_id(self.source_artifact_id, name="source artifact id")

    def manifest_entry(self) -> dict[str, JSONValue]:
        return {
            "exportId": self.export_id,
            "logicalName": self.logical_name,
            "kind": self.kind,
            "mediaType": self.media_type,
            "disclosure": self.disclosure,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
            "createdAt": self.created_at,
            "sourceArtifactId": self.source_artifact_id,
        }


def _require_exact_keys(
    value: Mapping[str, JSONValue],
    *,
    required: set[str],
    name: str,
) -> None:
    keys = set(value)
    if keys != required:
        missing = sorted(required - keys)
        extra = sorted(keys - required)
        raise ValueError(f"{name} keys are invalid; missing={missing}, extra={extra}")


def _text(value: Mapping[str, JSONValue], key: str) -> str:
    result = value[key]
    if not isinstance(result, str):
        raise TypeError(f"{key} must be a string")
    return result


def _optional_text(value: Mapping[str, JSONValue], key: str) -> str | None:
    result = value[key]
    if result is not None and not isinstance(result, str):
        raise TypeError(f"{key} must be a string or null")
    return result


def _integer(value: Mapping[str, JSONValue], key: str) -> int:
    result = value[key]
    if isinstance(result, bool) or not isinstance(result, int):
        raise TypeError(f"{key} must be an integer")
    return result


def _number(value: Mapping[str, JSONValue], key: str) -> float:
    result = value[key]
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise TypeError(f"{key} must be a number")
    return float(result)


def _disclosure(
    value: Mapping[str, JSONValue], key: str
) -> ArtifactDisclosure:
    result = _text(value, key)
    if result not in {"private", "redact", "shareable"}:
        raise ValueError(f"unsupported artifact disclosure: {result!r}")
    return cast(ArtifactDisclosure, result)


def _require_portable_id(value: str, *, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if _PORTABLE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a portable identifier")


def _require_logical_name(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("logical name must be a string")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or path.is_absolute()
        or PureWindowsPath(value).drive
        or ".." in path.parts
        or path.as_posix() != value
        or str(path) in {"", "."}
        or len(value) > 240
    ):
        raise ValueError("logical name must be a safe relative path")


def _require_media_type(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("media type must be a string")
    if not value or len(value) > 128 or any(ord(character) < 32 for character in value):
        raise ValueError("media type must be a non-empty portable value")


def _require_disclosure(value: str) -> None:
    if value not in {"private", "redact", "shareable"}:
        raise ValueError(f"unsupported artifact disclosure: {value!r}")


def _require_size(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("size must be an integer")
    if value < 0:
        raise ValueError("size must not be negative")


def _require_digest(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("sha256 must be a string")
    if _SHA256.fullmatch(value) is None:
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")


def _require_timestamp(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("created_at must be a number")
    if not math.isfinite(value):
        raise ValueError("created_at must be finite")


def _require_optional_label(value: str | None, *, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")
    if not value or len(value) > 128 or any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must be a non-empty portable value")


__all__ = [
    "RunArtifactRef",
    "SessionBlobRef",
    "UserExportRef",
    "require_portable_artifact_id",
]
