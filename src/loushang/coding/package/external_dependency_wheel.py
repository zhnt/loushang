"""Fenced, inert custody for exact local dependency Wheel Sources.

This catalog only pins bytes for Product resolution. It grants no Plugin root
admission, Resource consumption, or executable authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from hashlib import sha256 as sha256

from packaging.utils import InvalidWheelFilename as InvalidWheelFilename
from packaging.utils import parse_wheel_filename as parse_wheel_filename

from loushang.harness.package_product._local_source_catalog import (
    _DependencyWheelBindingMethods,
    _DependencyWheelSourceCatalog,
    verify_dependency_wheel_source,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
)

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


_verify_wheel_body = partial(
    verify_dependency_wheel_source,
    maximum_filename_length=_MAX_WHEEL_FILENAME,
    maximum_artifact_bytes=_MAX_WHEEL_BYTES,
    budgets=_INSPECTION_BUDGET,
    error_factory=CodingExternalDependencyWheelError,
)


@dataclass(frozen=True, slots=True)
class CodingExternalDependencyWheelBindingV1(_DependencyWheelBindingMethods):
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

    _binding_label = "Dependency Wheel"
    _dependency_directory = _DIRECTORY
    _max_wheel_filename = _MAX_WHEEL_FILENAME


CodingExternalDependencyWheelBindingV1._binding_schema = RecordSchema.for_dataclass(
    CodingExternalDependencyWheelBindingV1, lambda value: value
)


_CODEC = CodingExternalDependencyWheelBindingV1._record_codec()


class CodingExternalDependencyWheelCatalog(
    _DependencyWheelSourceCatalog[CodingExternalDependencyWheelBindingV1]
):
    """Append-only exact dependency Sources under one fenced Product namespace."""

    _label = "Dependency Wheel"
    _path_label = "Dependency Wheel"
    _error_factory = CodingExternalDependencyWheelError
    _codec = _CODEC
    _create_binding = staticmethod(CodingExternalDependencyWheelBindingV1.create)

    _source_label = "Dependency Wheel"
    _product_id = "coding"
    _product_journal_name = "external-dependency-wheel-bindings.jsonl"

    def _directory_name(self) -> str:
        return _DIRECTORY

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES

    def _validate_source_name(self, filename: str) -> None:
        CodingExternalDependencyWheelBindingV1._wheel_identity(filename)

    def _verify_source_body(self, filename: str, body: bytes) -> None:
        _verify_wheel_body(filename, body)


__all__ = [
    "CodingExternalDependencyWheelBindingV1",
    "CodingExternalDependencyWheelCatalog",
    "CodingExternalDependencyWheelError",
]
