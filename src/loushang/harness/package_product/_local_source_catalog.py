"""Private Product-owned catalogs over existing Journal and controlled Source IO.

Concrete Products retain record classes, codecs, kind admission and policy.
The catalogs share binding identities, namespace checks and Source publication.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Generic,
    Literal,
    Protocol,
    Self,
    TypeVar,
    cast,
)

from packaging.version import Version

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
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
from loushang.harness.plugin_management.application import (
    PluginManagementSourceRecordV1,
    PluginManagementSourceSnapshotV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
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
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
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
from loushang.harness.resources.packages.product_legacy_source_wheel import (
    _LegacyLocalWheelFields,
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

from ._legacy_runtime import _LegacyEpoch, matches_epoch_layout

if TYPE_CHECKING:
    from ._application_runtime import FencedSourceCatalogRoots
    from ._legacy_inventory import LegacyInventoryEvidence, _BindingHead
    from ._legacy_local_migration import _AcceptedSource


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

    def _matches_approval(self, accepted: _AcceptedSource) -> bool: ...


CatalogRecordT = TypeVar("CatalogRecordT", bound=_CatalogRecord)
LegacyRecordT = TypeVar("LegacyRecordT", bound=_LegacyRecord)
LegacyCandidateT = TypeVar("LegacyCandidateT", bound=_LegacyLocalWheelFields)
LegacyAcceptanceT = TypeVar("LegacyAcceptanceT", bound="_AcceptedSource")


class _PluginSourceRecord(_SourceRecord, Protocol):
    @property
    def plugin_id(self) -> str: ...
    @property
    def version(self) -> str: ...
    def to_dict(self) -> dict[str, object]: ...
    def policy_binding(
        self, source_root: Path
    ) -> PackageProductLocalWheelBindingV1: ...


_SOURCE_RECORD_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _source_binding_scope_matches(
    record: _SourceRecord,
    *,
    require_strings: bool = False,
) -> bool:
    return (
        type(record.record_revision) is int
        and record.record_revision >= 1
        and (not require_strings or isinstance(record.store_id, str))
        and bool(record.store_id)
        and (not require_strings or isinstance(record.namespace_id, str))
        and _SOURCE_RECORD_DIGEST.fullmatch(record.namespace_id) is not None
        and (not require_strings or isinstance(record.scope_id, str))
        and bool(record.scope_id)
        and (not require_strings or isinstance(record.original_source, str))
        and Path(record.original_source).is_absolute()
        and os.path.normpath(record.original_source) == record.original_source
    )


def plugin_wheel_source_fields_match(
    record: _PluginSourceRecord, match: re.Match[str] | None, *, maximum_filename: int
) -> bool:
    """Check shared identity and path fields of a controlled Plugin Wheel."""
    return (
        _source_binding_scope_matches(record)
        and match is not None
        and len(record.wheel_filename) <= maximum_filename
        and record.plugin_id == match["plugin"]
        and record.version == match["version"]
        and _SOURCE_RECORD_DIGEST.fullmatch(record.artifact_digest) is not None
    )


RecordT = TypeVar("RecordT", bound=_SourceRecord)
PluginRecordT = TypeVar("PluginRecordT", bound=_PluginSourceRecord)


def local_wheel_bindings_in_source_order(
    bindings: Iterable[PackageProductLocalWheelBindingV1],
) -> tuple[PackageProductLocalWheelBindingV1, ...]:
    return tuple(sorted(bindings, key=lambda item: item.source_identity))


def project_local_source_policy_group(
    policy: PackageProductLocalWheelPolicy,
    bindings: Iterable[PackageProductLocalWheelBindingV1],
    *,
    trust_classes: frozenset[str],
) -> tuple[
    tuple[PackageProductLocalWheelBindingV1, ...],
    tuple[PackageProductLocalWheelBindingV1, ...],
]:
    """Return observed bindings and the corresponding existing policy partition."""
    return local_wheel_bindings_in_source_order(bindings), tuple(
        item for item in policy.bindings if item.source_trust_class in trust_classes
    )


def wheel_source_binding_digest(document: Mapping[str, object]) -> str:
    """Hash the canonical record content without the stored digest."""
    fields = {key: value for key, value in document.items() if key != "recordId"}
    return sha256(canonical_json_bytes(fields)).hexdigest()


class _WheelSourceBindingMethods:
    """Encode and authenticate a controlled Wheel using its declared wire fields."""

    __slots__ = ()
    record_id: str
    _binding_schema: ClassVar[RecordSchema]
    _binding_label: ClassVar[str]
    _sort_binding_fields: ClassVar[bool] = False

    @classmethod
    def _seal_binding(cls, **attributes: object) -> Self:
        """Seal the declared wire fields before constructing the nominal record."""
        document: dict[str, object] = {}
        for field in cls._binding_schema.fields:
            if field.attribute == "record_id":
                continue
            value = attributes[field.attribute]
            document[field.wire_key] = (
                value if field.encoder is None else field.encoder(value)
            )
        construct: Callable[..., Self] = cls
        return construct(**attributes, record_id=wheel_source_binding_digest(document))

    def to_dict(self) -> dict[str, object]:
        return self._binding_schema.encode(self, sort_keys=self._sort_binding_fields)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != cls._binding_schema.keys:
            raise ValueError(f"{cls._binding_label} binding record is invalid")
        return cls._binding_schema.decode(cls, value)

    @classmethod
    def _record_codec(cls) -> FunctionalJournalRecordCodec[Self]:
        return FunctionalJournalRecordCodec(encoder=cls.to_dict, decoder=cls.from_dict)

    def _require_binding_identity(self) -> None:
        if self.record_id != wheel_source_binding_digest(self.to_dict()):
            raise ValueError(f"{self._binding_label} binding identity changed")


class _ExternalWheelBindingMethods(_WheelSourceBindingMethods):
    """Seal captured Wheel Source metadata before constructing its nominal receipt."""

    __slots__ = ()
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    original_source: str
    wheel_filename: str
    artifact_digest: str

    @classmethod
    def _wheel_identity_fields(cls, wheel_filename: str) -> dict[str, str]:
        raise NotImplementedError

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
    ) -> Self:
        return cls._seal_binding(
            **cls._wheel_identity_fields(wheel_filename),
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            original_source=original_source,
            wheel_filename=wheel_filename,
            artifact_digest=artifact_digest,
        )


class _DataWheelBindingMethods(_ExternalWheelBindingMethods):
    """Use the controlled Plugin filename as the original binding identity."""

    __slots__ = ()
    plugin_id: str
    version: str
    _wheel_name: ClassVar[re.Pattern[str]]
    _max_wheel_filename: ClassVar[int]
    _data_trust_class: ClassVar[str]

    @classmethod
    def _wheel_identity_fields(cls, wheel_filename: str) -> dict[str, str]:
        return plugin_wheel_identity_fields(
            wheel_filename, cls._wheel_name, cls._binding_label
        )

    def __post_init__(self) -> None:
        if (
            not plugin_wheel_source_fields_match(
                self,
                self._wheel_name.fullmatch(self.wheel_filename),
                maximum_filename=self._max_wheel_filename,
            )
            or _SOURCE_RECORD_DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError(f"{self._binding_label} binding is invalid")
        self._require_binding_identity()

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return project_plugin_wheel_binding(
            self, source_root, trust_class=self._data_trust_class
        )


class _WorkerWheelBindingMethods(_WheelSourceBindingMethods):
    """Validate and seal an inert Worker Wheel Source and its exact admission."""

    __slots__ = ()
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    original_source: str
    wheel_filename: str
    plugin_id: str
    version: str
    artifact_digest: str
    admission: PackageProductLocalWorkerAdmissionV1

    _binding_label = "External Worker Wheel"
    _sort_binding_fields = True
    _wheel_name: ClassVar[re.Pattern[str]]
    _max_wheel_filename: ClassVar[int]

    def __post_init__(self) -> None:
        if not all(
            isinstance(getattr(self, field.attribute), str)
            for field in self._binding_schema.fields
            if field.attribute not in {"record_revision", "admission"}
        ):
            raise ValueError(f"{self._binding_label} binding fields are invalid")
        match = self._wheel_name.fullmatch(self.wheel_filename)
        platform = (
            "windows-amd64"
            if match is not None and match["tag"] == "win_amd64"
            else "linux-x86_64"
        )
        if (
            not plugin_wheel_source_fields_match(
                self, match, maximum_filename=self._max_wheel_filename
            )
            or not isinstance(self.admission, PackageProductLocalWorkerAdmissionV1)
            or self.admission.native_platform != platform
            or _SOURCE_RECORD_DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError(f"{self._binding_label} binding is invalid")
        self._require_binding_identity()

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
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> Self:
        return cls._seal_binding(
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            original_source=original_source,
            wheel_filename=wheel_filename,
            **plugin_wheel_identity_fields(
                wheel_filename, cls._wheel_name, cls._binding_label
            ),
            artifact_digest=artifact_digest,
            admission=admission,
        )

    @classmethod
    def _worker_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            lambda value: value,
            RecordField(
                "admission",
                decoder=PackageProductLocalWorkerAdmissionV1._from_record_payload,
                encoder=PackageProductLocalWorkerAdmissionV1._to_record_payload,
            ),
        )

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return project_plugin_wheel_binding(
            self,
            source_root,
            trust_class="local-worker-candidate",
            admission=self.admission,
        )


def plugin_wheel_identity_fields(
    wheel_filename: str,
    pattern: re.Pattern[str],
    label: str,
) -> dict[str, str]:
    match = pattern.fullmatch(wheel_filename)
    if match is None:
        raise ValueError(f"{label} filename is unsupported")
    return {"plugin_id": match["plugin"], "version": match["version"]}


def project_plugin_wheel_binding(
    record: _PluginSourceRecord,
    source_root: Path,
    *,
    trust_class: str,
    admission: PackageProductLocalWorkerAdmissionV1 | None = None,
) -> PackageProductLocalWheelBindingV1:
    return PackageProductLocalWheelBindingV1(
        source_identity=str(source_root / record.wheel_filename),
        requested_package=f"{record.plugin_id}=={record.version}",
        plugin_id=record.plugin_id,
        artifact_digest=record.artifact_digest,
        plugin_manifest_path=f"{record.plugin_id}/plugin.json",
        source_trust_class=trust_class,
        worker_admission=admission,
    )


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
    _codec: JournalRecordCodec[RecordT]
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
            record_codec=self._codec,
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

    def _record_key(self, record: RecordT) -> Hashable:
        raise NotImplementedError


class _StableWheelSource(Generic[RecordT]):
    _label: str
    _source_label: str
    source_root: Path
    store_id: str
    namespace_id: str
    scope_id: str
    _create_binding: Callable[..., RecordT]
    _persist_admission = False
    _binding_limit = 125
    _error_factory: Callable[[str], Exception]
    _source_read_errors: tuple[type[BaseException], ...] = (OSError,)
    _source_read_error_suffix = "Source changed"
    _wheel_name: re.Pattern[str]
    _max_wheel_filename: int

    def _max_source_bytes(self) -> int:
        raise NotImplementedError

    def _validate_source_name(self, filename: str) -> None:
        pass

    def _new_record(
        self,
        source: Path,
        digest: str,
        revision: int,
        *,
        admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> RecordT:
        extra = {"admission": admission} if self._persist_admission else {}
        return self._create_binding(
            record_revision=revision,
            store_id=self.store_id,
            namespace_id=self.namespace_id,
            scope_id=self.scope_id,
            original_source=str(source),
            wheel_filename=source.name,
            artifact_digest=digest,
            **extra,
        )

    def _is_external_source(self, source: Path) -> bool:
        return (
            source.is_absolute()
            and os.path.normpath(str(source)) == str(source)
            and not source.is_relative_to(self.source_root)
        )

    def _require_worker_capture_source(
        self,
        source: Path,
        admission: PackageProductLocalWorkerAdmissionV1,
        *,
        native_platform: str,
        required_suffix: str = "",
    ) -> None:
        if (
            not isinstance(admission, PackageProductLocalWorkerAdmissionV1)
            or admission.native_platform != native_platform
            or not isinstance(source, Path)
            or not self._is_external_source(source)
            or self._wheel_name.fullmatch(source.name) is None
            or (required_suffix and not source.name.endswith(required_suffix))
            or len(source.name) > self._max_wheel_filename
        ):
            raise self._error_factory(f"{self._source_label} Source is invalid")

    def _existing_capture(
        self,
        records: Sequence[RecordT],
        source: Path,
        digest: str,
        admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> RecordT | None:
        record = next((item for item in records if item.wheel_filename == source.name), None)
        if record is None:
            if len(records) >= self._binding_limit:
                raise self._error_factory(f"{self._label} binding limit reached")
        elif (
            record.artifact_digest != digest
            or record.original_source != str(source)
            or (
                self._persist_admission
                and cast(_WorkerSourceRecord, record).admission != admission
            )
        ):
            raise self._error_factory(f"{self._label} binding conflicts")
        return record

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


class _WheelSourceCatalog(_PosixSourceCatalog[RecordT], _StableWheelSource[RecordT]):
    _read_only_capture_error = "Read-only catalog cannot capture"

    def _admit_capture_source(self, source: Path) -> bool:
        return self._is_external_source(source)

    def _capture_external(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> RecordT:
        self._require_capture_epoch(epoch_runtime)
        if not self._admit_capture_source(source):
            raise self._error_factory(f"{self._source_label} Source is invalid")
        return self._capture_validated(source, epoch_runtime=epoch_runtime)

    def _require_capture_epoch(
        self, epoch_runtime: PackageProductPosixFencedRuntimeOwner
    ) -> None:
        if self._read_only:
            raise self._error_factory(self._read_only_capture_error)
        self._assert_epoch(epoch_runtime)

    def _verify_source_body(self, filename: str, body: bytes) -> None:
        pass

    def _require_new_record(
        self, record: RecordT, records: tuple[RecordT, ...]
    ) -> None:
        pass

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
            existing = self._existing_capture(records, source, digest, admission)
            if existing is not None:
                self._verify_controlled(existing)
                return existing
            record = self._new_record(
                source, digest, len(records) + 1, admission=admission
            )
            self._require_new_record(record, records)
            self._publish_controlled(record, body)
            append_jsonl_record(
                self.path,
                record,
                record_codec=self._codec,
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
            bindings=local_wheel_bindings_in_source_order(
                (
                    *base.bindings,
                    *(item.policy_binding(self.source_root) for item in records),
                )
            ),
        )


class _PluginWheelSourceCatalog(
    _WheelSourceCatalog[PluginRecordT], _PluginSourcePolicy[PluginRecordT]
):
    def _record_key(self, record: PluginRecordT) -> Hashable:
        return record.plugin_id, record.version


class _PosixWorkerSourceCatalog(_PluginWheelSourceCatalog[PluginRecordT]):
    _read_only_capture_error = "Read-only Worker Source cannot capture"
    _catalog_regular_single_link = True
    _persist_admission = True

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> PluginRecordT:
        self._require_capture_epoch(epoch_runtime)
        self._require_worker_capture_source(
            source, admission, native_platform="linux-x86_64"
        )
        return self._capture_validated(
            source, epoch_runtime=epoch_runtime, admission=admission
        )


class _DataWheelSourceCatalog(_PluginWheelSourceCatalog[PluginRecordT]):
    _record_type: type[PluginRecordT]
    _error_factory: type[Exception]
    _product_journal_name: str

    @classmethod
    def for_roots(cls, roots: FencedSourceCatalogRoots, *, read_only: bool = False) -> Self:
        return cls(
            roots.state_root / cls._product_journal_name,
            **roots.identity,
            read_only=read_only,
        )

    def project_policy_group(
        self, policy: PackageProductLocalWheelPolicy, *, trust_class: str
    ) -> tuple[
        tuple[PackageProductLocalWheelBindingV1, ...],
        tuple[PackageProductLocalWheelBindingV1, ...],
    ]:
        """Capture the journal bindings used to decide whether to retain the Product."""
        return project_local_source_policy_group(
            policy,
            (record.policy_binding(self.source_root) for record in self.records()),
            trust_classes=frozenset({trust_class}),
        )

    def _admit_capture_source(self, source: Path) -> bool:
        return (
            super()._admit_capture_source(source)
            and self._wheel_name.fullmatch(source.name) is not None
            and len(source.name) <= self._max_wheel_filename
        )

    def capture(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> PluginRecordT:
        return self._capture_external(source, epoch_runtime=epoch_runtime)

    def verify_record(self, record: PluginRecordT) -> None:
        """Prove selection and controlled bytes of one already admitted binding."""
        if (
            not isinstance(record, self._record_type)
            or record.store_id != self.store_id
            or record.namespace_id != self.namespace_id
            or record.scope_id != self.scope_id
            or record not in self.records()
        ):
            raise self._error_factory(f"{self._label} binding changed")
        self._verify_controlled(record)

    def project_management_source_snapshot(
        self,
        desired_state: PluginDesiredStateLedger,
        *,
        owner_revision_prefix: str,
    ) -> PluginManagementSourceSnapshotV1:
        """Project current controlled sources with committed selections preferred."""

        all_bindings = self.records()
        selected = {
            item.installation_key.plugin_id: item.selection.package_revision
            for item in desired_state.snapshot().installations
            if item.installation_key.product_id == self._product_id
            and item.installation_key.scope_id == self.scope_id
        }
        latest: dict[str, PluginRecordT] = {}
        for item in all_bindings:
            prior = latest.get(item.plugin_id)
            if prior is None or item.record_revision > prior.record_revision:
                latest[item.plugin_id] = item
        for item in all_bindings:
            revision = selected.get(item.plugin_id)
            if (
                revision is not None
                and revision.package_source_identity
                == str(self.source_root / item.wheel_filename)
                and revision.package_content_digest == item.artifact_digest
            ):
                latest[item.plugin_id] = item
        records = []
        for item in latest.values():
            availability: Literal["available", "unavailable"]
            try:
                self.verify_record(item)
            except (self._error_factory, OSError):
                availability = "unavailable"
            else:
                availability = "available"
            records.append(
                PluginManagementSourceRecordV1(
                    installation_key=PluginInstallationKeyV1(
                        product_id=self._product_id,
                        installation_scope="workspace",
                        scope_id=item.scope_id,
                        plugin_id=item.plugin_id,
                    ),
                    source_identity=f"local:{self.source_root / item.wheel_filename}",
                    source_kind="local",
                    availability=availability,
                    source_location=item.original_source,
                    plugin_version=item.version,
                    manifest_enabled_default=None,
                )
            )
        ordered = tuple(sorted(records, key=lambda value: value.installation_key))
        owner_revision = sha256(
            canonical_json_bytes(
                {
                    "bindings": [item.to_dict() for item in all_bindings],
                    "selected": [item.to_dict() for item in ordered],
                }
            )
        ).hexdigest()
        return PluginManagementSourceSnapshotV1(
            owner_revision=f"{owner_revision_prefix}{owner_revision}",
            records=ordered,
        )


class _DependencySourceRecord(_SourceRecord, Protocol):
    @property
    def project_name(self) -> str: ...
    @property
    def version(self) -> str: ...
    def policy_dependency(
        self, source_root: Path
    ) -> PackageProductLocalWheelDependencyV1: ...


class _DependencyWheelBindingMethods(_ExternalWheelBindingMethods):
    """Prove that a controlled dependency retains its exact project/version."""

    __slots__ = ()
    project_name: str
    version: str
    _dependency_directory: ClassVar[str]

    @staticmethod
    def _wheel_identity(wheel_filename: str) -> tuple[str, str]:
        raise NotImplementedError

    @classmethod
    def _wheel_identity_fields(cls, wheel_filename: str) -> dict[str, str]:
        project_name, version = cls._wheel_identity(wheel_filename)
        return {"project_name": project_name, "version": version}

    def __post_init__(self) -> None:
        project_name, version = self._wheel_identity(self.wheel_filename)
        if (
            not _source_binding_scope_matches(self, require_strings=True)
            or self.project_name != project_name
            or self.version != version
            or not isinstance(self.artifact_digest, str)
            or _SOURCE_RECORD_DIGEST.fullmatch(self.artifact_digest) is None
            or not isinstance(self.record_id, str)
            or _SOURCE_RECORD_DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError(f"{self._binding_label} binding is invalid")
        self._require_binding_identity()

    def policy_dependency(
        self, source_root: Path
    ) -> PackageProductLocalWheelDependencyV1:
        return PackageProductLocalWheelDependencyV1(
            source_identity=str(
                source_root / self._dependency_directory / self.wheel_filename
            ),
            project_name=self.project_name,
            version=self.version,
            artifact_digest=self.artifact_digest,
        )


DependencyRecordT = TypeVar("DependencyRecordT", bound=_DependencySourceRecord)


class _DependencyWheelSourceCatalog(_WheelSourceCatalog[DependencyRecordT]):
    _product_id: str
    _source_read_errors = (OSError, ValueError)
    _source_read_error_suffix = "Source changed or is invalid"
    _binding_limit = 128

    def capture(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> DependencyRecordT:
        return self._capture_external(source, epoch_runtime=epoch_runtime)

    def _record_key(self, record: DependencyRecordT) -> tuple[str, Version]:
        return record.project_name, Version(record.version)

    def _require_new_record(
        self, record: DependencyRecordT, records: tuple[DependencyRecordT, ...]
    ) -> None:
        key = self._record_key(record)
        if any(self._record_key(item) == key for item in records):
            raise self._error_factory(f"{self._label} version is already bound")

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


class _WorkerSourceRecord(_PluginSourceRecord, Protocol):
    @property
    def admission(self) -> PackageProductLocalWorkerAdmissionV1: ...
    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> Self: ...


WindowsRecordT = TypeVar("WindowsRecordT", bound=_WorkerSourceRecord)


class _WindowsWorkerSourceCatalog(
    _StableWheelSource[WindowsRecordT], _PluginSourcePolicy[WindowsRecordT]
):
    _receipt_io: WindowsPrivateReceiptIO
    _source_files: ExactProductSourceFiles
    _record_type: type[WindowsRecordT]
    _receipt_write_maximum: int
    _publication_label: str
    _persist_admission = True

    def _max_record_bytes(self) -> int:
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

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> WindowsRecordT:
        self._assert_epoch()
        self._require_worker_capture_source(
            source, admission,
            native_platform="windows-amd64", required_suffix="-win_amd64.whl",
        )
        return self._capture_validated(source, admission=admission)

    def _capture_validated(
        self, source: Path, *, admission: PackageProductLocalWorkerAdmissionV1
    ) -> WindowsRecordT:
        body, digest = self._read_source(source)
        records = self._records(allow_pending_stage=True)
        existing = self._existing_capture(records, source, digest, admission)
        if existing is not None:
            self.verify_record(existing)
            return existing
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
    _SourceCatalogReadScopes[LegacyRecordT],
    Generic[LegacyRecordT, LegacyCandidateT, LegacyAcceptanceT],
):
    source_root: Path
    store_id: str
    namespace_id: str
    scope_id: str
    policy_revision: str
    _product_id: str
    _product_journal_name: str
    _candidate_type: type[LegacyCandidateT]
    _new_binding: Callable[..., LegacyRecordT]
    _max_wheel_bytes: Callable[[], int]
    _wheel_filename_pattern: re.Pattern[str]
    _duplicate_key_hook: Callable[[list[tuple[str, object]]], dict[str, object]]
    _unlocked_durability: JournalDurabilityProfile
    _load_policy: JournalLoadPolicy
    _read_errors: tuple[type[BaseException], ...] = ()

    _acceptance_type: type[LegacyAcceptanceT]

    def __init__(
        self,
        path: Path,
        *,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        policy_revision: str,
        acceptance_reader: Callable[[str], LegacyAcceptanceT | None] | None = None,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("Legacy binding catalog path is invalid")
        self.path = path
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        self.policy_revision = policy_revision
        self._acceptance_reader = acceptance_reader
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @classmethod
    def for_roots(
        cls,
        roots: FencedSourceCatalogRoots,
        *,
        policy_revision: str,
        acceptance_reader: Callable[[str], LegacyAcceptanceT | None] | None = None,
    ) -> Self:
        return cls(
            roots.state_root / cls._product_journal_name,
            **roots.identity,
            policy_revision=policy_revision,
            acceptance_reader=acceptance_reader,
        )

    @classmethod
    def publish_reviewed_source(
        cls,
        *,
        plugin_id: str,
        acceptance_reader: Callable[[str], LegacyAcceptanceT | None],
        reacquire: Callable[[], tuple[LegacyInventoryEvidence, int, LegacyCandidateT]],
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
        resolve_epoch: Callable[[], _LegacyEpoch],
        read_scope_id: Callable[[], str],
        policy_revision: str,
    ) -> LegacyRecordT:
        """Reopen approval and bind the recaptured local Wheel in its original epoch."""
        from loushang.harness.plugin_authoring.resource_item import (
            _inspect_legacy_local_data_wheel,
        )

        accepted = acceptance_reader(plugin_id)
        if accepted is None:
            raise cls._error_factory("Legacy local Source has no accepted review")
        evidence, position, candidate = reacquire()
        binding, desired_state, _ = evidence.inventory.active_local[position]
        try:
            resource_kind, _ = _inspect_legacy_local_data_wheel(candidate)
        except (OSError, ValueError) as exc:
            raise cls._error_factory(
                "Legacy local Source Resource type is unsupported"
            ) from exc
        return cls.publish_from_accepted_review(
            candidate,
            accepted=accepted,
            binding=binding,
            desired_state=desired_state,
            inspected_kind=resource_kind,
            epoch_runtime=epoch_runtime,
            resolve_epoch=resolve_epoch,
            scope_id=read_scope_id(),
            policy_revision=policy_revision,
            acceptance_reader=acceptance_reader,
        )

    @classmethod
    def publish_from_accepted_review(
        cls,
        candidate: LegacyCandidateT,
        *,
        accepted: LegacyAcceptanceT,
        binding: _BindingHead,
        desired_state: str,
        inspected_kind: str,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
        resolve_epoch: Callable[[], _LegacyEpoch],
        scope_id: str,
        policy_revision: str,
        acceptance_reader: Callable[[str], LegacyAcceptanceT | None],
    ) -> LegacyRecordT:
        """Bind the accepted bytes to the admitted epoch and publish the binding."""
        from ._legacy_local_migration import verify_accepted_legacy_wheel

        verify_accepted_legacy_wheel(
            accepted,
            binding,
            candidate,
            desired_state=desired_state,
            inspected_kind=inspected_kind,
            error_type=cls._error_factory,
        )
        epoch = resolve_epoch()
        review = accepted.review
        switch = epoch_runtime.cutover_result.switch_receipt
        if (
            switch is None
            or not matches_epoch_layout(epoch_runtime, epoch)
            or switch.namespace_id != review.namespace_id
            or scope_id != review.scope_id
            or policy_revision != review.policy_revision
        ):
            raise cls._error_factory("Legacy local Source Product authority changed")
        epoch_runtime.assert_current()
        source_root = epoch_runtime.prepare_product_source_root()
        state_root = epoch_runtime.prepare_product_state_root()
        catalog = cls(
            state_root / cls._product_journal_name,
            source_root=source_root,
            store_id=epoch.store_id,
            namespace_id=switch.namespace_id,
            scope_id=scope_id,
            policy_revision=policy_revision,
            acceptance_reader=acceptance_reader,
        )
        return catalog.publish_accepted_candidate(
            candidate,
            epoch_runtime=epoch_runtime,
            legacy_source_identity=review.legacy_source_identity,
            legacy_binding_digest=review.legacy_binding_digest,
            dependency_lock_digest=review.dependency_lock_digest,
            approval_id=accepted.acceptance_id,
            resource_kind=cast(Literal["skill", "prompt", "theme"], accepted.resource_kind),
        )

    def _require_accepted_binding(self, record: LegacyRecordT) -> None:
        if self._acceptance_reader is None:
            raise self._error_factory("Legacy Product binding has no acceptance owner")
        accepted = self._acceptance_reader(record.plugin_id)
        if not isinstance(accepted, self._acceptance_type):
            raise self._error_factory("Legacy Product binding has no accepted review")
        if not record._matches_approval(accepted):
            raise self._error_factory(
                "Legacy Product binding differs from accepted review"
            )

    def publish_accepted_candidate(
        self,
        candidate: LegacyCandidateT,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
        legacy_source_identity: str,
        legacy_binding_digest: str,
        dependency_lock_digest: str,
        approval_id: str,
        resource_kind: Literal["skill", "prompt", "theme"],
    ) -> LegacyRecordT:
        """Publish inert bytes and settle the authorized catalog binding."""
        self.publish_candidate(candidate, epoch_runtime=epoch_runtime)
        committed = self.append(
            candidate,
            legacy_source_identity=legacy_source_identity,
            legacy_binding_digest=legacy_binding_digest,
            dependency_lock_digest=dependency_lock_digest,
            approval_id=approval_id,
            resource_kind=resource_kind,
        )
        self._require_accepted_binding(committed)
        epoch_runtime.assert_current()
        return committed

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

    def project_policy_group(
        self, policy: PackageProductLocalWheelPolicy, *, trust_classes: frozenset[str]
    ) -> tuple[
        tuple[PackageProductLocalWheelBindingV1, ...],
        tuple[PackageProductLocalWheelBindingV1, ...],
    ]:
        """Observe migrated bindings without allowing catalog repair."""
        return project_local_source_policy_group(
            policy,
            (record.to_policy_binding(self.source_root) for record in self.read_records()),
            trust_classes=trust_classes,
        )

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
            bindings=local_wheel_bindings_in_source_order(
                (
                    *base.bindings,
                    *(item.to_policy_binding(self.source_root) for item in records),
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
