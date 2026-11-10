"""Real files/FDs against frozen original capture; Windows ports controlled.

ACL/attributes/streams and Product root admission are declared ports. Cancellation
is synchronous CancelledError at an IO boundary, not Task.cancel or native Win32.
Fresh input identities/bytes are checked before strict physical-role projection.
"""

from __future__ import annotations

import asyncio
import dataclasses
import gzip
import hashlib
import importlib
import json
import os
import stat
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve().parent
REAL_OS = os
ATTEMPT = "a" * 32
BODY = b"original captured worker bytes\x00\xff\n"
CASES = (
    "valid-flat",
    "valid-nested",
    "valid-deep",
    "invalid-intent",
    "acl-enter-error",
    "acl-exit-error",
    "root-enter-error",
    "root-exit-error",
    "root-validate-error",
    "root-fstat-error",
    "root-lstat-error",
    "root-mismatch",
    "stage-open-error",
    "stage-validate-error",
    "stage-unsafe",
    "stage-link-unsafe",
    "stage-stream-unsafe",
    "expected-stage-mismatch",
    "intent-stage-mismatch",
    "stage-name-mismatch",
    "marker-open-error",
    "marker-validate-error",
    "marker-too-large",
    "marker-overflow",
    "marker-read-error",
    "marker-short-read",
    "marker-after-change",
    "marker-name-change",
    "marker-invalid-json",
    "marker-invalid-path",
    "marker-invalid-fields",
    "tree-top-extra",
    "child-open-error",
    "child-validate-error",
    "child-name-change",
    "tree-child-extra",
    "second-child-open-error",
    "second-child-validate-error",
    "executable-open-error",
    "executable-too-large",
    "executable-read-error",
    "executable-short-read",
    "executable-after-change",
    "executable-name-change",
    "digest-mismatch",
    "marker-size-mismatch",
    "child-close-error",
    "child-and-stage-close-error",
    "body-and-child-close-error",
    "marker-and-stage-close-error",
    "final-stage-fstat-error",
    "final-stage-change",
    "final-stage-name-change",
    "final-tree-change",
    "stage-close-error",
    "stage-and-root-close-error",
    "capture-constructor-error",
    "cancel-marker-read",
    "cancel-child-open",
    "cancel-executable-read",
    "keyboardinterrupt-marker-read",
)


def error_data(e, seen=frozenset()):
    if id(e) in seen:
        return {"cycle": type(e).__name__}
    seen = seen | {id(e)}
    return {
        "type": type(e).__module__ + "." + type(e).__qualname__,
        "message": str(e),
        "code": getattr(e, "code", None),
        "notes": list(getattr(e, "__notes__", ())),
        "suppress_context": e.__suppress_context__,
        "cause": error_data(e.__cause__, seen) if e.__cause__ else None,
        "context": error_data(e.__context__, seen) if e.__context__ else None,
    }


def value(v):
    if dataclasses.is_dataclass(v):
        return {
            "type": type(v).__name__,
            "fields": {
                f.name: value(getattr(v, f.name)) for f in dataclasses.fields(v)
            },
        }
    if isinstance(v, tuple):
        return [value(x) for x in v]
    if isinstance(v, bytes):
        return {"hex": v.hex()}
    return v


def seeded(case):
    root = HERE / "physical-inputs" / case
    stage = root / ("worker-payload-" + ATTEMPT)
    entrypoint = (
        "worker.exe"
        if case == "valid-flat"
        else "bin/worker.exe"
        if case == "valid-nested"
        else "bin/deep/worker.exe"
    )
    marker = stage / "worker-payload.json"
    executable = stage / entrypoint
    if not marker.exists():
        executable.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        body = b"corrupted worker" if case == "digest-mismatch" else BODY
        executable.write_bytes(body)
        if case == "executable-too-large":
            with executable.open("r+b") as file:
                file.truncate(16 * 1024 * 1024 + 1)
        if case == "tree-top-extra":
            (stage / "unexpected").write_bytes(b"extra")
        if case == "tree-child-extra":
            (stage / "bin" / "unexpected").write_bytes(b"extra")
        st = stage.stat()
        raw = _marker_input(case, (st.st_dev, st.st_ino))
        marker.write_bytes(raw)
    return root, stage, entrypoint


