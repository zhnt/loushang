"""The Windows Worker candidate operator entry stays explicitly gated."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import loushang.coding.cli.package_worker_windows_candidate as cli


@pytest.mark.parametrize(
    ("platform", "windows_candidate"), (("posix", True), ("nt", False))
)
def test_windows_worker_candidate_cli_requires_native_explicit_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    platform: str,
    windows_candidate: bool,
) -> None:
    monkeypatch.setattr(cli, "os", SimpleNamespace(name=platform))
    args = ["--workspace", str(tmp_path)]
    if windows_candidate:
        args.append("--windows-candidate")
    args.extend(("recover-crash", "--attempt-id", "a" * 32))
    with patch.object(cli, "open_coding_fenced_product_application_owner") as opened:
        assert cli.main(args) == 1
    opened.assert_not_called()
    assert "windows_worker_candidate_platform_closed" in capsys.readouterr().err
    assert tuple(tmp_path.iterdir()) == ()
