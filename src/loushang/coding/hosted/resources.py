"""Session-scoped access to files managed by the Coding hosted integration."""

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
    TEXT_MEDIA_TYPE,
    ResourceV1,
    SessionResourceQueryV1,
    SessionResourceResultV1,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.coding.hosted_workspace import CodingHostedWorkspace
from loushang.foundation.json import JSONValue
from loushang.harness.artifacts import (
    ArtifactStoreError,
    SessionBlobRef,
    SessionBlobStore,
    resolve_session_blob_data_root,
)
from loushang.harness.transcript.types import AgentTranscriptRecord, SessionImagePart

from .host_references import HOST_REFERENCE, HostReference

_SOURCE = "managed-resource"
SUBMISSION_ID = "hosted_resource_submission_id"
SUBMISSION_DIGEST = "hosted_resource_submission_digest"
_FILE_IDS = "hosted_resource_file_ids"


@dataclass(slots=True)
class _Upload:
    file: BinaryIO
    size: int
    media_type: str
    name: str | None


def image_ids(message: object) -> tuple[str, ...]:
    if not isinstance(message, UserMessage) or not isinstance(message.content, list):
        return ()
    return tuple(part.blob.sha256 for part in message.content if isinstance(part, SessionImagePart))


def _resource(blob: SessionBlobRef) -> ResourceV1:
    name = blob.logical_name.rsplit("/", 1)[-1] if blob.kind == "file" else None
    return ResourceV1(blob.sha256, "file", "managed", blob.media_type, blob.size_bytes, name)


def record_resource_ids(entry: AgentTranscriptRecord) -> tuple[str, ...]:
    files = entry.metadata.get(_FILE_IDS)
    return image_ids(entry.payload) + (
        tuple(item for item in files if isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item))
        if isinstance(files, list) else ()
    )


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
        workspace: CodingHostedWorkspace | None = None,
    ) -> None:
        self._root = resolve_session_blob_data_root(session_dir)
        self._session_id = session_id
        self._records = records
        self._workspace = workspace
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

    def _uploaded(self, refs: tuple[ResourceRefV1, ...]) -> tuple[SessionBlobStore, list[SessionBlobRef]]:
        store, resources = self._manifest()
        selected = []
        for ref in refs:
            blob = resources.get(ref.id)
            if blob is None or blob.sha256 != ref.sha256:
                raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
            selected.append(blob)
        return store, selected

    def input_metadata(self, refs: tuple[ResourceRefV1, ...]) -> dict[str, JSONValue]:
        _, selected = self._uploaded(refs)
        ids: list[JSONValue] = [blob.sha256 for blob in selected if blob.kind != "image"]
        return {_FILE_IDS: ids} if ids else {}

    def images(self, refs: tuple[ResourceRefV1, ...]) -> list[ImagePart]:
        try:
            store, selected = self._uploaded(refs)
            images = []
            for blob in selected:
                if blob.kind == HOST_REFERENCE:
                    HostReference.load(store, blob).resolve(self._workspace)
                    continue
                content = store.read_bytes(blob)
                if blob.kind != "image":
                    continue
                images.append(ImagePart(type="image", mime_type=blob.media_type,
                                        data=base64.b64encode(content).decode("ascii")))
            return images
        except (ArtifactStoreError, OSError, ValueError) as exc:
            raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE) from exc

    def associated(self, *, kind: str | None = None) -> tuple[ResourceV1, ...]:
        store, resources = self._manifest()
        used = {id for entry in self._records() for id in record_resource_ids(entry)}
        return tuple(self._metadata(store, blob) for id, blob in resources.items() if id in used
                     and (kind is None or blob.kind == kind or blob.kind == HOST_REFERENCE))

    def _metadata(self, store: SessionBlobStore, blob: SessionBlobRef) -> ResourceV1:
        if blob.kind == HOST_REFERENCE:
            return HostReference.load(store, blob).resource(blob)
        return _resource(blob)

    def resolve_host(
        self, resource_id: str, relative: str,
    ) -> tuple[HostReference, Path]:
        try:
            store, resources = self._manifest()
            blob = resources.get(resource_id)
            if blob is None or blob.kind != HOST_REFERENCE or not any(
                resource_id in record_resource_ids(entry) for entry in self._records()
            ):
                raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
            reference = HostReference.load(store, blob)
            return reference, reference.resolve(self._workspace, relative)
        except (ArtifactStoreError, OSError, ValueError) as exc:
            raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE) from exc

    def read_text(self, id: str, *, offset: int = 0) -> dict[str, JSONValue]:
        if type(offset) is not int or not 0 <= offset <= 2**20:
            raise ValueError("invalid text offset")
        try:
            store, resources = self._manifest()
            blob = resources.get(id)
            if blob is None or blob.kind != "file" or not any(
                id in record_resource_ids(entry) for entry in self._records()
            ):
                raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
            text = store.read_bytes(blob).decode("utf-8-sig")
            end = offset + 12000
            return {"text": text[offset:end], "nextOffset": end if end < len(text) else None}
        except (ArtifactStoreError, OSError, ValueError) as exc:
            raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE) from exc

    def exchange(self, query: SessionResourceQueryV1) -> SessionResourceResultV1:
        try:
            if query.action == "list":
                # The canonical transcript is authoritative, including messages outside the UI window.
                return SessionResourceResultV1(self.associated())
            store, resources = self._manifest()
            if query.action == "reference":
                assert query.path is not None
                ref = HostReference.select(self._workspace, query.path)
                data = ref.descriptor()
                id = sha256(data).hexdigest()
                blob = resources.get(id)
                if blob is None:
                    blob = store.put_bytes(data, logical_name=f"resources/{id}", kind=HOST_REFERENCE,
                                           media_type="application/json", source=_SOURCE)
                return SessionResourceResultV1((ref.resource(blob),))
            id = query.resource_id
            if id is None or re.fullmatch(r"[a-f0-9]{64}", id) is None:
                raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
            blob = resources.get(id)
            if query.action == "upload":
                return self._upload(store, query, id, blob)
            if blob is not None and blob.kind == HOST_REFERENCE:
                # Descriptor bytes can include paths and native file identities.
                if query.offset:
                    raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
                return SessionResourceResultV1((self._metadata(store, blob),))
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
            item = _Upload(TemporaryFile(dir=self._root), query.total_bytes, query.media_type, query.name)
            self._uploads[id] = item
        if (item is None or item.size != query.total_bytes or item.media_type != query.media_type
                or item.name != query.name or item.file.tell() != query.offset):
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
        try:
            item.file.write(chunk)
            if end < item.size:
                return SessionResourceResultV1()
            item.file.seek(0)
            data = item.file.read(item.size)
            if sha256(data).hexdigest() != id:
                raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
            if item.media_type == TEXT_MEDIA_TYPE:
                if b"\x00" in data:
                    raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
                try:
                    data.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST) from exc
                kind, name = "file", f"resources/{id}/{item.name}"
            elif _image_signature(data, item.media_type):
                kind, name = "image", f"resources/{id}"
            else:
                raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
            stored = store.put_bytes(data, logical_name=name, kind=kind,
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
