"""Native terminal against real Coding/G13 ownership, without live model IO."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import subprocess
import sys
import threading
from collections import deque
from contextlib import contextmanager
from pathlib import Path

import pytest

from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.tui.cell_width import strip_control_sequences
from tests.tui.terminal_process_support import (
    selected_backend_name,
    spawn_terminal_process,
)

from .test_mux_command import _selector, _serve
from .test_mux_terminal_process import _installed, _terminal_environment


@contextmanager
def _product(root, *, installed=False, discovery=False):
    environment = _terminal_environment(root)
    process = subprocess.Popen(
        [
            *([_installed()] if installed else [
                sys.executable, str(Path(__file__).with_name("_local_product_child.py"))
            ]),
            *_serve(root),
            *(["--session-discovery"] if discovery else []),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    errors = deque(maxlen=32)

    def drain():
        while chunk := process.stderr.read(1024):
            errors.append(chunk)

    drainer = threading.Thread(target=drain, name="g16-test-stderr")
    drainer.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as reader:
            line = reader.submit(process.stdout.readline)
            try:
                ready = json.loads(line.result(timeout=35))
            except BaseException:
                process.kill()
                process.wait(timeout=10)
                raise
        assert ready["status"] == "ready"
        yield process, environment
    except BaseException as error:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        drainer.join(timeout=10)
        error.add_note("G16 Product stderr: " + "".join(errors)[-16384:])
        raise
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        drainer.join(timeout=10)
        assert not drainer.is_alive(), "test-owned stderr drainer did not settle"
        process.stdout.close()
        process.stderr.close()


def _command(root, environment, *args):
    result = subprocess.run(
        [_installed(), *_selector(root), *args],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@contextmanager
def _terminal(root, environment, name):
    driver = spawn_terminal_process(
        [_installed(), *_selector(root), "attach", name],
        cwd=root,
        env=environment,
        columns=100,
        rows=30,
    )
    try:
        _see(driver, name + " |")
        yield driver
    finally:
        driver.close(timeout=10)


def _see(driver, text, *, after=0):
    driver.read_until(
        lambda output: text in strip_control_sequences(output[after:]),
        timeout=30,
    )


def _completed_reply_seen(output):
    plain = strip_control_sequences(output)
    reply = plain.rfind("真实跨进程回复")
    # A text delta is not turn settlement. The member's idle projection must
    # follow the reply, not come from the initial, pre-submission screen.
    return reply >= 0 and plain.rfind("*1 |") > reply


def test_completed_reply_requires_idle_after_reply_not_initial_idle():
    initial = "dev | *1 | /help /detach\n"
    streaming = initial + "真实跨进程回复\nG14\ndev | *1~ | /help /detach"
    assert not _completed_reply_seen(initial)
    assert not _completed_reply_seen(streaming)
    assert _completed_reply_seen(streaming + "\ndev | \x1b[32m*1\x1b[0m | /help")


def test_G16_PRODUCT_TERMINAL_two_muxes_approval_detach_reattach_and_interrupt(
    tmp_path,
    record_testsuite_property,
    discovery=False,
):
    root = tmp_path.resolve()
    record_testsuite_property("terminal_backend", selected_backend_name())
    config = root / ".loushang"
    config.mkdir()
    (config / "settings.json").write_text(
        json.dumps({"tools": {"ask_tools": ["g14_preview"]}})
    )
    with _product(root, discovery=discovery) as (server, environment):
        _command(root, environment, "create", "dev")
        _command(root, environment, "create", "review")
        with _terminal(root, environment, "review") as reviewer:
            reviewer.write("/new user_home Review\r")
            _see(reviewer, "*1")
            with _terminal(root, environment, "dev") as developer:
                developer.write("/new cwd Development\r")
                _see(developer, "*1")
                developer.write("hello\r")
                _see(developer, "真实跨进程回复")
                reviewer.write("approval\r")
                _see(reviewer, "*1!")
                reviewer.write("/question\r")
                _see(reviewer, "Approval details")
                _see(reviewer, "{}")
                assert "APPROVED_PREVIEW_EXECUTED" not in reviewer.raw_output
                checkpoint = len(reviewer.raw_output)
                reviewer.write("\x1b")
                _see(reviewer, "Approval pending", after=checkpoint)
                reviewer.write("/approve\r")
                _see(reviewer, "APPROVED_PREVIEW_EXECUTED")
                developer.write("hold\r")
                _see(developer, "waiting")
                developer.write("\x02d")
                assert developer.wait(timeout=15) == 0, developer.diagnostics
            assert server.poll() is None and reviewer.is_alive()
            with _terminal(root, environment, "dev") as reattached:
                _see(reattached, "*1~")
                # v1 snapshots restore committed history + running state, not
                # replay of previously delivered transient assistant deltas.
                _see(reattached, "真实跨进程回复")
                checkpoint = len(reattached.raw_output)
                reattached.write("\x03")
                _see(reattached, "*1 |", after=checkpoint)
                reattached.write("\x02d")
                assert reattached.wait(timeout=15) == 0, reattached.diagnostics
            reviewer.write("\x02d")
            assert reviewer.wait(timeout=15) == 0, reviewer.diagnostics
        listed = _command(root, environment, "list")
        assert {item["name"] for item in listed["muxes"]} == {"dev", "review"}
        assert all(item["members"] == 1 for item in listed["muxes"])
        _command(root, environment, "stop")
        assert server.wait(timeout=20) == 0


def _identities(root):
    async def inspect():
        directory = LocalConnectionDirectoryV1(root / "connections")
        connection = LocalAppClientConnectionV1(
            directory, "workspace", expected_product_id="coding"
        )
        try:
            await connection.start()
            result = await connection.client.list_muxes()
            identities = tuple(
                (
                    mux.mux_space_id,
                    mux.name,
                    tuple((member.member_id, member.session) for member in mux.members),
                )
                for mux in result.mux_spaces
            )
            return directory.read("workspace").instance, identities
        finally:
            await connection.close()
            directory.close()

    return asyncio.run(asyncio.wait_for(inspect(), 10))


@pytest.mark.parametrize("scope", ["cwd", "user_home"])
def test_G16_PRODUCT_TERMINAL_process_death_recovers_history_not_execution(
    tmp_path,
    record_testsuite_property,
    scope,
):
    root = tmp_path.resolve()
    record_testsuite_property("terminal_backend", selected_backend_name())
    with _product(root) as (server, environment):
        _command(root, environment, "create", "dev")
        with _terminal(root, environment, "dev") as driver:
            driver.write(f"/new {scope} Durable\r")
            _see(driver, "*1")
            checkpoint = len(driver.raw_output)
            driver.write("persisted-before-process-death\r")
            driver.read_until(
                lambda output: _completed_reply_seen(output[checkpoint:]), timeout=30
            )
            driver.write("hold\r")
            _see(driver, "waiting")
            before_instance, before_identities = _identities(root)
            server.kill()  # Exact test-owned process: no graceful Product cleanup.
            assert server.wait(timeout=10) != 0
            assert driver.wait(timeout=15) != 0, driver.diagnostics
    with _product(root) as (replacement, environment):
        after_instance, after_identities = _identities(root)
        assert after_instance != before_instance
        assert after_identities == before_identities
        with _terminal(root, environment, "dev") as recovered:
            _see(recovered, "persisted-before-process-death")
            _see(recovered, "真实跨进程回复")
            _see(recovered, "*1 |")
            assert "*1~" not in strip_control_sequences(recovered.raw_output)
            checkpoint = len(recovered.raw_output)
            recovered.write("fresh-after-restart\r")
            _see(recovered, "真实跨进程回复", after=checkpoint)
            recovered.write("\x02d")
            assert recovered.wait(timeout=15) == 0, recovered.diagnostics
        _command(root, environment, "stop")
        assert replacement.wait(timeout=20) == 0
