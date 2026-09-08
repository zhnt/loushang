"""Stdlib-only retained CLI parent; never reads input or restores terminal modes.

This witness is usable only inside an open native observation scope. Its caller
must retain that scope through physical descendant proof and witness release.
"""

from __future__ import annotations

import json
import os
import runpy
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


class ReceiptIOError(OSError):
    """Retryable fixture-file IO, never a native observation error."""


def _exists(root, name):
    try:
        return (root / name).exists()
    except OSError as error:
        raise ReceiptIOError("native witness command stat pending") from error


def publish(root, name, value):
    try:
        pending = root / (name + ".pending")
        with pending.open("w", encoding="utf-8") as target:
            json.dump(value, target)
            target.flush()
            os.fsync(target.fileno())
        pending.replace(root / name)
    except OSError as error:
        raise ReceiptIOError("native witness publication pending") from error


def _request(root, name, pid):
    path = root / name
    try:
        if not path.exists():
            return False
        with path.open(encoding="utf-8") as source:
            raw = source.read(129)
    except OSError as error:
        raise ReceiptIOError("native witness command read pending") from error
    # Exactly the canonical decimal PID, no coercion, extra fields or JSON.
    if raw != str(pid):
        raise RuntimeError("invalid native witness command identity")
    return True


class RetainedWitness:
    """One child and monotonic proof states, retained across receipt IO retry."""

    def __init__(self, root, arguments, *, api, spawn=subprocess.Popen):
        self.root, self.arguments = root, arguments
        self.api, self.spawn = api, spawn
        self.process = None
        self.phase = "new"
        self.baseline = self.sample = self.finished = None
        self.sample_published = False
        self.failed = False

    def step(self):
        if self.failed:
            raise RuntimeError("native witness retains unknown observation")
        if self.phase == "new":
            if _exists(self.root, "reap.request") or _exists(self.root, "release"):
                raise RuntimeError("native witness command before spawn")
            self.baseline = self.api.modes()
            self.phase = "spawning"
            # Never retry an ambiguous spawn. The outer receipt remains open.
            self.process = self.spawn(self.arguments)
        if self.phase == "spawning":
            if self.process is None:
                raise RuntimeError("native witness spawn outcome unknown")
            publish(self.root, "started", {
                "pid": self.process.pid, "witness": os.getpid(), "baseline": self.baseline,
            })
            self.phase = "running"
        if self.phase == "running":
            if _exists(self.root, "reap.request") or _exists(self.root, "release"):
                raise RuntimeError("native witness cannot release an unobserved child")
            if self.sample is None and _request(self.root, "sample.request", self.process.pid):
                self.sample = {"modes": self.api.modes()}
            if self.sample is not None and not self.sample_published:
                publish(self.root, "sample", self.sample)
                self.sample_published = True
            code = self.api.exited_unreaped(self.process.pid)
            if code is None:
                return False
            self.finished = {"code": code, "modes": self.api.modes()}
            self.phase = "exited"
        if self.phase == "exited":
            publish(self.root, "exited-retained", self.finished)
            self.phase = "awaiting-reap"
        if self.phase == "awaiting-reap":
            if _exists(self.root, "release"):
                raise RuntimeError("native witness release precedes reap proof")
            if not _request(self.root, "reap.request", self.process.pid):
                return False
            # WNOWAIT already established a waitable direct child. This is the
            # only reap operation; Popen preserves the result across IO retries.
            code = self.process.wait(timeout=0)
            if code != self.finished["code"]:
                raise RuntimeError("native witness exit code changed during reap")
            self.phase = "reaped"
        if self.phase == "reaped":
            publish(self.root, "reaped", {"pid": self.process.pid, "code": self.finished["code"]})
            self.phase = "awaiting-release"
        return _request(self.root, "release", self.process.pid)


def witness(root, arguments, *, api, spawn=subprocess.Popen):
    # A caught handler, not SIG_IGN: exec restores the actual CLI's SIGINT
    # disposition. The witness and CLI share the PTY; only the CLI reads it.
    signal.signal(signal.SIGINT, lambda *_: None)
    retained = RetainedWitness(root, arguments, api=api, spawn=spawn)
    while True:
        try:
            if retained.step():
                return 0
        except ReceiptIOError:
            # Publication/read failures retain the same object and child.
            pass
        except BaseException as error:
            retained.failed = True
            with suppress(OSError):
                publish(root, "failed", {"type": type(error).__name__})
        time.sleep(0.01)


def _product_environment(environ):
    repository = Path(__file__).resolve().parents[2]
    ledger = runpy.run_path(str(repository / "scripts/dev/_evidence_observation.py"))
    key = ledger["ENVIRONMENT_KEY"]
    scope = Path(environ.get(key, ""))
    if not scope.is_absolute() or scope.suffix != ".json":
        raise RuntimeError("native witness requires an open supervisor observation")
    with ledger["_locked"](scope.parent):
        entries = ledger["_registry"](scope.parent)
        current = scope.stem
        while current is not None:
            receipt = ledger["_read"](scope.parent / f"{current}.json")
            if (receipt["token"] != current or entries[current]["sealed"]
                    or receipt["phase"] not in {"unused", "open", "admitted"}
                    or (current == scope.stem and receipt["phase"] != "open")):
                raise RuntimeError("native witness observation is unavailable")
            current = entries[current]["parent"]
    return {name: value for name, value in environ.items() if name.casefold() != key.casefold()}


def main():
    import termios

    environment = _product_environment(os.environ)
    definitions = runpy.run_path(str(Path(__file__).with_name("_hosted_darwin_api.py")))

    class TerminalObservationApi(definitions["DarwinObservationApi"]):
        def modes(self):
            attributes = termios.tcgetattr(0)
            attributes[6] = [value[0] if isinstance(value, bytes) else value for value in attributes[6]]
            return attributes

    return witness(
        Path(sys.argv[1]), sys.argv[2:], api=TerminalObservationApi(),
        spawn=lambda args: subprocess.Popen(args, env=environment),
    )


if __name__ == "__main__":
    raise SystemExit(main())
