"""Fenced Coding Product authorization for one narrow local data Wheel shape."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256 as sha256

from loushang.harness.package_product._local_source_catalog import (
    _DataWheelBindingMethods,
    _DataWheelSourceCatalog,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)

_WHEEL_NAME = re.compile(
    r"(?P<plugin>[a-z][a-z0-9]*)-(?P<version>[0-9]+(?:\.[0-9]+){0,2})-py3-none-any\.whl\Z"
)
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_FILENAME = 180
_CHUNK_SIZE = 64 * 1024


class CodingExternalDataWheelError(RuntimeError):
    """External data Wheel Source was not safely admitted."""


@dataclass(frozen=True, slots=True)
class CodingExternalDataWheelBindingV1(_DataWheelBindingMethods):
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

    _wheel_name = _WHEEL_NAME
    _max_wheel_filename = _MAX_WHEEL_FILENAME
    _data_trust_class = "local-data-only"


CodingExternalDataWheelBindingV1._binding_schema = RecordSchema.for_dataclass(
    CodingExternalDataWheelBindingV1, lambda value: value
)


_CODEC = CodingExternalDataWheelBindingV1._record_codec()


class CodingExternalDataWheelCatalog(
    _DataWheelSourceCatalog[CodingExternalDataWheelBindingV1]
):
    """Append-only Product Source authorization for a fenced B namespace."""

    _label = "External data Wheel"
    _path_label = "External data Wheel"
    _error_factory = CodingExternalDataWheelError
    _codec = _CODEC
    _create_binding = staticmethod(CodingExternalDataWheelBindingV1.create)
    _read_only_capture_error = "Read-only Source catalog cannot capture"
    _product_id = "coding"
    _product_journal_name = "external-data-wheel-bindings.jsonl"
    _source_label = "External data Wheel"

    _record_type = CodingExternalDataWheelBindingV1
    _wheel_name = _WHEEL_NAME
    _max_wheel_filename = _MAX_WHEEL_FILENAME

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES


__all__ = [
    "CodingExternalDataWheelBindingV1",
    "CodingExternalDataWheelCatalog",
    "CodingExternalDataWheelError",
]
