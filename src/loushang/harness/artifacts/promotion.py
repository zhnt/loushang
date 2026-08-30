"""Explicit transitions from run-local artifacts into durable authorities."""

from __future__ import annotations

import hashlib
import stat
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .references import RunArtifactRef, SessionBlobRef, UserExportRef
from .session_blobs import SessionBlobWriter
from .store import (
    ArtifactReader,
    ArtifactSourceRejected,
    _is_reparse_point,
    _publish_file_exclusive,
    _sync_directory,
    _unlink_owned_file,
    _write_new_private_file,
)


class ArtifactPromotionError(ValueError):
    """Raised when policy rejects a requested lifetime transition."""


@dataclass(frozen=True, slots=True)
class UserExportResult:
    """Explicit export receipt plus its caller-authorized destination."""

    reference: UserExportRef
    path: Path


class ArtifactPromotionService:
    """Promote verified run bytes without exposing their physical source path."""

    def __init__(
        self,
        reader: ArtifactReader,
        *,
        session_writer: SessionBlobWriter | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._reader = reader
        self._session_writer = session_writer
        self._now = now

    def promote_to_session(self, artifact: RunArtifactRef) -> SessionBlobRef:
        """Copy one verified run artifact into the bound Session authority."""

        writer = self._session_writer
        if writer is None:
            raise ArtifactPromotionError("session promotion requires a session writer")
        payload = self._read_verified(artifact)
        return writer.put_bytes(
            payload,
            logical_name=artifact.logical_name,
            kind=artifact.kind,
            media_type=artifact.media_type,
            disclosure=artifact.disclosure,
            source=_promotion_source(artifact),
        )

    def export_to_user(
        self,
        artifact: RunArtifactRef,
        destination: str | Path,
        *,
        allow_private: bool = False,
        redactor: Callable[[bytes], bytes] | None = None,
    ) -> UserExportResult:
        """Publish to an explicit path atomically and without overwriting.

        ``private`` content requires an additional explicit opt-in. ``redact``
        content cannot be exported until a caller supplies the redaction
        transform. The portable receipt deliberately excludes ``destination``.
        """

        if artifact.disclosure == "private" and not allow_private:
            raise ArtifactPromotionError(
                "private artifact export requires allow_private=True"
            )
        if artifact.disclosure == "redact" and redactor is None:
            raise ArtifactPromotionError("redact artifact export requires a redactor")
        payload = self._read_verified(artifact)
        if artifact.disclosure == "redact":
            assert redactor is not None
            payload = bytes(redactor(payload))

        path = Path(destination).expanduser().resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        parent_metadata = path.parent.lstat()
        if not stat.S_ISDIR(parent_metadata.st_mode) or _is_reparse_point(
            parent_metadata
        ):
            raise ArtifactPromotionError("user export parent is not a safe directory")
        if path.exists():
            raise FileExistsError(path)

        temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        identity: tuple[int, int] | None = None
        try:
            identity = _write_new_private_file(temporary, payload)
            _publish_file_exclusive(temporary, path)
            _sync_directory(path.parent)
        finally:
            if identity is not None:
                with suppress(FileNotFoundError):
                    _unlink_owned_file(temporary, identity)

        digest = hashlib.sha256(payload).hexdigest()
        reference = UserExportRef(
            export_id=uuid4().hex,
            logical_name=artifact.logical_name,
            kind=artifact.kind,
            media_type=artifact.media_type,
            disclosure=(
                "shareable" if artifact.disclosure == "redact" else artifact.disclosure
            ),
            size_bytes=len(payload),
            sha256=digest,
            created_at=float(self._now()),
            source_artifact_id=artifact.artifact_id,
        )
        return UserExportResult(reference=reference, path=path)

    def _read_verified(self, artifact: RunArtifactRef) -> bytes:
        payload = self._reader.read_bytes(artifact)
        if len(payload) != artifact.size_bytes:
            raise ArtifactSourceRejected("artifact size does not match its reference")
        if hashlib.sha256(payload).hexdigest() != artifact.sha256:
            raise ArtifactSourceRejected("artifact digest does not match its reference")
        return payload


def _promotion_source(artifact: RunArtifactRef) -> str:
    value = f"run-artifact:{artifact.artifact_id}"
    return value[:128]


__all__ = [
    "ArtifactPromotionError",
    "ArtifactPromotionService",
    "UserExportResult",
]
