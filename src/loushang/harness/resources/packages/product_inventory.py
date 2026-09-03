"""Durable Product-owned manifests for correlated Package inventory work."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductUpdateManifestReceiptV1,
)

PACKAGE_PRODUCT_UPDATE_MANIFEST_VERSION = 1
_SHA256_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PackageProductUpdateManifestError(RuntimeError):
    """A durable batch manifest is corrupt or changed on replay."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageProductUpdateManifestV1:
    """One pathless, credential-free snapshot of a Product update batch."""

    binding_id: str
    operation_id: str
    scope: str
    target_refs: tuple[str, ...]
    manifest_id: str
    record_revision: int
    manifest_version: int = PACKAGE_PRODUCT_UPDATE_MANIFEST_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.binding_id, str) or not self.binding_id:
            raise ValueError("Package Product update manifest owner is required")
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ValueError("Package Product update operation id is required")
        if self.scope not in {"user", "project", "session"}:
            raise ValueError("Package Product update manifest scope is invalid")
        if (
            not isinstance(self.target_refs, tuple)
            or tuple(sorted(self.target_refs)) != self.target_refs
            or len(set(self.target_refs)) != len(self.target_refs)
            or any(_SHA256_REF.fullmatch(item) is None for item in self.target_refs)
        ):
            raise ValueError("Package Product update manifest targets are invalid")
        if not isinstance(self.record_revision, int) or self.record_revision < 1:
            raise ValueError("Package Product update manifest revision is invalid")
        if self.manifest_version != PACKAGE_PRODUCT_UPDATE_MANIFEST_VERSION:
            raise ValueError("Unsupported Package Product update manifest")
        if self.manifest_id != _manifest_id(
            binding_id=self.binding_id,
            operation_id=self.operation_id,
            scope=self.scope,
            target_refs=self.target_refs,
            manifest_version=self.manifest_version,
        ):
            raise ValueError("Package Product update manifest identity changed")

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        operation_id: str,
        scope: str,
        target_refs: tuple[str, ...],
        record_revision: int,
    ) -> PackageProductUpdateManifestV1:
        return cls(
            binding_id=binding_id,
            operation_id=operation_id,
            scope=scope,
            target_refs=target_refs,
            manifest_id=_manifest_id(
                binding_id=binding_id,
                operation_id=operation_id,
                scope=scope,
                target_refs=target_refs,
                manifest_version=PACKAGE_PRODUCT_UPDATE_MANIFEST_VERSION,
            ),
            record_revision=record_revision,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingId": self.binding_id,
            "manifestId": self.manifest_id,
            "manifestVersion": self.manifest_version,
            "operationId": self.operation_id,
            "recordRevision": self.record_revision,
            "scope": self.scope,
            "targetRefs": list(self.target_refs),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageProductUpdateManifestV1:
        if not isinstance(value, dict) or set(value) != {
            "bindingId",
            "manifestId",
            "manifestVersion",
            "operationId",
            "recordRevision",
            "scope",
            "targetRefs",
        }:
            raise ValueError("Package Product update manifest record is invalid")
        target_refs = value["targetRefs"]
        if not isinstance(target_refs, list) or any(
            not isinstance(item, str) for item in target_refs
        ):
            raise ValueError("Package Product update manifest targets are invalid")
        binding_id = value["bindingId"]
        operation_id = value["operationId"]
        scope = value["scope"]
        manifest_id = value["manifestId"]
        record_revision = value["recordRevision"]
        manifest_version = value["manifestVersion"]
        if (
            not isinstance(binding_id, str)
            or not isinstance(operation_id, str)
            or not isinstance(scope, str)
            or not isinstance(manifest_id, str)
            or not isinstance(record_revision, int)
            or isinstance(record_revision, bool)
            or not isinstance(manifest_version, int)
            or isinstance(manifest_version, bool)
        ):
            raise ValueError("Package Product update manifest record is invalid")
        return cls(
            binding_id=binding_id,
            operation_id=operation_id,
            scope=scope,
            target_refs=tuple(target_refs),
            manifest_id=manifest_id,
            record_revision=record_revision,
            manifest_version=manifest_version,
        )


def _encode_manifest(record: PackageProductUpdateManifestV1) -> dict[str, object]:
    if not isinstance(record, PackageProductUpdateManifestV1):
        raise TypeError("Package Product update manifest is required")
    return record.to_dict()


def _decode_manifest(value: object) -> PackageProductUpdateManifestV1:
    try:
        return PackageProductUpdateManifestV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package Product update manifest record is invalid",
            code="invalid_package_product_update_manifest",
        ) from exc


PACKAGE_PRODUCT_UPDATE_MANIFEST_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_manifest,
    decoder=_decode_manifest,
)


