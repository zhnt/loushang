"""Native public-API evidence only; not installed CLI or terminal acceptance."""

from __future__ import annotations

import os
import signal
import sys
import time

import pytest

from ._hosted_darwin_api import DarwinExitWatch, DarwinObservationApi
from ._hosted_primitive_child import _child
from ._hosted_terminal import process_table


def _until(predicate, *, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            return result
        assert time.monotonic() < deadline, "native primitive did not reach its barrier"
        time.sleep(0.01)


def _release(process):
    process.stdin.write(b"x")
    process.stdin.flush()


def _exit_observed(watch, api, pid, code):
    # NOTE_EXIT can precede the kernel's waitable-zombie transition. Both facts
    # must arrive within the caller's one observation deadline before reaping.
    return watch.exited() == {pid} and api.exited_unreaped(pid) == code


@pytest.mark.skipif(sys.platform != "darwin", reason="native Darwin public APIs")
@pytest.mark.parametrize("case", [
    "G17-DARWIN-WNOWAIT",
    "G17-DARWIN-EXIT-WATCH",
    "G17-DARWIN-STOP-BARRIER",
    "G17-DARWIN-FORK-REJECT",
    "G17-DARWIN-EXEC-REJECT",
])
def test_G17_DARWIN_public_observation_primitives(case, tmp_path, record_testsuite_property):
    record_testsuite_property("native_platform", sys.platform)
    record_testsuite_property("observation_backend", "waitid-kqueue")
    api = DarwinObservationApi()
    if case == "G17-DARWIN-WNOWAIT":
        with _child("import sys; sys.exit(7)") as process:
            _until(lambda: api.exited_unreaped(process.pid) == 7)
            assert api.exited_unreaped(process.pid) == 7
            assert process.returncode is None
            entry = process_table()[process.pid]
            assert entry[0] == os.getpid() and "Z" in entry[1]
            assert process.wait(timeout=5) == 7
            assert process.pid not in process_table()
            with pytest.raises(OSError):
                api.exited_unreaped(process.pid)
        return
    if case == "G17-DARWIN-STOP-BARRIER":
        _heartbeat(tmp_path, api)
        return
    tail = "sys.exit(7)"
    if case == "G17-DARWIN-FORK-REJECT":
        tail = (
            "child=os.fork()\n"
            "if child == 0: os._exit(0)\n"
            "while True:\n"
            "    try:\n"
            "        os.waitpid(child, 0)\n"
            "        break\n"
            "    except BaseException: time.sleep(.01)\n"
        )
    elif case == "G17-DARWIN-EXEC-REJECT":
        tail = "os.execv(sys.executable, [sys.executable, '-I', '-S', '-c', 'import sys; assert sys.flags.no_site'])"
    code = (
        "import os,sys,signal,time\nassert sys.flags.no_site\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "if sys.stdin.buffer.read(1) != b'x': sys.exit(0)\n" + tail
    )
    with _child(code, forking=case == "G17-DARWIN-FORK-REJECT") as process:
        watch = DarwinExitWatch([process.pid])
        try:
            _release(process)
            if case == "G17-DARWIN-EXIT-WATCH":
                _until(lambda: _exit_observed(watch, api, process.pid, 7))
                assert process.wait(timeout=5) == 7
            else:
                with pytest.raises(RuntimeError, match="topology became unknown"):
                    _until(lambda: watch.exited())
                with pytest.raises(RuntimeError, match="unavailable"):
                    watch.exited()
                # The negative fork child is explicitly reaped by its retained
                # parent. Unknown topology must not be cleared by observer retry.
                assert process.wait(timeout=5) == 0
            assert process.pid not in process_table()
        finally:
            watch.close()


def _heartbeat(root, api):
    counter, stop = root / "counter", root / "stop"
    code = (
        "import time\nfrom pathlib import Path\n"
        f"counter,stop=Path({str(counter)!r}),Path({str(stop)!r})\n"
        "index=0\n"
        "while not stop.exists():\n"
        "    index+=1\n"
        "    pending=counter.with_suffix('.pending')\n"
        "    pending.write_text(str(index))\n"
        "    pending.replace(counter)\n"
        "    time.sleep(.01)\n"
    )
    with _child(code) as process:
        watch = DarwinExitWatch([process.pid])
        try:
            _until(counter.exists)
            # Direct-child PID remains reserved: no poll/wait before signalling.
            os.kill(process.pid, signal.SIGSTOP)
            _until(lambda: "T" in process_table()[process.pid][1])
            frozen = counter.read_bytes()
            time.sleep(0.05)
            assert counter.read_bytes() == frozen
            assert api.exited_unreaped(process.pid) is None
            os.kill(process.pid, signal.SIGCONT)
            _until(lambda: counter.read_bytes() != frozen)
            stop.touch()
            _until(lambda: _exit_observed(watch, api, process.pid, 0))
            assert process.wait(timeout=5) == 0
            assert process.pid not in process_table()
        finally:
            watch.close()
