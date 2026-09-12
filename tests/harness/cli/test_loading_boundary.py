"""Cold-process compatibility checks for the package-local CLI facade."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_submodule_import_fallback_and_directory_listing_stay_lazy(tmp_path):
    cold(
        tmp_path,
        """
import loushang.harness.cli as cli
before = set(sys.modules)
assert 'CliProfile' in dir(cli)
assert set(sys.modules) == before
from loushang.harness.cli import host_operations
assert host_operations is sys.modules['loushang.harness.cli.host_operations']
assert 'CliProfile' not in cli.__dict__
""",
    )


def cold(tmp_path, source):
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() in {"path", "systemroot", "windir", "pathext"}
    }
    environment.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r})\n" + source,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_grammar_does_not_load_application_or_optional_commands(tmp_path):
    cold(
        tmp_path,
        """
from loushang.harness.cli import CliProfile, STANDARD_CLI_PROFILE
assert STANDARD_CLI_PROFILE.profile_id
for name in ('application', 'agent_host', 'package_lifecycle', 'export', 'method_listing'):
    assert 'loushang.harness.cli.' + name not in sys.modules, name
""",
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_all_legacy_exports_keep_order_and_original_identity(tmp_path, reverse):
    cold(
        tmp_path,
        f"""
import hashlib, importlib, json
import loushang.harness.cli as cli
origins = {{name:(module, name) for name, module in cli._EXPORTS.items()}}
fingerprint = hashlib.sha256(json.dumps({{'exports':cli.__all__, 'origins':origins}},sort_keys=True).encode()).hexdigest()
assert fingerprint == '2bfe86567fe6edf9faee04c1346dda5a1e189aa807a0dcbd110837be9f09f911'
assert set(cli.__all__).issubset(dir(cli))
for name in (list(reversed(cli.__all__)) if {reverse!r} else cli.__all__):
    value = getattr(cli, name)
    assert value is getattr(importlib.import_module(cli._EXPORTS[name]),name), name
    assert cli.__dict__[name] is value
namespace = {{}}
exec('from loushang.harness.cli import *', namespace)
assert all(namespace[name] is getattr(cli,name) for name in cli.__all__)
""",
    )


def test_failure_is_not_cached_and_explicit_replacement_is_honored(tmp_path):
    cold(
        tmp_path,
        """
import loushang.harness.cli as cli
original = cli._import_module
def unavailable(name):
    raise ImportError('dependency unavailable')
cli._import_module = unavailable
try:
    cli.CliProfile
except ImportError:
    pass
else:
    raise AssertionError('must preserve import failure')
assert 'CliProfile' not in cli.__dict__
cli._import_module = original
value = cli.CliProfile
sentinel = object()
cli.CliProfile = sentinel
from loushang.harness.cli import CliProfile
assert CliProfile is sentinel
cli.CliProfile = value
from loushang.harness.cli import CliProfile
assert CliProfile is value
try:
    cli.nonexistent_export
except AttributeError:
    pass
else:
    raise AssertionError('unknown name must fail')
""",
    )
