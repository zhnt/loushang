from __future__ import annotations

import ast
import asyncio
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.coding.cli.__main__ import run_cli
from loushang.coding.cli.apphost import (
    extract_apphost_argv,
    run_coding_apphost_command,
)


@dataclass(frozen=True)
class _Report:
    operation: str
    state: str = "enabled"

    @property
    def succeeded(self) -> bool:
        return self.state != "failed"

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptFingerprint": None,
            "code": f"coding_apphost_canary_{self.state}",
            "hostingBackendId": None,
            "hostingTransitions": [],
            "operation": self.operation,
            "receiptFingerprint": None,
            "reportVersion": 1,
            "selectionGeneration": 1,
            "state": self.state,
        }


@pytest.mark.parametrize(
    "_case",
    ("G10-EXACT-COMMAND",),
    ids=("G10-EXACT-COMMAND",),
)
def test_exact_command_dispatches_before_current_session_bootstrap(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case
    calls: list[tuple[tuple[str, ...], Path | str | None]] = []

    async def apphost_runner(
        argv: tuple[str, ...],
        *,
        stdout: io.StringIO,
        stderr: io.StringIO,
        cwd: Path | str | None,
    ) -> int:
        del stdout, stderr
        calls.append((tuple(argv), cwd))
        return 17

    result = asyncio.run(
        run_cli(
            ("--cwd", str(tmp_path), "apphost", "canary", "status"),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            cwd=tmp_path,
            services=object(),
            runtime_builder=lambda **_: pytest.fail("session bootstrap ran"),
            apphost_runner=apphost_runner,
        )
    )
    assert result == 17
    assert calls == [(("--cwd", str(tmp_path), "canary", "status"), tmp_path)]


@pytest.mark.parametrize(
    "_case",
    ("G10-OMISSION-CURRENT",),
    ids=("G10-OMISSION-CURRENT",),
)
def test_only_root_apphost_prefix_is_recognized_and_import_stays_lazy(
    _case: str,
) -> None:
    del _case
    assert extract_apphost_argv(("apphost", "canary", "run")) == (
        "canary",
        "run",
    )
    assert extract_apphost_argv(("--cwd=/tmp", "apphost", "canary", "run")) == (
        "--cwd=/tmp",
        "canary",
        "run",
    )
    for argv in (
        (),
        ("--tui",),
        ("--tui", "apphost", "canary", "run"),
        ("resume", "apphost", "canary", "run"),
        ("canary", "run"),
    ):
        assert extract_apphost_argv(argv) is None
    module = ast.parse(
        Path("src/loushang/coding/cli/apphost.py").read_text(encoding="utf-8")
    )
    top_level_imports = {
        alias.name
        for node in module.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "CodingAppHostCanaryRequestV1" not in top_level_imports


def test_adapter_renders_bounded_json_and_stable_exit_codes(tmp_path: Path) -> None:
    async def runner(*, operation: str, cwd: Path) -> _Report:
        assert cwd == tmp_path
        return _Report(operation)

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = asyncio.run(
        run_coding_apphost_command(
            ("canary", "enable", "--format", "json", "--cwd", str(tmp_path)),
            stdout=stdout,
            stderr=stderr,
            canary_runner=runner,
        )
    )
    assert result == 0
    assert json.loads(stdout.getvalue())["state"] == "enabled"
    assert stderr.getvalue() == ""

    failed = io.StringIO()

    async def failed_runner(*, operation: str, cwd: Path) -> _Report:
        del cwd
        return _Report(operation, state="failed")

    result = asyncio.run(
        run_coding_apphost_command(
            ("canary", "run"),
            stdout=failed,
            stderr=stderr,
            cwd=tmp_path,
            canary_runner=failed_runner,
        )
    )
    assert result == 1
    assert "State: failed" in failed.getvalue()

    prefixed = io.StringIO()
    result = asyncio.run(
        run_coding_apphost_command(
            ("--cwd", str(tmp_path), "canary", "status", "--format", "json"),
            stdout=prefixed,
            stderr=stderr,
            cwd=tmp_path / "ignored",
            canary_runner=runner,
        )
    )
    assert result == 0
    assert json.loads(prefixed.getvalue())["operation"] == "status"


@pytest.mark.parametrize(
    "argv",
    (
        ("canary", "unknown"),
        ("canary", "run", "--format", "yaml"),
        ("wrong", "canary", "run"),
    ),
)
def test_adapter_rejects_invalid_grammar_without_invoking_runtime(
    tmp_path: Path,
    argv: tuple[str, ...],
) -> None:
    async def forbidden(**kwargs: object) -> _Report:
        del kwargs
        raise AssertionError("runtime must not run")

    stderr = io.StringIO()
    result = asyncio.run(
        run_coding_apphost_command(
            argv,
            stdout=io.StringIO(),
            stderr=stderr,
            cwd=tmp_path,
            canary_runner=forbidden,
        )
    )
    assert result == 2
    assert "usage:" in stderr.getvalue()
