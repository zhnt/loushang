"""Cold-process guards for the small CLI entrypoint and its unchanged fallback."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _probe(tmp_path: Path, body: str) -> None:
    source = Path(__file__).resolve().parents[2] / "src"
    code = f"""
import importlib.abc
import importlib.metadata
import io
import sys
import types
from contextlib import redirect_stdout, redirect_stderr
sys.path.insert(0, {str(source)!r})
{body}
"""
    env = {
        name: value
        for name in ("PATH", "SYSTEMROOT", "WINDIR")
        if (value := os.environ.get(name)) is not None
    }
    for name in (
        "HOME",
        "USERPROFILE",
        "LOUSHANG_HOME",
        "LOUSHANG_RUNTIME_DIR",
        "LOUSHANG_TMPDIR",
        "TMPDIR",
        "TMP",
        "TEMP",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "XDG_RUNTIME_DIR",
    ):
        env[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-I", "-X", f"pycache_prefix={tmp_path / 'pyc'}", "-c", code],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr


_BLOCK_APPLICATION = """
class BlockApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('loushang.') and fullname not in {
            'loushang.coding', 'loushang.coding.cli', 'loushang.coding.cli.__main__',
        }:
            raise AssertionError(f'unexpected runtime import: {fullname}')
sys.meta_path.insert(0, BlockApplication())
"""


def test_cold_entry_and_grammar_facade_do_not_import_runtime(tmp_path):
    _probe(
        tmp_path,
        _BLOCK_APPLICATION
        + """
import loushang.coding.cli as cli
import loushang.coding.cli.__main__ as entry
assert set(cli.__all__) == {'CliArgs', 'parse_args'}
assert set(cli.__all__) <= set(dir(cli))
assert not hasattr(cli, 'main') and not hasattr(cli, 'run_cli')
assert not hasattr(entry, '__path__')
assert 'run_cli' not in vars(entry)
assert not any(name.startswith('loushang.harness') for name in sys.modules)
""",
    )


@pytest.mark.parametrize("invocation", ["explicit", "process-argv", "module"])
def test_canonical_version_never_loads_application(tmp_path, invocation):
    _probe(
        tmp_path,
        _BLOCK_APPLICATION
        + f"""
def version(name):
    assert name == 'loushang'
    return '42.3-test'
importlib.metadata.version = version
out, err = io.StringIO(), io.StringIO()
with redirect_stdout(out), redirect_stderr(err):
    if {invocation!r} == 'module':
        import runpy
        sys.argv = ['loushang', '--version']
        try:
            runpy.run_module('loushang.coding.cli', run_name='__main__')
        except SystemExit as error:
            assert error.code == 0
        else:
            raise AssertionError('module entry did not exit')
    else:
        import loushang.coding.cli.__main__ as entry
        sys.argv = ['loushang', '--version']
        assert entry.main(['--version'] if {invocation!r} == 'explicit' else None) == 0
assert out.getvalue() == '42.3-test\\n' and err.getvalue() == ''
assert 'loushang.coding.cli.application' not in sys.modules
""",
    )


@pytest.mark.parametrize("failure", ["missing", "invalid", "interrupt"])
def test_metadata_fallback_errors_and_interrupt_policy(tmp_path, failure):
    _probe(
        tmp_path,
        _BLOCK_APPLICATION
        + f"""
import loushang.coding.cli.__main__ as entry
marker = (importlib.metadata.PackageNotFoundError('loushang') if {failure!r} == 'missing'
          else ValueError('invalid metadata') if {failure!r} == 'invalid'
          else KeyboardInterrupt())
def fail(name):
    assert name == 'loushang'
    raise marker
importlib.metadata.version = fail
out, err = io.StringIO(), io.StringIO()
with redirect_stdout(out), redirect_stderr(err):
    if {failure!r} == 'invalid':
        try:
            entry.main(['--version'])
        except ValueError as error:
            assert error is marker
        else:
            raise AssertionError('metadata error was hidden')
    else:
        assert entry.main(['--version']) == (0 if {failure!r} == 'missing' else 130)
