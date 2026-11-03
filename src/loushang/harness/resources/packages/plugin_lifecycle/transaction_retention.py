"""Durable local transaction-pin owner over the Package pin journal.

The same journal is read by staging, commit, and Product handoff. Acquiring a
pin here is therefore visible to every publication and retention gate before
the lifecycle owner advances its phase. No process-local receipt is authority.
"""

from __future__ import annotations

from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)


class PackageTransactionRetentionError(RuntimeError):
    """An existing durable pin does not authorize the requested transition."""


class PackageJournaledTransactionRetentionOwner:
    """Issue and replay exact pin receipts from one shared durable journal."""

    def __init__(
        self,
        *,
        journal: PackageTransactionPinJournal,
        owner_identity: str = "package-transaction-retention",
    ) -> None:
        if not isinstance(journal, PackageTransactionPinJournal):
            raise TypeError("Package transaction pin journal is required")
        if not isinstance(owner_identity, str) or not owner_identity:
            raise ValueError("Package retention owner identity is required")
        self._journal = journal
        self._owner_identity = owner_identity

    def acquire(
        self, request: PackageTransactionPinRequestV1
    ) -> PackageTransactionPinReceiptV1:
        if not isinstance(request, PackageTransactionPinRequestV1):
            raise TypeError("Package transaction pin request is required")
        current = self._journal.current_for_operation(request.operation_id)
        if current is not None:
            if current.pin_request == request and current.state == "acquired":
                return current
            raise PackageTransactionRetentionError(
                "Package transaction pin is already owned or terminal"
            )
        pin_id = sha256(f"transaction:{request.pin_request_id}".encode()).hexdigest()
        receipt = PackageTransactionPinReceiptV1.acquire(
            request,
            pin_id=pin_id,
            owner_identity=self._owner_identity,
            owner_revision=1,
            lease_id=f"lease:{request.pin_request_id}",
            lease_revision=1,
        )
        return self._journal.append(receipt)

    def release(
        self,
        receipt: PackageTransactionPinReceiptV1,
        *,
        transition_evidence_ref: str,
    ) -> PackageTransactionPinReceiptV1:
        if not isinstance(receipt, PackageTransactionPinReceiptV1):
            raise TypeError("Package transaction pin receipt is required")
        current = self._journal.current_for_operation(receipt.pin_request.operation_id)
        if current == receipt and receipt.state == "acquired":
            released = PackageTransactionPinReceiptV1.transition(
                receipt,
                state="released",
                owner_revision=receipt.owner_revision + 1,
                lease_revision=receipt.lease_revision + 1,
                transition_evidence_ref=transition_evidence_ref,
            )
            return self._journal.append(released)
        if (
            current is not None
            and current.state == "released"
            and current.prior_receipt_id == receipt.receipt_id
            and current.transition_evidence_ref == transition_evidence_ref
        ):
            return current
        raise PackageTransactionRetentionError(
            "Package transaction pin release changed durable ownership"
        )


__all__ = [
    "PackageJournaledTransactionRetentionOwner",
    "PackageTransactionRetentionError",
]
