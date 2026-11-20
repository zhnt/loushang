"""Path-free Session resources on the scoped AppServer connection."""

from dataclasses import dataclass
from typing import Literal

from ._validation import _identifier

IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
MAX_IMAGE_BYTES = 4 * 1024 * 1024
RESOURCE_CHUNK_BYTES = 192 * 1024


@dataclass(frozen=True, slots=True)
class ResourceV1:
    id: str
    kind: Literal["file", "directory"]
    source: Literal["managed", "host_reference", "client_reference"]
    media_type: str
    size_bytes: int

    def __post_init__(self) -> None:
        _identifier(self.id)
        if self.kind not in {"file", "directory"} or self.source not in {
            "managed", "host_reference", "client_reference",
        }:
            raise ValueError("invalid resource type")
        if type(self.media_type) is not str or len(self.media_type) > 128:
            raise ValueError("invalid resource media type")
        if type(self.size_bytes) is not int or not 0 <= self.size_bytes < 2**53:
            raise ValueError("invalid resource size")


@dataclass(frozen=True, slots=True)
class SessionResourceQueryV1:
    action: Literal["upload", "read", "list"]
    resource_id: str | None = None
    offset: int = 0
    total_bytes: int = 0
    media_type: str = ""
    data: str = ""

    def __post_init__(self) -> None:
        if self.action not in {"upload", "read", "list"}:
            raise ValueError("invalid resource action")
        if type(self.offset) is not int or not 0 <= self.offset < MAX_IMAGE_BYTES:
            raise ValueError("invalid resource offset")
        if self.action == "list":
            if self.resource_id is not None or self.offset:
                raise ValueError("unexpected resource selection")
        else:
            if self.resource_id is None:
                raise ValueError("missing resource selection")
            _identifier(self.resource_id)
        if self.action == "upload":
            if (type(self.total_bytes) is not int or not self.offset < self.total_bytes <= MAX_IMAGE_BYTES
                    or self.media_type not in IMAGE_MEDIA_TYPES
                    or type(self.data) is not str or not 0 < len(self.data) <= RESOURCE_CHUNK_BYTES // 3 * 4):
                raise ValueError("invalid image upload")
        elif self.total_bytes or self.media_type or self.data:
            raise ValueError("unexpected upload data")


@dataclass(frozen=True, slots=True)
class SessionResourceResultV1:
    resources: tuple[ResourceV1, ...] = ()
    data: str = ""

    def __post_init__(self) -> None:
        if (type(self.resources) is not tuple or len(self.resources) > 256
                or any(type(resource) is not ResourceV1 for resource in self.resources)):
            raise ValueError("invalid resource result")
        if (type(self.data) is not str or len(self.data) > RESOURCE_CHUNK_BYTES // 3 * 4
                or (self.data and len(self.resources) != 1)):
            raise ValueError("invalid resource chunk")
