"""Private Product-owned catalogs over existing Journal and controlled Source IO.

Concrete Products retain record classes, codecs, kind admission and policy.
These classes share the original namespace/query/publication mechanics only.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Callable, Hashable
from contextlib import suppress
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Generic, Literal, Protocol, Self, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    JournalCodecError,
    JournalDurabilityProfile,
    JournalFileError,
    JournalLoadPolicy,
    JournalRecordCodec,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle._controlled_source_io import (
    file_identity as _file_identity,
)
from loushang.harness.resources.packages.plugin_lifecycle._controlled_source_io import (
    publish_controlled_source,
    read_controlled_source,
    verify_private_controlled_source,
)
from loushang.harness.resources.packages.plugin_lifecycle._exact_product_source import (
    ExactProductSourceFiles,
)
from loushang.harness.resources.packages.plugin_lifecycle.local_source import (
    open_regular_no_follow,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelDependencyV1,
    PackageProductLocalWheelPolicy,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)


class _CatalogRecord(Protocol):
    @property
    def record_revision(self) -> int: ...

    @property
    def store_id(self) -> str: ...

    @property
    def namespace_id(self) -> str: ...

    @property
    def scope_id(self) -> str: ...

    @property
    def wheel_filename(self) -> str: ...

    @property
    def artifact_digest(self) -> str: ...


class _SourceRecord(_CatalogRecord, Protocol):
    @property
    def original_source(self) -> str: ...


class _LegacyRecord(_CatalogRecord, Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def policy_revision(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...

    def to_policy_binding(
        self, source_root: Path
    ) -> PackageProductLocalWheelBindingV1: ...


class _LegacyCandidate(Protocol):
    @property
    def wheel_bytes(self) -> bytes: ...

    @property
    def filename(self) -> str: ...

    @property
    def artifact_digest(self) -> str: ...


CatalogRecordT = TypeVar("CatalogRecordT", bound=_CatalogRecord)
LegacyRecordT = TypeVar("LegacyRecordT", bound=_LegacyRecord)
LegacyCandidateT = TypeVar("LegacyCandidateT", bound=_LegacyCandidate)


class _PluginSourceRecord(_SourceRecord, Protocol):
    @property
    def plugin_id(self) -> str: ...
    @property
    def version(self) -> str: ...
    def policy_binding(
        self, source_root: Path
    ) -> PackageProductLocalWheelBindingV1: ...


RecordT = TypeVar("RecordT", bound=_SourceRecord)
PluginRecordT = TypeVar("PluginRecordT", bound=_PluginSourceRecord)


class _SourceCatalogReadScopes(Generic[CatalogRecordT]):
    path: Path
    _label: str
    _error_factory: Callable[[str], Exception]
    _read_only = False
    _read_errors: tuple[type[BaseException], ...] = (
        JournalFileError,
        JournalCodecError,
        OSError,
        UnicodeError,
        ValueError,
    )

    def records(self) -> tuple[CatalogRecordT, ...]:
        if self._read_only:
            return self.read_records()
        with journal_file_lock(self.path, "exclusive"):
            return self._load_unlocked()

    def read_records(self) -> tuple[CatalogRecordT, ...]:
        """Observe Source policy without creating or repairing owner state."""
        try:
            with journal_file_read_lock(self.path, "shared", create_lock=False):
                return self._load_unlocked(
                    load_policy=JournalLoadPolicy(
                        partial_tail="raise", create_lock=False
                    )
                )
        except self._read_errors as exc:
            raise self._error_factory(
                f"{self._label} binding catalog is corrupt"
            ) from exc

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[CatalogRecordT, ...]:
        raise NotImplementedError


class _PosixSourceCatalog(_SourceCatalogReadScopes[RecordT]):
    _label: str
    _path_label: str
    _error_factory: Callable[[str], Exception]
    _catalog_regular_single_link = False

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
            raise ValueError(f"{self._path_label} catalog paths must be absolute")
        self.path = path
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        self._read_only = read_only
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)

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
            raise self._error_factory(f"{self._label} epoch changed")
        epoch_runtime.assert_current()

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[RecordT, ...]:
        if not self._catalog_present():
            return ()
        records = load_jsonl(
            self.path,
            record_codec=self._record_codec(),
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
            raise self._error_factory(f"{self._label} binding chain changed")
        filenames = tuple(record.wheel_filename for record in records)
        identities = tuple(self._record_key(record) for record in records)
        if len(set(filenames)) != len(records) or len(set(identities)) != len(records):
            raise self._error_factory(f"{self._label} binding is duplicated")
        return records

    def _catalog_present(self) -> bool:
        if not self._catalog_regular_single_link:
            return self.path.exists()
        try:
            present = self.path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(present.st_mode) or present.st_nlink != 1:
            raise self._error_factory(f"{self._label} binding file is unsafe")
        return True

    def _record_codec(self) -> JournalRecordCodec[RecordT]:
        raise NotImplementedError

    def _record_key(self, record: RecordT) -> Hashable:
        raise NotImplementedError


class _StableWheelSource:
    _source_label: str
    _error_factory: Callable[[str], Exception]
    _source_read_errors: tuple[type[BaseException], ...] = (OSError,)
    _source_read_error_suffix = "Source changed"

    def _max_source_bytes(self) -> int:
        raise NotImplementedError

    def _validate_source_name(self, filename: str) -> None:
        pass

    def _read_source(self, source: Path) -> tuple[bytes, str]:
        try:
            self._validate_source_name(source.name)
            descriptor = open_regular_no_follow(source)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if before.st_size <= 0 or before.st_size > self._max_source_bytes():
                    raise self._error_factory(f"{self._source_label} exceeds budget")
                body = handle.read(self._max_source_bytes() + 1)
                after = os.fstat(handle.fileno())
            visible = source.lstat()
        except self._source_read_errors as exc:
            raise self._error_factory(
                f"{self._source_label} {self._source_read_error_suffix}"
            ) from exc
        if (
            not body
            or len(body) > self._max_source_bytes()
            or _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(visible)
        ):
            raise self._error_factory(f"{self._source_label} Source changed")
        digest = sha256(body).hexdigest()
        return body, digest


class _WheelSourceCatalog(_PosixSourceCatalog[RecordT], _StableWheelSource):
    _binding_limit = 125

    def _verify_source_body(self, filename: str, body: bytes) -> None:
        pass

    def _require_new_record(
        self, record: RecordT, records: tuple[RecordT, ...]
    ) -> None:
        pass

    def _admission_conflicts(
        self,
        record: RecordT,
        admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> bool:
        return False

    def _new_record(
        self,
        source: Path,
        digest: str,
        revision: int,
        *,
        admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> RecordT:
        raise NotImplementedError

    def _capture_validated(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
        admission: PackageProductLocalWorkerAdmissionV1 | None = None,
    ) -> RecordT:
        body, digest = self._read_source(source)
        self._verify_source_body(source.name, body)
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
                    or self._admission_conflicts(existing, admission)
                ):
                    raise self._error_factory(f"{self._label} binding conflicts")
                self._verify_controlled(existing)
                return existing
            if len(records) >= self._binding_limit:
                raise self._error_factory(f"{self._label} binding limit reached")
            record = self._new_record(
                source, digest, len(records) + 1, admission=admission
            )
            self._require_new_record(record, records)
            self._publish_controlled(record, body)
            append_jsonl_record(
                self.path,
                record,
                record_codec=self._record_codec(),
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
            )
            epoch_runtime.assert_current()
            return record

    def _open_directory(self, *, create: bool) -> int:
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
                raise self._error_factory(f"{self._label} root is unsafe")
        except BaseException:
            os.close(directory)
            raise
        return directory

    def _publish_controlled(self, record: RecordT, body: bytes) -> None:
        directory = self._open_directory(create=True)
        try:
            publish_controlled_source(
                directory,
                record.wheel_filename,
                body,
                write_error=f"{self._label} write made no progress",
            )
        finally:
            os.close(directory)
        self._verify_controlled(record)

    def _verify_controlled(self, record: RecordT) -> None:
        read_controlled_source(
            self.source_root / record.wheel_filename,
            digest=record.artifact_digest,
            max_bytes=self._max_source_bytes(),
            label=self._label,
            error_factory=self._error_factory,
        )


class _PluginSourcePolicy(Generic[PluginRecordT]):
    _label: str
    _product_id: str
    _error_factory: Callable[[str], Exception]
    source_root: Path
    scope_id: str

    def records(self) -> tuple[PluginRecordT, ...]:
        raise NotImplementedError

    def _verify_controlled(self, record: PluginRecordT) -> None:
        raise NotImplementedError

    def _check_policy_current(self) -> None:
        pass

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != self._product_id
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
        ):
            raise self._error_factory(f"{self._label} Product changed")
        records = self.records()
        existing_ids = {item.plugin_id for item in base.bindings}
        for record in records:
            if record.plugin_id in existing_ids:
                raise self._error_factory(f"{self._label} Plugin id collides")
            self._verify_controlled(record)
        self._check_policy_current()
        return replace(
            base,
            bindings=tuple(
                sorted(
                    (
                        *base.bindings,
                        *(item.policy_binding(self.source_root) for item in records),
                    ),
                    key=lambda item: item.source_identity,
                )
            ),
        )


class _PluginWheelSourceCatalog(
    _WheelSourceCatalog[PluginRecordT], _PluginSourcePolicy[PluginRecordT]
):
    def _record_key(self, record: PluginRecordT) -> Hashable:
        return record.plugin_id, record.version


class _DependencySourceRecord(_SourceRecord, Protocol):
    @property
    def project_name(self) -> str: ...
    @property
    def version(self) -> str: ...
    def policy_dependency(
        self, source_root: Path
    ) -> PackageProductLocalWheelDependencyV1: ...


DependencyRecordT = TypeVar("DependencyRecordT", bound=_DependencySourceRecord)


class _DependencyWheelSourceCatalog(_WheelSourceCatalog[DependencyRecordT]):
    _product_id: str
    _source_read_errors = (OSError, ValueError)
    _source_read_error_suffix = "Source changed or is invalid"
    _binding_limit = 128

    def _directory_name(self) -> str:
        raise NotImplementedError

    def _open_directory(self, *, create: bool) -> int:
        root_fd = super()._open_directory(create=create)
        try:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(self._directory_name(), 0o700, dir_fd=root_fd)
            directory_fd = os.open(
                self._directory_name(),
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
                raise self._error_factory("Dependency Wheel directory is unsafe")
        except BaseException:
            os.close(directory_fd)
            raise
        return directory_fd

    def _verify_controlled(self, record: DependencyRecordT) -> None:
        directory = self._open_directory(create=False)
        os.close(directory)
        body = read_controlled_source(
            self.source_root / self._directory_name() / record.wheel_filename,
            digest=record.artifact_digest,
            max_bytes=self._max_source_bytes(),
            label=self._label,
            error_factory=self._error_factory,
        )
        self._verify_source_body(record.wheel_filename, body)

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != self._product_id
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
        ):
            raise self._error_factory("Dependency Wheel Product changed")
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


class _WindowsWorkerRecord(_PluginSourceRecord, Protocol):
    @property
    def admission(self) -> PackageProductLocalWorkerAdmissionV1: ...
    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> Self: ...


WindowsRecordT = TypeVar("WindowsRecordT", bound=_WindowsWorkerRecord)


class _WindowsWorkerSourceCatalog(
    _StableWheelSource, _PluginSourcePolicy[WindowsRecordT]
):
    _receipt_io: WindowsPrivateReceiptIO
    _source_files: ExactProductSourceFiles
    _record_type: type[WindowsRecordT]
    _receipt_write_maximum: int
    _publication_label: str

    def _max_record_bytes(self) -> int:
        raise NotImplementedError

    def _new_record(
        self,
        source: Path,
        digest: str,
        revision: int,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> WindowsRecordT:
        raise NotImplementedError

    def _check_policy_current(self) -> None:
        self._assert_epoch()

    def __init__(
        self,
        *,
        epoch_runtime: PackageProductWindowsFencedRuntimeOwner,
        state_root: Path,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
    ) -> None:
        if (
            not isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
            or os.name != "nt"
            or (not state_root.is_absolute())
            or (not source_root.is_absolute())
            or (epoch_runtime.registry.store_id != store_id)
            or (epoch_runtime.prepare_product_state_root() != state_root)
            or (epoch_runtime.prepare_product_source_root() != source_root)
        ):
            raise self._error_factory(f"{self._label} Product roots changed")
        switch = epoch_runtime.cutover_result.switch_receipt
        if switch is None or switch.namespace_id != namespace_id:
            raise self._error_factory(f"{self._label} Product epoch changed")
        self.epoch_runtime = epoch_runtime
        self.state_root = state_root
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        epoch_runtime.assert_current()

    def _capture_validated(
        self, source: Path, *, admission: PackageProductLocalWorkerAdmissionV1
    ) -> WindowsRecordT:
        body, digest = self._read_source(source)
        records = self._records(allow_pending_stage=True)
        existing = next(
            (item for item in records if item.wheel_filename == source.name), None
        )
        if existing is not None:
            if (
                existing.artifact_digest != digest
                or existing.original_source != str(source)
                or existing.admission != admission
            ):
                raise self._error_factory(f"{self._label} binding conflicts")
            self.verify_record(existing)
            return existing
        if len(records) >= 125:
            raise self._error_factory(f"{self._label} binding limit reached")
        record = self._new_record(source, digest, len(records) + 1, admission=admission)
        receipt_bytes = canonical_json_bytes(record.to_dict())
        if len(receipt_bytes) > self._max_record_bytes():
            raise self._error_factory(f"{self._label} binding exceeds budget")
        try:
            self._source_files.publish_windows(
                self.source_root,
                filename=record.wheel_filename,
                body=body,
                label=self._publication_label,
            )
            self._assert_epoch()
            self._receipt_io.write_private_receipt(
                self._record_path(record.record_revision),
                receipt_bytes,
                maximum_bytes=self._receipt_write_maximum,
            )
        except self._receipt_io.error_type as exc:
            # A competing writer may have won; only exact native replay is admitted.
            current = self.records()
            winner = next(
                (item for item in current if item.wheel_filename == source.name), None
            )
            if winner is not None and winner == record:
                self.verify_record(winner)
                return winner
            raise self._error_factory(
                f"{self._label} binding revision conflicts"
            ) from exc
        self._assert_epoch()
        self.verify_record(record)
        return record

    def records(self) -> tuple[WindowsRecordT, ...]:
        return self._records(allow_pending_stage=False)

    def verify_record(self, record: WindowsRecordT) -> None:
        """Reopen one exact receipt and its Product-controlled Wheel bytes."""
        if not isinstance(record, self._record_type) or record not in self.records():
            raise self._error_factory(f"{self._label} binding changed")
        self._verify_controlled(record)
        self._assert_epoch()

    def _records(self, *, allow_pending_stage: bool) -> tuple[WindowsRecordT, ...]:
        self._assert_epoch()
        records: list[WindowsRecordT] = []
        missing = False
        try:
            for revision in range(1, 127):
                raw = self._receipt_io.read_private_receipt(
                    self._record_path(revision),
                    maximum_bytes=self._max_record_bytes(),
                    allow_unpublished_stage=allow_pending_stage,
                )
                if revision == 126:
                    if raw is not None:
                        raise self._error_factory(
                            f"{self._label} binding limit was exceeded"
                        )
                    break
                if raw is None:
                    missing = True
                    continue
                if missing:
                    raise self._error_factory(
                        f"{self._label} binding revisions have a gap"
                    )
                record = self._record_type.from_dict(json.loads(raw.decode("utf-8")))
                if (
                    raw != canonical_json_bytes(record.to_dict())
                    or record.record_revision != revision
                    or record.store_id != self.store_id
                    or (record.namespace_id != self.namespace_id)
                    or (record.scope_id != self.scope_id)
                ):
                    raise self._error_factory(f"{self._label} binding chain changed")
                records.append(record)
        except (
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            self._receipt_io.error_type,
        ) as exc:
            raise self._error_factory(
                f"{self._label} binding catalog is corrupt"
            ) from exc
        names = tuple((item.wheel_filename for item in records))
        identities = tuple(((item.plugin_id, item.version) for item in records))
        if len(set(names)) != len(records) or len(set(identities)) != len(records):
            raise self._error_factory(f"{self._label} binding is duplicated")
        self._assert_epoch()
        return tuple(records)

    def _record_path(self, revision: int) -> Path:
        return self.state_root / f"external-worker-binding-{revision:03d}.json"

    def _assert_epoch(self) -> None:
        if (
            self.epoch_runtime.registry.store_id != self.store_id
            or self.epoch_runtime.prepare_product_state_root() != self.state_root
            or self.epoch_runtime.prepare_product_source_root() != self.source_root
            or (self.epoch_runtime.cutover_result.switch_receipt is None)
            or (
                self.epoch_runtime.cutover_result.switch_receipt.namespace_id
                != self.namespace_id
            )
        ):
            raise self._error_factory(f"{self._label} Product epoch changed")
        self.epoch_runtime.assert_current()

    def _verify_controlled(self, record: WindowsRecordT) -> None:
        pinned = _PinnedWindowsAuthority.open(self.source_root, read_control=True)
        try:
            with WindowsPrivateDirectoryAcl() as acl:
                acl.validate(pinned.descriptor)
                descriptor = open_windows_regular_file_at(
                    pinned.descriptor,
                    record.wheel_filename,
                    create_new=False,
                    write=False,
                    read_control=True,
                )
                try:
                    acl.validate(descriptor)
                    before = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_nlink != 1
                        or before.st_size > self._max_source_bytes()
                    ):
                        raise self._error_factory(
                            f"{self._label} controlled bytes are unsafe"
                        )
                    body = os.read(descriptor, self._max_source_bytes() + 1)
                    after = os.fstat(descriptor)
                    acl.validate(descriptor)
                finally:
                    os.close(descriptor)
            pinned.assert_visible()
        finally:
            pinned.close()
        if (
            _file_identity(before) != _file_identity(after)
            or len(body) != before.st_size
            or sha256(body).hexdigest() != record.artifact_digest
        ):
            raise self._error_factory(f"{self._label} controlled bytes changed")


__all__: list[str] = []


class _LegacyLocalSourceCatalog(
    _SourceCatalogReadScopes[LegacyRecordT], Generic[LegacyRecordT, LegacyCandidateT]
):
    source_root: Path
    store_id: str
    namespace_id: str
    scope_id: str
    policy_revision: str
    _product_id: str
    _candidate_type: type[LegacyCandidateT]
    _new_binding: Callable[..., LegacyRecordT]
    _max_wheel_bytes: Callable[[], int]
    _wheel_filename_pattern: re.Pattern[str]
    _duplicate_key_hook: Callable[[list[tuple[str, object]]], dict[str, object]]
    _unlocked_durability: JournalDurabilityProfile
    _load_policy: JournalLoadPolicy
    _read_errors: tuple[type[BaseException], ...] = ()

    def publish_candidate(
        self,
        candidate: LegacyCandidateT,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> Path:
        """Stage verified inert bytes atomically under the exact B Source root."""
        if not isinstance(candidate, self._candidate_type):
            raise TypeError("Reacquired legacy Wheel candidate is required")
        if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
            raise TypeError("Fenced Product epoch owner is required")
        switch = epoch_runtime.cutover_result.switch_receipt
        if (
            epoch_runtime.registry.store_id != self.store_id
            or switch is None
            or switch.namespace_id != self.namespace_id
            or (epoch_runtime.prepare_product_source_root() != self.source_root)
        ):
            raise self._error_factory("Legacy Product Source epoch changed")
        body = candidate.wheel_bytes
        if (
            self._wheel_filename_pattern.fullmatch(candidate.filename) is None
            or not isinstance(body, bytes)
            or (not body)
            or (len(body) > self._max_wheel_bytes())
            or (sha256(body).hexdigest() != candidate.artifact_digest)
        ):
            raise self._error_factory("Legacy Wheel candidate is invalid")
        with journal_file_lock(self.path, "exclusive"):
            epoch_runtime.assert_current()
            descriptor = os.open(
                self.source_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                root_before = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(root_before.st_mode)
                    or stat.S_IMODE(root_before.st_mode) & 63
                    or root_before.st_uid != os.geteuid()
                ):
                    raise self._error_factory(
                        "Legacy Product Source root is not private"
                    )
                try:
                    os.stat(
                        candidate.filename, dir_fd=descriptor, follow_symlinks=False
                    )
                except FileNotFoundError:
                    self._publish_missing_candidate(descriptor, candidate, body)
                self._verify_artifact(
                    self.source_root, candidate.filename, candidate.artifact_digest
                )
                with suppress(FileNotFoundError):
                    os.unlink(f".{candidate.filename}.staging", dir_fd=descriptor)
                    os.fsync(descriptor)
                root_after = self.source_root.lstat()
                if (
                    root_before.st_dev,
                    root_before.st_ino,
                    root_before.st_mode,
                    root_before.st_uid,
                ) != (
                    root_after.st_dev,
                    root_after.st_ino,
                    root_after.st_mode,
                    root_after.st_uid,
                ):
                    raise self._error_factory(
                        "Legacy Product Source root changed on disk"
                    )
                epoch_runtime.assert_current()
                return self.source_root / candidate.filename
            finally:
                os.close(descriptor)

    @staticmethod
    def _publish_missing_candidate(
        directory: int, candidate: LegacyCandidateT, body: bytes
    ) -> None:
        publish_controlled_source(
            directory,
            candidate.filename,
            body,
            write_error="Legacy Product Wheel write made no progress",
        )

    def append(
        self,
        candidate: LegacyCandidateT,
        *,
        legacy_source_identity: str,
        legacy_binding_digest: str,
        dependency_lock_digest: str,
        approval_id: str,
        resource_kind: Literal["skill", "prompt", "theme"] = "skill",
    ) -> LegacyRecordT:
        if not isinstance(candidate, self._candidate_type):
            raise TypeError("Reacquired legacy Wheel candidate is required")
        if sha256(candidate.wheel_bytes).hexdigest() != candidate.artifact_digest:
            raise self._error_factory("Legacy Wheel candidate digest changed")
        self._verify_artifact(
            self.source_root, candidate.filename, candidate.artifact_digest
        )
        with journal_file_lock(self.path, "exclusive"):
            records = self._load_unlocked()
            proposed = self._new_binding(
                record_revision=len(records) + 1,
                store_id=self.store_id,
                namespace_id=self.namespace_id,
                scope_id=self.scope_id,
                legacy_source_identity=legacy_source_identity,
                legacy_binding_digest=legacy_binding_digest,
                dependency_lock_digest=dependency_lock_digest,
                policy_revision=self.policy_revision,
                approval_id=approval_id,
                candidate=candidate,
                resource_kind=resource_kind,
            )
            previous = next(
                (item for item in records if item.plugin_id == proposed.plugin_id), None
            )
            if previous is not None:
                ignored = {"recordRevision", "recordId"}
                proposed_payload = {
                    key: value
                    for key, value in proposed.to_dict().items()
                    if key not in ignored
                }
                previous_payload = {
                    key: value
                    for key, value in previous.to_dict().items()
                    if key not in ignored
                }
                if proposed_payload != previous_payload:
                    raise self._error_factory(
                        "Legacy Product binding conflicts with prior approval"
                    )
                self._require_accepted_binding(previous)
                return previous
            self._require_accepted_binding(proposed)
            append_jsonl_record(
                self.path,
                proposed,
                record_codec=self._record_codec(),
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return proposed

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        return self._extend_policy(base, self.records())

    def read_extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        """Build the same policy from strict, non-repairing Source evidence."""
        return self._extend_policy(base, self.read_records())

    def _extend_policy(
        self, base: PackageProductLocalWheelPolicy, records: tuple[LegacyRecordT, ...]
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != self._product_id
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
            or (base.policy_revision != self.policy_revision)
        ):
            raise self._error_factory("Legacy Product policy authority changed")
        used_ids = {item.plugin_id for item in base.bindings}
        for record in records:
            self._require_accepted_binding(record)
            if record.plugin_id in used_ids:
                raise self._error_factory("Legacy Product Plugin identity collides")
            used_ids.add(record.plugin_id)
            self._verify_artifact(
                self.source_root, record.wheel_filename, record.artifact_digest
            )
        return replace(
            base,
            bindings=tuple(
                sorted(
                    (
                        *base.bindings,
                        *(item.to_policy_binding(self.source_root) for item in records),
                    ),
                    key=lambda item: item.source_identity,
                )
            ),
        )

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[LegacyRecordT, ...]:
        if not self.path.exists():
            return ()
        try:
            loaded: JsonlSnapshot[None, LegacyRecordT] = load_jsonl(
                self.path,
                record_codec=self._record_codec(),
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=load_policy or self._load_policy,
            )
            records = loaded.records
            self._require_unique_json_keys(self.path)
            identities: set[str] = set()
            for revision, record in enumerate(records, start=1):
                if (
                    record.record_revision != revision
                    or record.plugin_id in identities
                    or record.store_id != self.store_id
                    or (record.namespace_id != self.namespace_id)
                    or (record.scope_id != self.scope_id)
                    or (record.policy_revision != self.policy_revision)
                ):
                    raise ValueError("Legacy Product binding chain changed")
                identities.add(record.plugin_id)
            return records
        except (
            JournalFileError,
            JournalCodecError,
            OSError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise self._error_factory(
                "Legacy Product binding catalog is corrupt"
            ) from exc

    def _require_accepted_binding(self, record: LegacyRecordT) -> None:
        raise NotImplementedError

    def _record_codec(self) -> JournalRecordCodec[LegacyRecordT]:
        raise NotImplementedError

    def _verify_artifact(self, root: Path, filename: str, expected_digest: str) -> None:
        verify_private_controlled_source(
            root,
            filename,
            expected_digest,
            label=self._label,
            error_factory=self._error_factory,
            filename_pattern=self._wheel_filename_pattern,
            max_bytes=self._max_wheel_bytes,
        )

    def _require_unique_json_keys(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=self._duplicate_key_hook)