class Observer:
    def __init__(self, case, root):
        self.case = case
        self.root = root
        self.rows = []
        self.raw = []
        self.opened = {}
        self.counts = {}

    def add(self, event, **kw):
        self.rows.append({"event": event, **kw})

    def number(self, event):
        self.counts[event] = self.counts.get(event, 0) + 1
        return self.counts[event]

    def fail(self, event):
        self.add(event)
        target = {
            "acl-enter-error": "acl.enter",
            "acl-exit-error": "acl.exit",
            "root-enter-error": "root.enter",
            "root-exit-error": "root.exit",
            "root-validate-error": "acl.validate:root",
            "root-fstat-error": "fstat:root:1",
            "root-lstat-error": "root.lstat",
            "stage-open-error": "open.dir:stage",
            "stage-validate-error": "acl.validate:stage",
            "marker-open-error": "open.file:marker",
            "marker-validate-error": "acl.validate:marker",
            "child-open-error": "open.dir:dir0",
            "child-validate-error": "acl.validate:dir0",
            "second-child-open-error": "open.dir:dir1",
            "second-child-validate-error": "acl.validate:dir1",
            "executable-open-error": "open.file:executable",
            "marker-read-error": "read:marker:1",
            "executable-read-error": "read:executable:1",
            "child-close-error": "close:dir1",
            "body-and-child-close-error": "close:dir1",
            "stage-close-error": "close:stage",
            "final-stage-fstat-error": "fstat:stage:2",
        }.get(self.case)
        if self.case == "child-and-stage-close-error" and event in {
            "close:dir1",
            "close:stage",
        }:
            raise OSError("injected " + event)
        if self.case == "marker-and-stage-close-error" and event in {
            "read:marker:1",
            "close:stage",
        }:
            raise OSError("injected " + event)
        if self.case == "stage-and-root-close-error" and event in {
            "close:stage",
            "root.exit",
        }:
            raise OSError("injected " + event)
        if self.case == "body-and-child-close-error" and event == "read:executable:1":
            raise OSError("injected " + event)
        if event == target:
            raise OSError("injected " + event)
        if (
            self.case
            in {"cancel-marker-read", "cancel-executable-read", "cancel-child-open"}
            and event
            == {
                "cancel-marker-read": "read:marker:1",
                "cancel-executable-read": "read:executable:1",
                "cancel-child-open": "open.dir:dir0",
            }[self.case]
        ):
            raise asyncio.CancelledError("injected " + event)
        if self.case == "keyboardinterrupt-marker-read" and event == "read:marker:1":
            raise KeyboardInterrupt("injected " + event)

    def acquire(self, fd, role, path):
        self.opened[fd] = (role, path)
        self.raw.append({"event": "acquire", "fd": fd, "role": role, "path": str(path)})
        self.add("acquired", role=role)

    def role(self, fd):
        return self.opened[fd][0]

    def metadata(self, raw, role):
        self.raw.append(
            {
                "event": "stat",
                "role": role,
                "identity": [
                    raw.st_dev,
                    raw.st_ino,
                    raw.st_nlink,
                    raw.st_size,
                    raw.st_mtime_ns,
                ],
            }
        )
        return NS(
            st_dev=raw.st_dev,
            st_ino=raw.st_ino,
            st_mode=raw.st_mode,
            st_nlink=1,
            st_size=raw.st_size,
            st_mtime_ns=raw.st_mtime_ns,
            st_file_attributes=0x10 if stat.S_ISDIR(raw.st_mode) else 0x80,
        )

    def fstat(self, fd):
        role = self.role(fd)
        n = self.number("fstat:" + role)
        self.fail(f"fstat:{role}:{n}")
        v = self.metadata(REAL_OS.fstat(fd), role)
        if role == "stage" and self.case == "stage-unsafe":
            v.st_mode = stat.S_IFLNK
        if role == "stage" and self.case == "stage-link-unsafe":
            v.st_nlink = 2
        if role == "stage" and self.case == "final-stage-change" and n == 2:
            v.st_mtime_ns += 1
        if (
            role in {"marker", "executable"}
            and self.case == role + "-after-change"
            and n == 2
        ):
            v.st_mtime_ns += 1
        if role == "marker" and self.case == "marker-overflow":
            v.st_size = 1024
        self.add(
            "stat.result",
            role=role,
            identity=[v.st_dev, v.st_ino, v.st_nlink, v.st_size, v.st_mtime_ns],
        )
        return v

    def close(self, fd):
        role = self.role(fd)
        REAL_OS.close(fd)
        self.opened.pop(fd)
        self.raw.append({"event": "close", "fd": fd, "role": role})
        self.fail("close:" + role)

    def open_dir(self, name, *, dir_fd, **kwargs):
        parent = self.role(dir_fd)
        role = "stage" if parent == "root" else "dir0" if parent == "stage" else "dir1"
        self.fail("open.dir:" + role)
        fd = REAL_OS.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd
        )
        self.acquire(fd, role, self.opened[dir_fd][1] / name)
        self.add("open.options", role=role, options=kwargs)
        return fd

    def open_file(self, parent, name, **kwargs):
        role = "marker" if name == "worker-payload.json" else "executable"
        self.fail("open.file:" + role)
        fd = REAL_OS.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        self.acquire(fd, role, self.opened[parent][1] / name)
        self.add("open.options", role=role, options=kwargs)
        return fd

    def stat_at(self, parent, name):
        role = (
            "stage"
            if self.role(parent) == "root"
            else "marker"
            if name == "worker-payload.json"
            else "dir0"
            if name == "bin"
            else "dir1"
            if name == "deep"
            else "executable"
        )
        n = self.number("name.stat:" + role)
        self.fail(f"name.stat:{role}:{n}")
        v = self.metadata(
            REAL_OS.stat(name, dir_fd=parent, follow_symlinks=False), role
        )
        if self.case in {
            "stage-name-mismatch",
            "marker-name-change",
            "executable-name-change",
            "child-name-change",
            "final-stage-name-change",
        } and (
            (role == "stage" and self.case == "stage-name-mismatch" and n == 1)
            or (role == "stage" and self.case == "final-stage-name-change" and n == 2)
            or (role == "marker" and self.case == "marker-name-change")
            or (role == "executable" and self.case == "executable-name-change")
            or (role == "dir0" and self.case == "child-name-change")
        ):
            v.st_ino += 1
        self.add(
            "name.stat.result",
            role=role,
            identity=[v.st_dev, v.st_ino, v.st_nlink, v.st_size, v.st_mtime_ns],
        )
        return v

    def listdir(self, fd):
        role = self.role(fd)
        n = self.number("listdir:" + role)
        self.fail(f"listdir:{role}:{n}")
        names = REAL_OS.listdir(fd)
        if self.case == "final-tree-change" and role == "stage" and n == 2:
            names.append("later-added")
        self.add("listdir.result", role=role, names=sorted(names))
        return names

    def streams(self, fd):
        role = self.role(fd)
        self.fail("streams:" + role)
        return (
            ("evil:stream",)
            if self.case == "stage-stream-unsafe" and role == "stage"
            else ("::$DATA",)
        )

    def read(self, fd, maximum):
        role = self.role(fd)
        n = self.number("read:" + role)
        self.fail(f"read:{role}:{n}")
        raw = REAL_OS.read(
            fd, 1 if self.case == role + "-short-read" and n == 1 else maximum
        )
        if self.case == role + "-short-read" and n == 1:
            REAL_OS.lseek(fd, 0, os.SEEK_END)
            self.add("injected.seek_eof", role=role)
        self.add("read.result", role=role, requested=maximum, body=raw.hex())
        return raw

    @contextmanager
    def root_borrow(self):
        self.fail("root.enter")
        fd = REAL_OS.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.acquire(fd, "root", self.root)
        try:
            yield fd
        finally:
            REAL_OS.close(fd)
            self.opened.pop(fd)
            self.add("root.closed")
            self.fail("root.exit")

    def root_lstat(self):
        self.fail("root.lstat")
        v = REAL_OS.stat(self.root, follow_symlinks=False)
        if self.case == "root-mismatch":
            return NS(st_dev=v.st_dev, st_ino=v.st_ino + 1)
        return v

    def acl_type(self):
        observer = self

        class Acl:
            def __enter__(self):
                observer.fail("acl.enter")
                return self

            def __exit__(self, *exc):
                observer.fail("acl.exit")
                return False

            def validate(self, fd):
                observer.fail("acl.validate:" + observer.role(fd))

        return Acl


