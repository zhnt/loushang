"""Fenced Coding Product authorization for one narrow local data Wheel shape."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalRecordCodec,
)
from loushang.harness.package_product._local_source_catalog import (
    _PluginWheelSourceCatalog,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWorkerAdmissionV1,
)

_WHEEL_NAME = re.compile(
    r"(?P<plugin>[a-z][a-z0-9]*)-(?P<version>[0-9]+(?:\.[0-9]+){0,2})-py3-none-any\.whl\Z"
)
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
        return {
            key: value for key, value in self.to_dict().items() if key != "recordId"
        }

    def to_dict(self) -> dict[str, object]:
        return _BINDING_SCHEMA.encode(self)

    @classmethod
    def from_dict(cls, value: object) -> CodingExternalDataWheelBindingV1:
        if type(value) is not dict or set(value) != _BINDING_SCHEMA.keys:
            raise ValueError("External data Wheel binding record is invalid")
        return _BINDING_SCHEMA.decode(cls, value)

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return PackageProductLocalWheelBindingV1(
            source_identity=str(source_root / self.wheel_filename),
            requested_package=f"{self.plugin_id}=={self.version}",
            plugin_id=self.plugin_id,
            artifact_digest=self.artifact_digest,
            plugin_manifest_path=f"{self.plugin_id}/plugin.json",
            source_trust_class="local-data-only",
        )


_BINDING_SCHEMA = RecordSchema.for_dataclass(
    CodingExternalDataWheelBindingV1, lambda value: value
)


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingExternalDataWheelBindingV1.to_dict,
    decoder=CodingExternalDataWheelBindingV1.from_dict,
)


class CodingExternalDataWheelCatalog(_PluginWheelSourceCatalog[CodingExternalDataWheelBindingV1]):
    """Append-only Product Source authorization for a fenced B namespace."""

    _label = 'External data Wheel'
    _path_label = 'External data Wheel'
    _error_factory = CodingExternalDataWheelError
    _product_id = "coding"
    _source_label = 'External data Wheel'


    def capture(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> CodingExternalDataWheelBindingV1:
        if self._read_only:
            raise CodingExternalDataWheelError(
                "Read-only Source catalog cannot capture"
            )
        self._assert_epoch(epoch_runtime)
        if (
            not source.is_absolute()
            or os.path.normpath(str(source)) != str(source)
            or source.is_relative_to(self.source_root)
            or _WHEEL_NAME.fullmatch(source.name) is None
            or len(source.name) > _MAX_WHEEL_FILENAME
        ):
            raise CodingExternalDataWheelError("External data Wheel Source is invalid")
        return self._capture_validated(
            source, epoch_runtime=epoch_runtime
        )

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

    def _record_codec(self) -> JournalRecordCodec[CodingExternalDataWheelBindingV1]:
        return _CODEC

    def records(self) -> tuple[CodingExternalDataWheelBindingV1, ...]:
        return super().records()

    def read_records(self) -> tuple[CodingExternalDataWheelBindingV1, ...]:
        return super().read_records()

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES

    def _new_record(
        self, source: Path, digest: str, revision: int,
        *, admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> CodingExternalDataWheelBindingV1:
        return CodingExternalDataWheelBindingV1.create(
            record_revision=revision, store_id=self.store_id,
            namespace_id=self.namespace_id, scope_id=self.scope_id,
            original_source=str(source), wheel_filename=source.name,
            artifact_digest=digest,
        )



__all__ = [
    "CodingExternalDataWheelBindingV1",
    "CodingExternalDataWheelCatalog",
    "CodingExternalDataWheelError",
]
