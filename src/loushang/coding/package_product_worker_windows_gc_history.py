"""Coding-owned proof that retained Windows Worker history has no GC debt.

The Product GC owner keeps audit history in place. This reader only permits
Package root deletion after every observed attempt has a complete retirement
proof; unknown, partial, or changed history fails closed.
"""

from __future__ import annotations

import os
import re

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)

from .package_product_worker_windows_opt_in_journal import (
    CodingWindowsWorkerOptInJournal,
)
from .package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from .package_product_worker_windows_recovery_inventory import (
    _current_after_verified_retirements_under_gc_guard,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_stage_retirement import _RETIREMENT_NAME

_INTENT = re.compile(r"worker-launch-intent-[0-9a-f]{32}\.json\Z")
_NATIVE = re.compile(r"worker-native-provisioning-[0-9a-f]{32}\.jsonl(?:\.lock)?\Z")
_EXACT = frozenset(
    {
        "worker-supervisor.jsonl",
        "worker-supervisor.jsonl.lock",
        "worker-activation-receipts.jsonl",
        "worker-activation-receipts.jsonl.lock",
        "worker-opt-in.jsonl",
        "worker-opt-in.jsonl.lock",
        "worker-native-release-approvals.jsonl",
        "worker-native-release-approvals.jsonl.lock",
        "worker-native-backend-release-v1.whl",
    }
)


def _require_known_windows_worker_state_names(names: tuple[str, ...]) -> None:
    for name in names:
        if not name.casefold().startswith(("worker-", ".worker-")):
            continue
        if (
            name not in _EXACT
            and _INTENT.fullmatch(name) is None
            and _NATIVE.fullmatch(name) is None
            and _RETIREMENT_NAME.fullmatch(name) is None
        ):
            raise ValueError("Windows Worker GC state owner is unrecognized")


class CodingWindowsWorkerGcHistoryAuthority:
    """Read-only Coding proof consumed by the Product Package GC owner."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Coding Windows Worker GC requires its Product owner")
        self._product = product

    @property
    def product_owner(self) -> WindowsLocalWheelProductSessionOwner:
        return self._product

    def require_settled(self, *, observed_names: tuple[str, ...]) -> None:
        """Verify every retained attempt without mutating Worker or Package state.

        The caller holds runtime quiescence and the Product GC guard. Names are
        compared before and after the owner reads to catch a changed inventory.
        """

        if type(observed_names) is not tuple or any(
            type(name) is not str for name in observed_names
        ):
            raise ValueError("Windows Worker GC inventory is invalid")
        self._product.assert_root_gc_authority_current()
        with self._product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            if set(windows_listdir_at(root)) != set(observed_names):
                raise ValueError("Windows Worker GC inventory changed")
            _require_known_windows_worker_state_names(observed_names)

            inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(
                self._product
            )
            if _current_after_verified_retirements_under_gc_guard(
                self._product, inventory, attempt_id=None
            ):
                raise ValueError("Windows Worker GC attempt is unsettled")

            receipts = CodingWindowsWorkerReceiptJournal(
                self._product.state_root / "worker-activation-receipts.jsonl",
                scope_id=self._product.policy.project_scope_id,
            ).records(directory_fd=root)
            opt_in_decisions = CodingWindowsWorkerOptInJournal(
                self._product.state_root / "worker-opt-in.jsonl",
                scope_id=self._product.policy.project_scope_id,
            ).history_read_only(directory_fd=root)
            opt_in_by_digest = {
                decision.decision_digest: decision for decision in opt_in_decisions
            }
            if any(
                (decision := opt_in_by_digest.get(record.opt_in_decision_digest))
                is None
                or decision.action != "allow"
                or decision.plugin_id != record.receipt.policy.plugin_id
                for record in receipts
            ):
                raise ValueError("Windows Worker GC opt-in history is incomplete")
            receipt_fingerprints = {record.receipt.fingerprint for record in receipts}
            if any(
                attempt.launch_receipt_fingerprint is not None
                and attempt.launch_receipt_fingerprint not in receipt_fingerprints
                for attempt in inventory
            ):
                raise ValueError("Windows Worker GC receipt history is incomplete")
            if set(windows_listdir_at(root)) != set(observed_names):
                raise ValueError("Windows Worker GC inventory changed")
        self._product.assert_root_gc_authority_current()


__all__ = ["CodingWindowsWorkerGcHistoryAuthority"]