assert out.getvalue() == ('0.1.0\\n' if {failure!r} == 'missing' else '')
assert err.getvalue() == ('Interrupted.\\n' if {failure!r} == 'interrupt' else '')
""",
    )


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--help"],
        ["-h"],
        ["--version", "--verbose"],
        ["--verbose", "--version"],
        ["--version", "--help"],
        ["--", "--version"],
        ["--version", "--provider"],
        ["apphost", "--version"],
        ["--bogus", "--version"],
        ["--version", "--extension", "removed"],
        ["--tui", "--version"],
        ["--version", "--version"],
        ["--resume"],
    ],
)
def test_every_noncanonical_invocation_forwards_original_argv(tmp_path, argv):
    _probe(
        tmp_path,
        f"""
import loushang.coding.cli.__main__ as entry
original = {argv!r}
calls = []
async def run_cli(argv):
    assert argv is original
    calls.append(argv)
    return 29
application = types.ModuleType('loushang.coding.cli.application')
application.run_cli = run_cli
sys.modules[application.__name__] = application
def forbidden(name):
    raise AssertionError('noncanonical invocation used metadata shortcut')
importlib.metadata.version = forbidden
assert entry.main(original) == 29
assert calls == [original]
assert entry.run_cli is run_cli
""",
    )


def test_explicit_run_cli_binding_is_not_bypassed_by_version(tmp_path):
    _probe(
        tmp_path,
        _BLOCK_APPLICATION
        + """
import loushang.coding.cli.__main__ as entry
calls = []
async def replacement(argv):
    calls.append(argv)
    return 17
entry.run_cli = replacement
assert entry.main(['--version']) == 17
assert calls == [['--version']]
""",
    )


def test_tty_application_runner_injection_preserves_original_call(tmp_path):
    _probe(
        tmp_path,
        """
import loushang.coding.cli.__main__ as entry
class TTY(io.StringIO):
    def isatty(self):
        return True
sys.stdin, sys.stdout, sys.stderr = TTY(), TTY(), TTY()
original = []
calls = []
async def replacement(argv):
    assert argv is original
    calls.append(argv)
    return 31
application = types.ModuleType('loushang.coding.cli.application')
application.run_cli = replacement
sys.modules[application.__name__] = application
assert entry.main(original) == 31
assert calls == [original]
assert entry.run_cli is replacement
assert 'loushang.coding.cli.screen_startup' not in sys.modules
""",
    )


def test_historical_function_reads_keep_actual_application_identity(tmp_path):
    _probe(
        tmp_path,
        """
from loushang.coding.cli import application, args, __main__ as entry
import loushang.coding.cli as cli
assert entry.run_cli is application.run_cli
assert entry.build_default_services is application.build_default_services
assert entry.default_runtime_builder is application.default_runtime_builder
assert entry._help_text is application._help_text
assert cli.CliArgs is args.CliArgs
assert cli.parse_args is args.parse_args
""",
    )


@pytest.mark.parametrize("phase", ["import", "lookup"])
def test_grammar_facade_caches_only_successful_owner_lookup(tmp_path, phase):
    _probe(
        tmp_path,
        f"""
import loushang.coding.cli as cli
marker = RuntimeError('owner failure')
value = object()
class Owner:
    @property
    def parse_args(self):
        raise marker
def fail(name):
    assert name == 'loushang.coding.cli.args'
    if {phase!r} == 'import':
        raise marker
    return Owner()
cli._import_module = fail
try:
    cli.parse_args
except RuntimeError as error:
    assert error is marker
else:
    raise AssertionError('owner failure was hidden')
assert 'parse_args' not in vars(cli)
cli._import_module = lambda name: types.SimpleNamespace(parse_args=value)
assert cli.parse_args is value and vars(cli)['parse_args'] is value
""",
    )


def test_entrypoint_project_imports_are_only_explicit_startup_boundaries():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "src/loushang/coding/cli/__main__.py").read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module.startswith("loushang.")
    }
    # Early screen routing is a lightweight composition boundary, not permission
    # for the entrypoint to import Product/bootstrap/provider implementations.
    assert imports == {
        "loushang.coding.cli",
        "loushang.coding.cli.application",
        "loushang.coding.cli.startup_route",
        "loushang.coding.cli.screen_startup",
    }
