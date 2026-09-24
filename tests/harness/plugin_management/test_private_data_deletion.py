from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.plugin_management import PluginInstallationKeyV1
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionCoordinator,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="coding.example",
    )


@dataclass
class _PrivateDataOwner:
    root: Path
    target_id: str = "private-data:one"
    delete_calls: int = 0

    def plan_for(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        return PluginPrivateDataDeletionPlanV1(
            installation_key=key,
            owner_id="coding.private-data",
            target_id=self.target_id,
        )

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        self.delete_calls += 1
        receipt_path = self.root / "receipt.json"
        if receipt_path.exists():
            record = json.loads(receipt_path.read_text())
            return PluginPrivateDataDeletionReceiptV1(
                installation_key=plan.installation_key,
                owner_id=record["ownerId"],
                target_id=record["targetId"],
                plan_fingerprint=record["planFingerprint"],
                confirmation_id=record["confirmationId"],
                receipt_id=record["receiptId"],
                disposition=record["disposition"],
            )
        (self.root / "user-state.txt").unlink()
        receipt = PluginPrivateDataDeletionReceiptV1(
            installation_key=plan.installation_key,
            owner_id=plan.owner_id,
            target_id=plan.target_id,
            plan_fingerprint=plan.fingerprint,
            confirmation_id=confirmation.confirmation_id,
            receipt_id="private-data-receipt:1",
            disposition="deleted",
        )
        receipt_path.write_text(json.dumps(receipt.to_dict()))
        return receipt


@dataclass
class _ConfirmationAuthority:
    accepted: set[tuple[str, str]]

    def is_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> bool:
        return (plan.fingerprint, confirmation.confirmation_id) in self.accepted


def test_private_data_deletion_requires_exact_separate_confirmation_and_owner_receipt(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "user-state.txt"
    marker.write_text("must survive removal and GC")
    owner = _PrivateDataOwner(tmp_path)
    authority = _ConfirmationAuthority(set())
    coordinator = PluginPrivateDataDeletionCoordinator(
        owner, confirmation_authority=authority
    )
    plan = coordinator.preview(_key())

    with pytest.raises(ValueError, match="confirmation"):
        coordinator.delete(
            plan,
            PluginPrivateDataDeletionConfirmationV1(
                plan_fingerprint="0" * 64,
                confirmation_id="operator:wrong-plan",
            ),
        )
    assert marker.exists() and owner.delete_calls == 0

    owner.target_id = "private-data:changed"
    with pytest.raises(ValueError, match="stale"):
        coordinator.delete(
            plan,
            PluginPrivateDataDeletionConfirmationV1(
                plan_fingerprint=plan.fingerprint,
                confirmation_id="operator:stale-plan",
            ),
        )
    assert marker.exists() and owner.delete_calls == 0

    current_plan = coordinator.preview(_key())
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=current_plan.fingerprint,
        confirmation_id="operator:confirmed-plan",
    )
    with pytest.raises(ValueError, match="not authorized"):
        coordinator.delete(current_plan, confirmation)
    assert marker.exists() and owner.delete_calls == 0

    authority.accepted.add((current_plan.fingerprint, confirmation.confirmation_id))
    receipt = coordinator.delete(current_plan, confirmation)
    assert receipt.disposition == "deleted"
    assert receipt.confirmation_id == confirmation.confirmation_id
    assert not marker.exists()
    assert (tmp_path / "receipt.json").exists()

    restarted = PluginPrivateDataDeletionCoordinator(
        _PrivateDataOwner(tmp_path, owner.target_id), confirmation_authority=authority
    )
    assert restarted.delete(current_plan, confirmation) == receipt


def test_private_data_deletion_rejects_foreign_receipt(tmp_path: Path) -> None:
    class _ForeignReceiptOwner(_PrivateDataOwner):
        def delete_confirmed(
            self,
            plan: PluginPrivateDataDeletionPlanV1,
            confirmation: PluginPrivateDataDeletionConfirmationV1,
        ) -> PluginPrivateDataDeletionReceiptV1:
            return PluginPrivateDataDeletionReceiptV1(
                installation_key=plan.installation_key,
                owner_id=plan.owner_id,
                target_id=plan.target_id,
                plan_fingerprint="1" * 64,
                confirmation_id=confirmation.confirmation_id,
                receipt_id="foreign-receipt",
                disposition="deleted",
            )

    owner = _ForeignReceiptOwner(tmp_path)
    authority = _ConfirmationAuthority(set())
    coordinator = PluginPrivateDataDeletionCoordinator(
        owner, confirmation_authority=authority
    )
    plan = coordinator.preview(_key())
    authority.accepted.add((plan.fingerprint, "operator:confirmed-plan"))
    with pytest.raises(ValueError, match="receipt"):
        coordinator.delete(
            plan,
            PluginPrivateDataDeletionConfirmationV1(
                plan_fingerprint=plan.fingerprint,
                confirmation_id="operator:confirmed-plan",
            ),
        )
