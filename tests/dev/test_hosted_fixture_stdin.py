"""Non-interactive installed commands cannot inherit a supervisor pipe."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

from tests.coding import test_hosted_client_terminal as foreground
from tests.coding import test_mux_product_terminal as local


def test_foreground_help_and_local_management_have_explicit_empty_input(tmp_path, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 30
        calls.append(argv)
        return SimpleNamespace(returncode=0, stderr="", stdout=(
            "exit ends its application" if "--help" in argv else "{}"
        ))

    monkeypatch.setattr(foreground, "_installed", lambda: "foreground-cli")
    monkeypatch.setattr(local, "_installed", lambda: "local-cli")
    monkeypatch.setattr(foreground, "_terminal_environment", lambda root: {})
    monkeypatch.setattr(subprocess, "run", run)
    foreground._installed_help(tmp_path)
    assert local._command(tmp_path, {}, "create", "dev") == {}
    assert len(calls) == 2


def test_g14_help_null_input_does_not_replace_the_service_protocol_pipe():
    from tests.coding import test_hosted_subprocess as legacy

    tree = ast.parse(Path(legacy.__file__).read_text())
    owners = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name in {"_child", "test_G14_PRODUCT_installed_entrypoint_help_startup_and_clean_eof"}]
    commands = [node for owner in owners for node in ast.walk(owner) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "create_subprocess_exec"]
    assert len(commands) == 2
    for call in commands:
        help_command = any(isinstance(arg, ast.Constant) and arg.value == "--help" for arg in call.args)
        stdin = next(keyword.value for keyword in call.keywords if keyword.arg == "stdin")
        assert ast.unparse(stdin) == ("asyncio.subprocess.DEVNULL" if help_command else "asyncio.subprocess.PIPE")
