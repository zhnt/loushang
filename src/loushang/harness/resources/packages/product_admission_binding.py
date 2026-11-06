"""Durable Product binding of an accepted A2 request to its original lease.

The binding is written after Package acceptance and before transaction effects.
If a crash leaves an accepted request without a binding, later cross-runtime
recovery must refuse. The same admitted runtime can fill that gap on replay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    journal_file_lock,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_binding_journal import (
    _ProductBindingJournal,
)

PACKAGE_PRODUCT_ADMISSION_BINDING_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PackageProductAdmissionBindingJournalError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageProductAdmissionBindingV1:
    record_revision: int
    operation_id: str
    request_fingerprint: str
    admission: PackageEpochRuntimeAdmissionReceiptV1
    record_version: int = PACKAGE_PRODUCT_ADMISSION_BINDING_VERSION
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Product admission binding revision is invalid")
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ValueError("Product admission binding operation is invalid")
        if (
            not isinstance(self.request_fingerprint, str)
            or _SHA256.fullmatch(self.request_fingerprint) is None
        ):
            raise ValueError("Product admission binding fingerprint is invalid")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Product runtime admission receipt is required")
        if self.record_version != PACKAGE_PRODUCT_ADMISSION_BINDING_VERSION:
            raise ValueError("Unsupported Product admission binding")
        object.__setattr__(
            self,
            "binding_id",
            sha256(canonical_json_bytes(self._identity_dict())).hexdigest(),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "admission": self.admission.to_dict(),
            "operationId": self.operation_id,
            "requestFingerprint": self.request_fingerprint,
            "recordVersion": self.record_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingId": self.binding_id,
            "recordRevision": self.record_revision,
            **self._identity_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageProductAdmissionBindingV1:
        if not isinstance(value, dict) or set(value) != {
            "admission", "bindingId", "operationId", "recordRevision",
            "recordVersion", "requestFingerprint",
        }:
            raise ValueError("Product admission binding schema changed")
        result = cls(
            record_revision=value["recordRevision"],
            operation_id=value["operationId"],
            request_fingerprint=value["requestFingerprint"],
            admission=PackageEpochRuntimeAdmissionReceiptV1.from_dict(
                value["admission"]
            ),
            record_version=value["recordVersion"],
        )
        if value["bindingId"] != result.binding_id:
            raise ValueError("Product admission binding identity changed")
        return result


def _encode(record: PackageProductAdmissionBindingV1) -> dict[str, object]:
    if not isinstance(record, PackageProductAdmissionBindingV1):
        raise TypeError("Product admission binding is required")
    return record.to_dict()


def _decode(value: object) -> PackageProductAdmissionBindingV1:
    try:
        return PackageProductAdmissionBindingV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Product admission binding is invalid",
            code="invalid_package_product_admission_binding",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(encoder=_encode, decoder=_decode)


class PackageProductAdmissionBindingJournal(
    _ProductBindingJournal[PackageProductAdmissionBindingV1]
):
    """Product sole writer for original admission-to-lease identity."""

    _codec = _CODEC
    _label = "Product admission binding"
    _corrupt_code = "package_product_admission_binding_corrupt"

    def _record_key(self, record: PackageProductAdmissionBindingV1) -> str:
        return record.operation_id

    def bind(
        self,
        request: PackageLifecycleRequestV2,
        status: PackageLifecycleStatusV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductAdmissionBindingV1:
        if (
            not isinstance(request, PackageLifecycleRequestV2)
            or not isinstance(status, PackageLifecycleStatusV1)
            or not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1)
        ):
            raise TypeError("Exact Product admission binding evidence is required")
        if (
            request.operation_id != status.operation_id
            or request.request_fingerprint != status.request_fingerprint
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or status.disposition not in {"active", "retryable_failure", "committed"}
        ):
            raise self._error(
                "Product original admission does not match Package owner",
                code="package_product_admission_binding_invalid",
            )
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            records = self._load_unlocked()
            existing = next(
                (record for record in records if record.operation_id == request.operation_id),
                None,
            )
            if existing is not None:
                if (
                    existing.request_fingerprint == request.request_fingerprint
                    and existing.admission.request == admission.request
                ):
                    return existing
                raise self._error(
                    "Product original runtime admission changed",
                    code="package_product_admission_binding_conflict",
                )
            if (
                request.runtime_admission_request_id
                != admission.request.admission_request_id
            ):
                raise self._error(
                    "Product original admission does not match Package owner",
                    code="package_product_admission_binding_invalid",
                )
            record = PackageProductAdmissionBindingV1(
                record_revision=len(records) + 1,
                operation_id=request.operation_id,
                request_fingerprint=request.request_fingerprint,
                admission=admission,
            )
            self._append_record(record)
            return record

    def read_binding(self, operation_id: str) -> PackageProductAdmissionBindingV1 | None:
        """Read without creating locks or repairing a damaged journal tail."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Product admission binding operation id is required")
        records = self._read_only_records()
        return next(
            (record for record in records if record.operation_id == operation_id),
            None,
        )


    def _error(
        self, message: str, *, code: str
    ) -> PackageProductAdmissionBindingJournalError:
        return PackageProductAdmissionBindingJournalError(
            message, code=code, path=self._path
        )
