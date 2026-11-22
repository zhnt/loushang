"""Explicit, default-dark Coding Source custody for local Worker Wheels.

Capturing a Wheel only pins its bytes and Product admission inputs. Package
transaction, Desired State selection, native preparation, and activation are
separate owners and decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256 as sha256
from pathlib import Path

from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
)
from loushang.harness.package_product._local_source_catalog import (
    _PluginWheelSourceCatalog,
    _WheelSourceBindingMethods,
    _WindowsWorkerSourceCatalog,
    plugin_wheel_source_fields_match,
    project_plugin_wheel_binding,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
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
    PackageProductLocalWorkerAdmissionV1,
)

from .builtin_wheel import _product_source_files as _worker_source_files
from .legacy_windows_receipt import _receipt_io as _worker_receipt_io

_WHEEL_NAME = re.compile(
    r"(?P<plugin>[a-z][a-z0-9]*)-(?P<version>[0-9]+(?:\.[0-9]+){0,2})-"
    r"py3-none-(?P<tag>(?:(?:linux|manylinux_[0-9]+_[0-9]+)_x86_64|win_amd64))\.whl\Z"
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_FILENAME = 180
_MAX_WINDOWS_RECORD_BYTES = 16 * 1024


class CodingExternalWorkerWheelError(RuntimeError):
    """Worker Wheel Source custody or binding could not be proved."""


@dataclass(frozen=True, slots=True)
class CodingExternalWorkerWheelBindingV1(_WheelSourceBindingMethods):
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

    _binding_label = "External Worker Wheel"
    _sort_binding_fields = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.store_id, str)
            or not isinstance(self.namespace_id, str)
            or not isinstance(self.scope_id, str)
            or not isinstance(self.original_source, str)
            or not isinstance(self.wheel_filename, str)
            or not isinstance(self.plugin_id, str)
            or not isinstance(self.version, str)
            or not isinstance(self.artifact_digest, str)
            or not isinstance(self.record_id, str)
        ):
            raise ValueError("External Worker Wheel binding fields are invalid")
        match = _WHEEL_NAME.fullmatch(self.wheel_filename)
        if (
            not plugin_wheel_source_fields_match(
                self, match, maximum_filename=_MAX_WHEEL_FILENAME
            )
            or not isinstance(self.admission, PackageProductLocalWorkerAdmissionV1)
            or self.admission.native_platform
            != (
                "windows-amd64"
                if match is not None and match["tag"] == "win_amd64"
                else "linux-x86_64"
            )
            or _DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError("External Worker Wheel binding is invalid")
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
    ) -> CodingExternalWorkerWheelBindingV1:
        match = _WHEEL_NAME.fullmatch(wheel_filename)
        if match is None:
            raise ValueError("External Worker Wheel filename is unsupported")
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
            admission=admission,
        )

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return project_plugin_wheel_binding(
            self, source_root, trust_class="local-worker-candidate", admission=self.admission
        )


def _encode_admission(
    admission: PackageProductLocalWorkerAdmissionV1,
) -> dict[str, object]:
    return {
        "contributionId": admission.contribution_id,
        "nativePlatform": admission.native_platform,
        "ownerId": admission.owner_id,
    }


def _decode_admission(value: object) -> PackageProductLocalWorkerAdmissionV1:
    if type(value) is not dict or set(value) != {
        "contributionId",
        "nativePlatform",
        "ownerId",
    }:
        raise ValueError("External Worker Wheel admission record is invalid")
    return PackageProductLocalWorkerAdmissionV1(
        contribution_id=value["contributionId"],
        owner_id=value["ownerId"],
        native_platform=value["nativePlatform"],
    )


CodingExternalWorkerWheelBindingV1._binding_schema = RecordSchema.for_dataclass(
    CodingExternalWorkerWheelBindingV1,
    lambda value: value,
    RecordField("admission", decoder=_decode_admission, encoder=_encode_admission),
)


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingExternalWorkerWheelBindingV1.to_dict,
    decoder=CodingExternalWorkerWheelBindingV1.from_dict,
)


class CodingExternalWorkerWheelCatalog(
    _PluginWheelSourceCatalog[CodingExternalWorkerWheelBindingV1]
):
    """Pin explicit Linux Worker candidates under a fenced Product Source."""

    _label = "External Worker"
    _path_label = "External Worker Wheel"
    _error_factory = CodingExternalWorkerWheelError
    _codec = _CODEC
    _create_binding = staticmethod(CodingExternalWorkerWheelBindingV1.create)
    _read_only_capture_error = "Read-only Worker Source cannot capture"
    _product_id = "coding"
    _source_label = "External Worker Wheel"
    _read_errors = (
        JournalFileError,
        JournalCodecError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    )
    _catalog_regular_single_link = True
    _persist_admission = True

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> CodingExternalWorkerWheelBindingV1:
        self._require_capture_epoch(epoch_runtime)
        self._require_worker_capture_source(
            source,
            admission,
            native_platform="linux-x86_64",
            filename=_WHEEL_NAME,
            max_filename=_MAX_WHEEL_FILENAME,
        )
        return self._capture_validated(
            source, epoch_runtime=epoch_runtime, admission=admission
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
    _product_id = "coding"
    _error_factory = CodingExternalWorkerWheelError
    _record_type = CodingExternalWorkerWheelBindingV1
    _create_binding = staticmethod(CodingExternalWorkerWheelBindingV1.create)
    _receipt_io = _worker_receipt_io
    _source_files = _worker_source_files
    _receipt_write_maximum = 4 * 1024 * 1024
    _publication_label = "external Worker"

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> CodingExternalWorkerWheelBindingV1:
        self._assert_epoch()
        self._require_worker_capture_source(
            source,
            admission,
            native_platform="windows-amd64",
            filename=_WHEEL_NAME,
            max_filename=_MAX_WHEEL_FILENAME,
            required_suffix="-win_amd64.whl",
        )
        return self._capture_validated(source, admission=admission)

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
