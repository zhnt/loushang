from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from loushang.tui.cell_width import strip_control_sequences
from tests.tui.terminal_process_support import (
    selected_backend_name,
    spawn_terminal_process,
    terminal_test_environment,
)

from .test_hosted_subprocess import _environment
from .test_mux_command import _selector, _serve


def _installed() -> str:
    path = Path(sys.executable).parent / (
        "loushang-mux.exe" if os.name == "nt" else "loushang-mux"
    )
    assert path.is_file()
    return str(path)


def _terminal_environment(root):
    environment = terminal_test_environment(
        Path(__file__).resolve().parents[2], base=_environment(root)
    )
    # Installed commands must resolve their installed package, including when
    # these exact cases run against an isolated wheel instead of editable src.
    return {
        key: value
        for key, value in environment.items()
        if key.casefold() not in {"pythonpath", "pythonhome"}
    }


def test_G16_TERMINAL_NATIVE_installed_attach_creates_scoped_member_and_detaches(
    tmp_path, record_testsuite_property
):
    root = tmp_path.resolve()
    executable = _installed()
    record_testsuite_property("terminal_backend", selected_backend_name())
    environment = _terminal_environment(root)
    server = subprocess.Popen(
        [executable, *_serve(root)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    driver = None
    try:
        # Bound cold startup even when no ready line is produced.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as reader:
            line = reader.submit(server.stdout.readline)
            try:
                ready = json.loads(line.result(timeout=35))
            except BaseException:
                server.kill()
                server.wait(timeout=10)
                raise
        assert ready["status"] == "ready"
        created = subprocess.run(
            [executable, *_selector(root), "create", "dev"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert created.returncode == 0, created.stderr
        driver = spawn_terminal_process(
            [executable, *_selector(root), "attach", "dev"],
            cwd=root,
            env=environment,
            columns=80,
            rows=24,
        )
        driver.read_until(lambda out: "dev" in strip_control_sequences(out), timeout=30)
        driver.write("/new user_home Review\r")
        driver.read_until(lambda out: "*1" in strip_control_sequences(out), timeout=30)
        driver.write("a local unsent draft")
        driver.read_until(
            lambda out: "unsent draft" in strip_control_sequences(out), timeout=10
        )
        driver.write("\x02d")
        assert driver.wait(timeout=15) == 0, driver.diagnostics
        assert server.poll() is None, "detach must not terminate the application"
        listing = subprocess.run(
            [executable, *_selector(root), "list"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert listing.returncode == 0, listing.stderr
        assert json.loads(listing.stdout)["muxes"][0]["members"] == 1
        stop = subprocess.run(
            [executable, *_selector(root), "stop"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert (
            stop.returncode == 0
            and json.loads(stop.stdout)["status"] == "stop_requested"
        )
        assert server.wait(timeout=20) == 0, server.stderr.read()
    finally:
        if driver is not None:
            driver.close(timeout=10)
        if server.poll() is None:
            server.kill()
            server.wait(timeout=10)
        server.stdout.close()
        server.stderr.close()
