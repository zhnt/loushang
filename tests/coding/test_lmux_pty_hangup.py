"""Real transport-loss stimulus, using the original POSIX driver owner."""
from __future__ import annotations

import errno
import os
import sys
import threading

import pytest

if sys.platform != "linux":
    pytest.skip("Linux PTY hangup", allow_module_level=True)

from tests.tui.terminal_process_support.posix_pty import PosixPtyDriver  # noqa: I001


EOF_READER = """
import errno, os
from pathlib import Path
print('READY', flush=True)
try:
    value = os.read(0, 1)
    assert value == b''
except OSError as error:
    assert error.errno == errno.EIO
Path('hung-up').touch()
"""


def spawn_reader(tmp_path):
    driver = PosixPtyDriver.spawn(
        [sys.executable, "-c", EOF_READER], cwd=tmp_path, env=dict(os.environ),
        columns=80, rows=24,
    )
    driver.read_until(lambda text: "READY" in text, timeout=10)
    assert driver.is_alive()
    return driver


def test_abrupt_context_records_transport_not_unobservable_termios(tmp_path):
    from tests.coding._g18_native_probe import abrupt_terminal

    report = {}
    with abrupt_terminal(
        [sys.executable, "-c", EOF_READER], tmp_path, dict(os.environ),
        failure_report=report,
    ) as (driver, master, original):
        driver.read_until(lambda text: "READY" in text, timeout=10)
        assert master == driver._master_fd and original
        assert driver.hangup_transport(timeout=10) == 0
    assert report["terminal_transport"] == {
        "stimulus": "pty-master-close", "client_settled": True,
        "client_exit_status": 0, "client_exit_clean": True,
        "terminal_mode_restoration": "not-observable-after-hangup",
    }
    assert driver._closed and not driver.diagnostics.reader_alive
    assert driver.diagnostics.termination is None


def test_already_exited_client_is_not_a_successful_transport_hangup(tmp_path):
    driver = PosixPtyDriver.spawn(
        [sys.executable, "-c", "pass"], cwd=tmp_path, env=dict(os.environ),
        columns=80, rows=24,
    )
    try:
        assert driver.wait(timeout=10) == 0
        with pytest.raises(RuntimeError, match="exited before transport hangup"):
            driver.hangup_transport(timeout=10)
        assert driver._transport_state == "open"
        os.fstat(driver._master_fd)
    finally:
        driver.close()


def test_hangup_is_real_eof_and_close_does_not_close_reused_fd(tmp_path):
    driver = spawn_reader(tmp_path)
    replacement = None
    try:
        old_fd = driver._master_fd
        assert driver.hangup_transport(timeout=10) == 0
        assert (tmp_path / "hung-up").is_file()
        assert not driver.diagnostics.reader_alive
        assert driver.diagnostics.termination is None
        replacement = os.open(os.devnull, os.O_RDONLY)
        if replacement != old_fd:
            os.dup2(replacement, old_fd)
            os.close(replacement)
            replacement = old_fd
        assert driver.hangup_transport(timeout=2) == 0
        with pytest.raises(RuntimeError, match="fenced"):
            driver.write("x")
        with pytest.raises(RuntimeError, match="fenced"):
            driver.resize(columns=90, rows=30)
        driver.close()
        os.fstat(replacement)
    finally:
        driver.close()
        if replacement is not None:
            os.close(replacement)


def test_lost_hangup_close_receipt_never_recloses_reused_fd(tmp_path, monkeypatch):
    driver = spawn_reader(tmp_path)
    original = os.close
    target = driver._master_fd
    replacement = None
    closes = 0

    def lose_receipt(fd):
        nonlocal replacement, closes
        if fd != target:
            return original(fd)
        closes += 1
        original(fd)
        replacement = os.open(os.devnull, os.O_RDONLY)
        if replacement != target:
            os.dup2(replacement, target)
            original(replacement)
            replacement = target
        raise OSError(errno.EIO, "lost close receipt")

    try:
        monkeypatch.setattr(os, "close", lose_receipt)
        with pytest.raises(OSError, match="lost close receipt"):
            driver.hangup_transport(timeout=10)
        assert driver.wait(timeout=10) == 0
        for operation in (driver.close, lambda: driver.hangup_transport(timeout=1), driver.close):
            with pytest.raises(RuntimeError, match="outcome unknown"):
                operation()
        assert closes == 1
        os.fstat(replacement)
        assert driver.diagnostics.termination is None
    finally:
        monkeypatch.setattr(os, "close", original)
        # Test-only resolution: this injector knows the original close succeeded.
        driver._transport_state = "closed"
        driver.close()
        if replacement is not None:
            original(replacement)


@pytest.mark.parametrize("timeout_first", [False, True, "close-retry"])
def test_inflight_reader_query_settles_without_writer_lock_deadlock(tmp_path, monkeypatch, timeout_first):
    entered, release = threading.Event(), threading.Event()
    driver = PosixPtyDriver.spawn(
        [sys.executable, "-c", "import os; print('READY', flush=True); os.read(0, 1); print('QUERY', flush=True); os.read(0, 1)"],
        cwd=tmp_path, env=dict(os.environ), columns=80, rows=24,
    )
    original_record = driver._record_output
    errors = []
    waiter = None

    def record(text):
        if "QUERY" in text:
            entered.set()
            assert release.wait(10)
            driver.write("terminal query reply")  # Fenced reader replies are suppressed.
        original_record(text)

    def hangup():
        try:
            driver.hangup_transport(timeout=10)
        except BaseException as error:
            errors.append(error)

    try:
        driver.read_until(lambda text: "READY" in text, timeout=10)
        monkeypatch.setattr(driver, "_record_output", record)
        driver.write("\n")
        assert entered.wait(10)
        if timeout_first:
            with pytest.raises(TimeoutError, match="reader did not settle"):
                driver.hangup_transport(timeout=0.01)
            assert driver._transport_state == "fenced"
            os.fstat(driver._master_fd)  # Still owned; reader has not settled.
            assert driver.is_alive()
            if timeout_first == "close-retry":
                with pytest.raises(TimeoutError):
                    driver.close(timeout=0.01)
                assert not driver._closed
                os.fstat(driver._master_fd)
        waiter = threading.Thread(target=hangup)
        waiter.start()
        assert driver._stop_reader.wait(10)
        release.set()
        waiter.join(10)
        assert not waiter.is_alive()
        assert not errors
        assert driver._reader_error is None
        assert (driver.diagnostics.termination is not None) is (timeout_first == "close-retry")
    finally:
        release.set()
        if waiter is not None:
            waiter.join(10)
        driver.close()


@pytest.mark.parametrize("lock_name", ["_close_lock", "_writer_lock"])
def test_hangup_lock_deadline_has_no_transport_effect(tmp_path, lock_name):
    driver = spawn_reader(tmp_path)
    lock = getattr(driver, lock_name)
    try:
        lock.acquire()
        try:
            with pytest.raises(TimeoutError, match="deadline"):
                driver.hangup_transport(timeout=0.01)
        finally:
            lock.release()
        assert driver._transport_state == "open"
        assert driver.is_alive()
        os.fstat(driver._master_fd)
        assert driver.hangup_transport(timeout=10) == 0
    finally:
        driver.close()


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1])
def test_hangup_invalid_timeout_has_no_transport_effect(tmp_path, timeout):
    driver = spawn_reader(tmp_path)
    try:
        with pytest.raises(ValueError, match="finite"):
            driver.hangup_transport(timeout=timeout)
        assert driver._transport_state == "open"
        assert driver.hangup_transport(timeout=10) == 0
    finally:
        driver.close()
