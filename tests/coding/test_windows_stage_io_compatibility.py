"""Original Windows stage protocols through synthetic native IO, not OS authority."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding import (
    package_product_worker_windows_crash_stage_retirement as crash,
)
from loushang.coding import (
    package_product_worker_windows_partial_stage_retirement as partial,
)
from loushang.coding import package_product_worker_windows_payload as payload
from loushang.coding import package_product_worker_windows_stage_retirement as full
from loushang.coding import package_product_worker_windows_stage_review as review_module
from loushang.coding import (
    package_product_worker_windows_unlaunched_stage_retirement as unlaunched,
)
from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
)
from loushang.coding.package_product_worker_windows_partial_stage_review import (
    CodingWindowsWorkerPartialStageReviewV1,
)
from loushang.coding.package_product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux synthetic Windows IO baseline"
)
ROLES = ("complete", "partial", "unlaunched", "crash")
CASES = (
    "normal",
    "missing-stage",
    "payload-missing",
    "bad-attributes",
    "stream-error",
    "empty-streams",
    "extra-member",
    "marker-changed",
    "directory-changed",
    "delete-lost-ack",
    "root-write-lost-ack",
    "close-stage-lost-ack",
    "extra-after-delete",
    "short-reads",
    "empty-stage",
)
ATTEMPT = "7" * 32


class NativeModel:
    def __init__(self, role, case):
        self.role, self.case = role, case
        self.nodes = {}
        self.handles = {}
        self.next_handle = 1_000_000
        self.events = []
        self.receipts = {}
        self.fired = False
        self.original_close, self.original_read, self.original_fstat = (
            os.close,
            os.read,
            os.fstat,
        )
        self.root = self.node("/product-state", 1, True)
        self.stage = self.node("/product-state/worker-payload-" + ATTEMPT, 10, True)
        self.root.children["worker-payload-" + ATTEMPT] = self.stage
        self.directory = self.node(self.stage.path + "/bin", 11, True)
        self.stage.children["bin"] = self.directory
        self.executable = self.node(
            self.directory.path + "/worker.exe", 12, False, b"payload"
        )
        self.directory.children["worker.exe"] = self.executable
        self.root_handle = self.handle(self.root)

    def node(self, path, inode, directory, body=b""):
        value = SimpleNamespace(
            path=path,
            inode=inode,
            directory=directory,
            body=body,
            children={},
            attributes=16 if directory else 32,
            nlink=1,
        )
        self.nodes[path] = value
        return value

    def metadata(self, node):
        return SimpleNamespace(
            st_dev=1,
            st_ino=node.inode,
            st_nlink=node.nlink,
            st_size=0 if node.directory else len(node.body),
            st_mtime_ns=100 + node.inode,
            st_mode=(stat.S_IFDIR | 0o700)
            if node.directory
            else (stat.S_IFREG | 0o600),
            st_file_attributes=node.attributes,
        )

    def identity(self, node):
        m = self.metadata(node)
        return m.st_dev, m.st_ino, m.st_nlink, m.st_size, m.st_mtime_ns

    def handle(self, node):
        fd = self.next_handle
        self.next_handle += 1
        self.handles[fd] = SimpleNamespace(node=node, position=0)
        return fd

    def fstat(self, fd):
        if fd not in self.handles:
            return self.original_fstat(fd)
        node = self.handles[fd].node
        self.events.append(["fstat", node.path])
        return self.metadata(node)

    def close(self, fd):
        if fd not in self.handles:
            return self.original_close(fd)
        node = self.handles.pop(fd).node
        self.events.append(["close", node.path])
        if (
            self.case == "close-stage-lost-ack"
            and node is self.stage
            and not self.fired
        ):
            self.fired = True
            raise OSError("stage close happened; acknowledgement lost")

    def read(self, fd, size):
        if fd not in self.handles:
            return self.original_read(fd, size)
        opened = self.handles[fd]
        self.events.append(["read", opened.node.path, size])
        count = min(size, 7) if self.case == "short-reads" else size
        result = opened.node.body[opened.position : opened.position + count]
        opened.position += len(result)
        return result

    def open_directory(self, name, *, dir_fd, **kwargs):
        parent = self.handles[dir_fd].node
        self.events.append(["open-directory", parent.path, name, kwargs])
        if name not in parent.children:
            raise FileNotFoundError(name)
        return self.handle(parent.children[name])

    def open_file(self, parent_fd, name, **kwargs):
        parent = self.handles[parent_fd].node
        self.events.append(["open-file", parent.path, name, kwargs])
        return self.handle(parent.children[name])

    def open_deletion(self, parent_fd, name, *, directory):
        if (
            self.case == "payload-changed-after-proof"
            and not directory
            and name == "worker.exe"
        ):
            self.fired = True
            self.executable.body = b"PAYLOAD"
        return self.open_file(parent_fd, name, deletion=True, directory=directory)

    def listdir(self, fd):
        node = self.handles[fd].node
        self.events.append(["list", node.path])
        return tuple(node.children)

    def stat_at(self, fd, name):
        parent = self.handles[fd].node
        self.events.append(["stat-at", parent.path, name])
        return self.metadata(parent.children[name])

    def streams(self, fd):
        node = self.handles[fd].node
        self.events.append(["streams", node.path])
        if self.case == "stream-error" and node is self.root:
            self.fired = True
            raise OSError("stream query failed before attribute rejection")
        if self.case == "named-stream" and node is self.executable:
            return ("::$DATA", ":hidden:$DATA")
        return () if self.case == "empty-streams" else ("::$DATA",)

    def flush(self, fd):
        self.events.append(["flush", self.handles[fd].node.path])

    def delete(self, fd, *, expected_identity, directory):
        node = self.handles[fd].node
        m = self.metadata(node)
        assert expected_identity == (
            m.st_dev,
            m.st_ino,
            m.st_mode,
            m.st_size,
            m.st_mtime_ns,
        )
        assert directory is node.directory
        self.events.append(["delete", node.path, list(expected_identity), directory])
        parent_path, _, name = node.path.rpartition("/")
        del self.nodes[parent_path].children[name]
        if (
            self.case == "delete-lost-ack"
            and node is self.executable
            and not self.fired
        ):
            self.fired = True
            raise OSError("delete happened; acknowledgement lost")
        if self.case == "extra-after-delete" and (
            name == "worker-payload.json"
            or (self.role == "partial" and node is self.executable)
        ):
            self.fired = True
            self.stage.children["late"] = self.node(
                self.stage.path + "/late", 99, False, b"late"
            )

    def receipt_read(self, path, *, maximum_bytes, allow_unpublished_stage=False):
        self.events.append(
            ["receipt-read", path.name, maximum_bytes, allow_unpublished_stage]
        )
        return self.receipts.get(path.name)

    def receipt_write(self, path, body, *, maximum_bytes):
        self.events.append(
            [
                "receipt-write",
                path.name,
                maximum_bytes,
                hashlib.sha256(body).hexdigest(),
            ]
        )
        self.receipts[path.name] = body
        if self.case == "root-write-lost-ack" and not self.fired:
            self.fired = True
            raise OSError("root intent committed; acknowledgement lost")

    def install(self, patch):
        model = self

        class Acl:
            def __enter__(self):
                model.events.append(["acl-enter"])
                return self

            def __exit__(self, *_):
                model.events.append(["acl-exit"])

            def validate(self, fd):
                model.events.append(["acl", model.handles[fd].node.path])

        bindings = dict(
            WindowsPrivateDirectoryAcl=Acl,
            open_windows_directory=self.open_directory,
            open_windows_regular_file_at=self.open_file,
            open_windows_deletion_entry_at=self.open_deletion,
            windows_listdir_at=self.listdir,
            windows_stat_at=self.stat_at,
            windows_directory_stream_names=self.streams,
            windows_regular_file_stream_names=self.streams,
            windows_delete_open_entry=self.delete,
            windows_flush_directory=self.flush,
            read_windows_private_receipt=self.receipt_read,
            write_windows_private_receipt=self.receipt_write,
        )
        modules = [full, partial, unlaunched, crash, review_module, payload]
        for name in ("_windows_stage_io", "_windows_stage_retirement"):
            module_name = "loushang.harness.worker.payload." + name
            try:
                modules.append(importlib.import_module(module_name))
            except ModuleNotFoundError as error:
                if error.name != module_name:
                    raise
        for module in modules:
            for name, value in bindings.items():
                if hasattr(module, name):
                    patch.setattr(module, name, value)
        patch.setattr(os, "fstat", self.fstat)
        patch.setattr(os, "read", self.read)
        patch.setattr(os, "close", self.close)

    def state(self):
        return dict(
            members={
                n.path: list(n.children) for n in self.nodes.values() if n.directory
            },
            receipts={name: body.hex() for name, body in self.receipts.items()},
            open_paths=sorted(opened.node.path for opened in self.handles.values()),
        )


def observed_error(action):
    try:
        action()
    except Exception as error:
        result = []
        while error is not None:
            result.append(
                [
                    type(error).__module__ + "." + type(error).__name__,
                    str(error),
                    getattr(error, "code", None),
                    error.__suppress_context__,
                ]
            )
            error = error.__cause__
        return result
    return None


def observe_stage(role, case, patch):
    fs = NativeModel(role, case)
    digest = hashlib.sha256(fs.executable.body).hexdigest()
    intent = CodingWindowsWorkerLaunchIntentV1(
        ATTEMPT, (1, 10), "b" * 64, "c" * 64, "d" * 64, "e" * 64, digest, "owner", 1
    )
    marker = payload._marker_bytes(
        attempt_id=ATTEMPT,
        entrypoint="bin/worker.exe",
        owner_id="owner",
        payload_digest=digest,
        payload_size=len(fs.executable.body),
        receipt_fingerprint=intent.receipt_fingerprint,
        stage_identity=(1, 10),
    )
    marker_node = fs.node(fs.stage.path + "/worker-payload.json", 13, False, marker)
    if role != "partial":
        fs.stage.children["worker-payload.json"] = marker_node
    fields = dict(
        attempt_id=ATTEMPT,
        lease_owner_revision=3,
        stage_identity=fs.identity(fs.stage),
        directory_identities=(("bin", fs.identity(fs.directory)),),
        entrypoint="bin/worker.exe",
        executable_identity=fs.identity(fs.executable),
        executable_digest=digest,
    )
    if role == "partial":
        if case == "empty-stage":
            fields.update(
                directory_identities=(),
                entrypoint=None,
                executable_identity=None,
                executable_digest=None,
            )
        review = CodingWindowsWorkerPartialStageReviewV1(**fields)
    elif role == "unlaunched":
        review = CodingWindowsWorkerReservedNoEffectReviewV1(
            **fields,
            intent_fingerprint=intent.fingerprint,
            native_revision=2,
            marker_identity=fs.identity(marker_node),
        )
    else:
        review = review_module.CodingWindowsWorkerStageReviewV1(
            **fields,
            intent_fingerprint=intent.fingerprint,
            native_revision=13,
            supervisor_revision=4,
            marker_identity=fs.identity(marker_node),
        )
    receipt = full.CodingWindowsWorkerStageRetirementReceiptV1(
        ATTEMPT, review.fingerprint, (1, 10)
    )
    product = SimpleNamespace(state_root=Path("/product-state"))
    if case == "missing-stage":
        fs.root.children.clear()
    elif case == "empty-stage":
        fs.stage.children.clear()
    elif case == "payload-missing":
        fs.directory.children.clear()
    elif case in {"bad-attributes", "stream-error"}:
        fs.root.attributes = 0
    elif case == "extra-member":
        fs.stage.children["foreign"] = fs.node(
            fs.stage.path + "/foreign", 99, False, b"x"
        )
    elif case == "marker-changed":
        marker_node.body += b" "
        fs.stage.children["worker-payload.json"] = marker_node
    elif case == "directory-changed":
        fs.directory.inode += 100
    with patch.context() as native:
        fs.install(native)

        def execute():
            if role == "partial":
                return partial._remove_remaining_stage(
                    product, fs.root_handle, review, receipt
                )
            if role == "unlaunched":
                return unlaunched._remove_remaining_stage(
                    product, fs.root_handle, review, intent, receipt
                )
            options = (
                {}
                if role == "complete"
                else dict(
                    root_delete_intent_path=crash._root_intent_path(product, ATTEMPT),
                    read_root_delete_intent=lambda: crash._read_root_intent(
                        product, ATTEMPT
                    ),
                )
            )
            return full._remove_remaining_stage(
                product, fs.root_handle, review, intent, receipt, **options
            )

        first = observed_error(execute)
        pending = fs.state()
        if case in {
            "delete-lost-ack",
            "root-write-lost-ack",
            "close-stage-lost-ack",
            "stream-error",
            "extra-after-delete",
            "payload-changed-after-proof",
        }:
            assert fs.fired, "the selected native/intent failure must actually occur"
        retry = (
            observed_error(execute)
            if case
            in {"delete-lost-ack", "root-write-lost-ack", "close-stage-lost-ack"}
            else None
        )
        result = dict(
            first=first,
            pending=pending,
            retry=retry,
            final=fs.state(),
            events=fs.events,
        )
    return result


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("case", CASES)
def test_original_stage_retirement_protocol(role, case, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/windows_stage_io_v1.json").read_text()
    )
    assert observe_stage(role, case, monkeypatch) == expected[role + ":" + case]


IO_CASES = (
    "exact-negative",
    "exact-zero",
    "exact-long",
    "exact-short",
    "checked-too-large",
    "checked-short",
    "marker-bool-size",
    "marker-noncanonical",
    "marker-wrong-type",
    "write-short",
    "write-zero",
)


def observe_bytes(case, patch):
    fs = NativeModel("complete", case)
    if case == "exact-zero":
        fs.executable.body = b""
    descriptor = fs.handle(fs.executable)
    with patch.context() as native:
        fs.install(native)
        value = []
        if case.startswith("exact-"):
            size = {
                "exact-negative": -1,
                "exact-zero": 0,
                "exact-long": 6,
                "exact-short": 8,
            }[case]
            read = getattr(full, "_read_exact", None)
            if read is None:
                read = full._retirement().read_exact

            def action():
                return value.append(read(descriptor, size).hex())
        elif case.startswith("checked-"):
            if case == "checked-short":
                original = fs.read

                def truncated(fd, size):
                    if fd in fs.handles:
                        fs.events.append(["short-body"])
                        return b""
                    return original(fd, size)

                native.setattr(os, "read", truncated)
            maximum = 6 if case == "checked-too-large" else 100

            def action():
                return value.append(
                    list(
                        review_module._read_checked_file(
                            fs.directory and fs.handle(fs.directory),
                            "worker.exe",
                            type(
                                "Acl",
                                (),
                                {
                                    "validate": lambda _, fd: fs.events.append(
                                        ["acl", fs.handles[fd].node.path]
                                    )
                                },
                            )(),
                            maximum_bytes=maximum,
                        )
                    )
                )
        elif case.startswith("marker-"):
            intent = CodingWindowsWorkerLaunchIntentV1(
                ATTEMPT,
                (1, 10),
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "owner",
                1,
            )
            body = payload._marker_bytes(
                attempt_id=ATTEMPT,
                entrypoint="bin/worker.exe",
                owner_id="owner",
                payload_digest="f" * 64,
                payload_size=7,
                receipt_fingerprint="b" * 64,
                stage_identity=(1, 10),
            )
            if case == "marker-bool-size":
                body = body.replace(b'"payloadSize":7', b'"payloadSize":true')
            elif case == "marker-noncanonical":
                body += b" "
            else:
                intent = (
                    SimpleNamespace(**vars(intent))
                    if hasattr(intent, "__dict__")
                    else object()
                )

            def action():
                return value.append(
                    review_module._verify_marker(
                        body, intent=intent, stage_identity=(1, 10)
                    )
                )
        else:

            def writer(fd, chunk):
                fs.events.append(["write", fd, bytes(chunk).hex()])
                return 0 if case == "write-zero" else min(2, len(chunk))

            native.setattr(os, "write", writer)

            def action():
                return payload._write_all(descriptor, b"payload")

        error = observed_error(action)
        return dict(error=error, value=value, events=fs.events)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("case", ("payload-changed-after-proof", "named-stream"))
def test_original_stage_additional_errors(role, case, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/windows_stage_extra_v1.json").read_text()
    )
    assert observe_stage(role, case, monkeypatch) == expected[role + ":" + case]


@pytest.mark.parametrize("case", IO_CASES)
def test_original_stage_byte_boundaries(case, monkeypatch):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/windows_stage_extra_v1.json").read_text()
    )
    assert observe_bytes(case, monkeypatch) == expected[case]
