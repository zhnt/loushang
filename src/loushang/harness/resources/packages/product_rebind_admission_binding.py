"""Product-owned admission-to-lease evidence for proposed A2 rebinds.

Write the proposal before the Package decision. A proposal without a durable
Package decision is inert; only the Package journal selects a pending decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import FunctionalJournalRecordCodec, JournalCodecError
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRebindRequestV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_binding_journal import (
    _ProductDecisionBindingJournal,
)

PACKAGE_PRODUCT_REBIND_ADMISSION_BINDING_VERSION = 1


class PackageProductRebindAdmissionBindingError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageProductRebindAdmissionBindingV1:
    record_revision: int
    decision: PackageLifecycleRebindRequestV1
    admission: PackageEpochRuntimeAdmissionReceiptV1
    record_version: int = PACKAGE_PRODUCT_REBIND_ADMISSION_BINDING_VERSION
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Product rebind binding revision is invalid")
        if not isinstance(self.decision, PackageLifecycleRebindRequestV1):
            raise TypeError("Package rebind decision is required")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Product rebind admission receipt is required")
        if (
            self.decision.new_runtime_admission_request_id
            != self.admission.request.admission_request_id
        ):
            raise ValueError("Product rebind admission changed decision")
        if self.record_version != PACKAGE_PRODUCT_REBIND_ADMISSION_BINDING_VERSION:
            raise ValueError("Unsupported Product rebind admission binding")
        object.__setattr__(
            self,
            "binding_id",
            sha256(canonical_json_bytes(self._identity_dict())).hexdigest(),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "admission": self.admission.to_dict(),
            "decision": self.decision.to_dict(),
            "recordVersion": self.record_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingId": self.binding_id,
            "recordRevision": self.record_revision,
            **self._identity_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageProductRebindAdmissionBindingV1:
        if not isinstance(value, dict) or set(value) != {
            "admission",
            "bindingId",
            "decision",
            "recordRevision",
            "recordVersion",
        }:
            raise ValueError("Product rebind admission binding schema changed")
        result = cls(
            record_revision=value["recordRevision"],
            decision=PackageLifecycleRebindRequestV1.from_dict(value["decision"]),
            admission=PackageEpochRuntimeAdmissionReceiptV1.from_dict(
                value["admission"]
            ),
            record_version=value["recordVersion"],
        )
        if value["bindingId"] != result.binding_id:
            raise ValueError("Product rebind admission binding identity changed")
        return result


def _encode(record: PackageProductRebindAdmissionBindingV1) -> dict[str, object]:
    if not isinstance(record, PackageProductRebindAdmissionBindingV1):
        raise TypeError("Product rebind admission binding is required")
    return record.to_dict()


def _decode(value: object) -> PackageProductRebindAdmissionBindingV1:
    try:
        return PackageProductRebindAdmissionBindingV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Product rebind admission binding is invalid",
            code="invalid_package_product_rebind_admission_binding",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(encoder=_encode, decoder=_decode)


class PackageProductRebindAdmissionBindingJournal(
    _ProductDecisionBindingJournal[
        PackageProductRebindAdmissionBindingV1, PackageLifecycleRebindRequestV1
    ]
):
    """Append-once Product evidence for each proposed rebind decision."""

    _codec = _CODEC
    _label = "Product rebind admission"
    _query_label = "Product rebind"
    _corrupt_code = "package_product_rebind_admission_corrupt"
    _invalid_code = "package_product_rebind_admission_invalid"
    _conflict_code = "package_product_rebind_admission_conflict"
    _decision_type = PackageLifecycleRebindRequestV1
    _record_type = PackageProductRebindAdmissionBindingV1
    _match_snapshot = False

    def bind(
        self,
        decision: PackageLifecycleRebindRequestV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductRebindAdmissionBindingV1:
        return self._bind_decision(decision, admission)

    def read_decision(
        self, decision_id: str
    ) -> PackageProductRebindAdmissionBindingV1 | None:
        """Read a proposal without creating locks or repairing a damaged tail."""
        return self._read_decision(decision_id)

    def read_operation(
        self, operation_id: str
    ) -> tuple[PackageProductRebindAdmissionBindingV1, ...]:
        return self._read_operation(operation_id)

    def _error(
        self, message: str, *, code: str
    ) -> PackageProductRebindAdmissionBindingError:
        return PackageProductRebindAdmissionBindingError(
            message, code=code, path=self._path
        )