class OsPort:
    def __init__(self, observer):
        self.observer = observer

    def __getattr__(self, name):
        return getattr(REAL_OS, name)

    def fstat(self, fd):
        return self.observer.fstat(fd)

    def close(self, fd):
        return self.observer.close(fd)

    def read(self, fd, maximum):
        return self.observer.read(fd, maximum)


def scenario(case):
    module = importlib.import_module(
        "loushang.coding.package_product_worker_windows_stage_review"
    )
    io = importlib.import_module("loushang.harness.worker.payload._windows_stage_io")
    consumption = importlib.import_module(
        "loushang.harness.resources.packages._file_consumption"
    )
    intent_module = importlib.import_module(
        "loushang.coding.package_product_worker_windows_launch_intent"
    )
    root, stage, entrypoint = seeded(case)
    observer = Observer(case, root)
    port = OsPort(observer)
    m = stage.stat()
    stage_identity = (m.st_dev, m.st_ino)
    intent = intent_module.CodingWindowsWorkerLaunchIntentV1(
        attempt_id=ATTEMPT,
        stage_identity=stage_identity,
        receipt_fingerprint="b" * 64,
        request_fingerprint="c" * 64,
        identity_fingerprint="d" * 64,
        runtime_fingerprint="e" * 64,
        payload_digest=hashlib.sha256(BODY).hexdigest(),
        owner_id="worker-owner",
        supervisor_epoch=1,
    )
    if case == "intent-stage-mismatch":
        intent = dataclasses.replace(intent, stage_identity=(m.st_dev, m.st_ino + 1))
    if case == "invalid-intent":
        intent = NS()
    expected = (
        (m.st_dev, m.st_ino + 1)
        if case == "expected-stage-mismatch"
        else stage_identity
    )
    product = NS(
        epoch_runtime=NS(borrow_product_state_root_descriptor=observer.root_borrow),
        state_root=NS(lstat=observer.root_lstat),
    )
    effect = importlib.import_module(
        "loushang.harness.package_product._worker_windows_attempt"
    )
    result = None
    error = None
    with ExitStack() as stack:
        for owner in (effect, io):
            stack.enter_context(patch.object(owner, "os", port))
            stack.enter_context(
                patch.object(owner, "open_windows_directory", observer.open_dir)
            )
            stack.enter_context(
                patch.object(owner, "windows_stat_at", observer.stat_at)
            )
            stack.enter_context(
                patch.object(owner, "windows_listdir_at", observer.listdir)
            )
        stack.enter_context(
            patch.object(effect, "WindowsPrivateDirectoryAcl", observer.acl_type())
        )
        stack.enter_context(
            patch.object(io, "open_windows_regular_file_at", observer.open_file)
        )
        stack.enter_context(
            patch.object(io, "windows_directory_stream_names", observer.streams)
        )
        stack.enter_context(
            patch.object(io, "windows_regular_file_stream_names", observer.streams)
        )
        stack.enter_context(patch.object(consumption, "os", port))
        if case == "capture-constructor-error":

            def broken(self, **kwargs):
                observer.add("capture.construct", keys=sorted(kwargs))
                raise ValueError("capture construction failed")

            stack.enter_context(
                patch.object(module._CapturedStageBytesV1, "__init__", broken)
            )
        try:
            result = value(
                module._capture_stage_bytes(
                    product, attempt_id=ATTEMPT, expected_stage=expected, intent=intent
                )
            )
        except BaseException as exc:
            error = error_data(exc)
    outstanding = [role for role, _path in observer.opened.values()]
    for fd, (role, _path) in list(observer.opened.items()):
        REAL_OS.close(fd)
        observer.opened.pop(fd)
        observer.raw.append({"event": "observer.cleanup", "fd": fd, "role": role})
    return {
        "result": result,
        "error": error,
        "trace": observer.rows,
        "outstanding_before_observer_cleanup": outstanding,
        "outstanding_after_observer_cleanup": [],
    }, observer.raw


