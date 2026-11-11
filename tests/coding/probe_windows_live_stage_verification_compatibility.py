"""Original live-stage verifier over reused synthetic native handles, not Windows IO."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_windows_payload as code
import loushang.harness.package_product._worker_windows_attempt as core
import loushang.harness.worker.payload._windows_stage_io as stage_io
from loushang.harness.worker.contracts import WorkerRuntimeBindingV1
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1
from tests.coding.probe_windows_stage_io_compatibility import ATTEMPT, NativeModel
from tests.harness.worker.test_product_activation import _receipt

EXPECTED = (
    Path(__file__).parent / "fixtures" / "windows_live_stage_verification_v1.json.gz"
)
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux synthetic Windows IO model"
)


def error_data(error, seen=frozenset()):
    if error is None:
        return None
    if id(error) in seen:
        return {"cycle": True}
    seen = seen | {id(error)}
    return dict(
        type=f"{type(error).__module__}.{type(error).__qualname__}",
        args=list(error.args),
        code=getattr(error, "code", None),
        notes=list(getattr(error, "__notes__", ())),
        cause=error_data(error.__cause__, seen),
        context=error_data(error.__context__, seen),
        suppress=error.__suppress_context__,
    )


class Trace(list):
    def __init__(self, faults):
        super().__init__()
        self.faults = {(f["event"], f.get("occurrence", 1)): f for f in faults}
        self.counts = Counter()
        self.fired = []

    def append(self, row):
        super().append(row)
        name = row[0]
        self.counts[name] += 1
        key = (name, self.counts[name])
        fault = self.faults.get(key)
        if fault is not None:
            self.fired.append(list(key))
            label = f"fault:{name}:{key[1]}"
            if fault.get("kind") == "stop":
                raise StopIteration(label)
            if fault.get("kind") == "cancel":
                raise asyncio.CancelledError(label)
            if fault.get("kind") == "interrupt":
                raise KeyboardInterrupt(label)
            raise OSError(5, label)


def observe(spec, monkeypatch):
    fs = NativeModel("complete", "normal")
    fs.handles.clear()  # Root acquisition belongs to the borrow scope below.
    fs.events = Trace(spec.get("faults", ()))
    entrypoint = (
        "worker.exe"
        if spec.get("shape") == "flat"
        else "bin/worker.exe"
        if spec.get("shape") == "nested"
        else "bin/deep/worker.exe"
    )
    if spec.get("shape") == "flat":
        fs.stage.children.clear()
        fs.executable.path = fs.stage.path + "/worker.exe"
        fs.stage.children["worker.exe"] = fs.executable
    elif spec.get("shape") != "nested":
        child = fs.node(fs.directory.path + "/deep", 14, True)
        fs.directory.children = {"deep": child}
        fs.executable.path = child.path + "/worker.exe"
        child.children["worker.exe"] = fs.executable
    body = fs.executable.body
    receipt = _receipt()
    runtime = WorkerRuntimeBindingV1(
        package_root=Path(fs.stage.path),
        executable=Path(fs.executable.path),
        executable_digest=hashlib.sha256(body).hexdigest(),
        executable_size=len(body),
        cwd_device=1,
        cwd_inode=10,
        worker_configuration_fingerprint="a" * 64,
        protocol="worker",
        protocol_version=1,
    )
    lease = code.CodingWindowsWorkerPayloadLeaseV1(
        attempt_id=ATTEMPT,
        runtime=runtime,
        receipt_fingerprint=receipt.fingerprint,
        payload_digest=runtime.executable_digest,
        owner_id="owner",
        stage_identity=(1, 99) if spec.get("bad") == "stage-identity" else (1, 10),
    )
    marker_bytes = stage_io.marker_bytes
    raw = marker_bytes(
        attempt_id=ATTEMPT,
        entrypoint=entrypoint,
        owner_id=lease.owner_id,
        payload_digest=lease.payload_digest,
        payload_size=len(body),
        receipt_fingerprint=receipt.fingerprint,
        stage_identity=(1, 10),
    )
    marker = fs.node(fs.stage.path + "/worker-payload.json", 13, False, raw)
    fs.stage.children["worker-payload.json"] = marker
    bad = spec.get("bad")
    if bad == "top-extra":
        fs.stage.children["extra"] = fs.node(fs.stage.path + "/extra", 21, False)
    if bad == "child-extra":
        fs.directory.children["extra"] = fs.node(
            fs.directory.path + "/extra", 22, False
        )
    if bad == "executable-size":
        fs.executable.body += b"extra"
    if bad == "marker-suffix":
        marker.body += b" "
    original_lstat = Path.lstat
    original_size = WorkerRuntimeBindingV1.executable_size
    original_fingerprint = ProductWorkerActivationReceiptV1.fingerprint
    original_read = fs.read
    original_streams = fs.streams
    original_stat_at = fs.stat_at
    root_reads = 0
    root_acquired = False

    def event(*row):
        fs.events.append(list(row))

    class Acl:
        def __init__(self):
            event("acl-construct")

        def __enter__(self):
            event("acl-enter")
            return self

        def __exit__(self, _type, error, _tb):
            event("acl-exit", error_data(error))

        def validate(self, fd):
            event("acl", fs.handles[fd].node.path)

    class Borrow:
        def __enter__(self):
            nonlocal root_acquired
            event("root-enter")
            self.fd = fs.handle(fs.root)
            root_acquired = True
            return self.fd

        def __exit__(self, _type, error, _tb):
            event("root-exit", error_data(error))
            fs.close(self.fd)

    class Product:
        epoch_runtime = SimpleNamespace(borrow_product_state_root_descriptor=Borrow)

        @property
        def state_root(self):
            nonlocal root_reads
            root_reads += 1
            event("root-path", root_reads)
            return Path(fs.root.path)

    def lstat(path, *args, **kwargs):
        if str(path) != fs.root.path:
            return original_lstat(path, *args, **kwargs)
        event("root-lstat", root_reads)
        value = fs.metadata(fs.root)
        if bad == "root-before" or (bad == "root-after" and root_reads == 2):
            value.st_ino += 1
        return value

    def runtime_size(value):
        event("runtime-size")
        return original_size.__get__(value, type(value))

    def fingerprint(value):
        event("receipt-fingerprint")
        return original_fingerprint.fget(value)

    def expected_marker(**kwargs):
        event("marker-expected", kwargs)
        return marker_bytes(**kwargs)

    def streams(fd):
        result = original_streams(fd)
        node = fs.handles[fd].node
        if bad == "named-" + (
            "marker"
            if node is marker
            else "executable"
            if node is fs.executable
            else "stage"
            if node is fs.stage
            else "child"
        ):
            return ("::$DATA", ":hidden:$DATA")
        return result

    def stat_at(fd, name):
        result = original_stat_at(fd, name)
        if bad == "visible-stage" and name == "worker-payload-" + ATTEMPT:
            result.st_ino += 1
        return result

    def read(fd, size):
        if bad != "short-marker" or fd not in fs.handles:
            return original_read(fd, size)
        opened = fs.handles[fd]
        fs.events.append(["read", opened.node.path, size])
        chunk = opened.node.body[opened.position : opened.position + min(size, 3)]
        opened.position += len(chunk)
        return chunk

    error = None
    result = "not-returned"
    with monkeypatch.context() as patch:
        fs.install(patch)
        for module in (code, core, stage_io):
            for name, replacement in dict(
                WindowsPrivateDirectoryAcl=Acl,
                open_windows_directory=fs.open_directory,
                open_windows_regular_file_at=fs.open_file,
                windows_listdir_at=fs.listdir,
                windows_stat_at=stat_at,
                windows_directory_stream_names=streams,
                windows_regular_file_stream_names=streams,
            ).items():
                if hasattr(module, name):
                    patch.setattr(module, name, replacement)
        patch.setattr(Path, "lstat", lstat)
        patch.setattr(os, "read", read)
        patch.setattr(WorkerRuntimeBindingV1, "executable_size", property(runtime_size))
        patch.setattr(
            ProductWorkerActivationReceiptV1, "fingerprint", property(fingerprint)
        )
        for module, name in ((code, "_marker_bytes"), (core, "marker_bytes")):
            if hasattr(module, name):
                patch.setattr(module, name, expected_marker)
        try:
            result = code._verify_stage_marker(
                receipt_owner=SimpleNamespace(product_owner=Product()),
                receipt=receipt,
                payload_lease=lease,
                entrypoint=entrypoint,
                initial=spec.get("initial", True),
            )
        except BaseException as caught:
            error = error_data(caught)
        state = fs.state()
    assert fs.events.fired == [
        [f["event"], f.get("occurrence", 1)] for f in spec.get("faults", ())
    ], (spec, fs.events.fired, fs.events)
    if spec.get("faults") or bad:
        assert error is not None and result == "not-returned", (spec, error, fs.events)
    else:
        assert error is None and result is None and not state["open_paths"]
        assert root_reads == 2
        assert sum(row[0] == "read" for row in fs.events) == 1
        assert sum(row[0] == "runtime-size" for row in fs.events) == 2
        assert sum(row[0] == "marker-expected" for row in fs.events) == 1
        assert sum(row[0] == "receipt-fingerprint" for row in fs.events) == 1
        if not spec.get("initial", True):
            assert [row for row in fs.events if row[0] == "acl"] == [
                ["acl", fs.root.path]
            ]
    return dict(
        trace=list(fs.events),
        fired=fs.events.fired,
        error=error,
        result=result,
        root_reads=root_reads,
        root_acquired=root_acquired,
        state=state,
    )


def source_guard():
    root = Path(__file__).resolve().parents[2]
    for module, relative in (
        (code, "src/loushang/coding/package_product_worker_windows_payload.py"),
        (core, "src/loushang/harness/package_product/_worker_windows_attempt.py"),
    ):
        assert Path(module.__file__).resolve() == root / relative


_ROWS = json.loads(gzip.decompress(EXPECTED.read_bytes()))


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row["spec"]["name"])
def test_replay(row, monkeypatch):
    source_guard()
    assert json.dumps(observe(row["spec"], monkeypatch), sort_keys=True) == json.dumps(
        row["result"], sort_keys=True
    )
