"""Explicit, default-dark Coding Source custody for local Worker Wheels.

Capturing a Wheel only pins its bytes and Product admission inputs. Package
transaction, Desired State selection, native preparation, and activation are
separate owners and decisions.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from hashlib import sha256 as sha256
from pathlib import Path
from typing import cast

from loushang.coding.harness.package_product import (
    worker_source_record as _lifecycle_programs,
)
from loushang.harness.journal import (
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalRecordCodec,
)
from loushang.harness.package_product._local_source_catalog import (
    _PluginWheelSourceCatalog,
    _WindowsWorkerSourceCatalog,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
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


_LIFECYCLE_PROGRAM_VALUES = {
    "value_001": "External Worker Wheel binding fields are invalid",
    "value_002": "External Worker Wheel binding is invalid",
    "value_003": "External Worker Wheel binding identity changed",
    "value_004": "External Worker Wheel filename is unsupported",
    "value_005": "External Worker Wheel binding record is invalid",
    "value_006": "External Worker Wheel admission record is invalid",
}


class CodingExternalWorkerWheelError(RuntimeError):
    """Worker Wheel Source custody or binding could not be proved."""


@dataclass(frozen=True, slots=True)
class CodingExternalWorkerWheelBindingV1:
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

    def __post_init__(self) -> None:
        return _lifecycle_programs.validate_record(self)

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
        return _lifecycle_programs.create_record(
            cls,
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            original_source=original_source,
            wheel_filename=wheel_filename,
            artifact_digest=artifact_digest,
            admission=admission,
        )

    def _identity(self) -> dict[str, object]:
        return {
            key: value for key, value in self.to_dict().items() if key != "recordId"
        }

    def to_dict(self) -> dict[str, object]:
        return _lifecycle_programs.encode_record(self)

    @classmethod
    def from_dict(cls, value: object) -> CodingExternalWorkerWheelBindingV1:
        return _lifecycle_programs.decode_record(cls, value)

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return PackageProductLocalWheelBindingV1(
            source_identity=str(source_root / self.wheel_filename),
            requested_package=f"{self.plugin_id}=={self.version}",
            plugin_id=self.plugin_id,
            artifact_digest=self.artifact_digest,
            plugin_manifest_path=f"{self.plugin_id}/plugin.json",
            source_trust_class="local-worker-candidate",
            worker_admission=self.admission,
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

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> CodingExternalWorkerWheelBindingV1:
        if self._read_only:
            raise CodingExternalWorkerWheelError(
                "Read-only Worker Source cannot capture"
            )
        self._assert_epoch(epoch_runtime)
        if (
            not isinstance(admission, PackageProductLocalWorkerAdmissionV1)
            or admission.native_platform != "linux-x86_64"
            or not isinstance(source, Path)
            or not source.is_absolute()
            or os.path.normpath(str(source)) != str(source)
            or source.is_relative_to(self.source_root)
            or _WHEEL_NAME.fullmatch(source.name) is None
            or len(source.name) > _MAX_WHEEL_FILENAME
        ):
            raise CodingExternalWorkerWheelError(
                "External Worker Wheel Source is invalid"
            )
        return self._capture_validated(
            source, epoch_runtime=epoch_runtime, admission=admission
        )

    def _record_codec(self) -> JournalRecordCodec[CodingExternalWorkerWheelBindingV1]:
        return _CODEC

    def records(self) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        return super().records()

    def read_records(self) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        return super().read_records()

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES

    def _new_record(
        self,
        source: Path,
        digest: str,
        revision: int,
        *,
        admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> CodingExternalWorkerWheelBindingV1:
        return CodingExternalWorkerWheelBindingV1.create(
            record_revision=revision,
            store_id=self.store_id,
            namespace_id=self.namespace_id,
            scope_id=self.scope_id,
            original_source=str(source),
            wheel_filename=source.name,
            artifact_digest=digest,
            admission=cast(PackageProductLocalWorkerAdmissionV1, admission),
        )

    def _admission_conflicts(
        self,
        record: CodingExternalWorkerWheelBindingV1,
        admission: PackageProductLocalWorkerAdmissionV1 | None,
    ) -> bool:
        return record.admission != admission


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
    _receipt_io = _worker_receipt_io
    _source_files = _worker_source_files
    _receipt_write_maximum = 4 * 1024 * 1024
    _publication_label = "external Worker"

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
        super().__init__(
            epoch_runtime=epoch_runtime,
            state_root=state_root,
            source_root=source_root,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
        )

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> CodingExternalWorkerWheelBindingV1:
        self._assert_epoch()
        if (
            not isinstance(admission, PackageProductLocalWorkerAdmissionV1)
            or admission.native_platform != "windows-amd64"
            or not isinstance(source, Path)
            or not source.is_absolute()
            or os.path.normpath(str(source)) != str(source)
            or source.is_relative_to(self.source_root)
            or _WHEEL_NAME.fullmatch(source.name) is None
            or not source.name.endswith("-win_amd64.whl")
            or len(source.name) > _MAX_WHEEL_FILENAME
        ):
            raise CodingExternalWorkerWheelError(
                "Windows Worker Wheel Source is invalid"
            )
        return self._capture_validated(source, admission=admission)

    def records(self) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        return super().records()

    def verify_record(self, record: CodingExternalWorkerWheelBindingV1) -> None:
        """Reopen one exact receipt and its Product-controlled Wheel bytes."""
        super().verify_record(record)

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        return super().extend_policy(base)

    def _max_source_bytes(self) -> int:
        return _MAX_WHEEL_BYTES

    def _max_record_bytes(self) -> int:
        return _MAX_WINDOWS_RECORD_BYTES

    def _new_record(
        self,
        source: Path,
        digest: str,
        revision: int,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> CodingExternalWorkerWheelBindingV1:
        return CodingExternalWorkerWheelBindingV1.create(
            record_revision=revision,
            store_id=self.store_id,
            namespace_id=self.namespace_id,
            scope_id=self.scope_id,
            original_source=str(source),
            wheel_filename=source.name,
            artifact_digest=digest,
            admission=admission,
        )


__all__ = [
    "CodingExternalWorkerWheelBindingV1",
    "CodingExternalWorkerWheelCatalog",
    "CodingWindowsExternalWorkerWheelCatalog",
    "CodingExternalWorkerWheelError",
]
