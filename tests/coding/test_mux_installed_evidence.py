"""Exact installed-terminal evidence IDs; never a substitute for native IO."""

from __future__ import annotations

import json
import sys
from functools import partial
from importlib.metadata import distribution
from pathlib import Path

import pytest

from . import test_mux_product_terminal as product
from . import test_mux_terminal_process as installed


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            installed.test_G16_TERMINAL_NATIVE_installed_attach_creates_scoped_member_and_detaches,
            id="G16-INSTALLED-ATTACH",
        ),
        pytest.param(
            product.test_G16_PRODUCT_TERMINAL_two_muxes_approval_detach_reattach_and_interrupt,
            id="G16-INSTALLED-TWO-MUX",
        ),
        pytest.param(
            partial(
                product.test_G16_PRODUCT_TERMINAL_process_death_recovers_history_not_execution,
                scope="cwd",
            ),
            id="G16-INSTALLED-CRASH-CWD",
        ),
        pytest.param(
            partial(
                product.test_G16_PRODUCT_TERMINAL_process_death_recovers_history_not_execution,
                scope="user_home",
            ),
            id="G16-INSTALLED-CRASH-HOME",
        ),
    ],
)
def test_G16_installed_evidence(case, tmp_path, record_testsuite_property):
    from loushang.coding.cli import mux
    from loushang.harnesstui.mux import shell
    from loushang.tui.ui_parts import text_pager

    record_testsuite_property("native_platform", sys.platform)
    direct = json.loads(distribution("loushang").read_text("direct_url.json") or "{}")
    installed = all(
        Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        for module in (mux, shell, text_pager)
    )
    kind = "wheel" if installed and "archive_info" in direct else "editable/source"
    record_testsuite_property("installation", kind)
    case(tmp_path=tmp_path, record_testsuite_property=record_testsuite_property)
