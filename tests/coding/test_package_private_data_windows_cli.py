"""The Windows private-data command must bind the existing Product client."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import loushang.coding.cli.plugin_private_data as cli


def test_windows_private_data_status_uses_product_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))
    record = SimpleNamespace(to_dict=lambda: {"status": "retained"})
    with (
        patch.object(cli, "resolve_coding_plugin_lifecycle_state_layout") as layout,
        patch.object(cli, "open_coding_windows_arch_backup_candidate_client") as open_client,
        patch.object(cli, "version", return_value="2.0.0"),
    ):
        open_client.return_value.status.return_value = record
        assert cli.main(
            (
                "--workspace",
                str(tmp_path),
                "--plugin-id",
                "coding.arch.default",
                "backup-status",
            )
        ) == 0
    open_client.assert_called_once_with(
        tmp_path, layout=layout.return_value, runtime_version="2.0.0"
    )
    assert json.loads(capsys.readouterr().out) == {
        "backupRetention": {"status": "retained"}
    }


def test_windows_restore_confirmation_needs_original_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))
    with (
        patch.object(cli, "resolve_coding_plugin_lifecycle_state_layout"),
        patch.object(cli, "open_coding_windows_arch_backup_candidate_client") as open_client,
        patch.object(cli, "version", return_value="2.0.0"),
    ):
        assert cli.main(
            (
                "--workspace",
                str(tmp_path),
                "--plugin-id",
                "coding.arch.default",
                "restore-confirm",
                "--backup-id",
                "a" * 64,
            )
        ) == 1
    open_client.return_value.restore_confirm.assert_not_called()
    assert "operation_refused" in capsys.readouterr().err
