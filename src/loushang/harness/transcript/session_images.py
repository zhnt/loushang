"""Externalize durable transcript images and hydrate them for model input."""

from __future__ import annotations

import base64
import binascii
import hashlib
import time
from dataclasses import dataclass, replace

from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    Message,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from loushang.harness.artifacts import (
    ArtifactStoreQuotaExceeded,
    SessionBlobPublication,
    SessionBlobRef,
    SessionBlobStore,
)
from loushang.harness.transcript.types import ApplicationMessage, SessionImagePart

DEFAULT_SESSION_IMAGE_CONTEXT_BYTES = 64 * 1024 * 1024


class SessionImageHydrationBudgetExceeded(ValueError):
    """Hydrating more inline image data would exceed the model context budget."""


@dataclass(slots=True)
class SessionImageHydrationContext:
    """Per-build bounded cache keyed by immutable content identity."""

    max_total_bytes: int = DEFAULT_SESSION_IMAGE_CONTEXT_BYTES
    total_bytes: int = 0
    _encoded_by_blob_id: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.max_total_bytes < 1:
            raise ValueError("Session image hydration budget must be positive")
        if self._encoded_by_blob_id is None:
            self._encoded_by_blob_id = {}

    def encode(self, reference: SessionBlobRef, store: SessionBlobStore) -> str:
        if reference.session_id != store.session_id or reference not in store.records:
            raise ValueError("session image reference is not owned by this store")
        assert self._encoded_by_blob_id is not None
        cached = self._encoded_by_blob_id.get(reference.blob_id)
        if cached is not None:
            return cached
        if self.total_bytes + reference.size_bytes > self.max_total_bytes:
            raise SessionImageHydrationBudgetExceeded(
                "Session image context byte budget exceeded"
            )
        payload = store.read_bytes(reference)
        encoded = base64.b64encode(payload).decode("ascii")
        self._encoded_by_blob_id[reference.blob_id] = encoded
        self.total_bytes += len(payload)
        return encoded


@dataclass(frozen=True, slots=True)
class ExternalizedSessionImages:
    """One pathless message plus rollback authority for newly published bytes."""

    message: Message | ApplicationMessage
    publication: SessionBlobPublication | None = None


def externalize_session_message_images(
    message: Message | ApplicationMessage,
    store: SessionBlobStore,
    *,
    now: float | None = None,
) -> ExternalizedSessionImages:
    """Replace inline image bytes with durable Session-owned references."""

    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return ExternalizedSessionImages(message)
    prepared: list[tuple[SessionBlobRef, bytes]] = []
    replacements: list[ImagePart | SessionImagePart | object] = []
    created_at = float(time.time() if now is None else now)
    role = _message_role(message)
    for part in content:
        if isinstance(part, SessionImagePart):
            if part.blob.session_id != store.session_id:
                raise ValueError("session image belongs to another Session authority")
            store.read_bytes(part.blob)
            replacements.append(part)
            continue
        if not isinstance(part, ImagePart):
            replacements.append(part)
            continue
        payload = _decode_image(part, max_bytes=store.policy.max_blob_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        reference = SessionBlobRef(
            session_id=store.session_id,
            blob_id=digest,
            logical_name=f"images/{role}-{digest[:16]}{_image_suffix(part.mime_type)}",
            kind="image",
            media_type=part.mime_type,
            disclosure="private",
            size_bytes=len(payload),
            sha256=digest,
            created_at=created_at,
            source=f"transcript-image:{role}",
        )
        prepared.append((reference, payload))
        replacements.append(SessionImagePart(type="image", blob=reference))
    if not prepared:
        return ExternalizedSessionImages(message)
    publication = store.import_blobs(prepared)
    # Every prepared image has one replacement, including duplicate content.
    published = iter(publication.references)
    resolved_parts = [
        SessionImagePart(type="image", blob=next(published))
        if isinstance(original, ImagePart)
        else replacement
        for original, replacement in zip(content, replacements, strict=True)
    ]
    return ExternalizedSessionImages(
        replace(message, content=resolved_parts),  # type: ignore[arg-type]
        publication,
    )


def hydrate_session_message_images(
    message: object,
    store: SessionBlobStore,
    *,
    hydration: SessionImageHydrationContext | None = None,
) -> object:
    """Project Session image refs into verified inline AI image parts.

    Missing or corrupt bytes degrade to a text marker so resume remains usable.
    """

    if not isinstance(
        message,
        UserMessage | AssistantMessage | ToolResultMessage | ApplicationMessage,
    ):
        return message
    content = message.content
    if not isinstance(content, list):
        return message
    hydrated: list[object] = []
    changed = False
    hydration = hydration or SessionImageHydrationContext()
    for part in content:
        if not isinstance(part, SessionImagePart):
            hydrated.append(part)
            continue
        changed = True
        try:
            encoded = hydration.encode(part.blob, store)
            hydrated.append(
                ImagePart(
                    type="image",
                    data=encoded,
                    mime_type=part.blob.media_type,
                )
            )
        except SessionImageHydrationBudgetExceeded:
            hydrated.append(
                TextPart(
                    type="text",
                    text=f"[Image omitted: context budget exceeded: {part.blob.logical_name}]",
                )
            )
        except (OSError, ValueError):
            hydrated.append(
                TextPart(
                    type="text",
                    text=f"[Image unavailable: {part.blob.logical_name}]",
                )
            )
    if not changed:
        return message
    return replace(message, content=hydrated)  # type: ignore[arg-type]


def rollback_externalized_session_images(
    externalized: ExternalizedSessionImages,
    error: BaseException,
) -> None:
    publication = externalized.publication
    if publication is None:
        return
    try:
        publication.rollback()
    except BaseException as cleanup_error:
        error.add_note(
            "session image rollback also failed: "
            f"{cleanup_error.__class__.__name__}: {cleanup_error}"
        )


def _decode_image(part: ImagePart, *, max_bytes: int) -> bytes:
    if not isinstance(part.mime_type, str) or not part.mime_type.startswith("image/"):
        raise ValueError("inline image must have an image media type")
    if len(part.data) > ((max_bytes + 2) // 3) * 4 + 4:
        raise ArtifactStoreQuotaExceeded(
            f"inline image exceeds per-blob limit of {max_bytes} bytes"
        )
    try:
        payload = base64.b64decode(part.data, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("inline image data must be canonical base64") from error
    if len(payload) > max_bytes:
        raise ArtifactStoreQuotaExceeded(
            f"inline image exceeds per-blob limit of {max_bytes} bytes"
        )
    if base64.b64encode(payload).decode("ascii") != part.data:
        raise ValueError("inline image data must be canonical base64")
    return payload


def _message_role(message: Message | ApplicationMessage) -> str:
    if isinstance(message, ToolResultMessage):
        return "tool-result"
    if isinstance(message, ApplicationMessage):
        return "application"
    return message.role


def _image_suffix(media_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(media_type.lower(), ".img")


__all__ = [
    "ExternalizedSessionImages",
    "DEFAULT_SESSION_IMAGE_CONTEXT_BYTES",
    "SessionImageHydrationBudgetExceeded",
    "SessionImageHydrationContext",
    "externalize_session_message_images",
    "hydrate_session_message_images",
    "rollback_externalized_session_images",
]