class PackageProductUpdateManifestJournal:
    """Bind each batch id to exactly one ordered target set."""

    def __init__(self, path: str | Path, *, binding_id: str) -> None:
        if not isinstance(binding_id, str) or not binding_id:
            raise ValueError("Package Product update manifest owner is required")
        self._path = Path(os.path.abspath(Path(path).expanduser()))
        self._binding_id = binding_id
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def bind(
        self,
        *,
        operation_id: str,
        scope: str,
        target_refs: tuple[str, ...],
    ) -> PackageProductUpdateManifestV1:
        with self._exclusive():
            records = self._load_unlocked()
            current = next(
                (item for item in records if item.operation_id == operation_id),
                None,
            )
            proposed = PackageProductUpdateManifestV1.create(
                binding_id=self._binding_id,
                operation_id=operation_id,
                scope=scope,
                target_refs=target_refs,
                record_revision=(
                    len(records) + 1 if current is None else current.record_revision
                ),
            )
            if current is not None:
                if current != proposed:
                    raise self._error(
                        "Package Product update targets changed on replay",
                        code="package_product_update_manifest_conflict",
                    )
                return current
            append_jsonl_record(
                self._path,
                proposed,
                record_codec=PACKAGE_PRODUCT_UPDATE_MANIFEST_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return proposed

    def bind_receipt(
        self,
        *,
        operation_id: str,
        scope: str,
        target_refs: tuple[str, ...],
    ) -> PackageProductUpdateManifestReceiptV1:
        manifest = self.bind(
            operation_id=operation_id,
            scope=scope,
            target_refs=target_refs,
        )
        return PackageProductUpdateManifestReceiptV1.create(
            binding_id=manifest.binding_id,
            operation_id=manifest.operation_id,
            scope=manifest.scope,
            target_refs=manifest.target_refs,
        )

    def records(self) -> tuple[PackageProductUpdateManifestV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _load_unlocked(self) -> tuple[PackageProductUpdateManifestV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageProductUpdateManifestV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_PRODUCT_UPDATE_MANIFEST_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            if any(
                item.record_revision != index
                for index, item in enumerate(records, start=1)
            ) or len({item.operation_id for item in records}) != len(records):
                raise ValueError("Package Product update manifest history is invalid")
            if any(item.binding_id != self._binding_id for item in records):
                raise ValueError("Package Product update manifest owner changed")
            return records
        except (JournalCodecError, JournalFileError, OSError, ValueError) as exc:
            raise self._error(
                "Package Product update manifest journal is corrupt",
                code="package_product_update_manifest_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return self._private_exclusive()

    @contextmanager
    def _private_exclusive(self) -> Iterator[None]:
        try:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _assert_private_storage(self._path)
            with journal_file_lock(
                self._path,
                "exclusive",
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            ):
                _assert_private_storage(self._path)
                yield
        except OSError as exc:
            raise self._error(
                "Package Product update manifest storage is not private",
                code="package_product_update_manifest_storage_unsafe",
            ) from exc

    def _error(self, message: str, *, code: str) -> PackageProductUpdateManifestError:
        return PackageProductUpdateManifestError(message, code=code, path=self._path)


def _manifest_id(
    *,
    binding_id: str,
    operation_id: str,
    scope: str,
    target_refs: tuple[str, ...],
    manifest_version: int,
) -> str:
    payload = {
        "bindingId": binding_id,
        "manifestVersion": manifest_version,
        "operationId": operation_id,
        "scope": scope,
        "targetRefs": list(target_refs),
    }
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _assert_private_storage(path: Path) -> None:
    parent = path.parent
    parent_metadata = parent.lstat()
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent.is_symlink()
        or (os.name == "posix" and parent_metadata.st_mode & 0o077)
        or not _owned_by_current_user(parent_metadata)
    ):
        raise OSError("Manifest parent is not a private directory")
    _assert_private_regular_file(path, required=False)
    _assert_private_regular_file(
        path.with_name(f"{path.name}{DURABLE_LOCKED_JOURNAL.lock_suffix}"),
        required=False,
    )


def _assert_private_regular_file(path: Path, *, required: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise
        return
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_nlink != 1
        or (os.name == "posix" and metadata.st_mode & 0o077)
        or not _owned_by_current_user(metadata)
    ):
        raise OSError("Manifest storage is not a private regular file")


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "geteuid", None)
    return not callable(getuid) or metadata.st_uid == getuid()


__all__ = [
    "PACKAGE_PRODUCT_UPDATE_MANIFEST_CODEC",
    "PACKAGE_PRODUCT_UPDATE_MANIFEST_VERSION",
    "PackageProductUpdateManifestError",
    "PackageProductUpdateManifestJournal",
    "PackageProductUpdateManifestV1",
]
