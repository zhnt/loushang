"""Frozen old-reader results, independent of the replacement parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.coding.package_private_data_backup_expiry_journal import (
    CodingArchPrivateDataBackupExpiryJournal,
)
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from loushang.coding.package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
)
from loushang.coding.package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreJournal,
)
from loushang.harness.journal import journal_file_lock
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationJournal,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
)


@pytest.mark.parametrize(
    ("name", "constructor"),
    [
        ("deletion", CodingArchPrivateDataDeletionJournal),
        ("restore", CodingArchPrivateDataRestoreJournal),
        ("confirmation", CodingArchPrivateDataRestoreConfirmationJournal),
        ("expiry", CodingArchPrivateDataBackupExpiryJournal),
        ("deletion_confirmation", PluginPrivateDataConfirmationJournal),
    ],
)
def test_original_journal_error_and_record_contracts(
    tmp_path: Path, name, constructor, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "private_data_journals_v1.json"
        ).read_text()
    )
    reference = fixture["journals"][name]
    line = reference["valid_utf8"]
    revision_key = "recordRevision" if name == "deletion_confirmation" else "revision"
    duplicate = '{"' + revision_key + '":1,' + line[1:]
    invalid = '{"' + revision_key + '":0}\n'
    raw_cases = {
        "valid": line,
        "duplicate_valid": duplicate,
        "duplicate_and_invalid_schema": '{"' + revision_key + '":1,' + invalid[1:],
        "duplicate_before_invalid_schema": duplicate + invalid,
        "duplicate_before_invalid_json": duplicate + "{not-json}\n",
        "duplicate_before_unterminated_tail": duplicate + line.rstrip("\n"),
    }
    tmp_path.chmod(0o700)
    journal = constructor(
        tmp_path / "private-data-confirmations.jsonl"
        if name == "deletion_confirmation"
        else tmp_path
    )
    with journal_file_lock(journal.path, "exclusive"):
        pass
    if name == "deletion_confirmation":
        row = json.loads(line)
        plan = PluginPrivateDataDeletionPlanV1.from_dict(row["plan"])
        confirmation = PluginPrivateDataDeletionConfirmationV1.from_dict(
            row["confirmation"]
        )

        def read():
            return journal.is_confirmed(plan, confirmation)
    else:
        read = journal.records if name == "confirmation" else journal.events
    original_open = Path.open
    reads: list[Path] = []

    def observe_open(path, mode="r", *args, **kwargs):
        if path == journal.path and mode == "r":
            reads.append(path)
        return original_open(path, mode, *args, **kwargs)

    for case, raw in raw_cases.items():
        journal.path.write_text(raw)
        journal.path.chmod(0o600)
        expected = reference["cases"][case]
        reads.clear()
        if "records" in expected or "confirmed" in expected:
            with monkeypatch.context() as patch:
                patch.setattr(Path, "open", observe_open)
                rows = read()
            assert len(reads) == 1, case
            if "confirmed" in expected:
                assert rows is expected["confirmed"], case
                continue
            assert len(rows) == expected["records"], case
            assert rows[0].to_dict() == json.loads(line), case
            continue
        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", observe_open)
            with pytest.raises(Exception) as result:
                read()
        assert len(reads) == 1, case
        error = result.value
        assert (
            type(error).__module__ + "." + type(error).__qualname__
            == expected["error_type"]
        ), case
        assert getattr(error, "code", None) == expected["code"], case
        assert str(error).replace(str(tmp_path), "<STATE>") == expected["message"], case
