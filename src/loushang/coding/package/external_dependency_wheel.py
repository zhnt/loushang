"""Fenced, inert custody for exact local dependency Wheel Sources.

This catalog only pins bytes for Product resolution. It grants no Plugin root
admission, Resource consumption, or executable authority.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import Version

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalRecordCodec,
)
from loushang.harness.package_product._local_source_catalog import (
    _DependencyWheelSourceCatalog,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
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
    PackageProductLocalWorkerAdmissionV1,
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
        return _BINDING_SCHEMA.encode(self)

    @classmethod
    def from_dict(cls, value: object) -> CodingExternalDependencyWheelBindingV1:
        if type(value) is not dict or set(value) != _BINDING_SCHEMA.keys:
            raise ValueError("Dependency Wheel binding record is invalid")
        return _BINDING_SCHEMA.decode(cls, value)

    def policy_dependency(
        self, source_root: Path
    ) -> PackageProductLocalWheelDependencyV1:
        return PackageProductLocalWheelDependencyV1(
            source_identity=str(source_root / _DIRECTORY / self.wheel_filename),
            project_name=self.project_name,
            version=self.version,
            artifact_digest=self.artifact_digest,
        )


_BINDING_SCHEMA = RecordSchema.for_dataclass(
    CodingExternalDependencyWheelBindingV1, lambda value: value
)


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingExternalDependencyWheelBindingV1.to_dict,
    decoder=CodingExternalDependencyWheelBindingV1.from_dict,
)


class CodingExternalDependencyWheelCatalog(
    _DependencyWheelSourceCatalog[CodingExternalDependencyWheelBindingV1]
):
    """Append-only exact dependency Sources under one fenced Product namespace."""

    _label = "Dependency Wheel"
    _path_label = "Dependency Wheel"
    _error_factory = CodingExternalDependencyWheelError

    _source_label = "Dependency Wheel"
    _product_id = "coding"

    def _directory_name(self) -> str:
        return _DIRECTORY

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES

    def _validate_source_name(self, filename: str) -> None:
        _wheel_identity(filename)

    def _verify_source_body(self, filename: str, body: bytes) -> None:
        _verify_wheel_body(filename, body)

    def _new_record(
        self,
        source: Path,
        digest: str,
        revision: int,
        *,
        admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> CodingExternalDependencyWheelBindingV1:
        return CodingExternalDependencyWheelBindingV1.create(
            record_revision=revision,
            store_id=self.store_id,
            namespace_id=self.namespace_id,
            scope_id=self.scope_id,
            original_source=str(source),
            wheel_filename=source.name,
            artifact_digest=digest,
        )

    def _require_new_record(
        self,
        record: CodingExternalDependencyWheelBindingV1,
        records: tuple[CodingExternalDependencyWheelBindingV1, ...],
    ) -> None:
        if any(
            item.project_name == record.project_name
            and Version(item.version) == Version(record.version)
            for item in records
        ):
            raise CodingExternalDependencyWheelError(
                "Dependency Wheel version is already bound"
            )


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
        return self._capture_validated(source, epoch_runtime=epoch_runtime)


    def _record_codec(
        self,
    ) -> JournalRecordCodec[CodingExternalDependencyWheelBindingV1]:
        return _CODEC

    def records(self) -> tuple[CodingExternalDependencyWheelBindingV1, ...]:
        return super().records()

    def read_records(self) -> tuple[CodingExternalDependencyWheelBindingV1, ...]:
        return super().read_records()

    def _record_key(
        self, record: CodingExternalDependencyWheelBindingV1
    ) -> tuple[str, Version]:
        return record.project_name, Version(record.version)


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


__all__ = [
    "CodingExternalDependencyWheelBindingV1",
    "CodingExternalDependencyWheelCatalog",
    "CodingExternalDependencyWheelError",
]
