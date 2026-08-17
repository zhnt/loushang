from __future__ import annotations

import json
from pathlib import Path

from loushang.coding.arch.cli import main


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from . import api\n", encoding="utf-8")
    (package / "api.py").write_text("from pkg import core\n", encoding="utf-8")
    (package / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    return package


def test_cli_prints_bounded_json_query(tmp_path: Path, capsys) -> None:
    package = _package(tmp_path)

    exit_code = main(
        (
            str(package),
            "--package-prefix",
            "pkg",
            "--query",
            "edges",
            "--source",
            "pkg.api",
            "--limit",
            "1",
            "--cache-dir",
            str(tmp_path / "cache"),
        )
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["query"] == "edges"
    assert payload["results"][0]["target"] == "pkg.core"


def test_cli_can_fail_a_boundary_gate(tmp_path: Path, capsys) -> None:
    package = _package(tmp_path)

    exit_code = main(
        (
            str(package),
            "--package-prefix",
            "pkg",
            "--query",
            "boundaries",
            "--deny",
            "pkg.api=pkg.core",
            "--fail-on-violations",
            "--cache-dir",
            str(tmp_path / "cache"),
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["results"][0]["rule_id"] == "deny:pkg.api=pkg.core"


def test_cli_reports_invalid_query_input_as_json(tmp_path: Path, capsys) -> None:
    package = _package(tmp_path)

    exit_code = main(
        (
            str(package),
            "--query",
            "path",
            "--cache-dir",
            str(tmp_path / "cache"),
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.err) == {
        "error": "path query requires source and target"
    }


def test_cli_uses_disk_cache_by_default_and_opt_in_telemetry_is_separate(
    tmp_path: Path,
    capsys,
) -> None:
    package = _package(tmp_path)
    cache_dir = tmp_path / "cache"
    arguments = (
        str(package),
        "--package-prefix",
        "pkg",
        "--cache-dir",
        str(cache_dir),
        "--cache-info",
    )

    assert main(arguments) == 0
    cold = json.loads(capsys.readouterr().out)
    assert main(arguments) == 0
    warm = json.loads(capsys.readouterr().out)

    assert cold["cache"]["misses"] == 3
    assert warm["cache"]["hits"] == 3
    cold.pop("cache")
    warm.pop("cache")
    assert cold == warm


def test_cli_can_disable_cache(tmp_path: Path, capsys) -> None:
    package = _package(tmp_path)

    assert main((str(package), "--no-cache", "--cache-info")) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["cache"] == {
        "enabled": False,
        "entries": 0,
        "error": None,
        "hits": 0,
        "invalidated": 0,
        "misses": 3,
    }
