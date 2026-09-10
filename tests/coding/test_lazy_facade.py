"""Fresh-process lazy facade contracts, independent of the real runtime owners."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_probe(tmp_path: Path, body: str) -> None:
    source = Path(__file__).resolve().parents[2] / "src"
    code = f"""
import importlib.abc
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, {str(source)!r})
source = Path({str(source)!r})
{body}
"""
    environment = {
        name: value
        for name in ("PATH", "SYSTEMROOT", "WINDIR")
        if (value := os.environ.get(name)) is not None
    }
    for name in (
        "HOME",
        "USERPROFILE",
        "LOUSHANG_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "LOUSHANG_TMPDIR",
        "TMPDIR",
        "TMP",
        "TEMP",
    ):
        environment[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-I", "-X", f"pycache_prefix={tmp_path / 'pyc'}", "-c", code],
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr


def test_import_dir_and_unknown_name_do_not_load_runtime_owners(tmp_path: Path) -> None:
    _run_probe(
        tmp_path,
        """
class NoRuntimeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('loushang.') and fullname != 'loushang.coding':
            raise AssertionError(f'unexpected eager runtime import: {fullname}')

sys.meta_path.insert(0, NoRuntimeImports())
import loushang.coding as coding
assert Path(coding.__file__).resolve() == source / 'loushang/coding/__init__.py'
assert all(name not in vars(coding) for name in coding.__all__)
assert set(coding.__all__) <= set(dir(coding))
assert not hasattr(coding, 'G18_missing_export')
try:
    getattr(coding, 'G18_missing_export')
except AttributeError:
    pass
else:
    raise AssertionError('unknown export did not raise AttributeError')
assert all(name not in vars(coding) for name in coding.__all__)
assert {name for name in sys.modules if name.startswith('loushang.')} == {'loushang.coding'}
""",
    )


@pytest.mark.parametrize(
    ("public", "owner", "original"),
    [
        ("SessionManager", "loushang.coding.session_manager", "SessionManager"),
        (
            "DefaultResourceLoader",
            "loushang.coding.resource_runtime",
            "CodingResourceLoader",
        ),
    ],
)
@pytest.mark.parametrize("phase", ["import", "attribute"])
@pytest.mark.parametrize(
    "error_name", ["ModuleNotFoundError", "AttributeError", "KeyError", "RuntimeError"]
)
def test_export_failure_propagates_and_only_success_is_cached(
    tmp_path: Path, public: str, owner: str, original: str, phase: str, error_name: str
) -> None:
    _run_probe(
        tmp_path,
        f"""
public, owner, original = {public!r}, {owner!r}, {original!r}
phase = {phase!r}
marker = {error_name}('G18 owner failure')
value = object()
loads = []
lookups = []
failed = False
allow_owner = False

class OwnerLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        global failed
        loads.append(module.__name__)
        if phase == 'import' and not failed:
            failed = True
            raise marker

        def resolve(name):
            global failed
            if name != original:
                raise AttributeError(name)
            lookups.append(name)
            if phase == 'attribute' and not failed:
                failed = True
                raise marker
            return value

        module.__getattr__ = resolve

class OnlySelectedOwner(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == owner and allow_owner:
            return importlib.util.spec_from_loader(fullname, OwnerLoader())
        if fullname.startswith('loushang.') and fullname != 'loushang.coding':
            raise AssertionError(f'unexpected runtime import: {{fullname}}')

sys.meta_path.insert(0, OnlySelectedOwner())
import loushang.coding as coding
assert Path(coding.__file__).resolve() == source / 'loushang/coding/__init__.py'
assert public not in vars(coding) and owner not in sys.modules
allow_owner = True
try:
    getattr(coding, public)
except BaseException as error:
    assert error is marker, (type(error).__name__, str(error))
else:
    raise AssertionError('owner failure was swallowed')
assert public not in vars(coding), 'failed lookup was cached'
assert (owner in sys.modules) == (phase == 'attribute')
assert getattr(coding, public) is value
assert vars(coding)[public] is value
assert getattr(coding, public) is value
assert len(loads) == (2 if phase == 'import' else 1)
assert len(lookups) == (1 if phase == 'import' else 2)
assert {{name for name in sys.modules if name.startswith('loushang.')}} == {{'loushang.coding', owner}}
""",
    )
