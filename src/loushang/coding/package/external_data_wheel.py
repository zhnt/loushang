"""Fenced Coding Product authorization for one narrow local data Wheel shape."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256 as sha256
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
)
from loushang.harness.package_product._local_source_catalog import (
    _PluginWheelSourceCatalog,
    _WheelSourceBindingMethods,
    plugin_wheel_source_fields_match,
    project_plugin_wheel_binding,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
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
class CodingExternalDataWheelBindingV1(_WheelSourceBindingMethods):
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

    _binding_label = "External data Wheel"

    def __post_init__(self) -> None:
        match = _WHEEL_NAME.fullmatch(self.wheel_filename)
        if (
            not plugin_wheel_source_fields_match(
                self, match, maximum_filename=_MAX_WHEEL_FILENAME
            )
            or _DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError("External data Wheel binding is invalid")
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
    ) -> CodingExternalDataWheelBindingV1:
        match = _WHEEL_NAME.fullmatch(wheel_filename)
        if match is None:
            raise ValueError("External data Wheel filename is unsupported")
        return cls._seal_binding(
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            original_source=original_source,
            wheel_filename=wheel_filename,
            plugin_id=match["plugin"],
            version=match["version"],
            artifact_digest=artifact_digest,
        )

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return project_plugin_wheel_binding(
            self, source_root, trust_class="local-data-only"
        )


CodingExternalDataWheelBindingV1._binding_schema = RecordSchema.for_dataclass(
    CodingExternalDataWheelBindingV1, lambda value: value
)


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingExternalDataWheelBindingV1.to_dict,
    decoder=CodingExternalDataWheelBindingV1.from_dict,
)


class CodingExternalDataWheelCatalog(
    _PluginWheelSourceCatalog[CodingExternalDataWheelBindingV1]
):
    """Append-only Product Source authorization for a fenced B namespace."""

    _label = "External data Wheel"
    _path_label = "External data Wheel"
    _error_factory = CodingExternalDataWheelError
    _codec = _CODEC
    _create_binding = staticmethod(CodingExternalDataWheelBindingV1.create)
    _read_only_capture_error = "Read-only Source catalog cannot capture"
    _product_id = "coding"
    _source_label = "External data Wheel"

    def capture(
        self,
        source: Path,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> CodingExternalDataWheelBindingV1:
        self._require_capture_epoch(epoch_runtime)
        if (
            not self._is_external_source(source)
            or _WHEEL_NAME.fullmatch(source.name) is None
            or len(source.name) > _MAX_WHEEL_FILENAME
        ):
            raise CodingExternalDataWheelError("External data Wheel Source is invalid")
        return self._capture_validated(source, epoch_runtime=epoch_runtime)

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

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES


__all__ = [
    "CodingExternalDataWheelBindingV1",
    "CodingExternalDataWheelCatalog",
    "CodingExternalDataWheelError",
]
