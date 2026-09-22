"""Installed short-command acceptance using the existing native PTY driver."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.terminal import FakeScreen, TerminalSize
from tests.tui.terminal_process_support import spawn_terminal_process

from ._g18_native_probe import (
    _replay_embedded_output,
    managed_completion_frame,
    managed_read_observation,
)
from .test_mux_terminal_process import _terminal_environment

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed lmux")


@pytest.mark.parametrize("reconnect_exit", ["\x02d", "\x04"], ids=["detach", "empty-ctrl-d"])
def test_installed_lmux_one_command_two_tabs_detach_and_cross_cwd_reconnect(tmp_path, reconnect_exit):
    import pty
    import termios

    executable = Path(sys.executable).parent / "lmux"
    assert executable.is_file(), "installed lmux entry point is required"
    environment = _terminal_environment(tmp_path)
    environment.pop("LOUSHANG_TMPDIR", None)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    drivers = []
    modes = {}

    def command(*args, cwd=tmp_path):
        result = subprocess.run(
            [str(executable), *args], cwd=cwd, env=environment,
            capture_output=True, text=True, timeout=45,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        if args[:1] == ("stop",):
            # Batch stop emits one JSON record per target plus its summary.
            return [json.loads(line) for line in result.stdout.splitlines()]
        return json.loads(result.stdout)

    def terminal(*args, cwd=tmp_path):
        original_open = pty.openpty
        captured = []

        def observed_open():
            master, slave = original_open()
            captured.append((master, termios.tcgetattr(slave)))
            return master, slave

        with patch.object(pty, "openpty", observed_open):
            driver = spawn_terminal_process(
                [str(executable), *args], cwd=cwd, env=environment, columns=80, rows=24,
            )
        drivers.append(driver)
        (modes[id(driver)],) = captured
        return driver

    def exited(driver):
        assert driver.wait(timeout=20) == 0, driver.diagnostics
        master, original = modes[id(driver)]
        assert termios.tcgetattr(master) == original, "terminal modes not restored"
        output = driver.raw_output
        assert output.rfind("\x1b[?25h") > output.rfind("\x1b[?25l")
        assert output.rfind("\x1b[?2004l") > output.rfind("\x1b[?2004h")
        assert driver.diagnostics.termination is None

    def see(driver, text, *, after=0):
        driver.read_until(
            lambda output: text in strip_control_sequences(output[after:]), timeout=40,
        )

    def see_draft(driver, expected, forbidden, *, after=0, columns=80, rows=24):
        def matches(output):
            end = output.rfind("\x1b[?2026l")
            if end < after:
                return False
            screen = _replay_embedded_output(
                output[:end + len("\x1b[?2026l")],
                screen=FakeScreen.empty(TerminalSize(columns=columns, rows=rows)),
            )
            lines = tuple(line.strip() for line in screen.visible_lines)
            return f"> {expected}" in lines and not any(forbidden in line for line in lines)
        driver.read_until(matches, timeout=40)

    try:
        driver = terminal("new", "-s", "dev")
        see(driver, "dev |")
        offset = len(driver.raw_output)
        driver.write("/he")
        driver.read_until(
            lambda output: managed_completion_frame(output, after=offset, columns=80, rows=24),
            timeout=40,
        )
        # Use editor keys, not an injected provider call. Never submit /he.
        driver.write("\x7f\x7f\x7f")
        driver.write("/new user_home First\r")
        see(driver, "*1")
        first = managed_read_observation(environment, "first-member", name="dev")
        assert len(first["members"]) == 1
        driver.write("/new user_home Second\r")
        see(driver, "*1 2")
        second = managed_read_observation(environment, "second-member", name="dev")
        assert len(second["members"]) == 2 and second["members"][:1] == first["members"]
        assert all(second[key] == first[key] for key in ("instanceId", "serviceId", "muxId"))
        offset = len(driver.raw_output)
        driver.write("\x022")
        see(driver, "*2", after=offset)
        driver.write("second unsent draft")
        see(driver, "second unsent draft")
        offset = len(driver.raw_output)
        driver.write("\x021")
        see(driver, "*1", after=offset)
        driver.write("first unsent draft")
        see_draft(driver, "first unsent draft", "second unsent draft", after=offset)
        offset = len(driver.raw_output)
        driver.write("\x022")
        see_draft(driver, "second unsent draft", "first unsent draft", after=offset)
        offset = len(driver.raw_output)
        driver.resize(columns=100, rows=30)
        see_draft(driver, "second unsent draft", "first unsent draft",
                  after=offset, columns=100, rows=30)
        driver.write("\x02d")
        exited(driver)
        detached = managed_read_observation(environment, "detached", name="dev")
        assert all(detached[key] == second[key] for key in ("instanceId", "serviceId", "muxId", "members"))
        before = command("ls")
        assert [row["name"] for row in before["muxes"]] == ["dev"]
        service_id = before["muxes"][0]["serviceId"]
        instance = command("status", "--server", service_id)["instanceId"]
        assert instance is not None

        reconnect = terminal("attach", "-t", "dev", cwd=elsewhere)
        see(reconnect, "dev |")
        reattached = managed_read_observation(environment, "reattached", name="dev")
        assert all(reattached[key] == second[key] for key in ("instanceId", "serviceId", "muxId", "members"))
        # Both server-owned members survive; client-local drafts need not.
        offset = len(reconnect.raw_output)
        reconnect.write("\x022")
        see(reconnect, "*2", after=offset)
        offset = len(reconnect.raw_output)
        reconnect.write("\x021")
        see(reconnect, "*1", after=offset)
        reconnect.write(reconnect_exit)
        exited(reconnect)
        after = command("ls", cwd=elsewhere)
        assert after == before, "reattach must not change registered muxes"
        assert command("status", "--server", service_id, cwd=elsewhere)["instanceId"] == instance
        assert not list(elsewhere.iterdir())
    finally:
        # Only this test's private namespace is selected. A failed stop stays
        # visible; never infer cleanup from a vanished client or force-kill an
        # unverified background PID.
        try:
            for driver in drivers:
                driver.close(timeout=10)
        finally:
            command("stop", "--all", "--yes")
