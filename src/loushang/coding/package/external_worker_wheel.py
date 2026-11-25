"""Explicit, default-dark Coding Source custody for local Worker Wheels.

Capturing a Wheel only pins its bytes and Product admission inputs. Package
transaction, Desired State selection, native preparation, and activation are
separate owners and decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256 as sha256

from loushang.harness.journal import (
    JournalCodecError,
    JournalFileError,
)
from loushang.harness.package_product._local_source_catalog import (
    _PosixWorkerSourceCatalog,
    _WindowsWorkerSourceCatalog,
    _WorkerWheelBindingMethods,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWorkerAdmissionV1,
)

from .builtin_wheel import _product_source_files as _worker_source_files
from .legacy_windows_receipt import _receipt_io as _worker_receipt_io

_WHEEL_NAME = re.compile(
    r"(?P<plugin>[a-z][a-z0-9]*)-(?P<version>[0-9]+(?:\.[0-9]+){0,2})-"
    r"py3-none-(?P<tag>(?:(?:linux|manylinux_[0-9]+_[0-9]+)_x86_64|win_amd64))\.whl\Z"
)
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_FILENAME = 180
_MAX_WINDOWS_RECORD_BYTES = 16 * 1024


class CodingExternalWorkerWheelError(RuntimeError):
    """Worker Wheel Source custody or binding could not be proved."""


@dataclass(frozen=True, slots=True)
class CodingExternalWorkerWheelBindingV1(_WorkerWheelBindingMethods):
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
    record_id: str

    _wheel_name = _WHEEL_NAME
    _max_wheel_filename = _MAX_WHEEL_FILENAME


CodingExternalWorkerWheelBindingV1._binding_schema = (
    CodingExternalWorkerWheelBindingV1._worker_schema()
)


_CODEC = CodingExternalWorkerWheelBindingV1._record_codec()


class CodingExternalWorkerWheelCatalog(
    _PosixWorkerSourceCatalog[CodingExternalWorkerWheelBindingV1]
):
    """Pin explicit Linux Worker candidates under a fenced Product Source."""

    _label = "External Worker"
    _path_label = "External Worker Wheel"
    _error_factory = CodingExternalWorkerWheelError
    _codec = _CODEC
    _create_binding = staticmethod(CodingExternalWorkerWheelBindingV1.create)
    _product_id = "coding"
    _product_journal_name = "external-worker-wheel-bindings.jsonl"
    _source_label = "External Worker Wheel"
    _wheel_name = _WHEEL_NAME
    _max_wheel_filename = _MAX_WHEEL_FILENAME
    _read_errors = (
        JournalFileError,
        JournalCodecError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    )

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES


class CodingWindowsExternalWorkerWheelCatalog(
    _WindowsWorkerSourceCatalog[CodingExternalWorkerWheelBindingV1]
):
    """Pin inert Worker candidates in immutable Windows Product receipts.

    Every revision has one native, ACL-verified receipt. Bounded sequential
    reads refuse gaps and partial stages; no path-based append is trusted as a
    Windows catalog authority.
    """

    _label = "Windows Worker"
    _source_label = "Windows Worker Wheel"
    _wheel_name = _WHEEL_NAME
    _max_wheel_filename = _MAX_WHEEL_FILENAME
    _product_id = "coding"
    _error_factory = CodingExternalWorkerWheelError
    _record_type = CodingExternalWorkerWheelBindingV1
    _create_binding = staticmethod(CodingExternalWorkerWheelBindingV1.create)
    _receipt_io = _worker_receipt_io
    _source_files = _worker_source_files
    _receipt_write_maximum = 4 * 1024 * 1024
    _publication_label = "external Worker"

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES

    def _max_record_bytes(self) -> int:
        return _MAX_WINDOWS_RECORD_BYTES


__all__ = [
    "CodingExternalWorkerWheelBindingV1",
    "CodingExternalWorkerWheelCatalog",
    "CodingWindowsExternalWorkerWheelCatalog",
    "CodingExternalWorkerWheelError",
]
