"""Cold-process coverage for TUI export loading and public identity."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _cold(body: str) -> None:
    source = Path(__file__).resolve().parents[2] / "src"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys\nsys.path.insert(0, {str(source)!r})\n{body}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "statement",
    (
        "import loushang.tui",
        "from loushang.tui import visible_width; assert visible_width('abc') == 3",
        "from loushang.tui.ui_parts.composer import Composer; Composer()",
    ),
)
def test_core_import_does_not_load_optional_widgets_or_playback(statement: str) -> None:
    _cold(
        statement
        + """
for name in (
    'loushang.tui.playback',
    'loushang.tui.playback_suite',
    'loushang.tui.ui_parts.widgets.data_grid',
    'loushang.tui.ui_parts.widgets.directory_tree',
    'loushang.tui.ui_parts.widgets.tree',
):
    assert name not in sys.modules, name
"""
    )


def test_widget_export_keeps_canonical_identity_without_loading_other_widgets() -> None:
    _cold(
        """
from concurrent.futures import ThreadPoolExecutor
import loushang.tui as tui
import loushang.tui.ui_parts as parts
import loushang.tui.ui_parts.widgets as widgets
assert 'DataGrid' not in tui.__dict__
assert 'DataGrid' in dir(tui)
assert 'loushang.tui.ui_parts.widgets.data_grid' not in sys.modules
with ThreadPoolExecutor(max_workers=8) as pool:
    grids = list(pool.map(lambda _: tui.DataGrid, range(32)))
from loushang.tui.ui_parts.widgets.data_grid import DataGrid
assert all(value is DataGrid for value in grids)
assert tui.DataGrid is parts.DataGrid is widgets.DataGrid is DataGrid
assert 'loushang.tui.ui_parts.widgets.tree' not in sys.modules
assert 'loushang.tui.playback' not in sys.modules
"""
    )


def test_wildcard_exports_and_renamed_alias_keep_existing_objects() -> None:
    _cold(
        """
from importlib import import_module
from loushang.tui.terminal_capabilities import ImageProtocol
import loushang.tui as tui
assert tui.TerminalRuntimeImageProtocol is ImageProtocol
for module_name in ('loushang.tui', 'loushang.tui.ui_parts', 'loushang.tui.ui_parts.widgets'):
    module = import_module(module_name)
    names = module.__all__.copy()
    namespace = {}
    exec(f'from {module_name} import *', namespace)
    assert module.__all__ == names
    assert set(names) <= set(dir(module))
    assert all(namespace[name] is getattr(module, name) for name in names)
"""
    )


def test_failed_export_import_is_retried_and_unknown_names_raise_attribute_error() -> (
    None
):
    _cold(
        """
import loushang.tui as tui
original = tui._import_module
def unavailable(name):
    raise ImportError('dependency unavailable')
tui._import_module = unavailable
try:
    tui.DataGrid
except ImportError:
    pass
else:
    raise AssertionError('import failure must propagate')
assert 'DataGrid' not in tui.__dict__
tui._import_module = original
from loushang.tui.ui_parts.widgets.data_grid import DataGrid
assert tui.DataGrid is DataGrid
try:
    tui.nonexistent_export
except AttributeError:
    pass
else:
    raise AssertionError('unknown name must fail')
"""
    )
