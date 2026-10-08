"""Controlled real-process/fork writer fixture; never a production entry."""

import json
import os
import signal
import sys
import threading
from pathlib import Path

from loushang.harness.journal import _directory_lease as module
from loushang.harness.transcript.writer_lease import (
    TranscriptWriterError,
    TranscriptWriterLease,
)


def output(stage, **facts):
    print(json.dumps({"stage": stage, **facts}), flush=True)


def main():
    mode = sys.argv[2]
    if mode == "create_pause":
        create_pause(Path(sys.argv[1]))
        return
    owner = TranscriptWriterLease(Path(sys.argv[1]), "coding", "one")
    owner.acquire()
    if mode == "unstable_fork":
        unstable_fork(owner)
        output("verified")
        return
    if mode == "orphan":
        pid = os.fork()
        if pid:
            output("orphan", pid=pid)
            os._exit(0)  # Test abrupt parent exit, without closing child copies.
        signal.alarm(20)  # Failure-only watchdog for an otherwise orphan fixture.
    elif mode == "fork_close":
        entered, release = threading.Event(), threading.Event()

        def hold():
            with owner._mutex:
                entered.set()
                release.wait(15)

        thread = threading.Thread(target=hold)
        thread.start()
        assert entered.wait(5)
        pid = os.fork()
        if pid == 0:
            signal.alarm(8)
            try:
                try:
                    owner.check(product_id="coding", conversation_id="one")
                except TranscriptWriterError as error:
                    assert error.code == "unsupported"
                else:
                    raise AssertionError("fork child gained writer authority")
                owner.close_inherited()  # Must not enter the inherited held mutex.
                assert not owner.cleanup_pending
            except BaseException:
                os._exit(2)
            os._exit(0)
        waited, status = os.waitpid(pid, 0)
        release.set()
        thread.join(2)
        assert waited == pid and status == 0 and not thread.is_alive()
        owner.check(product_id="coding", conversation_id="one")
        output("held")
    else:
        output("held")
    try:
        for command in sys.stdin:
            command = command.strip()
            if command == "release":
                if mode == "orphan":
                    try:
                        owner.check(product_id="coding", conversation_id="one")
                    except TranscriptWriterError as error:
                        assert error.code == "unsupported"
                    else:
                        raise AssertionError("fork child gained writer authority")
                    owner.close_inherited()
                else:
                    owner.close()
                output("released")
            elif command == "crash":
                os._exit(3)  # No finally or owner.close: sole-holder crash evidence.
            elif command == "quit":
                break
            else:
                raise AssertionError("unknown test command")
    finally:
        if mode == "orphan":
            owner.close_inherited()
        else:
            owner.close()


def create_pause(root):
    """Pause after real mkdir, before binding/sync, to expose the EEXIST race."""
    signal.alarm(15)
    owner = TranscriptWriterLease(root, "coding", "one", create_root=True)
    mkdir = os.mkdir

    def paused(path, *args, **kwargs):
        result = mkdir(path, *args, **kwargs)
        if path == root.name:
            output("created")
            assert sys.stdin.readline().strip() == "continue"
        return result

    module.os.mkdir = paused
    try:
        try:
            owner.acquire()
        except TranscriptWriterError as error:
            assert error.code == "busy"
            assert not owner._held and owner.claimed_owner is None
            output("busy")
        else:
            raise AssertionError("both creators admitted the same writer")
    finally:
        module.os.mkdir = mkdir
        owner.close()
    assert not owner.cleanup_pending


def unstable_fork(owner):
    original = os.close
    descriptor = owner._fds["lock"]
    entered, release = threading.Event(), threading.Event()
    replacements, failures = [], []

    def close(fd):
        original(fd)
        if fd == descriptor:
            replacement = os.open("/dev/null", os.O_RDONLY)
            assert replacement == descriptor
            replacements.append(replacement)
            entered.set()
            assert release.wait(12)

    def dispose():
        try:
            owner.close()
        except BaseException as error:
            failures.append(error)

    module.os.close = close
    thread = threading.Thread(target=dispose)
    thread.start()
    try:
        assert entered.wait(5)
        pid = os.fork()
        if pid == 0:
            signal.alarm(8)
            try:
                try:
                    owner.close_inherited()
                except TranscriptWriterError as error:
                    assert error.code == "unavailable"
                else:
                    raise AssertionError("unstable fork snapshot was closed")
                assert owner.cleanup_pending
                os.fstat(descriptor)  # Unrelated inherited fd was not closed.
            except BaseException:
                os._exit(2)
            os._exit(0)
        waited, status = os.waitpid(pid, 0)
        assert waited == pid and status == 0
    finally:
        release.set()
        thread.join(3)
        module.os.close = original
        assert not thread.is_alive()
        for fd in replacements:
            original(fd)
    assert not failures and not owner.cleanup_pending


if __name__ == "__main__":
    main()
