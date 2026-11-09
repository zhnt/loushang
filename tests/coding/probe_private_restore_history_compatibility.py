"""Frozen history outcomes preserve the different POSIX and Windows contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.package_private_data_restore_confirmation import (
    CodingArchPrivateDataRestoreConfirmationJournal,
    CodingArchPrivateDataRestoreConfirmationV1,
)
from loushang.coding.package_private_data_restore_journal import (
    CodingArchPrivateDataRestoreEventV1,
    CodingArchPrivateDataRestoreJournal,
)
from loushang.harness.plugin_management._private_data_restore_windows import (
    validate_windows_restore_sequence,
)


@pytest.mark.parametrize("platform", ("posix", "windows"))
def test_history_matches_pre_refactor_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "private_restore_history_v1.json"
        ).read_text()
    )
    journal = CodingArchPrivateDataRestoreJournal(tmp_path)
    monkeypatch.setattr(journal, "_require_safe_journal", lambda: True)
    for name, case in fixture["cases"].items():
        events = tuple(
            CodingArchPrivateDataRestoreEventV1.from_dict(row) for row in case["events"]
        )
        monkeypatch.setattr(
            journal._journal,
            "load",
            lambda rows=events, **kwargs: SimpleNamespace(
                records=rows, require_unique_keys=lambda message: None
            ),
        )
        expected = case[platform]
        try:
            if platform == "posix":
                assert journal._load_unlocked() == events
            else:
                validate_windows_restore_sequence(events, label="Windows Coding Arch")
        except ValueError as error:
            actual = {
                "error_type": type(error).__module__ + "." + type(error).__qualname__,
                "message": str(error),
            }
        else:
            actual = {"accepted": True}
        assert actual == expected, name


def test_result_confirmation_replays_match_original_journal(tmp_path: Path) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "private_restore_confirmation_replays_v1.json"
        ).read_text()
    )
    tmp_path.chmod(0o700)
    journal = CodingArchPrivateDataRestoreConfirmationJournal(tmp_path)
    for operation in fixture["operations"]:
        candidate = operation["record"]
        confirmation = (
            object()
            if candidate is None
            else CodingArchPrivateDataRestoreConfirmationV1.from_dict(candidate)
        )
        try:
            returned = journal.record(confirmation)
        except (TypeError, ValueError) as error:
            actual = {
                "error_type": type(error).__module__ + "." + type(error).__qualname__,
                "message": str(error),
            }
        else:
            actual = {"returned": returned.to_dict()}
        assert actual == operation["expected"], operation["name"]
        reopened = CodingArchPrivateDataRestoreConfirmationJournal(tmp_path)
        assert [item.to_dict() for item in reopened.records()] == operation["history"]
