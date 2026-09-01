from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDependencyPinReceiptV1,
    PackageDesiredStateCommitFailureV1,
    PackageDesiredStateCommitReceiptV1,
    PackageDesiredStateCommitRequestV1,
    PackageDesiredStateCommitResultV1,
    PackageRetentionHandoffError,
    PackageRetentionHandoffFailureV1,
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffOwner,
    PackageRetentionHandoffReceiptV1,
    PackageRetentionHandoffRequestV1,
    PackageRetentionHandoffResultV1,
)


def test_b4b_retention_handoff_contract_is_dark_and_versioned() -> None:
    records = (
        PackageDesiredStateCommitRequestV1,
        PackageDesiredStateCommitReceiptV1,
        PackageDesiredStateCommitFailureV1,
        PackageDesiredStateCommitResultV1,
        PackageDependencyPinReceiptV1,
        PackageRetentionHandoffRequestV1,
        PackageRetentionHandoffReceiptV1,
        PackageRetentionHandoffFailureV1,
        PackageRetentionHandoffResultV1,
    )

    assert all(record.__module__.endswith(".retention_handoff") for record in records)
    assert PackageRetentionHandoffJournal.__module__.endswith(".retention_handoff")
    assert PackageRetentionHandoffOwner.__module__.endswith(".retention_handoff")


def test_handoff_journal_rejects_duplicate_json_keys_with_stable_error(
    tmp_path: Path,
) -> None:
    journal = PackageRetentionHandoffJournal(tmp_path / "handoff.jsonl")
    journal.path.write_text(
        '{"recordVersion":1,"recordVersion":1}\n',
        encoding="utf-8",
    )

    with pytest.raises(PackageRetentionHandoffError) as caught:
        journal.records()

    assert caught.value.code == "package_retention_handoff_journal_corrupt"
    assert caught.value.path == journal.path
