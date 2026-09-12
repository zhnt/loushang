"""Early routing uses ordinary grammar and never claims management commands."""

import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from loushang.coding.cli.startup_route import early_screen_project_root


class TTY(StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize(
    "family", ["apphost", "workspace", "lsp", "storage", "ma", "multiagent"]
)
@pytest.mark.parametrize("prefix", [(), ("--cwd", "/repo"), ("--cwd=/repo",)])
def test_management_dispatch_cannot_claim_early_screen(family, prefix):
    assert (
        early_screen_project_root((*prefix, family), stdin=TTY(), stdout=TTY()) is None
    )


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("--tui",),
        ("--session", "saved"),
        ("--resume", "saved"),
        ("--unknown-extension-flag",),
    ],
)
def test_ordinary_conversation_preflight_uses_canonical_grammar(tmp_path, argv):
    assert (
        early_screen_project_root(
            ("--cwd", str(tmp_path), *argv), stdin=TTY(), stdout=TTY()
        )
        == tmp_path
    )


@pytest.mark.parametrize(
    "argv",
    [
        ("--resume",),
        ("--help",),
        ("--version",),
        ("--tui", "--no-tui"),
        ("--extension", "legacy"),
        ("--thinking", "invalid"),
        ("--prompt", "hello"),
    ],
)
def test_ineligible_or_invalid_preflight_defers_to_original_application(argv):
    assert early_screen_project_root(argv, stdin=TTY(), stdout=TTY()) is None


def test_cold_entry_selects_screen_without_importing_application(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src"
    script = (
        f"import sys; sys.path.insert(0, {str(source)!r})\n"
        + """
import asyncio
from io import StringIO
from loushang.coding.cli import __main__ as entry
from loushang.coding.cli import screen_startup

class TTY(StringIO):
    def isatty(self):
        return True

sys.stdin, sys.stdout, sys.stderr = TTY(), TTY(), TTY()
for name in ('loushang.coding.cli.application', 'loushang.coding.bootstrap', 'loushang.coding.ui.mode'):
    assert name not in sys.modules, name

async def screen(argv, *, project_root, cwd):
    assert argv == ('--tui',)
    assert 'loushang.coding.cli.application' not in sys.modules
    return 7

screen_startup.run_screen_first_cli = screen
assert asyncio.run(entry._run_entry(('--tui',))) == 7

async def explicit(argv):
    return 11

entry.run_cli = explicit
assert asyncio.run(entry._run_entry(('--tui',))) == 11
assert 'loushang.coding.cli.application' not in sys.modules
"""
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
