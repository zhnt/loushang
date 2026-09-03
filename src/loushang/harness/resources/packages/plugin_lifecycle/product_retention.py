"""Durable Product retention adapter for the PLC9B handoff saga."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDependencyPinReceiptV1,
    PackageDependencyPinRequestV1,
    PackageDesiredStateCommitFailureV1,
    PackageDesiredStateCommitReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
)

PACKAGE_PRODUCT_RETENTION_RECORD_VERSION = 1


class PackageProductRetentionError(RuntimeError):
    """Fail-closed Product retention journal error."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageProductRetentionRecordV1:
    record_revision: int
    receipt: PackageDependencyPinReceiptV1
    record_version: int = PACKAGE_PRODUCT_RETENTION_RECORD_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.record_revision, int) or self.record_revision <= 0:
            raise ValueError("Package Product retention revision must be positive")
        if not isinstance(self.receipt, PackageDependencyPinReceiptV1):
            raise TypeError("Package dependency pin receipt is required")
        if self.record_version != PACKAGE_PRODUCT_RETENTION_RECORD_VERSION:
            raise ValueError("Unsupported Package Product retention record")

    def to_dict(self) -> dict[str, object]:
        return {
            "pinRequestId": self.receipt.request.pin_request_id,
            "receipt": self.receipt.to_dict(),
            "receiptId": self.receipt.receipt_id,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "state": self.receipt.state,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageProductRetentionRecordV1:
        if not isinstance(value, dict) or set(value) != {
            "pinRequestId",
            "receipt",
            "receiptId",
            "recordRevision",
            "recordVersion",
            "state",
        }:
            raise ValueError("Package Product retention record has invalid fields")
        receipt = PackageDependencyPinReceiptV1.from_dict(value["receipt"])
        record = cls(
            record_revision=_integer(value["recordRevision"]),
            receipt=receipt,
            record_version=_integer(value["recordVersion"]),
        )
        if (
            value["pinRequestId"] != receipt.request.pin_request_id
            or value["receiptId"] != receipt.receipt_id
            or value["state"] != receipt.state
        ):
            raise ValueError("Package Product retention projection changed")
        return record


def _encode_record(record: PackageProductRetentionRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageProductRetentionRecordV1):
        raise TypeError("Package Product retention record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageProductRetentionRecordV1:
    try:
        return PackageProductRetentionRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package Product retention record is invalid",
            code="invalid_package_product_retention_record",
        ) from exc


PACKAGE_PRODUCT_RETENTION_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class PackageProductRetentionSettlementOwner:
    """Persist exact dependency pins and atomically release transaction pins."""

    def __init__(
        self,
        *,
        path: str | Path,
        transaction_pins: PackageTransactionPinJournal,
        owner_identity: str = "package-product-retention",
    ) -> None:
        self._path = Path(path).resolve()
        if not isinstance(transaction_pins, PackageTransactionPinJournal):
            raise TypeError("Package transaction pin journal is required")
        if self._path == transaction_pins.path:
            raise ValueError("Product retention and transaction pin journals differ")
        if not isinstance(owner_identity, str) or not owner_identity:
            raise ValueError("Package Product retention owner id must be non-empty")
        self._transaction_pins = transaction_pins
        self._owner_identity = owner_identity
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def acquire(
        self,
        request: PackageDependencyPinRequestV1,
        *,
        transaction_pin_receipt: PackageTransactionPinReceiptV1,
    ) -> PackageDependencyPinReceiptV1:
        if not isinstance(request, PackageDependencyPinRequestV1):
            raise TypeError("Package dependency pin request is required")
        if (
            not isinstance(transaction_pin_receipt, PackageTransactionPinReceiptV1)
            or transaction_pin_receipt.state != "acquired"
            or transaction_pin_receipt.receipt_id != request.transaction_pin_receipt_id
        ):
            raise ValueError("Package transaction pin evidence changed")
        with self._exclusive():
            transaction = self._transaction_pins.current(
                operation_id=request.operation_id,
                pin_request_id=transaction_pin_receipt.pin_request.pin_request_id,
            )
            if transaction != transaction_pin_receipt:
                raise self._error(
                    "Package transaction pin is not currently acquired",
                    code="package_retention_handoff_stale",
                )
            records = self._load_unlocked()
            current = _current(records, request.pin_request_id)
            if current is not None:
                if current.request != request or current.state == "aborted":
                    raise self._error(
                        "Package dependency pin request conflicts with history",
                        code="package_retention_handoff_stale",
                    )
                return current
            receipt = PackageDependencyPinReceiptV1.acquire(
                request,
                pin_ids=tuple(
                    sha256(f"{request.pin_request_id}:{ref_id}".encode()).hexdigest()
                    for ref_id in request.target_ref_ids
                ),
                owner_identity=self._owner_identity,
                owner_revision=len(records) + 1,
                lease_revision=1,
                transaction_pin_receipt=transaction_pin_receipt,
            )
            self._append_unlocked(records, receipt)
            return receipt

    def abort(
        self,
        receipt: PackageDependencyPinReceiptV1,
        *,
        failure: PackageDesiredStateCommitFailureV1,
    ) -> PackageDependencyPinReceiptV1:
        if not isinstance(receipt, PackageDependencyPinReceiptV1):
            raise TypeError("Package dependency pin receipt is required")
        if not isinstance(failure, PackageDesiredStateCommitFailureV1):
            raise TypeError("Package desired failure is required")
        with self._exclusive():
            records = self._load_unlocked()
            current = _current(records, receipt.request.pin_request_id)
            if current is None or current.request != receipt.request:
                raise self._error(
                    "Package dependency pin is absent",
                    code="package_retention_handoff_stale",
                )
            if current.state == "aborted":
                return current
            if current != receipt or current.state != "acquired":
                raise self._error(
                    "Package dependency pin cannot be aborted",
                    code="package_retention_handoff_stale",
                )
            aborted = PackageDependencyPinReceiptV1.abort(
                current,
                failure,
                owner_revision=len(records) + 1,
                lease_revision=current.lease_revision + 1,
            )
            self._append_unlocked(records, aborted)
            return aborted

    def settle(
        self,
        receipt: PackageDependencyPinReceiptV1,
        *,
        desired_receipt: PackageDesiredStateCommitReceiptV1,
    ) -> PackageDependencyPinReceiptV1:
        if not isinstance(receipt, PackageDependencyPinReceiptV1):
            raise TypeError("Package dependency pin receipt is required")
        if not isinstance(desired_receipt, PackageDesiredStateCommitReceiptV1):
            raise TypeError("Package desired receipt is required")
        with self._exclusive():
            records = self._load_unlocked()
            current = _current(records, receipt.request.pin_request_id)
            if current is None or current.request != receipt.request:
                raise self._error(
                    "Package dependency pin is absent",
                    code="package_retention_handoff_stale",
                )
            if current.state == "settled":
                if current.desired_receipt_id != desired_receipt.receipt_id:
                    raise self._error(
                        "Package dependency settlement evidence changed",
                        code="package_retention_handoff_stale",
                    )
                return current
            if current != receipt or current.state != "acquired":
                raise self._error(
                    "Package dependency pin cannot be settled",
                    code="package_retention_handoff_stale",
                )
            transaction = self._transaction_pins.current(
                operation_id=current.request.operation_id,
                pin_request_id=current.transaction_pin_receipt.pin_request.pin_request_id,
            )
            if transaction is None:
                raise self._error(
                    "Package transaction pin is absent",
                    code="package_retention_handoff_stale",
                )
            if transaction.state == "acquired":
                transaction = PackageTransactionPinReceiptV1.transition(
                    transaction,
                    state="released",
                    owner_revision=transaction.owner_revision + 1,
                    lease_revision=transaction.lease_revision + 1,
                    transition_evidence_ref=desired_receipt.receipt_id,
                )
                self._transaction_pins.append(transaction)
            if (
                transaction.state != "released"
                or transaction.prior_receipt_id
                != current.transaction_pin_receipt.receipt_id
                or transaction.transition_evidence_ref != desired_receipt.receipt_id
            ):
                raise self._error(
                    "Package transaction pin settlement changed",
                    code="package_retention_handoff_stale",
                )
            settled = PackageDependencyPinReceiptV1.settle(
                current,
                desired_receipt,
                transaction,
                owner_revision=len(records) + 1,
                lease_revision=current.lease_revision + 1,
            )
            self._append_unlocked(records, settled)
            return settled

    def current(
        self,
        request: PackageDependencyPinRequestV1,
    ) -> PackageDependencyPinReceiptV1 | None:
        if not isinstance(request, PackageDependencyPinRequestV1):
            raise TypeError("Package dependency pin request is required")
        with self._exclusive():
            return _current(self._load_unlocked(), request.pin_request_id)

    def records(self) -> tuple[PackageProductRetentionRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _append_unlocked(
        self,
        records: tuple[PackageProductRetentionRecordV1, ...],
        receipt: PackageDependencyPinReceiptV1,
    ) -> None:
        append_jsonl_record(
            self._path,
            PackageProductRetentionRecordV1(
                record_revision=len(records) + 1,
                receipt=receipt,
            ),
            record_codec=PACKAGE_PRODUCT_RETENTION_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[PackageProductRetentionRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageProductRetentionRecordV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_PRODUCT_RETENTION_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            _validate_records(snapshot.records)
            return snapshot.records
        except (JournalFileError, OSError, UnicodeError, ValueError) as exc:
            raise self._error(
                "Package Product retention journal is corrupt",
                code="package_product_retention_journal_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(self, message: str, *, code: str) -> PackageProductRetentionError:
        return PackageProductRetentionError(message, code=code, path=self._path)


def _current(
    records: tuple[PackageProductRetentionRecordV1, ...],
    pin_request_id: str,
) -> PackageDependencyPinReceiptV1 | None:
    matches = tuple(
        record.receipt
        for record in records
        if record.receipt.request.pin_request_id == pin_request_id
    )
    return matches[-1] if matches else None


def _validate_records(records: tuple[PackageProductRetentionRecordV1, ...]) -> None:
    if tuple(record.record_revision for record in records) != tuple(
        range(1, len(records) + 1)
    ):
        raise ValueError("Package Product retention revisions are not contiguous")
    latest: dict[str, PackageDependencyPinReceiptV1] = {}
    for record in records:
        receipt = record.receipt
        key = receipt.request.pin_request_id
        prior = latest.get(key)
        if prior is None:
            if receipt.state != "acquired":
                raise ValueError("Package Product retention chain has no acquisition")
        elif (
            receipt.prior_receipt_id != prior.receipt_id
            or receipt.request != prior.request
            or prior.state != "acquired"
            or receipt.state not in {"aborted", "settled"}
        ):
            raise ValueError("Package Product retention chain is invalid")
        latest[key] = receipt


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Package Product retention integer is invalid")
    return value


__all__ = [
    "PACKAGE_PRODUCT_RETENTION_JOURNAL_CODEC",
    "PACKAGE_PRODUCT_RETENTION_RECORD_VERSION",
    "PackageProductRetentionError",
    "PackageProductRetentionRecordV1",
    "PackageProductRetentionSettlementOwner",
]
