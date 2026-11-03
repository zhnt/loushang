"""Complete a committed PLC9B Package through the Product handoff owners."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitAdmissionOwner,
    PackageCommitAdmissionRequestV1,
    PackageCommitLifecycleOwner,
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDesiredStateCommitRequestV1,
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffOwner,
    PackageRetentionHandoffReceiptV1,
    PackageRetentionHandoffRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductPinnedAdoptedRouteRequestV1,
    PackageProductReboundRouteRequestV1,
    PackageProductRouteRequestV1,
    PackageProductStagingAdoptedRouteRequestV1,
    PackageProductTransactionRoute,
    require_rebound_decision,
)
from loushang.harness.resources.packages.product_pinned_adoption_binding import (
    PackageProductPinnedAdoptionBindingJournal,
)
from loushang.harness.resources.packages.product_rebind_admission_binding import (
    PackageProductRebindAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_staging_adoption_binding import (
    PackageProductStagingAdoptionBindingJournal,
)


class PackageProductHandoffError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductHandoffPort(Protocol):
    def finalize(
        self,
        request: PackageProductTransactionRoute,
        *,
        current: PackageLifecycleStatusV1,
    ) -> None: ...


class PackageProductHandoffFinalizer:
    """Reconstruct before journal open, then replay the exact durable handoff."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        commit: PackageCommitLifecycleOwner,
        admission: PackageCommitAdmissionOwner,
        transaction_pins: PackageTransactionPinJournal,
        journal: PackageRetentionHandoffJournal,
        handoff: PackageRetentionHandoffOwner,
        inventory_revision: Callable[[], int],
        update_inventory_revision: Callable[[str], int] | None = None,
        rebind_bindings: PackageProductRebindAdmissionBindingJournal | None = None,
        pinned_bindings: PackageProductPinnedAdoptionBindingJournal | None = None,
        staging_bindings: PackageProductStagingAdoptionBindingJournal | None = None,
    ) -> None:
        for value, expected, name in (
            (kernel, PackageLifecycleOwner, "lifecycle owner"),
            (commit, PackageCommitLifecycleOwner, "commit owner"),
            (admission, PackageCommitAdmissionOwner, "commit admission owner"),
            (transaction_pins, PackageTransactionPinJournal, "transaction pins"),
            (journal, PackageRetentionHandoffJournal, "handoff journal"),
            (handoff, PackageRetentionHandoffOwner, "handoff owner"),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"Package Product {name} is required")
        if not callable(inventory_revision):
            raise TypeError("Product inventory revision owner is required")
        if rebind_bindings is not None and not isinstance(
            rebind_bindings, PackageProductRebindAdmissionBindingJournal
        ):
            raise TypeError("Product rebind admission bindings are invalid")
        if pinned_bindings is not None and not isinstance(
            pinned_bindings, PackageProductPinnedAdoptionBindingJournal
        ):
            raise TypeError("Product pinned admission bindings are invalid")
        if staging_bindings is not None and not isinstance(
            staging_bindings, PackageProductStagingAdoptionBindingJournal
        ):
            raise TypeError("Product staging admission bindings are invalid")
        self._kernel = kernel
        self._commit = commit
        self._admission = admission
        self._transaction_pins = transaction_pins
        self._journal = journal
        self._handoff = handoff
        self._inventory_revision = inventory_revision
        self._update_inventory_revision = update_inventory_revision
        self._rebind_bindings = rebind_bindings
        self._pinned_bindings = pinned_bindings
        self._staging_bindings = staging_bindings

    def finalize(
        self,
        request: PackageProductTransactionRoute,
        *,
        current: PackageLifecycleStatusV1,
    ) -> None:
        if not isinstance(
            request,
            PackageProductRouteRequestV1
            | PackageProductReboundRouteRequestV1
            | PackageProductPinnedAdoptedRouteRequestV1
            | PackageProductStagingAdoptedRouteRequestV1,
        ):
            raise TypeError("Package Product route request is required")
        if not isinstance(current, PackageLifecycleStatusV1):
            raise TypeError("Committed Package status is required")
        classification = current.classification
        durable_request = self._kernel.journal.request(current.operation_id)
        if (
            current.phase != "committed"
            or current.disposition != "committed"
            or classification is None
            or classification.decision != "plugin_bound"
            or self._kernel.status(current.operation_id) != current
            or not isinstance(durable_request, PackageLifecycleRequestV2)
            or durable_request
            != request.ingress.bind_classification_facts(classification.basis_facts)
            or durable_request.action not in {"install", "update"}
        ):
            raise self._error(
                "Committed Package route changed", "package_product_handoff_stale"
            )
        require_rebound_decision(request, current, self._kernel.journal)
        if isinstance(request, PackageProductReboundRouteRequestV1):
            binding = (
                None
                if self._rebind_bindings is None
                else self._rebind_bindings.read_decision(request.decision.decision_id)
            )
            if (
                binding is None
                or binding.decision != request.decision
                or binding.admission.request != request.admission.request
            ):
                raise self._error(
                    "Committed rebound Package lost Product admission",
                    "package_product_handoff_stale",
                )
        if isinstance(request, PackageProductPinnedAdoptedRouteRequestV1):
            pinned_binding = (
                None
                if self._pinned_bindings is None
                else self._pinned_bindings.read_decision(request.decision.decision_id)
            )
            if (
                pinned_binding is None
                or pinned_binding.decision != request.decision
                or pinned_binding.admission != request.admission
            ):
                raise self._error(
                    "Committed pinned Package lost Product admission",
                    "package_product_handoff_stale",
                )
        if isinstance(request, PackageProductStagingAdoptedRouteRequestV1):
            staging_binding = (
                None
                if self._staging_bindings is None
                else self._staging_bindings.read_decision(request.decision.decision_id)
            )
            if (
                staging_binding is None
                or staging_binding.decision != request.decision
                or staging_binding.admission != request.admission
            ):
                raise self._error(
                    "Committed staging Package lost Product admission",
                    "package_product_handoff_stale",
                )
        command_id, command_fingerprint = package_product_command_identity(
            current.operation_id, current.request_fingerprint
        )
        prior = self._existing(
            current,
            request=request,
            command_id=command_id,
            command_fingerprint=command_fingerprint,
        )
        if prior is None:
            handoff_request = self._prepare(
                current,
                command_id=command_id,
                command_fingerprint=command_fingerprint,
            )
            expected = None
        else:
            handoff_request, expected = prior
        result = self._handoff.execute(handoff_request, expected_receipt=expected)
        receipt = result.receipt
        if (
            result.disposition != "settled"
            or receipt is None
            or receipt.request != handoff_request
            or self._journal.current(handoff_request.handoff_id) != receipt
            or receipt.desired_receipt is None
            or receipt.dependency_pin_receipt is None
            or receipt.dependency_pin_receipt.state != "settled"
        ):
            raise self._error(
                "Committed Package Product handoff is not settled",
                "package_product_handoff_unsettled",
            )

    def _existing(
        self,
        status: PackageLifecycleStatusV1,
        *,
        request: PackageProductTransactionRoute,
        command_id: str,
        command_fingerprint: str,
    ) -> (
        tuple[PackageRetentionHandoffRequestV1, PackageRetentionHandoffReceiptV1] | None
    ):
        receipts = tuple(
            item.receipt
            for item in self._journal.records()
            if item.receipt is not None
            and item.receipt.request.operation_id == status.operation_id
        )
        if not receipts:
            return None
        handoff_ids = {item.request.handoff_id for item in receipts}
        if len(handoff_ids) != 1:
            raise self._error(
                "Package handoff has another owner", "package_product_handoff_stale"
            )
        latest = receipts[-1]
        handoff_request = latest.request
        publication = handoff_request.admission_request.publication_receipt
        desired = handoff_request.desired_request
        if (
            publication is None
            or publication.operation_id != status.operation_id
            or publication.request_fingerprint != status.request_fingerprint
            or publication.attempt_epoch != status.attempt_epoch
            or publication.commit_status_revision != status.journal_revision
            or publication.product_id != request.ingress.product_id
            or publication.scope_id != request.ingress.scope_id
            or publication.plugin_id != request.ingress.requested_plugin_id
            or desired.command_id != command_id
            or desired.command_fingerprint != command_fingerprint
            or self._journal.current(handoff_request.handoff_id) != latest
        ):
            raise self._error(
                "Package handoff disagrees with route", "package_product_handoff_stale"
            )
        return handoff_request, latest

    def _prepare(
        self,
        status: PackageLifecycleStatusV1,
        *,
        command_id: str,
        command_fingerprint: str,
    ) -> PackageRetentionHandoffRequestV1:
        publication = self._commit.commit(status.operation_id)
        if (
            not isinstance(publication, PackagePublicationReceiptV1)
            or publication.operation_id != status.operation_id
            or publication.request_fingerprint != status.request_fingerprint
            or publication.attempt_epoch != status.attempt_epoch
            or publication.commit_status_revision != status.journal_revision
        ):
            raise self._error(
                "Package publication changed", "package_product_handoff_stale"
            )
        committed = publication.committed_set
        admission_request = PackageCommitAdmissionRequestV1.create(
            operation_id=publication.operation_id,
            request_fingerprint=publication.request_fingerprint,
            product_id=publication.product_id,
            scope_id=publication.scope_id,
            installation_id=publication.installation_id,
            plugin_id=publication.plugin_id,
            claimed_root_ref=committed.root_ref,
            committed_set_id=committed.set_id,
            closure_lock_digest=committed.closure_lock_digest,
            publication_receipt=publication,
        )
        admitted = self._admission.admit(admission_request)
        pin = self._transaction_pins.current_for_operation(status.operation_id)
        if (
            admitted.disposition != "admitted"
            or admitted.receipt is None
            or pin is None
            or pin.state != "acquired"
            or pin.receipt_id != publication.transaction_pin_receipt_id
        ):
            raise self._error(
                "Package handoff admission failed", "package_product_handoff_stale"
            )
        durable_request = self._kernel.journal.request(status.operation_id)
        if durable_request is not None and durable_request.action == "update":
            if self._update_inventory_revision is None:
                raise self._error(
                    "Product update anchor is unavailable",
                    "package_product_handoff_stale",
                )
            revision = self._update_inventory_revision(status.operation_id)
        else:
            revision = self._inventory_revision()
        if type(revision) is not int or revision < 0:
            raise self._error(
                "Product inventory revision is invalid", "package_product_handoff_stale"
            )
        desired = PackageDesiredStateCommitRequestV1.create(
            admission_request,
            command_id=command_id,
            command_fingerprint=command_fingerprint,
            expected_inventory_revision=revision,
        )
        return PackageRetentionHandoffRequestV1.create(
            admission_request=admission_request,
            admission_receipt=admitted.receipt,
            transaction_pin_receipt=pin,
            desired_request=desired,
        )

    @staticmethod
    def _error(message: str, code: str) -> PackageProductHandoffError:
        return PackageProductHandoffError(message, code=code)


def package_product_command_identity(
    operation_id: str, request_fingerprint: str
) -> tuple[str, str]:
    """Derive the durable A1 command key from an exact A2 request identity."""

    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError("Package operation identity is required")
    if (
        not isinstance(request_fingerprint, str)
        or len(request_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in request_fingerprint)
    ):
        raise ValueError("Package request fingerprint is invalid")
    digest = sha256(
        b"package-product-command-v1\0"
        + operation_id.encode("utf-8")
        + b"\0"
        + request_fingerprint.encode("ascii")
    ).hexdigest()
    return f"package:{digest}", digest


__all__ = [
    "PackageProductHandoffFinalizer",
    "PackageProductHandoffPort",
    "package_product_command_identity",
]
