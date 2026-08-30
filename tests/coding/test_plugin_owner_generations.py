from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding._plugin_owner_generations import (
    CodingOwnerGenerationEvidenceError,
    CodingOwnerGenerationEvidenceLedger,
)
from loushang.harness.resources.plugins import PluginInstanceRevisionRef
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)


def test_owner_generation_evidence_survives_restart_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    path = tmp_path / "owner-generations.jsonl"
    ref = _instance_ref()
    receipts = (_receipt("session-a", "tools.workspace", "coding.builtin"),)
    ledger = CodingOwnerGenerationEvidenceLedger(path)

    published = ledger.publish(
        family_id="family-a",
        instance_revision_ref=ref,
        receipts=receipts,
        publication_reference="publication:a",
    )
    repeated = ledger.publish(
        family_id="family-a",
        instance_revision_ref=ref,
        receipts=receipts,
        publication_reference="publication:repeated",
    )

    assert repeated == published
    assert published.retired is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    restarted = CodingOwnerGenerationEvidenceLedger(path)
    retired = restarted.retire(
        family_id="family-a",
        instance_revision_ref=ref,
        receipts=receipts,
        outcome_reference="disposed:a",
    )
    repeated_retirement = restarted.retire(
        family_id="family-a",
        instance_revision_ref=ref,
        receipts=receipts,
        outcome_reference="disposed:repeated",
    )

    assert repeated_retirement == retired
    assert retired.retired is True
    assert retired.retirement_outcome_reference == "disposed:a"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert restarted.retired_receipts_for_instance(ref) == receipts


def test_owner_generation_evidence_rejects_conflicting_family_reuse(
    tmp_path: Path,
) -> None:
    ledger = CodingOwnerGenerationEvidenceLedger(
        tmp_path / "owner-generations.jsonl"
    )
    ref = _instance_ref()
    original = (_receipt("session-a", "commands.session", "coding.standard"),)
    ledger.publish(
        family_id="family-a",
        instance_revision_ref=ref,
        receipts=original,
        publication_reference="publication:a",
    )

    with pytest.raises(CodingOwnerGenerationEvidenceError) as caught:
        ledger.publish(
            family_id="family-a",
            instance_revision_ref=ref,
            receipts=(
                _receipt("session-a", "tools.workspace", "coding.builtin"),
            ),
            publication_reference="publication:conflict",
        )

    assert caught.value.code == "coding_owner_generation_evidence_conflict"
    with pytest.raises(CodingOwnerGenerationEvidenceError) as pending:
        ledger.retired_receipts_for_instance(ref)
    assert pending.value.code == "coding_owner_generation_cleanup_pending"


def test_owner_generation_evidence_rejects_empty_publication(tmp_path: Path) -> None:
    ledger = CodingOwnerGenerationEvidenceLedger(
        tmp_path / "owner-generations.jsonl"
    )

    with pytest.raises(ValueError, match="must not be empty"):
        ledger.publish(
            family_id="family-a",
            instance_revision_ref=_instance_ref(),
            receipts=(),
            publication_reference="publication:a",
        )


def test_owner_generation_evidence_fails_closed_on_corrupt_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "owner-generations.jsonl"
    ledger = CodingOwnerGenerationEvidenceLedger(path)
    ledger.publish(
        family_id="family-a",
        instance_revision_ref=_instance_ref(),
        receipts=(
            _receipt("session-a", "commands.session", "coding.standard"),
        ),
        publication_reference="publication:a",
    )
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(CodingOwnerGenerationEvidenceError) as caught:
        CodingOwnerGenerationEvidenceLedger(path).family("family-a")

    assert caught.value.code == "coding_owner_generation_evidence_corrupt"


def _instance_ref() -> PluginInstanceRevisionRef:
    return PluginInstanceRevisionRef(
        instance_id="coding.base@workspace:test",
        plugin_id="coding.base",
        revision=1,
    )


def _receipt(
    session_id: str,
    owner_id: str,
    contribution_id: str,
) -> OwnerGenerationRetirementReceipt:
    return OwnerGenerationRetirementReceipt(
        owner_reference=f"owner:{session_id}:{owner_id}",
        owner_generation_reference=f"generation:{session_id}:{owner_id}:1",
        retirement_handle=f"retirement:{session_id}:{owner_id}:1",
        contribution_ids=(contribution_id,),
    )
