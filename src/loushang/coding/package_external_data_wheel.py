"""Fenced Coding Product authorization for one narrow local data Wheel shape."""

from __future__ import annotations

import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalLoadPolicy,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.local_source import (
    open_regular_no_follow,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)

_WHEEL_NAME = re.compile(r"(?P<plugin>[a-z][a-z0-9]*)-(?P<version>[0-9]+(?:\.[0-9]+){0,2})-py3-none-any\.whl\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_FILENAME = 180
_CHUNK_SIZE = 64 * 1024


class CodingExternalDataWheelError(RuntimeError):
    """External data Wheel Source was not safely admitted."""


@dataclass(frozen=True, slots=True)
class CodingExternalDataWheelBindingV1:
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    original_source: str
    wheel_filename: str
    plugin_id: str
    version: str
    artifact_digest: str
    record_id: str

    def __post_init__(self) -> None:
        match = _WHEEL_NAME.fullmatch(self.wheel_filename)
        if (
            type(self.record_revision) is not int
            or self.record_revision < 1
            or not self.store_id
            or _DIGEST.fullmatch(self.namespace_id) is None
            or not self.scope_id
            or not Path(self.original_source).is_absolute()
            or os.path.normpath(self.original_source) != self.original_source
            or match is None
            or len(self.wheel_filename) > _MAX_WHEEL_FILENAME
            or self.plugin_id != match["plugin"]
            or self.version != match["version"]
            or _DIGEST.fullmatch(self.artifact_digest) is None
            or _DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError("External data Wheel binding is invalid")
        if self.record_id != sha256(canonical_json_bytes(self._identity())).hexdigest():
            raise ValueError("External data Wheel binding identity changed")

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
    ) -> CodingExternalDataWheelBindingV1:
        match = _WHEEL_NAME.fullmatch(wheel_filename)
        if match is None:
            raise ValueError("External data Wheel filename is unsupported")
        fields = {
            "recordRevision": record_revision,
            "storeId": store_id,
            "namespaceId": namespace_id,
            "scopeId": scope_id,
            "originalSource": original_source,
            "wheelFilename": wheel_filename,
            "pluginId": match["plugin"],
            "version": match["version"],
            "artifactDigest": artifact_digest,
        }
        return cls(
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            original_source=original_source,
            wheel_filename=wheel_filename,
            plugin_id=match["plugin"],
            version=match["version"],
            artifact_digest=artifact_digest,
            record_id=sha256(canonical_json_bytes(fields)).hexdigest(),
        )

    def _identity(self) -> dict[str, object]:
        return {key: value for key, value in self.to_dict().items() if key != "recordId"}

    def to_dict(self) -> dict[str, object]:
        return {
            "recordRevision": self.record_revision,
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "originalSource": self.original_source,
            "wheelFilename": self.wheel_filename,
            "pluginId": self.plugin_id,
            "version": self.version,
            "artifactDigest": self.artifact_digest,
            "recordId": self.record_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingExternalDataWheelBindingV1:
        keys = {
            "recordRevision", "storeId", "namespaceId", "scopeId",
            "originalSource", "wheelFilename", "pluginId", "version",
            "artifactDigest", "recordId",
        }
        if type(value) is not dict or set(value) != keys:
            raise ValueError("External data Wheel binding record is invalid")
        return cls(
            record_revision=value["recordRevision"],
            store_id=value["storeId"],
            namespace_id=value["namespaceId"],
            scope_id=value["scopeId"],
            original_source=value["originalSource"],
            wheel_filename=value["wheelFilename"],
            plugin_id=value["pluginId"],
            version=value["version"],
            artifact_digest=value["artifactDigest"],
            record_id=value["recordId"],
        )

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return PackageProductLocalWheelBindingV1(
            source_identity=str(source_root / self.wheel_filename),
            requested_package=f"{self.plugin_id}=={self.version}",
            plugin_id=self.plugin_id,
            artifact_digest=self.artifact_digest,
            plugin_manifest_path=f"{self.plugin_id}/plugin.json",
            source_trust_class="local-data-only",
        )


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingExternalDataWheelBindingV1.to_dict,
    decoder=CodingExternalDataWheelBindingV1.from_dict,
)


class CodingExternalDataWheelCatalog:
    """Append-only Product Source authorization for a fenced B namespace."""

    def __init__(
        self,
        path: Path,
        *,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
    ) -> None:
        if not path.is_absolute() or not source_root.is_absolute():
            raise ValueError("External data Wheel catalog paths must be absolute")
        self.path = path
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)

    def capture(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> CodingExternalDataWheelBindingV1:
        self._assert_epoch(epoch_runtime)
        if (
            not source.is_absolute()
            or os.path.normpath(str(source)) != str(source)
            or source.is_relative_to(self.source_root)
            or _WHEEL_NAME.fullmatch(source.name) is None
            or len(source.name) > _MAX_WHEEL_FILENAME
        ):
            raise CodingExternalDataWheelError("External data Wheel Source is invalid")
        try:
            descriptor = open_regular_no_follow(source)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if before.st_size <= 0 or before.st_size > _MAX_WHEEL_BYTES:
                    raise CodingExternalDataWheelError("External data Wheel exceeds budget")
                body = handle.read(_MAX_WHEEL_BYTES + 1)
                after = os.fstat(handle.fileno())
            visible = source.lstat()
        except OSError as exc:
            raise CodingExternalDataWheelError("External data Wheel Source changed") from exc
        if (
            not body
            or len(body) > _MAX_WHEEL_BYTES
            or _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(visible)
        ):
            raise CodingExternalDataWheelError("External data Wheel Source changed")
        digest = sha256(body).hexdigest()
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
                    raise CodingExternalDataWheelError("External data Wheel binding conflicts")
                self._verify_controlled(existing)
                return existing
            if len(records) >= 125:
                raise CodingExternalDataWheelError("External data Wheel binding limit reached")
            record = CodingExternalDataWheelBindingV1.create(
                record_revision=len(records) + 1,
                store_id=self.store_id,
                namespace_id=self.namespace_id,
                scope_id=self.scope_id,
                original_source=str(source),
                wheel_filename=source.name,
                artifact_digest=digest,
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

    def records(self) -> tuple[CodingExternalDataWheelBindingV1, ...]:
        with journal_file_lock(self.path, "exclusive"):
            return self._load_unlocked()

    def verify_record(self, record: CodingExternalDataWheelBindingV1) -> None:
        """Recheck a catalog record's controlled Source bytes without mutation."""

        if (
            not isinstance(record, CodingExternalDataWheelBindingV1)
            or record.store_id != self.store_id
            or record.namespace_id != self.namespace_id
            or record.scope_id != self.scope_id
            or record not in self.records()
        ):
            raise CodingExternalDataWheelError("External data Wheel binding changed")
        self._verify_controlled(record)

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != "coding"
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
        ):
            raise CodingExternalDataWheelError("External data Wheel Product changed")
        records = self.records()
        existing_ids = {item.plugin_id for item in base.bindings}
        for record in records:
            if record.plugin_id in existing_ids:
                raise CodingExternalDataWheelError("External data Wheel Plugin id collides")
            self._verify_controlled(record)
        return replace(
            base,
            bindings=tuple(sorted(
                (*base.bindings, *(item.policy_binding(self.source_root) for item in records)),
                key=lambda item: item.source_identity,
            )),
        )

    def _assert_epoch(self, epoch_runtime: PackageProductPosixFencedRuntimeOwner) -> None:
        switch = epoch_runtime.cutover_result.switch_receipt
        if (
            epoch_runtime.registry.store_id != self.store_id
            or switch is None
            or switch.namespace_id != self.namespace_id
            or epoch_runtime.prepare_product_source_root() != self.source_root
        ):
            raise CodingExternalDataWheelError("External data Wheel epoch changed")
        epoch_runtime.assert_current()

    def _load_unlocked(self) -> tuple[CodingExternalDataWheelBindingV1, ...]:
        if not self.path.exists():
            return ()
        records = load_jsonl(
            self.path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=JournalLoadPolicy(partial_tail="raise"),
        ).records
        if any(
            record.record_revision != index
            or record.store_id != self.store_id
            or record.namespace_id != self.namespace_id
            or record.scope_id != self.scope_id
            for index, record in enumerate(records, start=1)
        ):
            raise CodingExternalDataWheelError("External data Wheel binding chain changed")
        filenames = tuple(record.wheel_filename for record in records)
        identities = tuple((record.plugin_id, record.version) for record in records)
        if len(set(filenames)) != len(records) or len(set(identities)) != len(records):
            raise CodingExternalDataWheelError("External data Wheel binding is duplicated")
        return records

    def _publish_controlled(
        self, record: CodingExternalDataWheelBindingV1, body: bytes
    ) -> None:
        directory = os.open(
            self.source_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            root = os.fstat(directory)
            if (
                not stat.S_ISDIR(root.st_mode)
                or stat.S_IMODE(root.st_mode) & 0o077
                or root.st_uid != os.geteuid()
            ):
                raise CodingExternalDataWheelError("External data Wheel root is unsafe")
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
                        raise OSError("External data Wheel write made no progress")
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

    def _verify_controlled(self, record: CodingExternalDataWheelBindingV1) -> None:
        descriptor = open_regular_no_follow(self.source_root / record.wheel_filename)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_size > _MAX_WHEEL_BYTES
            ):
                raise CodingExternalDataWheelError("External data Wheel bytes are unsafe")
            body = handle.read(_MAX_WHEEL_BYTES + 1)
            after = os.fstat(handle.fileno())
        if (
            _file_identity(before) != _file_identity(after)
            or sha256(body).hexdigest() != record.artifact_digest
        ):
            raise CodingExternalDataWheelError("External data Wheel bytes changed")


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
    "CodingExternalDataWheelBindingV1",
    "CodingExternalDataWheelCatalog",
    "CodingExternalDataWheelError",
]
