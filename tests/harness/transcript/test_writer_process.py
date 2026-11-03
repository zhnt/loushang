from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from pathlib import Path
from time import monotonic

import pytest

from loushang.harness.transcript.writer_lease import TranscriptWriterLease
from loushang.hosting.service import LinuxServiceObserverV1

from .test_writer_lease import busy, lease

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux writer process ownership")


def test_real_process_concurrent_root_creation_has_one_writer(tmp_path):
    root = tmp_path / "new" / "sessions"
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("_writer_child.py")), str(root), "create_pause"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    try:
        assert select.select([child.stdout], [], [], 10)[0]
        assert json.loads(child.stdout.readline()) == {"stage": "created"}
        assert root.is_dir() and not (root / ".transcript-writers").exists()
        owner.acquire()  # Independent process encounters real EEXIST before A's fsync.
        child.stdin.write(b"continue\n")
        child.stdin.flush()
        output, errors = child.communicate(timeout=10)
        assert child.returncode == 0 and not errors
        assert json.loads(output) == {"stage": "busy"}
        assert set(owner._fds) == {"root", "directory", "lock"}
        owner.check(product_id="coding", conversation_id="one")
        busy(root)
    finally:
        owner.close()
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
    fresh = lease(root)
    try:
        fresh.acquire()
    finally:
        fresh.close()


@pytest.mark.parametrize("mode", ["normal", "fork_close", "orphan", "crash"])
def test_real_process_and_inherited_open_description_ownership(tmp_path, mode):
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("_writer_child.py")), str(tmp_path), mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    observer = None

    def receipt():
        data = bytearray()
        deadline = monotonic() + 10
        while not data.endswith(b"\n"):
            remaining = deadline - monotonic()
            assert remaining > 0 and select.select([child.stdout], [], [], remaining)[0]
            value = os.read(child.stdout.fileno(), 1)
            assert value, "writer fixture exited before receipt"
            data.extend(value)
            assert len(data) < 1024
        return json.loads(data)

    def send(command):
        child.stdin.write(command + b"\n")
        child.stdin.flush()

    try:
        ready = receipt()
        if mode == "orphan":
            assert ready["stage"] == "orphan"
            observer = LinuxServiceObserverV1.capture(ready["pid"])
            assert child.wait(timeout=5) == 0
            assert not observer.exited()  # Father exited, inherited writer still held.
        else:
            assert ready["stage"] == "held"
        busy(tmp_path)
        busy(tmp_path, product="work")
        stable = next((tmp_path / ".transcript-writers").glob("*.lock"))
        inode = stable.stat().st_ino
        if mode == "crash":
            send(b"crash")
            assert child.wait(timeout=8) == 3
        else:
            send(b"release")
            assert receipt()["stage"] == "released"
        fresh = lease(tmp_path)
        try:
            fresh.acquire()
            assert stable.stat().st_ino == inode
        finally:
            fresh.close()
        if mode == "crash":
            return
        send(b"quit")
        if observer is not None:
            assert observer.exited(timeout=8)
        else:
            assert child.wait(timeout=8) == 0
    finally:
        # EOF asks the exact fixture (including orphan) to close; no production
        # unlock/termination authority is introduced by test failure hygiene.
        child.stdin.close()
        child.stdin = None
        if child.poll() is None:
            child.kill()
        _, errors = child.communicate(timeout=25)  # Orphan watchdog is 20 seconds.
        if observer is not None:
            assert observer.exited(timeout=1)
            observer.close()
        assert not errors, errors.decode(errors="replace")


def test_fork_during_native_close_cannot_close_reused_inherited_fd(tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("_writer_child.py")), str(tmp_path), "unstable_fork"],
        capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads(result.stdout) == {"stage": "verified"}
