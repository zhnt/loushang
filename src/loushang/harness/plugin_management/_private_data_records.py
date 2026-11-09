"""Inert private-data value contracts; Product subclasses declare identity policy."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar, Generic, Literal, Self, TypeVar, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .private_data_deletion import _require_sha256

M = TypeVar("M", bound="PrivateDataMemberV1")


def _unchanged(value: object) -> object:
    return value


_MEMBER_SCHEMA = RecordSchema(
    _unchanged,
    (
        RecordField("content_sha256"),
        RecordField("identity", decoder=tuple, encoder=list),
        RecordField("kind"),
        RecordField("relative_path"),
    ),
)
_TARGET_SCHEMA = RecordSchema(
    _unchanged,
    (
        RecordField(
            "members", encoder=lambda items: [item.to_dict() for item in items]
        ),
        RecordField(
            "root_identity",
            decoder=lambda value: None if value is None else tuple(value),
            encoder=lambda value: None if value is None else list(value),
        ),
        RecordField("root_path_digest"),
    ),
)


@dataclass(frozen=True, slots=True)
class PrivateDataMemberV1:
    """One exact file or directory observed beneath an Installation root."""

    label: ClassVar[str] = "Plugin"
    relative_path: str
    kind: Literal["directory", "file"]
    identity: tuple[int, int, int, int, int]
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        parts = (
            self.relative_path.split("/") if isinstance(self.relative_path, str) else ()
        )
        if (
            not parts
            or any(part in {"", ".", ".."} or "\x00" in part for part in parts)
            or self.kind not in {"directory", "file"}
            or not _valid_identity(self.identity)
        ):
            raise ValueError(f"{self.label} private-data member is invalid")
        if self.kind == "directory":
            if self.content_sha256 is not None or not stat.S_ISDIR(self.identity[2]):
                raise ValueError("Directory identity or content digest is invalid")
        elif not _valid_digest(self.content_sha256) or not stat.S_ISREG(
            self.identity[2]
        ):
            raise ValueError("File identity or content digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return _MEMBER_SCHEMA.encode(self)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != {
            "contentSha256",
            "identity",
            "kind",
            "relativePath",
        }:
            raise ValueError(f"{cls.label} private-data member fields are invalid")
        identity = value["identity"]
        if type(identity) is not list or len(identity) != 5:
            raise ValueError(f"{cls.label} private-data member identity is invalid")
        return _MEMBER_SCHEMA.decode(cls, value)


@dataclass(frozen=True, slots=True)
class PrivateDataTargetSnapshotV1(Generic[M]):
    """Bounded, serializable observation for commit-time recapture."""

    label: ClassVar[str] = "Plugin"
    max_entries: ClassVar[int] = 0
    fingerprint_domain: ClassVar[bytes] = b""

    @classmethod
    def member_from_dict(cls, value: object) -> M:
        raise NotImplementedError

    root_path_digest: str
    root_identity: tuple[int, int, int, int, int] | None
    members: tuple[M, ...]

    def __post_init__(self) -> None:
        if not self.fingerprint_domain or self.max_entries < 1:
            raise TypeError("Private-data snapshot identity policy is not configured")
        if not _valid_digest(self.root_path_digest) or (
            self.root_identity is not None
            and (
                not _valid_identity(self.root_identity)
                or not stat.S_ISDIR(self.root_identity[2])
            )
        ):
            raise ValueError(f"{self.label} private-data target identity is invalid")
        if self.root_identity is None and self.members:
            raise ValueError("Absent private-data root cannot have members")
        if len(self.members) > self.max_entries or self.members != tuple(
            sorted(self.members, key=lambda item: item.relative_path)
        ):
            raise ValueError(f"{self.label} private-data members are not sorted")
        paths = tuple(item.relative_path for item in self.members)
        if len(paths) != len(set(paths)):
            raise ValueError(f"{self.label} private-data members repeat")
        directories = {
            item.relative_path for item in self.members if item.kind == "directory"
        }
        if any(
            "/" in item.relative_path
            and item.relative_path.rsplit("/", 1)[0] not in directories
            for item in self.members
        ):
            raise ValueError(f"{self.label} private-data member parent is missing")

    @property
    def target_id(self) -> str:
        if self.root_identity is None:
            return "absent:" + self.root_path_digest
        return (
            "present:"
            + sha256(
                self.fingerprint_domain + canonical_json_bytes(self.to_dict())
            ).hexdigest()
        )

    def to_dict(self) -> dict[str, object]:
        return _TARGET_SCHEMA.encode(self)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != {
            "members",
            "rootIdentity",
            "rootPathDigest",
        }:
            raise ValueError(f"{cls.label} private-data target fields are invalid")
        raw_members = value["members"]
        raw_identity = value["rootIdentity"]
        if type(raw_members) is not list or (
            raw_identity is not None
            and (type(raw_identity) is not list or len(raw_identity) != 5)
        ):
            raise ValueError(f"{cls.label} private-data target is invalid")

        def construct(
            root_path_digest: str,
            root_identity: tuple[int, int, int, int, int] | None,
            members: list[object],
        ) -> PrivateDataTargetSnapshotV1[M]:
            return cls(
                root_path_digest,
                root_identity,
                tuple(cls.member_from_dict(item) for item in members),
            )

        return cast(Self, _TARGET_SCHEMA.decode(construct, value))


def _valid_identity(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 5
        and all(type(item) is int and item >= 0 for item in value)
    )


def _valid_digest(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        _require_sha256(value, name="private-data digest")
    except ValueError:
        return False
    return True
