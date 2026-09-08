"""Supplemental Linux ENTRY proof; macOS/Windows guarded observation is pending."""

from __future__ import annotations

import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.tui.cell_width import strip_control_sequences

from ._hosted_terminal import foreground_terminal, process_table
from .test_hosted_client import _argv
from .test_hosted_client_terminal import _installed
from .test_mux_terminal_process import _terminal_environment


def _observe_entry(tmp_path):
    import pty
    import termios

    opened = []
    openpty = pty.openpty

    def observe():
        master, slave = openpty()
        # Observe the real driver's PTY before Product starts. No Product
        # terminal, process owner, or installed CLI implementation is replaced.
        opened.append((master, termios.tcgetattr(slave)))
        return master, slave

    with patch.object(pty, "openpty", observe), foreground_terminal(
        [_installed(), *_argv(tmp_path)], cwd=tmp_path,
        env=_terminal_environment(tmp_path), columns=100, rows=30,
    ) as driver:
        driver.read_until(
            lambda out: "/exit ends app" in strip_control_sequences(out), timeout=35
        )
        (master, baseline), = opened
        active = termios.tcgetattr(master)
        assert active != baseline, "ready must actually enter native terminal mode"
        assert not active[3] & (termios.ECHO | termios.ICANON)
        parent = driver.diagnostics.pid
        children = [pid for pid, entry in process_table().items() if entry[0] == parent]
        assert children, "installed foreground command must own a real Hosted process"
        assert all(os.getpgid(pid) != os.getpgid(parent) for pid in children)
        driver.write("/exit\r")
        assert driver.wait(timeout=25) == 0, driver.diagnostics
        assert termios.tcgetattr(master) == baseline
        table = process_table()
        assert all(pid not in table for pid in children), "a zombie is not a reaped child"
        assert driver.diagnostics.termination is None, "fixture fallback is not normal exit"


def _guarded(operation):
    import ctypes

    # This runs in a private, retained pytest wrapper, never the calling suite.
    # Adopt an orphan even if a broken CLI exits before our first tree scan.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "entry fixture subreaper admission failed")
    leftovers = False
    try:
        operation()
    finally:
        deadline = time.monotonic() + 5
        while True:
            try:
                child, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            leftovers = True
            if child:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("entry fixture reclamation pending")
            children = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children")
            for pid in map(int, children.read_text().split()):
                os.kill(pid, signal.SIGKILL)
            time.sleep(0.01)
    if leftovers:
        # Physical fallback must never manufacture successful user evidence.
        # This executes only if operation itself returned without an exception.
        raise AssertionError("native observer left descendants for fixture cleanup")


def _scenario(root, case):
    if case == "real":
        _guarded(lambda: _observe_entry(root))
    else:
        def broken_controller():
            script = (
                "import subprocess,sys; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(60)'],"
                "start_new_session=True); Path('orphan.pid').write_text(str(child.pid))"
            )
            controller = subprocess.Popen([sys.executable, "-I", "-c", script], cwd=root)
            assert controller.wait(timeout=5) == 0
            pid = int((root / "orphan.pid").read_text())
            os.kill(pid, 0)
            if case == "controller-leak":
                raise AssertionError("controller exited but Hosted child remains")

        expected = "Hosted child remains" if case == "controller-leak" else "observer left descendants"
        with pytest.raises(AssertionError, match=expected):
            _guarded(broken_controller)
        with pytest.raises(ProcessLookupError):
            os.kill(int((root / "orphan.pid").read_text()), 0)
    (root / "observer.settled").touch()


@pytest.mark.skipif(sys.platform != "linux", reason="supplemental Linux independent reaper evidence")
@pytest.mark.parametrize("case", ["real", "controller-leak", "silent-leak"])
def test_G17_TERMINAL_ENTRY_native_observation_retains_failure_reaper(tmp_path, case):
    repository = Path(__file__).resolve().parents[2]
    root = tmp_path / "observation"
    root.mkdir()
    probe = tmp_path / "test_entry_probe.py"
    probe.write_text(
        "from pathlib import Path\n"
        "from tests.coding.test_hosted_entry_evidence import _scenario\n"
        f"def test_entry():\n    _scenario(Path({str(root)!r}), {case!r})\n"
    )
    supervisor = runpy.run_path(str(repository / "scripts/dev/_evidence_process.py"))
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    supervisor["run_pytest"](
        [sys.executable, "-I", "-m", "pytest", "-c", str(repository / "pyproject.toml"),
         "-o", f"pythonpath={repository}", "--import-mode=importlib", str(probe),
         "-q", "-m", "not live"],
        cwd=tmp_path, environment=environment, timeout=90,
    )
    assert (root / "observer.settled").exists()
