"""The explicit Windows Worker operator entry stays platform gated."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import loushang.coding.cli.package_worker_windows_candidate as cli


@pytest.mark.parametrize("windows_candidate", (True, False))
def test_windows_worker_candidate_cli_requires_native_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    windows_candidate: bool,
) -> None:
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="posix"))
    args = ["--workspace", str(tmp_path)]
    if windows_candidate:
        args.append("--windows-candidate")
    args.extend(("recover-crash", "--attempt-id", "a" * 32))
    with patch.object(cli, "open_coding_fenced_product_application_owner") as opened:
        assert cli.main(args) == 1
    opened.assert_not_called()
    assert "windows_worker_candidate_platform_closed" in capsys.readouterr().err
    assert tuple(tmp_path.iterdir()) == ()


def test_windows_worker_explicit_operator_command_needs_no_candidate_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))
    with (
        patch.object(cli.platform, "machine", return_value="AMD64"),
        patch.object(cli, "resolve_coding_plugin_lifecycle_state_layout") as layout,
        patch.object(
            cli, "_run_product_action", return_value={"workerSelection": "checked"}
        ) as action,
    ):
        assert (
            cli.main(
                (
                    "--workspace",
                    str(tmp_path),
                    "candidate-status",
                    "--plugin-id",
                    "demo",
                )
            )
            == 0
        )
    layout.assert_called_once_with(tmp_path)
    action.assert_called_once()
    assert '"workerSelection": "checked"' in capsys.readouterr().out


def test_windows_worker_update_reports_required_opt_in_revocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))

    def refuse_allowed_revision(*_args):
        cli._require_candidate_revoked(SimpleNamespace(), "demo")

    with (
        patch.object(cli.platform, "machine", return_value="AMD64"),
        patch.object(cli, "resolve_coding_plugin_lifecycle_state_layout"),
        patch.object(cli, "_run_product_action", side_effect=refuse_allowed_revision),
        patch.object(cli, "CodingWindowsWorkerProductOptInOwner") as opt_in,
    ):
        opt_in.return_value.current.return_value = SimpleNamespace(action="allow")
        assert (
            cli.main(
                (
                    "--workspace",
                    str(tmp_path),
                    "candidate-update",
                    "--plugin-id",
                    "demo",
                    "--from-artifact-digest",
                    "a" * 64,
                    "--artifact-digest",
                    "b" * 64,
                    "--operation-id",
                    "update-demo",
                    "--expected-inventory-revision",
                    "1",
                )
            )
            == 1
        )
    output = capsys.readouterr()
    assert output.out == ""
    assert "windows_worker_candidate_opt_in_revoke_required" in output.err
    assert tuple(tmp_path.iterdir()) == ()


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows")
def test_native_windows_worker_operator_accepts_command_without_candidate_switch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(cli, "resolve_coding_plugin_lifecycle_state_layout") as layout,
        patch.object(
            cli, "_run_product_action", return_value={"workerSelection": "checked"}
        ) as action,
    ):
        assert (
            cli.main(
                (
                    "--workspace",
                    str(tmp_path),
                    "candidate-status",
                    "--plugin-id",
                    "demo",
                )
            )
            == 0
        )
    layout.assert_called_once_with(tmp_path)
    action.assert_called_once()
    assert action.call_args.args[2].windows_candidate is False
    assert '"workerSelection": "checked"' in capsys.readouterr().out
