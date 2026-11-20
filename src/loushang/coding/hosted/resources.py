"""Session-scoped access to images managed by the Coding hosted integration."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryFile
from typing import BinaryIO

from loushang.ai.types import ImagePart, UserMessage
from loushang.appserver.execution.model import ResourceRefV1
from loushang.appserver.execution.resources import (
    RESOURCE_CHUNK_BYTES,
    ResourceV1,
    SessionResourceQueryV1,
    SessionResourceResultV1,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.harness.artifacts import (
    ArtifactStoreError,
    SessionBlobRef,
    SessionBlobStore,
    resolve_session_blob_data_root,
)
from loushang.harness.transcript.types import AgentTranscriptRecord, SessionImagePart

_SOURCE = "managed-resource"
SUBMISSION_ID = "hosted_resource_submission_id"
SUBMISSION_DIGEST = "hosted_resource_submission_digest"


@dataclass(slots=True)
class _Upload:
    file: BinaryIO
    size: int
    media_type: str


def image_ids(message: object) -> tuple[str, ...]:
    if not isinstance(message, UserMessage) or not isinstance(message.content, list):
        return ()
    return tuple(part.blob.sha256 for part in message.content if isinstance(part, SessionImagePart))


def _resource(blob: SessionBlobRef) -> ResourceV1:
    return ResourceV1(blob.sha256, "file", "managed", blob.media_type, blob.size_bytes)


def _image_signature(data: bytes, mime: str) -> bool:
    match mime:
        case "image/png":
            return data.startswith(b"\x89PNG\r\n\x1a\n")
        case "image/jpeg":
            return data.startswith(b"\xff\xd8\xff")
        case "image/gif":
            return data.startswith((b"GIF87a", b"GIF89a"))
        case "image/webp":
            return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False


class HostedResourceAccess:
    def __init__(
        self, session_id: str, session_dir: Path, records: Callable[[], Iterable[AgentTranscriptRecord]],
    ) -> None:
        self._root = resolve_session_blob_data_root(session_dir)
        self._session_id = session_id
        self._records = records
        self._uploads: dict[str, _Upload] = {}

    def submission_digest(self, submission_id: str) -> str | None:
        for entry in self._records():
            if entry.metadata.get(SUBMISSION_ID) == submission_id:
                digest = entry.metadata.get(SUBMISSION_DIGEST)
                if isinstance(digest, str):
                    return digest
        return None

    def close(self) -> None:
        for item in self._uploads.values():
            item.file.close()
        self._uploads.clear()

    def _manifest(self) -> tuple[SessionBlobStore, dict[str, SessionBlobRef]]:
        store = SessionBlobStore(self._root, self._session_id)
        return store, {ref.sha256: ref for ref in store.records if ref.source == _SOURCE}

    def images(self, refs: tuple[ResourceRefV1, ...]) -> list[ImagePart]:
        try:
            store, resources = self._manifest()
            images = []
            for ref in refs:
                blob = resources.get(ref.id)
                if blob is None or blob.sha256 != ref.sha256:
                    raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
                images.append(ImagePart(type="image", mime_type=blob.media_type,
                                        data=base64.b64encode(store.read_bytes(blob)).decode("ascii")))
            return images
        except (ArtifactStoreError, OSError, ValueError) as exc:
            raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE) from exc

    def exchange(self, query: SessionResourceQueryV1) -> SessionResourceResultV1:
        try:
            store, resources = self._manifest()
            if query.action == "list":
                # The canonical transcript is authoritative, including messages outside the UI window.
                used = {id for entry in self._records() for id in image_ids(entry.payload)}
                return SessionResourceResultV1(tuple(
                    _resource(ref) for id, ref in resources.items() if id in used
                ))
            id = query.resource_id
            if id is None or re.fullmatch(r"[a-f0-9]{64}", id) is None:
                raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
            blob = resources.get(id)
            if query.action == "upload":
                return self._upload(store, query, id, blob)
            if blob is None or query.offset >= blob.size_bytes:
                raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
            chunk = store.read_bytes(blob)[query.offset:query.offset + RESOURCE_CHUNK_BYTES]
            return SessionResourceResultV1((_resource(blob),), base64.b64encode(chunk).decode("ascii"))
        except (ArtifactStoreError, OSError, ValueError) as exc:
            raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE) from exc

    def _upload(
        self, store: SessionBlobStore, query: SessionResourceQueryV1,
        id: str, blob: SessionBlobRef | None,
    ) -> SessionResourceResultV1:
        if blob is not None:
            if blob.media_type != query.media_type or blob.size_bytes != query.total_bytes:
                raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
            store.read_bytes(blob)
            return SessionResourceResultV1((_resource(blob),))
        try:
            chunk = base64.b64decode(query.data, validate=True)
        except binascii.Error as exc:
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST) from exc
        end = query.offset + len(chunk)
        if not 0 < len(chunk) <= RESOURCE_CHUNK_BYTES or end > query.total_bytes:
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
        item = self._uploads.get(id)
        if query.offset == 0:
            if item is not None:
                item.file.close()
                del self._uploads[id]
            if len(self._uploads) >= 4:
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            item = _Upload(TemporaryFile(dir=self._root), query.total_bytes, query.media_type)
            self._uploads[id] = item
        if (item is None or item.size != query.total_bytes or item.media_type != query.media_type
                or item.file.tell() != query.offset):
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
        try:
            item.file.write(chunk)
            if end < item.size:
                return SessionResourceResultV1()
            item.file.seek(0)
            data = item.file.read(item.size)
            if sha256(data).hexdigest() != id or not _image_signature(data, item.media_type):
                raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
            stored = store.put_bytes(data, logical_name=f"resources/{id}", kind="image",
                                     media_type=item.media_type, source=_SOURCE)
            return SessionResourceResultV1((_resource(stored),))
        except BaseException:
            item.file.close()
            del self._uploads[id]
            raise
        finally:
            if end == item.size and id in self._uploads:
                item.file.close()
                del self._uploads[id]