def _entrypoint(case):
    return (
        "worker.exe"
        if case == "valid-flat"
        else "bin/worker.exe"
        if case == "valid-nested"
        else "bin/deep/worker.exe"
    )


def _marker_input(case, stage_identity):
    document = {
        "attemptId": ATTEMPT,
        "entrypoint": _entrypoint(case),
        "ownerId": "worker-owner",
        "payloadDigest": hashlib.sha256(BODY).hexdigest(),
        "payloadSize": len(BODY) + (1 if case == "marker-size-mismatch" else 0),
        "receiptFingerprint": "b" * 64,
        "stageDevice": stage_identity[0],
        "stageInode": stage_identity[1],
        "version": 1,
    }
    if case == "marker-invalid-json":
        return b"not JSON"
    if case in {"marker-too-large", "marker-overflow"}:
        return b"X" * 1025
    if case == "marker-invalid-path":
        document["entrypoint"] = "../escape"
    if case == "marker-invalid-fields":
        document["ownerId"] = "wrong"
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _input_context(case, root):
    stage = root / ("worker-payload-" + ATTEMPT)
    entrypoint = _entrypoint(case)
    paths = {
        "root": root,
        "stage": stage,
        "marker": stage / "worker-payload.json",
        "executable": stage / entrypoint,
    }
    parent = stage
    for index, part in enumerate(entrypoint.split("/")[:-1]):
        parent = parent / part
        paths["dir" + str(index)] = parent
    stats = {
        role: (v.st_dev, v.st_ino, v.st_nlink, v.st_size, v.st_mtime_ns)
        for role, path in paths.items()
        for v in (path.stat(),)
    }
    assert len({item[:2] for item in stats.values()}) == len(stats), (
        "physical roles must be one-to-one"
    )
    marker = paths["marker"].read_bytes()
    assert marker == _marker_input(case, stats["stage"][:2]), (
        "marker must match independent original input formula"
    )
    executable = b"corrupted worker" if case == "digest-mismatch" else BODY
    with paths["executable"].open("rb") as file:
        assert file.read(len(executable)) == executable
    assert stats["executable"][3] == (
        16 * 1024 * 1024 + 1 if case == "executable-too-large" else len(executable)
    )
    return {
        "stats": stats,
        "bytes": {"marker": marker, "executable": executable},
        "directory_roles": {
            "/".join(entrypoint.split("/")[: i + 1]): "dir" + str(i)
            for i in range(len(entrypoint.split("/")) - 1)
        },
    }


