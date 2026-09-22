from __future__ import annotations

import subprocess
import sys
import time

import pytest

from loushang.hosting.service import LinuxServiceObserverV1

from ._lmux_adopted_process import AdoptedLeader, stop_command

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux pidfd wait",
)


def cleanup(owner, leader, other):
    failures = []

    def attempt(operation):
        try:
            operation()
        except BaseException as error:
            failures.append(error)

    if owner is not None:
        attempt(owner.close)
    for process in (leader, other):
        def stop(process=process):
            if process.poll() is None:
                process.kill()
        attempt(stop)
        attempt(lambda process=process: process.wait(timeout=10))
    if leader.stdin is not None and not leader.stdin.closed:
        attempt(leader.stdin.close)
    if failures:
        primary = sys.exception()
        if primary is None:
            raise failures[0]
        primary.add_note("test resource cleanup also failed: " + type(failures[0]).__name__)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_exact_leader_wait_does_not_consume_other_popen_status(exit_code):
    leader = subprocess.Popen(
        [sys.executable, "-I", "-c", f"import sys; sys.stdin.buffer.read(1); sys.exit({exit_code})"],
        stdin=subprocess.PIPE, start_new_session=True,
    )
    other = subprocess.Popen([sys.executable, "-I", "-c", "raise SystemExit(23)"])
    owner = None
    try:
        captured = LinuxServiceObserverV1.capture(leader.pid)
        try:
            owner = AdoptedLeader(captured.identity)
        finally:
            captured.close()
        assert not owner.poll()
        leader.stdin.write(b"x")
        leader.stdin.close()
        if exit_code == 0:
            # Like the real stopper, this process cannot finish while an
            # unreaped leader still keeps its original process group present.
            command = (
                "import os,time\nwhile True:\n"
                f" try: os.killpg({leader.pid}, 0)\n"
                " except ProcessLookupError: break\n time.sleep(0.01)\n"
            )
            result = stop_command([sys.executable, "-I", "-c", command],
                                  cwd=None, env=None, leader=owner, timeout=10)
            assert result.returncode == 0
            leader.returncode = 0
        deadline = time.monotonic() + 10
        while True:
            try:
                complete = owner.poll()
            except AssertionError:
                assert exit_code == 7
                leader.returncode = exit_code  # Exact wait above consumed our child's status.
                with pytest.raises(AssertionError):
                    owner.poll()  # A failed wait cannot become success on retry.
                break
            if complete:
                assert exit_code == 0
                leader.returncode = exit_code
                assert owner.poll()
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert other.wait(timeout=10) == 23
    finally:
        cleanup(owner, leader, other)


def test_close_failure_is_sticky_and_does_not_replay_native_close():
    calls = []

    class Observer:
        def close(self):
            calls.append("native close")
            raise OSError("lost close receipt")

    owner = object.__new__(AdoptedLeader)
    owner._observer = Observer()
    owner._closed = owner._close_unknown = False
    with pytest.raises(OSError):
        owner.close()
    with pytest.raises(RuntimeError, match="unknown"):
        owner.close()
    with pytest.raises(RuntimeError, match="unknown"):
        owner.poll()
    assert calls == ["native close"]


def test_cleanup_attempts_children_even_when_owner_close_fails():
    from types import SimpleNamespace

    events = []
    failure = OSError("close")

    def close():
        raise failure

    def process(name):
        return SimpleNamespace(
            poll=lambda: None, kill=lambda: events.append((name, "kill")),
            wait=lambda **_: events.append((name, "wait")), stdin=None,
        )

    with pytest.raises(OSError) as caught:
        cleanup(SimpleNamespace(close=close), process("leader"), process("other"))
    assert caught.value is failure
    assert events == [("leader", "kill"), ("leader", "wait"), ("other", "kill"), ("other", "wait")]


def test_stop_cleanup_failure_is_not_hidden_by_callers_exception(monkeypatch):
    from types import SimpleNamespace

    from . import _lmux_adopted_process as module

    failure = OSError("pipe close failed")

    def close():
        raise failure

    process = SimpleNamespace(
        returncode=0, communicate=lambda **_: ("", ""), poll=lambda: 0,
        stdout=SimpleNamespace(close=close), stderr=None,
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: process)
    try:
        raise LookupError("caller exception, unrelated to stop")
    except LookupError:
        with pytest.raises(OSError) as caught:
            stop_command(["fixed-test-stop"], cwd=None, env=None,
                         leader=SimpleNamespace(poll=lambda: True))
    assert caught.value is failure
