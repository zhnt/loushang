"""Read-only, fenced preview of Coding Arch Installation private data.

This preview grants no deletion authority. The eventual domain owner must
recapture the target under the same Product fence before a confirmed mutation.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
)

_OWNER_ID = "coding.arch.private-data:posix-v1"
_MAX_ENTRIES = 4096
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataMemberV1:
    """One exact file or directory observed beneath an Installation root."""

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
            raise ValueError("Coding Arch private-data member is invalid")
        if self.kind == "directory":
            if self.content_sha256 is not None or not stat.S_ISDIR(self.identity[2]):
                raise ValueError("Directory identity or content digest is invalid")
        elif not _valid_digest(self.content_sha256) or not stat.S_ISREG(
            self.identity[2]
        ):
            raise ValueError("File identity or content digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "contentSha256": self.content_sha256,
            "identity": list(self.identity),
            "kind": self.kind,
            "relativePath": self.relative_path,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataMemberV1:
        if type(value) is not dict or set(value) != {
            "contentSha256",
            "identity",
            "kind",
            "relativePath",
        }:
            raise ValueError("Coding Arch private-data member fields are invalid")
        identity = value["identity"]
        if type(identity) is not list or len(identity) != 5:
            raise ValueError("Coding Arch private-data member identity is invalid")
        return cls(
            relative_path=value["relativePath"],
            kind=value["kind"],
            identity=tuple(identity),
            content_sha256=value["contentSha256"],
        )


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataTargetSnapshotV1:
    """Bounded, serializable observation for commit-time recapture."""

    root_path_digest: str
    root_identity: tuple[int, int, int, int, int] | None
    members: tuple[CodingArchPrivateDataMemberV1, ...]

    def __post_init__(self) -> None:
        if not _valid_digest(self.root_path_digest) or (
            self.root_identity is not None
            and (
                not _valid_identity(self.root_identity)
                or not stat.S_ISDIR(self.root_identity[2])
            )
        ):
            raise ValueError("Coding Arch private-data target identity is invalid")
        if self.root_identity is None and self.members:
            raise ValueError("Absent private-data root cannot have members")
        if len(self.members) > _MAX_ENTRIES or self.members != tuple(
            sorted(self.members, key=lambda item: item.relative_path)
        ):
            raise ValueError("Coding Arch private-data members are not sorted")
        paths = tuple(item.relative_path for item in self.members)
        if len(paths) != len(set(paths)):
            raise ValueError("Coding Arch private-data members repeat")
        directories = {
            item.relative_path for item in self.members if item.kind == "directory"
        }
        if any(
            "/" in item.relative_path
            and item.relative_path.rsplit("/", 1)[0] not in directories
            for item in self.members
        ):
            raise ValueError("Coding Arch private-data member parent is missing")

    @property
    def target_id(self) -> str:
        if self.root_identity is None:
            return "absent:" + self.root_path_digest
        return (
            "present:"
            + sha256(
                b"loushang.coding-arch-private-data-preview/v1\0"
                + canonical_json_bytes(self.to_dict())
            ).hexdigest()
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "members": [member.to_dict() for member in self.members],
            "rootIdentity": (
                None if self.root_identity is None else list(self.root_identity)
            ),
            "rootPathDigest": self.root_path_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataTargetSnapshotV1:
        if type(value) is not dict or set(value) != {
            "members",
            "rootIdentity",
            "rootPathDigest",
        }:
            raise ValueError("Coding Arch private-data target fields are invalid")
        raw_members = value["members"]
        raw_identity = value["rootIdentity"]
        if type(raw_members) is not list or (
            raw_identity is not None
            and (type(raw_identity) is not list or len(raw_identity) != 5)
        ):
            raise ValueError("Coding Arch private-data target is invalid")
        return cls(
            root_path_digest=value["rootPathDigest"],
            root_identity=(None if raw_identity is None else tuple(raw_identity)),
            members=tuple(
                CodingArchPrivateDataMemberV1.from_dict(item) for item in raw_members
            ),
        )


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataDeletionPreview:
    """Capture an exact target without creating files or authorizing deletion."""

    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if (
            not isinstance(self.layout, CodingPluginLifecycleStateLayout)
            or not isinstance(self.product, PosixLocalWheelProductSessionOwner)
            or self.product.policy.product_id != "coding"
            or self.layout
            != resolve_coding_plugin_lifecycle_state_layout(self.product.workspace)
            or self.product.policy.project_scope_id != self.layout.scope_id
            or self.product.epoch_runtime.registry.store_id
            != resolve_coding_package_epoch_layout(self.layout).store_id
        ):
            raise ValueError("Coding Arch private-data Product owner is not bound")

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        target = self.snapshot_for(key)
        return PluginPrivateDataDeletionPlanV1(
            installation_key=key, owner_id=_OWNER_ID, target_id=target.target_id
        )

    def snapshot_for(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataTargetSnapshotV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        with self._offline():
            return _capture_target_snapshot(
                root, private_base=self.layout.private_data_base
            )

    @contextmanager
    def _offline(self) -> Iterator[None]:
        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise ValueError("Coding Arch private-data Product runtime is active")
            self.product.assert_root_gc_authority_current()
            with self.product.gc_gate.guard():
                yield
            self.product.assert_root_gc_authority_current()


def _capture_target_snapshot(
    root: Path, *, private_base: Path
) -> CodingArchPrivateDataTargetSnapshotV1:
    base = private_base.absolute()
    relative = root.absolute().relative_to(base)
    path_digest = sha256(os.fsencode(str(root))).hexdigest()
    absent = CodingArchPrivateDataTargetSnapshotV1(path_digest, None, ())
    current = base
    try:
        base_metadata = current.lstat()
    except FileNotFoundError:
        return absent
    if not stat.S_ISDIR(base_metadata.st_mode):
        raise ValueError("Coding Arch private-data root is unsafe")
    for part in relative.parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return absent
        if not stat.S_ISDIR(metadata.st_mode) or (
            os.name == "posix"
            and (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077)
        ):
            raise ValueError("Coding Arch private-data root is unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = os.open(root, flags)
    try:
        root_identity = _identity(os.fstat(root_fd))
        if root_identity != _identity(root.lstat()):
            raise ValueError("Coding Arch private-data root changed")
        entries: list[CodingArchPrivateDataMemberV1] = []
        total_bytes = 0
        for current_path, directory_names, file_names, directory_fd in os.fwalk(
            ".", dir_fd=root_fd, follow_symlinks=False
        ):
            for name in sorted((*directory_names, *file_names)):
                if len(entries) >= _MAX_ENTRIES:
                    raise ValueError("Coding Arch private-data preview is too large")
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                relative_name = (Path(current_path) / name).as_posix()
                if stat.S_ISDIR(metadata.st_mode):
                    entries.append(
                        CodingArchPrivateDataMemberV1(
                            relative_name, "directory", _identity(metadata)
                        )
                    )
                    continue
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ValueError("Coding Arch private-data member is unsafe")
                if metadata.st_size > _MAX_FILE_BYTES:
                    raise ValueError("Coding Arch private-data preview is too large")
                file_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
                try:
                    if _identity(os.fstat(file_fd)) != _identity(metadata):
                        raise ValueError("Coding Arch private-data member changed")
                    digest = sha256()
                    size = 0
                    while chunk := os.read(file_fd, 1024 * 1024):
                        size += len(chunk)
                        total_bytes += len(chunk)
                        if size > _MAX_FILE_BYTES or total_bytes > _MAX_TOTAL_BYTES:
                            raise ValueError(
                                "Coding Arch private-data preview is too large"
                            )
                        digest.update(chunk)
                    if (
                        _identity(os.fstat(file_fd)) != _identity(metadata)
                        or size != metadata.st_size
                    ):
                        raise ValueError("Coding Arch private-data member changed")
                finally:
                    os.close(file_fd)
                if _identity(
                    os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                ) != _identity(metadata):
                    raise ValueError("Coding Arch private-data member changed")
                entries.append(
                    CodingArchPrivateDataMemberV1(
                        relative_name,
                        "file",
                        _identity(metadata),
                        digest.hexdigest(),
                    )
                )
        if root_identity != _identity(root.lstat()):
            raise ValueError("Coding Arch private-data root changed")
        return CodingArchPrivateDataTargetSnapshotV1(
            root_path_digest=path_digest,
            root_identity=root_identity,
            members=tuple(sorted(entries, key=lambda item: item.relative_path)),
        )
    finally:
        os.close(root_fd)


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _valid_identity(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) == 5
        and all(type(item) is int and item >= 0 for item in value)
    )


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "CodingArchPrivateDataDeletionPreview",
    "CodingArchPrivateDataMemberV1",
    "CodingArchPrivateDataTargetSnapshotV1",
]