def _metadata_token(identity, role, context, case, event):
    before = context["stats"][role]
    inode_offset = 0
    mtime_offset = 0
    size_offset = 0
    nlink = 1
    if event.startswith("name.stat:") and (
        (case == "stage-name-mismatch" and event == "name.stat:stage:1")
        or (case == "final-stage-name-change" and event == "name.stat:stage:2")
        or (case == "marker-name-change" and role == "marker")
        or (case == "executable-name-change" and role == "executable")
        or (case == "child-name-change" and role == "dir0")
    ):
        inode_offset = 1
    if (
        (case == "final-stage-change" and event == "fstat:stage:2")
        or (case == "marker-after-change" and event == "fstat:marker:2")
        or (case == "executable-after-change" and event == "fstat:executable:2")
    ):
        mtime_offset = 1
    if case == "stage-link-unsafe" and role == "stage" and event.startswith("fstat:"):
        nlink = 2
    if case == "marker-overflow" and role == "marker" and event.startswith("fstat:"):
        size_offset = 1024 - before[3]
    expected = [
        before[0],
        before[1] + inode_offset,
        nlink,
        before[3] + size_offset,
        before[4] + mtime_offset,
    ]
    assert identity == expected, (case, event, role, identity, expected)
    return [
        "input.dev:" + role,
        "input.ino:" + role + "+" + str(inode_offset),
        nlink,
        "input.size:" + role + "+" + str(size_offset),
        "input.mtime:" + role + "+" + str(mtime_offset),
    ]


