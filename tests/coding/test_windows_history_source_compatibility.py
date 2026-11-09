"""Real file bytes with synthetic Windows IO and explicit Product/GC substitutes."""

from __future__ import annotations

import importlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import package_product_worker_windows_history_sources as sources
from tests.coding.test_windows_recovery_value_compatibility import canonical, outcome

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux directory FDs with synthetic Windows IO"
)

_FIXTURE = Path(__file__).parent / "fixtures/windows_history_sources_io_v1.json"
CASES = (
    "normal",
    "empty",
    "zero-file",
    "short-read",
    "unknown-name",
    "prep-stage",
    "prep-allowed",
    "checkpoint-stage",
    "checkpoint-allowed",
    "base-stage",
    "base-allowed",
    "retirement-stage",
    "file-count",
    "file-cap",
    "total-cap",
    "lower-stream",
    "empty-stream",
    "named-stream",
    "acl-root-error",
    "acl-file-error",
    "root-before-changed",
    "root-after-changed",
    "source-meta-changed",
    "visible-changed",
    "source-truncated",
    "read-error",
    "close-error",
    "fdopen-error",
    "gc-error",
    "directory-changed",
    "missing-source",
)


def observe_sources(case, directory, patch):
    events = []
    # No expected stores machine paths/inodes or wall-clock values.
    directory.mkdir()
    bodies = {
        "worker-opt-in.jsonl": b"aaaa",
        "worker-supervisor.jsonl": b"bbbb",
        "notes": b"ignored",
    }
    if case == "empty":
        bodies = {"notes": b"ignored"}
    if case == "zero-file":
        bodies["worker-opt-in.jsonl"] = b""
    stage = {
        "prep-stage": "worker-history-preparation-v1.json.stage",
        "prep-allowed": "worker-history-preparation-v1.json.stage",
        "checkpoint-stage": "worker-history-checkpoint-v1.json.stage",
        "checkpoint-allowed": "worker-history-checkpoint-v1.json.stage",
        "base-stage": sorted(sources.WINDOWS_WORKER_BASE_STAGE_NAMES)[0],
        "base-allowed": sorted(sources.WINDOWS_WORKER_BASE_STAGE_NAMES)[0],
        "retirement-stage": "worker-stage-retired-" + "7" * 32 + ".json.stage",
    }
    if case in stage:
        bodies[stage[case]] = b"{}"
    if case == "unknown-name":
        bodies["worker-unknown.json"] = b"x"
    for name, body in bodies.items():
        (directory / name).write_bytes(body)
    fds = {}
    rootfds = set()
    reads_done = set()
    root_stats = 0
    fired = False
    original_fstat, original_fdopen = os.fstat, os.fdopen

    def name_of(fd):
        return "root" if fd in rootfds else fds.get(fd, "other")

    def fstat(fd):
        nonlocal root_stats, fired
        current = original_fstat(fd)
        name = name_of(fd)
        if name == "other":
            return current
        events.append(["fstat", name])
        doc = {
            k: getattr(current, k)
            for k in ["st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"]
        }
        if name == "root":
            root_stats += 1
            if (case == "root-before-changed" and root_stats == 1) or (
                case == "root-after-changed" and root_stats == 2
            ):
                doc["st_ino"] += 1
                fired = True
        elif case == "source-meta-changed" and fd in reads_done:
            doc["st_mtime_ns"] += 1
            fired = True
        return SimpleNamespace(**doc)

    class Product:
        policy = SimpleNamespace(project_scope_id="scope-a")

        @property
        def state_root(self):
            events.append(["state-root"])
            return directory

        def assert_root_gc_authority_current(self):
            events.append(["current"])

        @contextmanager
        def borrow(self):
            fd = os.open(directory, os.O_RDONLY)
            rootfds.add(fd)
            events.append(["borrow"])
            try:
                yield fd
            finally:
                os.close(fd)
                events.append(["release"])

        @property
        def epoch_runtime(self):
            return SimpleNamespace(borrow_product_state_root_descriptor=self.borrow)

    class Acl:
        def __enter__(self):
            events.append(["acl-enter"])
            return self

        def __exit__(self, *_):
            events.append(["acl-exit"])

        def validate(self, fd):
            nonlocal fired
            name = name_of(fd)
            events.append(["acl", name])
            if (case == "acl-root-error" and name == "root") or (
                case == "acl-file-error" and name != "root"
            ):
                fired = True
                raise OSError("ACL unavailable")

    def listing(fd):
        events.append(["list"])
        return tuple(sorted(os.listdir(fd)))

    def opener(parent, name, **kwargs):
        nonlocal fired
        events.append(["open", name, kwargs])
        if case == "missing-source":
            (directory / name).unlink()
            fired = True
        fd = os.open(name, os.O_RDONLY, dir_fd=parent)
        fds[fd] = name
        return fd

    def streams(fd):
        nonlocal fired
        events.append(["streams", name_of(fd)])
        if case in {"lower-stream", "empty-stream", "named-stream"}:
            fired = True
            return {
                "lower-stream": ("::$data",),
                "empty-stream": (),
                "named-stream": ("::$DATA", ":hidden:$DATA"),
            }[case]
        return ("::$DATA",)

    def visible(parent, name):
        nonlocal fired
        events.append(["visible", name])
        meta = os.stat(name, dir_fd=parent)
        if case == "visible-changed":
            fired = True
            return SimpleNamespace(
                st_dev=meta.st_dev,
                st_ino=meta.st_ino + 1,
                st_size=meta.st_size,
                st_mtime_ns=meta.st_mtime_ns,
                st_ctime_ns=meta.st_ctime_ns,
            )
        return meta

    def fdopen(fd, mode):
        nonlocal fired
        events.append(["fdopen", name_of(fd), mode])
        if case == "fdopen-error":
            fired = True
            raise OSError("fdopen failed before taking custody")
        stream = original_fdopen(fd, mode)

        class Reader:
            def __enter__(self):
                return self

            def fileno(self):
                return stream.fileno()

            def read(self, size):
                nonlocal fired
                events.append(["read", name_of(fd), size])
                if case == "read-error":
                    fired = True
                    raise OSError("source read failed")
                if case == "source-truncated":
                    fired = True
                    return b""
                chunk = stream.read(min(size, 2) if case == "short-read" else size)
                if not chunk:
                    reads_done.add(fd)
                return chunk

            def __exit__(self, *_):
                nonlocal fired
                stream.close()
                events.append(["close", name_of(fd)])
                if case == "close-error":
                    fired = True
                    raise OSError("source close failed")

        return Reader()

    class Gc:
        def __init__(self, product):
            events.append(["gc-owner"])

        def require_settled(self, **kwargs):
            nonlocal fired
            events.append(["gc", kwargs])
            if case == "gc-error":
                fired = True
                raise ValueError("GC proof failed")
            if case == "directory-changed":
                (directory / "ordinary-added").write_bytes(b"x")
                fired = True

    with patch.context() as bound:
        modules = [sources]
        try:
            modules.append(
                importlib.import_module(
                    "loushang.harness.worker.history._windows_sources"
                )
            )
        except ModuleNotFoundError as error:
            if error.name != "loushang.harness.worker.history._windows_sources":
                raise
        for module in modules:
            for name, value in dict(
                windows_listdir_at=listing,
                open_windows_regular_file_at=opener,
                windows_regular_file_stream_names=streams,
                windows_stat_at=visible,
            ).items():
                if hasattr(module, name):
                    bound.setattr(module, name, value)
        bound.setattr(sources, "WindowsPrivateDirectoryAcl", Acl)
        bound.setattr(sources, "CodingWindowsWorkerGcHistoryAuthority", Gc)
        bound.setattr(os, "fstat", fstat)
        bound.setattr(os, "fdopen", fdopen)
        if case == "file-count":
            bound.setattr(sources, "_MAX_FILES", 1)
        if case == "file-cap":
            bound.setattr(sources, "_MAX_FILE_BYTES", 3)
        if case == "total-cap":
            bound.setattr(sources, "_MAX_TOTAL_BYTES", 6)
        result = outcome(
            lambda: (
                sources._capture_coding_windows_worker_history_sources_under_gc_guard(
                    Product(),
                    store_id="store-a",
                    lease_owner_revision=2,
                    require_settled_history=True,
                    allow_preparation_stage=case == "prep-allowed",
                    allow_checkpoint_stage=case == "checkpoint-allowed",
                    allow_base_stage=case == "base-allowed",
                ).to_dict()
            )
        )
    leak = []
    for fd, name in fds.items():
        try:
            original_fstat(fd)
        except OSError:
            continue
        leak.append(name)
        os.close(fd)
    if case in {
        "lower-stream",
        "empty-stream",
        "named-stream",
        "acl-root-error",
        "acl-file-error",
        "root-before-changed",
        "root-after-changed",
        "source-meta-changed",
        "visible-changed",
        "source-truncated",
        "read-error",
        "close-error",
        "fdopen-error",
        "gc-error",
        "directory-changed",
        "missing-source",
    }:
        assert fired, "selected failure must actually occur"
    return canonical(dict(result=result, events=events, open_descriptors=leak))


@pytest.mark.parametrize("case", CASES)
def test_original_source_capture_contract(case, tmp_path, monkeypatch):
    assert (
        observe_sources(case, tmp_path / "source", monkeypatch)
        == json.loads(_FIXTURE.read_text())[case]
    )
