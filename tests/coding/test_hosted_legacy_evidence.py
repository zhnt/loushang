"""Complete legacy family: installed local, G14 stdio and Embedded CLI paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from loushang.tui.cell_width import strip_control_sequences
from tests.tui.terminal_process_support import selected_backend_name

from ._hosted_terminal import foreground_terminal
from .test_hosted_subprocess import (
    test_G14_PRODUCT_installed_entrypoint_help_startup_and_clean_eof as _g14,
)
from .test_hosted_workflow_terminal import (
    test_G17_TERMINAL_LEGACY_local_picker_unavailable_keeps_existing_commands as _local,
)
from .test_mux_terminal_process import _terminal_environment


def _private_environment(root):
    # Only OS/terminal prerequisites and the explicit private Loushang roots.
    # Do not pass ambient provider keys, tokens, plugin options or source paths.
    allowed = {
        "path",
        "pathext",
        "systemroot",
        "windir",
        "comspec",
        "temp",
        "tmp",
        "tmpdir",
        "ld_library_path",
        "dyld_library_path",
        "lang",
        "lc_all",
        "lc_ctype",
        "tz",
        "term",
        "colorterm",
        "pythonunbuffered",
        "loushang_home",
        "loushang_runtime_dir",
        "loushang_tmpdir",
    }
    return {
        key: value
        for key, value in _terminal_environment(root).items()
        if key.casefold() in allowed
    }


def _embedded(root):
    command = Path(sys.executable).parent / (
        "loushang.exe" if os.name == "nt" else "loushang"
    )
    assert command.is_file(), "the installed Embedded command must exist"
    with foreground_terminal(
        [str(command), "--tui"],
        cwd=root,
        env=_private_environment(root),
        columns=100,
        rows=30,
    ) as driver:
        driver.read_until(
            lambda out: (
                "Welcome to Loushang CLI" in strip_control_sequences(out)
                and "\x1b[?2004h" in out
                and "\x1b[?1004h" in out
            ),
            timeout=35,
        )
        assert "/exit ends app" not in strip_control_sequences(driver.raw_output)
        driver.write("/quit\r")
        assert driver.wait(timeout=25) == 0, driver.diagnostics
        output = driver.raw_output
        for enable, disable in (
            ("\x1b[?2004h", "\x1b[?2004l"),
            ("\x1b[?1004h", "\x1b[?1004l"),
        ):
            assert output.rfind(disable) > output.find(enable) >= 0
        assert driver.diagnostics.termination is None
    assert not driver.diagnostics.reader_alive


def test_G17_TERMINAL_LEGACY_installed_profiles_and_embedded_startup(
    tmp_path,
    record_testsuite_property,
    monkeypatch,
):
    record_testsuite_property("terminal_backend", selected_backend_name())
    record_testsuite_property("native_platform", sys.platform)
    roots = {name: tmp_path / name for name in ("local", "g14", "embedded")}
    for root in roots.values():
        root.mkdir()
    with patch.dict(os.environ, _private_environment(roots["local"]), clear=True):
        _local(roots["local"], record_testsuite_property)
    # G14's older helper inherits cwd/environment; confine it without changing
    # its legacy defaults or allowing source paths to satisfy this family.
    with monkeypatch.context() as scope:
        scope.chdir(roots["g14"])
        with patch.dict(os.environ, _private_environment(roots["g14"]), clear=True):
            _g14(roots["g14"])
    _embedded(roots["embedded"])


def test_legacy_environment_excludes_ambient_source_and_credentials(
    tmp_path, monkeypatch
):
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "LOUSHANG_G14_TEST_FAIL_DISPOSE",
    ):
        monkeypatch.setenv(name, "ambient-sentinel")
    environment = _private_environment(tmp_path)
    assert "ambient-sentinel" not in environment.values()
    assert environment["LOUSHANG_HOME"] == str(tmp_path / "platform")


def test_legacy_aggregate_confines_inherited_g14_environment(tmp_path, monkeypatch):
    module = sys.modules[__name__]
    observed = []
    for name in ("PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "ambient-sentinel")

    def check(root, *args):
        assert "ambient-sentinel" not in os.environ.values()
        assert os.environ["LOUSHANG_HOME"] == str(root / "platform")
        if root.name == "g14":
            assert Path.cwd() == root
        observed.append(root.name)

    monkeypatch.setattr(module, "_local", check)
    monkeypatch.setattr(module, "_g14", check)
    monkeypatch.setattr(module, "_embedded", lambda root: observed.append(root.name))
    test_G17_TERMINAL_LEGACY_installed_profiles_and_embedded_startup(
        tmp_path, lambda *args: None, monkeypatch,
    )
    assert observed == ["local", "g14", "embedded"]
    assert os.environ["PYTHONPATH"] == "ambient-sentinel"
