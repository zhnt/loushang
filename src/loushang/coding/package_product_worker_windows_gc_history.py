"""Coding-owned proof that retained Windows Worker history has no GC debt.

The Product GC owner keeps audit history in place. This reader only permits
Package root deletion after every observed attempt has a complete retirement
proof; unknown, partial, or changed history fails closed.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_opt_in_journal import (
    CodingWindowsWorkerOptInJournal,
)
from .package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _current_after_verified_retirements_under_gc_guard,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
    _observe_native_job_absence,
)
from .package_product_worker_windows_stage_retirement import _RETIREMENT_NAME

_INTENT = re.compile(r"worker-launch-intent-[0-9a-f]{32}\.json\Z")
_NATIVE = re.compile(r"worker-native-provisioning-[0-9a-f]{32}\.jsonl(?:\.lock)?\Z")
_C5_HEAD = re.compile(r"worker-activation-state\.h[0-9]{8}\.json\Z")
_EXACT = frozenset(
    {
        "worker-activation-state.jsonl",
        "worker-activation-state.jsonl.lock",
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
            and _C5_HEAD.fullmatch(name) is None
            and _RETIREMENT_NAME.fullmatch(name) is None
        ):
            raise ValueError("Windows Worker GC state owner is unrecognized")


def _require_c5_gc_history(
    state: Mapping[str, object] | None,
    retained: tuple[CodingProductWorkerRetainedAttemptV1, ...],
    inventory: tuple[CodingWindowsWorkerRecoveryAttemptV1, ...],
    receipt_policies: Mapping[str, tuple[str, int]],
    native_job_absence: Mapping[str, bool | None],
) -> None:
    """Join settled C5 attempts to exact launched attempts and Product receipts."""

    if state is None:
        raise ValueError("Windows Worker GC C5 owner is incomplete")
    active = cast(dict[str, dict[str, object]], state["attempts"])
    publications = cast(dict[str, object], state["publications"])
    if publications or any(
        attempt["phase"] != "settled" for attempt in active.values()
    ):
        raise ValueError("Windows Worker GC C5 activation remains active")
    by_id = {item.attempt_id: item for item in retained}
    launched = {
        item.attempt_id: item
        for item in inventory
        if item.launch_request_fingerprint is not None
        or item.native_phase is not None
        or item.supervisor_phase is not None
    }
    if len(by_id) != len(retained) or set(by_id) != set(launched):
        raise ValueError("Windows Worker GC C5 attempt history is incomplete")
    for attempt_id, item in by_id.items():
        observed = launched[attempt_id]
        if (
            item.phase != "settled"
            or item.cleanup_contract_version != 2
            or observed.launch_receipt_fingerprint != item.receipt_fingerprint
            or receipt_policies.get(item.receipt_fingerprint)
            != (item.policy_fingerprint, item.owner_generation)
            or native_job_absence.get(attempt_id) is not True
        ):
            raise ValueError("Windows Worker GC C5 attempt history is incomplete")


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
            if any(
                name.startswith("worker-activation-state") for name in observed_names
            ):
                journal = CodingWindowsWorkerActivationStateJournal(self._product)
                _require_c5_gc_history(
                    journal.load(),
                    journal.retained_attempts_read_only(),
                    inventory,
                    {
                        record.receipt.fingerprint: (
                            record.receipt.policy.fingerprint,
                            record.receipt.policy.owner_selection_generation,
                        )
                        for record in receipts
                    },
                    {
                        attempt.attempt_id: _observe_native_job_absence(
                            attempt.native_job_name
                        )
                        for attempt in inventory
                    },
                )
            if set(windows_listdir_at(root)) != set(observed_names):
                raise ValueError("Windows Worker GC inventory changed")
        self._product.assert_root_gc_authority_current()


__all__ = ["CodingWindowsWorkerGcHistoryAuthority"]
