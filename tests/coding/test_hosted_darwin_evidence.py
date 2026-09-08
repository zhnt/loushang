"""Native Darwin entry supplement; full installed families remain separate."""

from __future__ import annotations

import os
import runpy
import shlex
import sys
from pathlib import Path

import pytest


def run_observation(tmp_path, case):
    repository = Path(__file__).resolve().parents[2]
    root = tmp_path / "observation"
    root.mkdir()
    probe = tmp_path / "test_darwin_probe.py"
    probe.write_text(
        "from pathlib import Path\n"
        "from tests.coding._hosted_darwin_observer import scenario\n"
        f"def test_native():\n    scenario(Path({str(root)!r}), {case!r})\n"
    )
    supervisor = runpy.run_path(str(repository / "scripts/dev/_evidence_process.py"))
    supervisor["run_pytest"](
        [sys.executable, "-I", "-m", "pytest", "-c", str(repository / "pyproject.toml"),
         "--rootdir", str(tmp_path), "--confcutdir", str(tmp_path),
         "-o", f"pythonpath={shlex.quote(repository.as_posix())}",
         "--import-mode=importlib", str(probe), "-q", "-m", "not live"],
        cwd=tmp_path, environment={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        timeout=180, observation=True,
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="native Darwin retained CLI evidence")
@pytest.mark.parametrize("case", [
    pytest.param("real", id="G17-DARWIN-ENTRY"),
    pytest.param("start-cancel", id="G17-DARWIN-PUBLICATION-CANCEL"),
    pytest.param("forced-exit", id="G17-DARWIN-FORCED-EXIT"),
])
def test_G17_TERMINAL_DARWIN_modes_and_physical_exit(tmp_path, case, record_testsuite_property):
    record_testsuite_property("native_platform", sys.platform)
    record_testsuite_property("terminal_backend", "posix-pty")
    run_observation(tmp_path, case)
