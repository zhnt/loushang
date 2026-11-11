"""Original private-parent lifetime observations; no Product admission proof."""

from __future__ import annotations

import importlib
import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux retained-root Journal scope"
)

OWNERS = {
    "native_approval": "CodingWorkerNativeApprovalJournal",
    "opt_in": "CodingWorkerOptInJournal",
    "receipt": "CodingWorkerProductReceiptOwner",
    "start_gate_journal": "CodingWorkerStartGateJournal",
}
CASES = (
    "success",
    "open_failure",
    "fstat_failure",
    "unsafe_uid",
    "unsafe_mode",
    "wrong_identity",
    "constructor_failure",
    "bind_failure",
    "body_failure",
    "bind_exit_failure",
    "cleanup_failure",
    "body_and_cleanup_failure",
    "post_changed",
    "post_failure",
    "close_failure",
    "body_and_close_failure",
)
FIXTURE = Path(__file__).with_name("fixtures") / "private_journal_binding_v1.json"


def observe(stem, case, read_only, v2, monkeypatch):
    module = importlib.import_module("loushang.coding.package_product_worker_" + stem)
    native = importlib.import_module("loushang.harness.journal._rooted_io")
    trace = []

    def metadata(*, visible=False):
        return SimpleNamespace(
            st_dev=1,
            st_ino=2 + int(visible and case in {"wrong_identity", "post_changed"}),
            st_mode=stat.S_IFDIR | (0o770 if case == "unsafe_mode" else 0o700),
            st_uid=10 if case == "unsafe_uid" else 9,
        )

    observations = 0

    class ProbePath(PurePosixPath):
        def lstat(self):
            nonlocal observations
            observations += 1
            trace.append("parent-lstat")
            if observations > 1 and case == "post_failure":
                raise OSError("post failure")
            return metadata(visible=case == "wrong_identity" or observations > 1)

    def open_parent(path, flags):
        trace.append(["parent-open", str(path), flags])
        if case == "open_failure":
            raise OSError("open failure")
        return 71

    def fstat(descriptor):
        assert descriptor == 71
        trace.append("parent-fstat")
        if case == "fstat_failure":
            raise OSError("fstat failure")
        return metadata()

    def close(descriptor):
        assert descriptor == 71
        trace.append("parent-close")
        if case in {"close_failure", "body_and_close_failure"}:
            raise OSError("close failure")

    class Rooted:
        def sibling(self, name):
            trace.append(["sibling", name])
            return self

        def stat(self):
            trace.append("file-stat")
            return SimpleNamespace()

        def acquire_lock(self, **fields):
            trace.append(["lock", fields])
            return False

    class IO:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.cleanup()

        def __init__(self, path, descriptor):
            trace.append(["io", str(path), descriptor])
            if case == "constructor_failure":
                raise OSError("constructor failure")

        @contextmanager
        def bind(self, path, *, durable):
            trace.append(["bind", str(path), durable])
            if case == "bind_failure":
                raise OSError("bind failure")
            try:
                yield Rooted()
            finally:
                trace.append("bind-exit")
                if case == "bind_exit_failure":
                    raise OSError("bind exit failure")

        def cleanup(self):
            trace.append("io-cleanup")
            if case in {"cleanup_failure", "body_and_cleanup_failure"}:
                raise OSError("cleanup failure")

    fake_os = SimpleNamespace(
        O_RDONLY=os.O_RDONLY,
        O_DIRECTORY=os.O_DIRECTORY,
        O_NOFOLLOW=os.O_NOFOLLOW,
        O_CLOEXEC=os.O_CLOEXEC,
        open=open_parent,
        fstat=fstat,
        close=close,
        geteuid=lambda: 9,
    )
    monkeypatch.setattr(native, "os", fake_os)
    monkeypatch.setattr(native, "RootedFileIO", IO)
    if hasattr(module, "os"):
        monkeypatch.setattr(module, "os", fake_os)
    if hasattr(module, "RootedFileIO"):
        monkeypatch.setattr(module, "RootedFileIO", IO)
    # Inherit the real journal's pure bindings without invoking Product IO.
    # Earlier extractions also moved the three other scopes to instance ports.
    owner_type = getattr(module, OWNERS[stem])
    owner = owner_type.__new__(owner_type)
    owner._path = ProbePath("/state/history.jsonl")
    if stem != "native_approval":
        owner._v2_owner_exists = lambda rooted: v2
        owner._error_type = getattr(
            module,
            {
                "opt_in": "CodingWorkerOptInJournalError",
                "receipt": "CodingWorkerReceiptError",
                "start_gate_journal": "CodingWorkerStartGateJournalError",
            }[stem],
        )
    kwargs = (
        {}
        if stem == "receipt"
        else (
            {"read_only": read_only}
            if stem == "native_approval"
            else {"create_lock": not read_only}
        )
    )
    error = None
    try:
        with getattr(module, OWNERS[stem])._bound_journal(owner, **kwargs):
            trace.append("body")
            if case in {
                "body_failure",
                "body_and_cleanup_failure",
                "body_and_close_failure",
            }:
                raise ValueError("body failure")
    except BaseException as caught:

        def describe(exc, depth=0):
            if exc is None or depth == 4:
                return None
            return {
                "type": type(exc).__name__,
                "message": str(exc),
                "cause": describe(exc.__cause__, depth + 1),
                "context": describe(exc.__context__, depth + 1),
                "suppress_context": exc.__suppress_context__,
            }

        error = describe(caught)
    return {"trace": trace, "error": error}


def observations():
    result = {}
    for stem in OWNERS:
        for read_only, v2 in (
            (False, False),
            (True, False),
            (False, True),
            (True, True),
        ):
            for case in CASES:
                with pytest.MonkeyPatch.context() as patcher:
                    result[f"{stem}:{read_only}:{v2}:{case}"] = observe(
                        stem, case, read_only, v2, patcher
                    )
    return result


@pytest.mark.parametrize("stem", OWNERS)
def test_original_private_journal_parent_scope(stem):
    expected = json.loads(FIXTURE.read_text())
    for read_only, v2 in ((False, False), (True, False), (False, True), (True, True)):
        for case in CASES:
            key = f"{stem}:{read_only}:{v2}:{case}"
            with pytest.MonkeyPatch.context() as patcher:
                assert observe(stem, case, read_only, v2, patcher) == expected[key], key
