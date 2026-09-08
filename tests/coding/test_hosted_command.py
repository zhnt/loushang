from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.coding.cli.hosted import main, parse_launch


def _argv(root: Path) -> list[str]:
    return [
        "--workspace",
        str(root),
        "--application-root",
        str(root / "applications"),
        "--cwd-sessions",
        str(root / "cwd-sessions"),
        "--home-sessions",
        str(root / "home-sessions"),
    ]


def test_G14_PRODUCT_describe_is_read_only_and_path_free(
    tmp_path: Path, capsys
) -> None:
    before = set(tmp_path.iterdir())
    assert main([*_argv(tmp_path), "--describe"]) == 0
    output = capsys.readouterr()
    description = json.loads(output.out)
    assert output.err == ""
    assert description["profile"] == "foreground-stdio/v1"
    assert description["applicationId"] == "coding.default"
    assert {item["scope"] for item in description["scopes"]} == {"cwd", "user_home"}
    assert str(tmp_path) not in output.out
    assert set(tmp_path.iterdir()) == before


def test_G14_PRODUCT_launch_requires_explicit_separate_roots(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as missing:
        parse_launch([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as overlap:
        parse_launch(
            [*_argv(tmp_path), "--home-sessions", str(tmp_path / "cwd-sessions")]
        )
    assert overlap.value.code == 2
    assert not tuple(tmp_path.iterdir())
