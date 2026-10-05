from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.plugin_management import PluginInstallationKeyV1
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)
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
    assert PluginPrivateDataDeletionReceiptV1.from_dict(receipt.to_dict()) == receipt
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


def test_private_data_receipt_replays_after_target_becomes_absent(
    tmp_path: Path,
) -> None:
    class _ChangingOwner(_PrivateDataOwner):
        def plan_for(
            self, key: PluginInstallationKeyV1
        ) -> PluginPrivateDataDeletionPlanV1:
            self.target_id = (
                "private-data:present"
                if (self.root / "user-state.txt").exists()
                else "private-data:absent"
            )
            return super().plan_for(key)

        def receipt_for(
            self,
            plan: PluginPrivateDataDeletionPlanV1,
            confirmation: PluginPrivateDataDeletionConfirmationV1,
        ) -> PluginPrivateDataDeletionReceiptV1 | None:
            receipt_path = self.root / "receipt.json"
            if not receipt_path.exists():
                return None
            record = json.loads(receipt_path.read_text())
            if (
                record["planFingerprint"] != plan.fingerprint
                or record["confirmationId"] != confirmation.confirmation_id
            ):
                return None
            return PluginPrivateDataDeletionReceiptV1(
                installation_key=plan.installation_key,
                owner_id=record["ownerId"],
                target_id=record["targetId"],
                plan_fingerprint=record["planFingerprint"],
                confirmation_id=record["confirmationId"],
                receipt_id=record["receiptId"],
                disposition=record["disposition"],
            )

    (tmp_path / "user-state.txt").write_text("private", encoding="utf-8")
    authority = _ConfirmationAuthority(set())
    owner = _ChangingOwner(tmp_path)
    coordinator = PluginPrivateDataDeletionCoordinator(
        owner, confirmation_authority=authority
    )
    plan = coordinator.preview(_key())
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint, confirmation_id="operator:replay"
    )
    authority.accepted.add((plan.fingerprint, confirmation.confirmation_id))
    receipt = coordinator.delete(plan, confirmation)
    assert coordinator.preview(_key()).target_id == "private-data:absent"

    restarted_owner = _ChangingOwner(tmp_path)
    restarted = PluginPrivateDataDeletionCoordinator(
        restarted_owner, confirmation_authority=authority
    )
    assert restarted.delete(plan, confirmation) == receipt
    assert restarted_owner.delete_calls == 0


def test_durable_confirmation_is_required_after_restart(tmp_path: Path) -> None:
    marker = tmp_path / "user-state.txt"
    marker.write_text("private")
    path = tmp_path / "confirmations.jsonl"
    owner = _PrivateDataOwner(tmp_path)
    first = PluginPrivateDataConfirmationJournal(path)
    plan = PluginPrivateDataDeletionCoordinator(
        owner, confirmation_authority=first
    ).preview(_key())
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id="operator:approved-1",
    )
    with pytest.raises(ValueError, match="not authorized"):
        PluginPrivateDataDeletionCoordinator(
            owner, confirmation_authority=first
        ).delete(plan, confirmation)
    assert marker.exists()

    recorded = first.record_confirmation(
        plan, confirmation, actor_id="operator:alice", policy_revision="policy:1"
    )
    assert recorded.record_revision == 1
    assert (
        first.record_confirmation(
            plan, confirmation, actor_id="operator:alice", policy_revision="policy:1"
        )
        == recorded
    )
    restarted = PluginPrivateDataConfirmationJournal(path)
    assert restarted.is_confirmed(plan, confirmation)
    receipt = PluginPrivateDataDeletionCoordinator(
        owner, confirmation_authority=restarted
    ).delete(plan, confirmation)
    assert receipt.disposition == "deleted"
    assert not marker.exists()

    changed = PluginPrivateDataDeletionPlanV1(
        installation_key=_key(), owner_id=plan.owner_id, target_id="private-data:two"
    )
    with pytest.raises(ValueError, match="confirmation identity"):
        restarted.record_confirmation(
            changed,
            PluginPrivateDataDeletionConfirmationV1(
                plan_fingerprint=changed.fingerprint,
                confirmation_id=confirmation.confirmation_id,
            ),
            actor_id="operator:alice",
            policy_revision="policy:1",
        )

    original = path.read_text()
    assert '"actorId": "operator:alice",' in original
    path.write_text(
        original.replace(
            '"actorId": "operator:alice",',
            '"actorId": "operator:alice", "actorId": "operator:bob",',
            1,
        )
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        restarted.is_confirmed(plan, confirmation)


def test_confirmation_read_does_not_create_a_lock_for_absent_journal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "confirmations.jsonl"
    plan = _PrivateDataOwner(tmp_path).plan_for(_key())
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint, confirmation_id="operator:absent"
    )

    assert not PluginPrivateDataConfirmationJournal(path).is_confirmed(
        plan, confirmation
    )
    assert not path.exists()
    assert not path.with_name(path.name + ".lock").exists()


def test_confirmation_read_refuses_partial_tail_without_repairing_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "confirmations.jsonl"
    journal = PluginPrivateDataConfirmationJournal(path)
    plan = _PrivateDataOwner(tmp_path).plan_for(_key())
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint, confirmation_id="operator:approved"
    )
    journal.record_confirmation(
        plan, confirmation, actor_id="operator:alice", policy_revision="policy:1"
    )
    with path.open("ab") as handle:
        handle.write(b'{"recordRevision":')
    before = path.read_bytes()

    with pytest.raises(ValueError, match="Journal record is not valid JSON"):
        journal.is_confirmed(plan, confirmation)
    assert path.read_bytes() == before
    journal.record_confirmation(
        plan, confirmation, actor_id="operator:alice", policy_revision="policy:1"
    )
    assert journal.is_confirmed(plan, confirmation)
    assert path.read_bytes() == before[: -len(b'{"recordRevision":')]


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink admission")
def test_confirmation_journal_refuses_symlink_without_reading_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "other-owner.jsonl"
    target.write_text("private foreign evidence")
    path = tmp_path / "confirmations.jsonl"
    path.symlink_to(target)
    plan = _PrivateDataOwner(tmp_path).plan_for(_key())
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint, confirmation_id="operator:forged"
    )

    with pytest.raises(ValueError, match="journal is unsafe"):
        PluginPrivateDataConfirmationJournal(path).is_confirmed(plan, confirmation)
    assert target.read_text() == "private foreign evidence"
