"""Fenced, inert custody for exact local dependency Wheel Sources.

This catalog only pins bytes for Product resolution. It grants no Plugin root
admission, Resource consumption, or executable authority.
"""

from __future__ import annotations

import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import Version

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    append_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.local_source import (
    open_regular_no_follow,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerificationError,
    inspect_package_wheel_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelDependencyV1,
    PackageProductLocalWheelPolicy,
)

_WHEEL_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.whl\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_FILENAME = 180
_DIRECTORY = "dependencies"
_INSPECTION_BUDGET = PackageInspectionBudgetV1(
    max_entries=128,
    max_total_expanded_bytes=4 * 1024 * 1024,
    max_entry_expanded_bytes=2 * 1024 * 1024,
    max_path_length=512,
    max_path_components=32,
    max_metadata_bytes=128 * 1024,
    max_wall_time_ms=5000,
)


class CodingExternalDependencyWheelError(RuntimeError):
    """Dependency Source custody or its durable binding could not be proved."""


def _wheel_identity(filename: str) -> tuple[str, str]:
    if (
        not isinstance(filename, str)
        or len(filename) > _MAX_WHEEL_FILENAME
        or _WHEEL_FILENAME.fullmatch(filename) is None
    ):
        raise ValueError("Dependency Wheel filename is invalid")
    try:
        project_name, version, _build, _tags = parse_wheel_filename(filename)
    except InvalidWheelFilename as exc:
        raise ValueError("Dependency Wheel filename is invalid") from exc
    return project_name, str(version)


@dataclass(frozen=True, slots=True)
class CodingExternalDependencyWheelBindingV1:
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    original_source: str
    wheel_filename: str
    project_name: str
    version: str
    artifact_digest: str
    record_id: str

    def __post_init__(self) -> None:
        project_name, version = _wheel_identity(self.wheel_filename)
        if (
            type(self.record_revision) is not int
            or self.record_revision < 1
            or not isinstance(self.store_id, str)
            or not self.store_id
            or not isinstance(self.namespace_id, str)
            or _DIGEST.fullmatch(self.namespace_id) is None
            or not isinstance(self.scope_id, str)
            or not self.scope_id
            or not isinstance(self.original_source, str)
            or not Path(self.original_source).is_absolute()
            or os.path.normpath(self.original_source) != self.original_source
            or self.project_name != project_name
            or self.version != version
            or not isinstance(self.artifact_digest, str)
            or _DIGEST.fullmatch(self.artifact_digest) is None
            or not isinstance(self.record_id, str)
            or _DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError("Dependency Wheel binding is invalid")
        if self.record_id != sha256(canonical_json_bytes(self._identity())).hexdigest():
            raise ValueError("Dependency Wheel binding identity changed")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        original_source: str,
        wheel_filename: str,
        artifact_digest: str,
    ) -> CodingExternalDependencyWheelBindingV1:
        project_name, version = _wheel_identity(wheel_filename)
        fields = {
            "recordRevision": record_revision,
            "storeId": store_id,
            "namespaceId": namespace_id,
            "scopeId": scope_id,
            "originalSource": original_source,
            "wheelFilename": wheel_filename,
            "projectName": project_name,
            "version": version,
            "artifactDigest": artifact_digest,
        }
        return cls(
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            original_source=original_source,
            wheel_filename=wheel_filename,
            project_name=project_name,
            version=version,
            artifact_digest=artifact_digest,
            record_id=sha256(canonical_json_bytes(fields)).hexdigest(),
        )

    def _identity(self) -> dict[str, object]:
        return {
            key: value for key, value in self.to_dict().items() if key != "recordId"
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "recordRevision": self.record_revision,
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "originalSource": self.original_source,
            "wheelFilename": self.wheel_filename,
            "projectName": self.project_name,
            "version": self.version,
            "artifactDigest": self.artifact_digest,
            "recordId": self.record_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingExternalDependencyWheelBindingV1:
        keys = {
            "recordRevision",
            "storeId",
            "namespaceId",
            "scopeId",
            "originalSource",
            "wheelFilename",
            "projectName",
            "version",
            "artifactDigest",
            "recordId",
        }
        if type(value) is not dict or set(value) != keys:
            raise ValueError("Dependency Wheel binding record is invalid")
        return cls(
            record_revision=value["recordRevision"],
            store_id=value["storeId"],
            namespace_id=value["namespaceId"],
            scope_id=value["scopeId"],
            original_source=value["originalSource"],
            wheel_filename=value["wheelFilename"],
            project_name=value["projectName"],
            version=value["version"],
            artifact_digest=value["artifactDigest"],
            record_id=value["recordId"],
        )

    def policy_dependency(
        self, source_root: Path
    ) -> PackageProductLocalWheelDependencyV1:
        return PackageProductLocalWheelDependencyV1(
            source_identity=str(source_root / _DIRECTORY / self.wheel_filename),
            project_name=self.project_name,
            version=self.version,
            artifact_digest=self.artifact_digest,
        )


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingExternalDependencyWheelBindingV1.to_dict,
    decoder=CodingExternalDependencyWheelBindingV1.from_dict,
)


