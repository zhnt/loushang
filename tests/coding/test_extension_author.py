from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from loushang.coding.extension_author import main


def test_extension_author_init_and_real_offline_tool_smoke(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_home = tmp_path / "parent-home"
    parent_home.mkdir()
    (parent_home / "sentinel").write_text("unchanged", encoding="utf-8")
    monkeypatch.setenv("LOUSHANG_HOME", str(parent_home))
    source = tmp_path / ".loushang" / "extensions" / "hello.py"
    assert main(["init", str(source)]) == 0
    scaffold = json.loads(capsys.readouterr().out)
    assert source.is_file()
    assert scaffold["sourceLoad"] == "not_checked"
    assert scaffold["sessionSelection"] == "not_checked"
    assert scaffold["toolUse"] == "not_checked"
    assert main(scaffold["smokeCommand"][1:]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["sourceLoad"] == "passed"
    assert report["sessionSelection"] == "passed"
    assert report["toolUse"] == "passed"
    assert report["modelTransport"] == "offline"
    assert report["executionTrust"] == "trusted_in_process"
    assert os.environ["LOUSHANG_HOME"] == str(parent_home)
    assert sorted(path.name for path in parent_home.iterdir()) == ["sentinel"]
    with pytest.raises(SystemExit):
        main(["init", str(source)])
    assert "api.register_tool(direct_tool(hello_echo))" in source.read_text(
        encoding="utf-8"
    )


def test_extension_author_smoke_reports_missing_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "hello.py"
    assert main(["init", str(source)]) == 0
    capsys.readouterr()
    assert main(["smoke", str(source), "--tool", "absent"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["sourceLoad"] == "passed"
    assert report["sessionSelection"] == "failed"
    assert report["toolUse"] == "not_checked"
    assert report["failedStage"] == "session_selection"


def test_extension_author_smoke_reports_invalid_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def register(api):\n    nope(\n", encoding="utf-8")
    assert main(["smoke", str(source), "--tool", "broken_echo"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["sourceLoad"] == "failed"
    assert report["sessionSelection"] == "not_checked"
    assert report["toolUse"] == "not_checked"