def _portable_observation(observed, context, case):
    rows = []
    current_event = ""
    positions = {"marker": 0, "executable": 0}
    consumed = {"marker": 0, "executable": 0}
    pending_seek = set()
    for original in observed["trace"]:
        row = dict(original)
        event = row["event"]
        if event.startswith(("fstat:", "name.stat:")):
            current_event = event
        if event in {"stat.result", "name.stat.result"}:
            row["identity"] = _metadata_token(
                row["identity"], row["role"], context, case, current_event
            )
        if event == "injected.seek_eof":
            pending_seek.add(row["role"])
        if event == "read.result":
            role = row["role"]
            data = context["bytes"][role]
            start = positions[role]
            raw = bytes.fromhex(row["body"])
            end = start + len(raw)
            maximum_plus_one = 1025 if role == "marker" else 16 * 1024 * 1024 + 1
            assert row["requested"] == min(
                1024 * 1024, maximum_plus_one - consumed[role]
            ), (case, role, "bounded request changed", row["requested"], consumed[role])
            if role == "marker":
                row["requested"] = {
                    "maximum_plus_one": 1025,
                    "chunk_size": 1024 * 1024,
                    "already_read": "input.length:marker"
                    if consumed[role] == len(data) and consumed[role] > 0
                    else consumed[role],
                }
            consumed[role] += len(raw)
            assert raw == data[start:end], (
                case,
                role,
                "bytes differ from prior independent input",
            )
            if not raw:
                assert start == len(data), (
                    case,
                    role,
                    "early EOF without original injected seek",
                )
                row["body"] = {"input": role, "boundary": "EOF", "length": 0}
            else:
                assert end <= len(data)
                row["body"] = {
                    "input": role,
                    "start": start,
                    "end": "EOF" if end == len(data) else end,
                }
            positions[role] = len(data) if role in pending_seek else end
            pending_seek.discard(role)
        rows.append(row)
    result = observed["result"]
    if result is not None:
        assert set(result) == {"type", "fields"}
        fields = dict(result["fields"])
        assert set(fields) == {
            "entrypoint",
            "stage_identity",
            "directory_identities",
            "marker_identity",
            "executable_identity",
            "executable_digest",
        }
        for field, role in [
            ("stage_identity", "stage"),
            ("marker_identity", "marker"),
            ("executable_identity", "executable"),
        ]:
            fields[field] = _metadata_token(
                fields[field], role, context, case, "return"
            )
        fields["directory_identities"] = [
            [
                name,
                _metadata_token(
                    identity, context["directory_roles"][name], context, case, "return"
                ),
            ]
            for name, identity in fields["directory_identities"]
        ]
        result = fields
    return {**observed, "trace": rows, "result": result}


_FIXTURE = Path(__file__).parent / "fixtures" / "stage_capture_runtime_v1.json.gz"
_EXPECTED = json.loads(gzip.decompress(_FIXTURE.read_bytes()))


@pytest.mark.parametrize("case", CASES)
def test_stage_capture_runtime(case, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "HERE", tmp_path)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    root, _stage, _entry = seeded(case)
    context = _input_context(case, root)
    observed, _raw = scenario(case)
    assert _portable_observation(observed, context, case) == _EXPECTED[case], case