class CodingExternalDependencyWheelCatalog:
    """Append-only exact dependency Sources under one fenced Product namespace."""

    def __init__(
        self,
        path: Path,
        *,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        read_only: bool = False,
    ) -> None:
        if not path.is_absolute() or not source_root.is_absolute():
            raise ValueError("Dependency Wheel catalog paths must be absolute")
        self.path = path
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        self._read_only = read_only
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)

    def capture(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> CodingExternalDependencyWheelBindingV1:
        if self._read_only:
            raise CodingExternalDependencyWheelError("Read-only catalog cannot capture")
        self._assert_epoch(epoch_runtime)
        if (
            not source.is_absolute()
            or os.path.normpath(str(source)) != str(source)
            or source.is_relative_to(self.source_root)
        ):
            raise CodingExternalDependencyWheelError(
                "Dependency Wheel Source is invalid"
            )
        try:
            _wheel_identity(source.name)
            descriptor = open_regular_no_follow(source)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if before.st_size <= 0 or before.st_size > _MAX_WHEEL_BYTES:
                    raise CodingExternalDependencyWheelError(
                        "Dependency Wheel exceeds budget"
                    )
                body = handle.read(_MAX_WHEEL_BYTES + 1)
                after = os.fstat(handle.fileno())
            visible = source.lstat()
        except (OSError, ValueError) as exc:
            raise CodingExternalDependencyWheelError(
                "Dependency Wheel Source changed or is invalid"
            ) from exc
        if (
            not body
            or len(body) > _MAX_WHEEL_BYTES
            or _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(visible)
        ):
            raise CodingExternalDependencyWheelError("Dependency Wheel Source changed")
        digest = sha256(body).hexdigest()
        _verify_wheel_body(source.name, body)
        with journal_file_lock(self.path, "exclusive"):
            self._assert_epoch(epoch_runtime)
            records = self._load_unlocked()
            existing = next(
                (item for item in records if item.wheel_filename == source.name), None
            )
            if existing is not None:
                if (
                    existing.artifact_digest != digest
                    or existing.original_source != str(source)
                ):
                    raise CodingExternalDependencyWheelError(
                        "Dependency Wheel binding conflicts"
                    )
                self._verify_controlled(existing)
                return existing
            if len(records) >= 128:
                raise CodingExternalDependencyWheelError(
                    "Dependency Wheel binding limit reached"
                )
            record = CodingExternalDependencyWheelBindingV1.create(
                record_revision=len(records) + 1,
                store_id=self.store_id,
                namespace_id=self.namespace_id,
                scope_id=self.scope_id,
                original_source=str(source),
                wheel_filename=source.name,
                artifact_digest=digest,
            )
            if any(
                item.project_name == record.project_name
                and Version(item.version) == Version(record.version)
                for item in records
            ):
                raise CodingExternalDependencyWheelError(
                    "Dependency Wheel version is already bound"
                )
            self._publish_controlled(record, body)
            append_jsonl_record(
                self.path,
                record,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
            )
            epoch_runtime.assert_current()
            return record

    def records(self) -> tuple[CodingExternalDependencyWheelBindingV1, ...]:
        if self._read_only:
            return self.read_records()
        with journal_file_lock(self.path, "exclusive"):
            return self._load_unlocked()

    def read_records(self) -> tuple[CodingExternalDependencyWheelBindingV1, ...]:
        try:
            with journal_file_read_lock(self.path, "shared", create_lock=False):
                return self._load_unlocked(
                    load_policy=JournalLoadPolicy(
                        partial_tail="raise", create_lock=False
                    )
                )
        except (
            JournalFileError,
            JournalCodecError,
            OSError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise CodingExternalDependencyWheelError(
                "Dependency Wheel binding catalog is corrupt"
            ) from exc

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != "coding"
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
        ):
            raise CodingExternalDependencyWheelError("Dependency Wheel Product changed")
        records = self.records()
        for record in records:
            self._verify_controlled(record)
        return replace(
            base,
            dependencies=tuple(
                sorted(
                    (
                        *base.dependencies,
                        *(item.policy_dependency(self.source_root) for item in records),
                    ),
                    key=lambda item: (item.project_name, item.version),
                )
            ),
        )

    def _assert_epoch(
        self, epoch_runtime: PackageProductPosixFencedRuntimeOwner
    ) -> None:
        switch = epoch_runtime.cutover_result.switch_receipt
        if (
            epoch_runtime.registry.store_id != self.store_id
            or switch is None
            or switch.namespace_id != self.namespace_id
            or epoch_runtime.prepare_product_source_root() != self.source_root
        ):
            raise CodingExternalDependencyWheelError("Dependency Wheel epoch changed")
        epoch_runtime.assert_current()

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[CodingExternalDependencyWheelBindingV1, ...]:
        if not self.path.exists():
            return ()
        records = load_jsonl(
            self.path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=load_policy or JournalLoadPolicy(partial_tail="raise"),
        ).records
        if any(
            record.record_revision != index
            or record.store_id != self.store_id
            or record.namespace_id != self.namespace_id
            or record.scope_id != self.scope_id
            for index, record in enumerate(records, start=1)
        ):
            raise CodingExternalDependencyWheelError(
                "Dependency Wheel binding chain changed"
            )
        filenames = tuple(record.wheel_filename for record in records)
        versions = tuple(
            (record.project_name, Version(record.version)) for record in records
        )
        if len(set(filenames)) != len(records) or len(set(versions)) != len(records):
            raise CodingExternalDependencyWheelError(
                "Dependency Wheel binding is duplicated"
            )
        return records

    def _open_directory(self, *, create: bool) -> int:
        root_fd = os.open(
            self.source_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            root = os.fstat(root_fd)
            if (
                not stat.S_ISDIR(root.st_mode)
                or stat.S_IMODE(root.st_mode) & 0o077
                or root.st_uid != os.geteuid()
            ):
                raise CodingExternalDependencyWheelError(
                    "Dependency Wheel root is unsafe"
                )
            if create:
                with suppress(FileExistsError):
                    os.mkdir(_DIRECTORY, 0o700, dir_fd=root_fd)
            directory_fd = os.open(
                _DIRECTORY,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=root_fd,
            )
        finally:
            os.close(root_fd)
        try:
            directory = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(directory.st_mode)
                or stat.S_IMODE(directory.st_mode) & 0o077
                or directory.st_uid != os.geteuid()
            ):
                raise CodingExternalDependencyWheelError(
                    "Dependency Wheel directory is unsafe"
                )
        except BaseException:
            os.close(directory_fd)
            raise
        return directory_fd

    def _publish_controlled(
        self, record: CodingExternalDependencyWheelBindingV1, body: bytes
    ) -> None:
        directory = self._open_directory(create=True)
        try:
            staging = f".{record.wheel_filename}.staging"
            with suppress(FileNotFoundError):
                os.unlink(staging, dir_fd=directory)
            descriptor = os.open(
                staging,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            try:
                os.fchmod(descriptor, 0o600)
                pending = memoryview(body)
                while pending:
                    written = os.write(descriptor, pending)
                    if written <= 0:
                        raise OSError("Dependency Wheel write made no progress")
                    pending = pending[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                with suppress(FileExistsError):
                    os.link(
                        staging,
                        record.wheel_filename,
                        src_dir_fd=directory,
                        dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                os.fsync(directory)
            finally:
                os.unlink(staging, dir_fd=directory)
                os.fsync(directory)
        finally:
            os.close(directory)
        self._verify_controlled(record)

    def _verify_controlled(
        self, record: CodingExternalDependencyWheelBindingV1
    ) -> None:
        directory = self._open_directory(create=False)
        os.close(directory)
        descriptor = open_regular_no_follow(
            self.source_root / _DIRECTORY / record.wheel_filename
        )
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_size > _MAX_WHEEL_BYTES
            ):
                raise CodingExternalDependencyWheelError(
                    "Dependency Wheel bytes are unsafe"
                )
            body = handle.read(_MAX_WHEEL_BYTES + 1)
            after = os.fstat(handle.fileno())
        if (
            _file_identity(before) != _file_identity(after)
            or sha256(body).hexdigest() != record.artifact_digest
        ):
            raise CodingExternalDependencyWheelError("Dependency Wheel bytes changed")
        _verify_wheel_body(record.wheel_filename, body)


def _verify_wheel_body(filename: str, body: bytes) -> None:
    project_name, version = _wheel_identity(filename)
    try:
        inspected = inspect_package_wheel_bytes(
            body,
            wheel_filename=filename,
            budgets=_INSPECTION_BUDGET,
            max_artifact_bytes=_MAX_WHEEL_BYTES,
        )
    except PackageWheelVerificationError as exc:
        raise CodingExternalDependencyWheelError(
            "Dependency Wheel metadata is invalid"
        ) from exc
    if inspected.distribution != project_name or Version(inspected.version) != Version(
        version
    ):
        raise CodingExternalDependencyWheelError(
            "Dependency Wheel metadata identity changed"
        )


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


__all__ = [
    "CodingExternalDependencyWheelBindingV1",
    "CodingExternalDependencyWheelCatalog",
    "CodingExternalDependencyWheelError",
]
