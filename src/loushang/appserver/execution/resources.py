"""Path-free Session resources on the scoped AppServer connection."""

from dataclasses import dataclass
from typing import Literal
from unicodedata import category

from ._validation import _identifier

IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
MAX_IMAGE_BYTES = 4 * 1024 * 1024
TEXT_MEDIA_TYPE = "text/plain"
MAX_TEXT_BYTES = 1024 * 1024
RESOURCE_CHUNK_BYTES = 192 * 1024


def _validate_name(name: str | None) -> None:
    if name is not None and (
        type(name) is not str or not 0 < len(name) <= 150 or name in {".", ".."}
        or any(char in "/\\:" or category(char).startswith("C") for char in name)
    ):
        raise ValueError("invalid resource name")


@dataclass(frozen=True, slots=True)
class ResourceV1:
    id: str
    kind: Literal["file", "directory"]
    source: Literal["managed", "host_reference", "client_reference"]
    media_type: str
    size_bytes: int
    name: str | None = None

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
        _validate_name(self.name)


@dataclass(frozen=True, slots=True)
class SessionResourceQueryV1:
    action: Literal["upload", "read", "list", "reference"]
    resource_id: str | None = None
    offset: int = 0
    total_bytes: int = 0
    media_type: str = ""
    data: str = ""
    name: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        if self.action not in {"upload", "read", "list", "reference"}:
            raise ValueError("invalid resource action")
        if type(self.offset) is not int or not 0 <= self.offset < MAX_IMAGE_BYTES:
            raise ValueError("invalid resource offset")
        if self.action in {"list", "reference"}:
            if self.resource_id is not None or self.offset:
                raise ValueError("unexpected resource selection")
        else:
            if self.resource_id is None:
                raise ValueError("missing resource selection")
            _identifier(self.resource_id)
        if self.action == "reference":
            if type(self.path) is not str or not 0 < len(self.path) <= 4096 or "\x00" in self.path:
                raise ValueError("invalid reference path")
        elif self.path is not None:
            raise ValueError("unexpected reference path")
        if self.action == "upload":
            _validate_name(self.name)
            text = self.media_type == TEXT_MEDIA_TYPE and self.name is not None
            if (type(self.total_bytes) is not int
                    or not self.offset < self.total_bytes <= (MAX_TEXT_BYTES if text else MAX_IMAGE_BYTES)
                    or (not text and (self.media_type not in IMAGE_MEDIA_TYPES or self.name is not None))
                    or type(self.data) is not str or not 0 < len(self.data) <= RESOURCE_CHUNK_BYTES // 3 * 4):
                raise ValueError("invalid resource upload")
        elif self.total_bytes or self.media_type or self.data or self.name is not None:
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
