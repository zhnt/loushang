"""Windows-only native supplement; collection skips are not release evidence."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import pytest


def run_observation(tmp_path, case):
    repository = Path(__file__).resolve().parents[2]
    root = tmp_path / "observation"
    root.mkdir()
    probe = tmp_path / "test_windows_probe.py"
    probe.write_text(
        "from pathlib import Path\n"
        "from tests.coding._hosted_windows_observer import scenario\n"
        f"def test_native():\n    scenario(Path({str(root)!r}), {case!r})\n"
    )
    supervisor = runpy.run_path(str(repository / "scripts/dev/_evidence_process.py"))
    supervisor["run_pytest"](
        [sys.executable, "-I", "-m", "pytest", "-c", str(repository / "pyproject.toml"),
         "-o", f"pythonpath={repository}", "--import-mode=importlib", str(probe),
         "-q", "-m", "not live"],
        cwd=tmp_path, environment={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        timeout=180,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="native ConPTY evidence")
@pytest.mark.parametrize("case", [
    pytest.param("real", id="G17-WINDOWS-ENTRY"),
    pytest.param("start-cancel", id="G17-WINDOWS-PUBLICATION-CANCEL"),
    pytest.param("recovery-cancel", id="G17-WINDOWS-RECOVERY-CANCEL"),
    pytest.param("forced-exit", id="G17-WINDOWS-FORCED-EXIT"),
    pytest.param("heartbeat", id="G17-WINDOWS-SUSPEND-BARRIER"),
])
def test_G17_TERMINAL_WINDOWS_console_modes_and_physical_exit(
    tmp_path, case, record_testsuite_property,
):
    record_testsuite_property("native_platform", sys.platform)
    record_testsuite_property("terminal_backend", "conpty")
    run_observation(tmp_path, case)
