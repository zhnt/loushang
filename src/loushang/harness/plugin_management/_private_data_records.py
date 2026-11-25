"""Inert private-data value contracts; Product subclasses declare identity policy."""

from __future__ import annotations

import stat
from collections.abc import Callable, Mapping
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
from .records import PluginInstallationKeyV1

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


PRIVATE_DATA_INSTALLATION_KEY_FIELD = RecordField(
    "installation_key",
    decoder=PluginInstallationKeyV1.from_dict,
    encoder=PluginInstallationKeyV1.to_dict,
)


def private_data_identity_digest(domain: bytes, facts: Mapping[str, object]) -> str:
    return sha256(domain + canonical_json_bytes(facts)).hexdigest()


class PrivateDataRecordWire:
    """Encode and admit an exact conventional private-data record envelope."""

    __slots__ = ()
    _wire_schema: ClassVar[RecordSchema]
    _invalid_fields: ClassVar[str]

    @classmethod
    def _bind_wire_schema(cls, *overrides: RecordField) -> RecordSchema:
        cls._wire_schema = RecordSchema.for_dataclass(cls, _unchanged, *overrides)
        return cls._wire_schema

    def to_dict(self) -> dict[str, object]:
        return self._wire_schema.encode(self, sort_keys=True)

    @classmethod
    def _wire_document(cls, value: object) -> dict[str, object]:
        if type(value) is not dict or set(value) != cls._wire_schema.keys:
            raise ValueError(cls._invalid_fields)
        return value

    @classmethod
    def from_dict(cls, value: object) -> Self:
        return cls._wire_schema.decode(cls, cls._wire_document(value))


class PrivateDataRestoreRecordWire(PrivateDataRecordWire):
    """Seal restore evidence with the same fields used to decode its history."""

    __slots__ = ()
    _unsigned_order: ClassVar[tuple[str, ...]]
    record_digest: str

    @classmethod
    def _bind_restore_wire_schema(cls) -> RecordSchema:
        return cls._bind_wire_schema(
            RecordField(
                "installation_key",
                decoder=PluginInstallationKeyV1.from_dict,
                encoder=lambda key: key.to_dict(),
            )
        )

    @classmethod
    def _encode_values(cls, values: Mapping[str, object]) -> dict[str, object]:
        document = {}
        for field in cls._wire_schema.fields:
            if field.attribute in values:
                value = values[field.attribute]
                document[field.wire_key] = (
                    value if field.encoder is None else field.encoder(value)
                )
        return document

    @staticmethod
    def _digest_document(document: dict[str, object]) -> str:
        return private_data_identity_digest(b"", document)

    @classmethod
    def _seal(cls, **values: object) -> Self:
        create: Callable[..., Self] = cls
        digest = cls._digest_document(cls._encode_values(values))
        return create(record_digest=digest, **values)

    def _unsigned(self) -> dict[str, object]:
        document = self._wire_schema.encode(self)
        return {key: document[key] for key in self._unsigned_order}

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned(), "recordDigest": self.record_digest}


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
        return "present:" + private_data_identity_digest(
            self.fingerprint_domain, self.to_dict()
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


class WindowsPrivateArchiveSnapshotRecord(Generic[M]):
    """Validate and serialize an archive's directory, files tree and manifest."""

    __slots__ = ()
    label: ClassVar[str]
    fingerprint_domain: ClassVar[bytes]
    root_path_digest: str
    root_identity: tuple[int, int, int, int, int]
    files: PrivateDataTargetSnapshotV1[M]
    manifest: M

    @classmethod
    def _archive_files_type(cls) -> type[PrivateDataTargetSnapshotV1[M]]:
        raise NotImplementedError

    @classmethod
    def _archive_manifest_type(cls) -> type[M]:
        raise NotImplementedError

    def __post_init__(self) -> None:
        if (
            not _valid_digest(self.root_path_digest)
            or not _valid_identity(self.root_identity)
            or not stat.S_ISDIR(self.root_identity[2])
            or not isinstance(self.files, self._archive_files_type())
            or self.files.root_identity is None
            or not isinstance(self.manifest, self._archive_manifest_type())
            or self.manifest.relative_path != "manifest.json"
            or self.manifest.kind != "file"
        ):
            raise ValueError(f"{self.label} archive snapshot is invalid")

    @property
    def target_id(self) -> str:
        return "present:" + private_data_identity_digest(
            self.fingerprint_domain, self.to_dict()
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "files": self.files.to_dict(),
            "manifest": self.manifest.to_dict(),
            "rootIdentity": list(self.root_identity),
            "rootPathDigest": self.root_path_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != {
            "files",
            "manifest",
            "rootIdentity",
            "rootPathDigest",
        }:
            raise ValueError(f"{cls.label} archive snapshot fields changed")
        identity = value["rootIdentity"]
        if type(identity) is not list or len(identity) != 5:
            raise ValueError(f"{cls.label} archive identity changed")
        make_record: Callable[..., Self] = cls
        return make_record(
            root_path_digest=value["rootPathDigest"],
            root_identity=tuple(identity),
            files=cls._archive_files_type().from_dict(value["files"]),
            manifest=cls._archive_manifest_type().from_dict(value["manifest"]),
        )


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
