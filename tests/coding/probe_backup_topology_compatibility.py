"""Explicit fixed original topology custody observations, outside default discovery.

POSIX RootedFileIO, file bytes and descriptors are real. Product epoch, GC and
admission are controlled. Windows uses the actual receipt object with controlled
methods; its native ACL/stage implementation is covered by the existing receipt
probe, not proved here. Interruptions are synchronous KeyboardInterrupt or
CancelledError injection, not Task.cancel. Raw original observations are retained
outside Product. Expectations are immutable; this module has no capture mode.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import inspect
import json
import os
import pickle
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_backup_types as code
from loushang.coding.package_legacy_windows_receipt import _receipt_io
from loushang.harness.journal import _rooted_io
from loushang.harness.resources.packages.plugin_lifecycle import windows_quarantine

POSIX = (
    "new",
    "exact",
    "readonly-missing",
    "worker-lower",
    "worker-upper",
    "unknown",
    "scan-incomplete",
    "scan-error",
    "bad-scope",
    "wrong-bytes",
    "newline",
    "too-large",
    "file-mode",
    "file-symlink",
    "parent-mode",
    "parent-missing",
    "parent-identity",
    "parent-owner",
    "parent-type",
    "parent-open",
    "stale-first",
    "stale-last",
    "read-error",
    "interrupt",
    "cancel-exception",
    "create-before",
    "create-after",
    "read-after",
    "create-race",
    "fsync-after",
    "close-after",
    "cleanup-after",
    "body-and-cleanup",
    "write-zero",
    "write-short",
    "wrong-epoch",
    "changed-kinds",
    "existing-worker",
    "readonly-exact",
)
WINDOWS = (
    "new",
    "exact",
    "readonly-missing",
    "worker-lower",
    "worker-upper",
    "unknown",
    "wrong-bytes",
    "newline",
    "too-large",
    "bad-scope",
    "stale-first",
    "stale-last",
    "read-error",
    "write-error",
    "write-after",
    "read-after",
    "borrow-enter",
    "borrow-exit",
    "body-and-exit",
    "interrupt",
    "cancel-exception",
    "changed-kinds",
    "stage-exact",
    "stage-conflict",
    "existing-worker",
)
PUBLIC = (
    "ensure-new",
    "ensure-before-load",
    "ensure-admission-first",
    "ensure-admission-second",
    "ensure-gate-type",
    "ensure-guard-exit",
    "arch",
    "arch-denied",
    "worker",
    "worker-kind",
    "worker-attempt",
    "worker-product",
    "worker-current",
    "worker-readonly",
)
CASES = (
    tuple("posix:" + c for c in POSIX)
    + tuple("windows:" + c for c in WINDOWS)
    + tuple("public:" + c for c in PUBLIC)
)


def observe(name, base, patch):
    platform, case = name.split(":")
    base.chmod(0o700)
    root = base / "root"
    root.mkdir(mode=0o700)
    path = root / code._FILE_NAME
    expected = code._topology_bytes("scope")
    trace = []
    outputs = []
    phase = "seed"
    fired = False
    epoch_count = 0
    read_count = 0
    admission_count = 0
    owned = {}
    descriptor_sequence = 0
    original_open, original_close, original_dup = os.open, os.close, os.dup
    original_fstat, original_write, original_fsync = os.fstat, os.write, os.fsync
    original_lstat = Path.lstat
    original_read = _rooted_io.RootedFile.read_bytes
    original_create = _rooted_io.RootedFile.create_new
    original_scan = _rooted_io.RootedFile.scan_sibling_names
    original_cleanup = _rooted_io.RootedFileIO.cleanup

    exact_cases = {
        "exact",
        "readonly-exact",
        "stale-first",
        "stale-last",
        "read-error",
        "interrupt",
        "cancel-exception",
        "close-after",
        "cleanup-after",
        "body-and-cleanup",
        "body-and-exit",
        "borrow-enter",
        "borrow-exit",
        "changed-kinds",
        "existing-worker",
    }
    if (
        case in exact_cases
        or platform == "public"
        and case not in {"ensure-new", "ensure-before-load"}
    ):
        path.write_bytes(expected)
        path.chmod(0o600)
    if case in {"wrong-bytes", "newline", "too-large", "file-mode"}:
        path.write_bytes(
            {
                "wrong-bytes": b"{}",
                "newline": expected + b"\n",
                "too-large": b"x" * 4097,
                "file-mode": expected,
            }[case]
        )
        path.chmod(0o644 if case == "file-mode" else 0o600)
    if case == "file-symlink":
        (root / "target").write_bytes(expected)
        path.symlink_to("target")
    if case in {"worker-lower", "worker-upper", "existing-worker"}:
        (
            root / ("Worker-history" if case == "worker-upper" else "worker-history")
        ).write_bytes(b"history")
    if case == "unknown":
        (root / "other").write_bytes(b"unrelated")
    if case in {"stage-exact", "stage-conflict"}:
        (root / (code._FILE_NAME + ".stage")).write_bytes(
            expected if case == "stage-exact" else b"conflict"
        )
    if case == "parent-mode":
        root.chmod(0o755)
    if case == "parent-missing":
        root.rmdir()

    def norm(value):
        if isinstance(value, str):
            return value.replace(str(base), "<ROOT>")
        if isinstance(value, (list, tuple)):
            return [norm(v) for v in value]
        if isinstance(value, dict):
            return {str(k): norm(v) for k, v in value.items()}
        if dataclasses.is_dataclass(value):
            return {
                "type": type(value).__qualname__,
                "module": type(value).__module__,
                "fields": {
                    f.name: norm(getattr(value, f.name))
                    for f in dataclasses.fields(value)
                },
            }
        return value

    def error_graph(exc, seen=None):
        if exc is None:
            return None
        seen = {} if seen is None else seen
        if id(exc) in seen:
            return {"ref": seen[id(exc)]}
        seen[id(exc)] = len(seen)
        return {
            "id": seen[id(exc)],
            "type": type(exc).__name__,
            "message": norm(str(exc)),
            "suppress": exc.__suppress_context__,
            "notes": getattr(exc, "__notes__", []),
            "cause": error_graph(exc.__cause__, seen),
            "context": error_graph(exc.__context__, seen),
        }

    def fault():
        nonlocal fired
        fired = True
        trace.append(["fault", case])
        if case == "interrupt":
            raise KeyboardInterrupt("injected topology interruption")
        if case == "cancel-exception":
            raise asyncio.CancelledError("injected synchronous cancellation")
        raise OSError("injected " + case)

    def inject(*cases):
        return phase == "first" and case in cases and not fired

    class PosixEpoch(code.PackageProductPosixFencedRuntimeOwner):
        def __init__(self):
            pass

        def assert_current(self):
            nonlocal epoch_count
            epoch_count += 1
            trace.append(["epoch", epoch_count])
            if (
                inject("stale-first")
                and epoch_count == 1
                or inject("stale-last")
                and epoch_count == 2
            ):
                fault()

    class WindowsEpoch(code.PackageProductWindowsFencedRuntimeOwner):
        def __init__(self):
            pass

        assert_current = PosixEpoch.assert_current

        @contextmanager
        def borrow_product_state_root_descriptor(self):
            trace.append(["borrow-enter"])
            if inject("borrow-enter"):
                fault()
            fd = original_open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                yield fd
            finally:
                original_close(fd)
                trace.append(["borrow-exit"])
                if phase == "first" and case == "body-and-exit":
                    raise OSError("injected borrow exit after body")
                if inject("borrow-exit"):
                    fault()

    epoch = WindowsEpoch() if platform == "windows" else PosixEpoch()
    if case == "wrong-epoch":
        epoch = NS(assert_current=PosixEpoch().assert_current)

    def opened(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal descriptor_sequence
        related = str(name).startswith(str(root)) or dir_fd in owned
        if related:
            trace.append(["open", norm(str(name)), flags, mode, owned.get(dir_fd)])
            if str(name) == str(root) and inject("parent-open"):
                fault()
        fd = original_open(name, flags, mode, dir_fd=dir_fd)
        if related:
            descriptor_sequence += 1
            owned[fd] = "fd" + str(descriptor_sequence)
        return fd

    def dup(fd):
        nonlocal descriptor_sequence
        new = original_dup(fd)
        if fd in owned:
            descriptor_sequence += 1
            trace.append(["dup", owned[fd], "fd" + str(descriptor_sequence)])
            owned[new] = "fd" + str(descriptor_sequence)
        return new

    def closed(fd):
        label = owned.pop(fd, None)
        if label is not None:
            trace.append(["close", label])
        original_close(fd)
        if label == "fd1" and inject("close-after"):
            fault()

    def fstat(fd):
        value = original_fstat(fd)
        if owned.get(fd) == "fd1" and inject(
            "parent-identity", "parent-owner", "parent-type"
        ):
            fields = list(value)
            if case == "parent-identity":
                fields[1] += 1
            elif case == "parent-owner":
                fields[4] += 1
            else:
                fields[0] = stat.S_IFREG | 0o600
            return os.stat_result(fields)
        return value

    def read(self, *, max_bytes=None, **kwargs):
        nonlocal read_count
        read_count += 1
        trace.append(["read", max_bytes, read_count])
        if (
            inject("read-error", "interrupt", "cancel-exception", "body-and-cleanup")
            or inject("read-after")
            and read_count == 2
        ):
            fault()
        return original_read(self, max_bytes=max_bytes, **kwargs)

    def scan(self, *, limit):
        trace.append(["scan", limit])
        if inject("scan-error"):
            fault()
        names, complete = original_scan(self, limit=limit)
        return (names, False) if inject("scan-incomplete") else (names, complete)

    def create(self, data):
        trace.append(["create", data.hex()])
        if inject("create-before"):
            fault()
        if inject("create-race"):
            path.write_bytes(expected)
            path.chmod(0o600)
        value = original_create(self, data)
        if inject("create-after"):
            fault()
        return value

    def cleanup(self):
        trace.append(["cleanup"])
        original_cleanup(self)
        if inject("cleanup-after") or phase == "first" and case == "body-and-cleanup":
            raise OSError("injected cleanup after close")

    def write(fd, data):
        if fd in owned:
            if inject("write-zero"):
                trace.append(["write-zero"])
                return 0
            if case == "write-short":
                trace.append(["write-short", len(data)])
                return original_write(fd, data[: max(1, len(data) // 2)])
        return original_write(fd, data)

    def fsync(fd):
        original_fsync(fd)
        if fd in owned and inject("fsync-after"):
            fault()

    def windows_read(self, target, *, maximum_bytes, allow_unpublished_stage=False):
        nonlocal read_count
        assert self is _receipt_io
        read_count += 1
        trace.append(
            ["windows-read", maximum_bytes, allow_unpublished_stage, read_count]
        )
        if (
            inject("read-error", "interrupt", "cancel-exception", "body-and-exit")
            or inject("read-after")
            and read_count == 2
        ):
            fault()
        stage = target.with_name(target.name + ".stage")
        if not allow_unpublished_stage and stage.exists():
            raise self.error_type(
                "Windows Product unpublished receipt stage is present"
            )
        if not target.exists():
            return None
        raw = target.read_bytes()
        if len(raw) > maximum_bytes:
            raise self.error_type("controlled Windows receipt exceeds bound")
        return raw

    def windows_write(self, target, payload, *, maximum_bytes):
        assert self is _receipt_io
        trace.append(["windows-write", maximum_bytes, payload.hex()])
        if inject("write-error"):
            fault()
        stage = target.with_name(target.name + ".stage")
        if stage.exists():
            if stage.read_bytes() != payload:
                raise self.error_type("controlled Windows stage differs")
            stage.rename(target)
        else:
            target.write_bytes(payload)
        if inject("write-after"):
            fault()

    def windows_list(fd):
        trace.append(["windows-list"])
        return tuple(sorted(os.listdir(fd)))

    patch.setattr(os, "open", opened)
    patch.setattr(os, "close", closed)
    patch.setattr(os, "dup", dup)
    patch.setattr(os, "fstat", fstat)
    patch.setattr(os, "write", write)
    patch.setattr(os, "fsync", fsync)
    patch.setattr(_rooted_io.RootedFile, "read_bytes", read)
    patch.setattr(_rooted_io.RootedFile, "create_new", create)
    patch.setattr(_rooted_io.RootedFile, "scan_sibling_names", scan)
    patch.setattr(_rooted_io.RootedFileIO, "cleanup", cleanup)
    patch.setattr(type(_receipt_io), "read_private_receipt", windows_read)
    patch.setattr(type(_receipt_io), "write_private_receipt", windows_write)
    patch.setattr(windows_quarantine, "windows_listdir_at", windows_list)
    if case in {"changed-kinds", "worker-kind"}:
        patch.setattr(
            code, "_SUPPORTED_BACKUP_KINDS", ("arch_private_data", "worker_attempt")
        )
        if case == "worker-kind":
            path.write_bytes(code._topology_bytes("scope"))
    if case == "arch-denied":
        patch.setattr(code, "_SUPPORTED_BACKUP_KINDS", ())
        path.write_bytes(code._topology_bytes("scope"))

    class Gate(code.PluginPackageGcReservationJournal):
        def __init__(self):
            pass

        @contextmanager
        def guard(self, *, before_load=None, require_write=False):
            trace.append(["gc-enter", require_write])
            if before_load is not None:
                before_load()
            try:
                yield
            finally:
                trace.append(["gc-exit"])
                if inject("ensure-guard-exit"):
                    fault()

        @contextmanager
        def read_guard(self):
            trace.append(["gc-read-enter"])
            try:
                yield
            finally:
                trace.append(["gc-read-exit"])

    gate = Gate()
    product = object.__new__(code.PosixLocalWheelProductSessionOwner)
    for key, value in {
        "policy": NS(
            product_id="other" if case == "worker-product" else "coding",
            project_scope_id="scope",
        ),
        "state_root": root,
        "epoch_runtime": epoch,
        "gc_gate": gate,
    }.items():
        object.__setattr__(product, key, value)

    def current(self):
        assert self is product
        trace.append(["product-current"])
        if inject("worker-current"):
            fault()

    patch.setattr(
        code.PosixLocalWheelProductSessionOwner,
        "assert_root_gc_authority_current",
        current,
    )

    def admit():
        nonlocal admission_count
        admission_count += 1
        trace.append(["admission", admission_count])
        if (
            inject("ensure-admission-first")
            and admission_count == 1
            or inject("ensure-admission-second")
            and admission_count == 2
        ):
            fault()

    def before_load():
        trace.append(["before-load"])

    def tree():
        rows = {}
        if root.exists():
            for item in [root, *sorted(root.iterdir())]:
                metadata = original_lstat(item)
                row = {"mode": stat.S_IMODE(metadata.st_mode)}
                if stat.S_ISREG(metadata.st_mode):
                    row["bytes"] = item.read_bytes().hex()
                if item.is_symlink():
                    row["link"] = os.readlink(item)
                rows["." if item == root else item.name] = row
        return rows

    for phase in ("first", "retry"):
        epoch_count = read_count = admission_count = 0
        descriptor_sequence = 0
        trace.append(["call", phase])
        try:
            if platform == "public":
                if case.startswith("ensure-"):
                    value = code.ensure_coding_product_backup_types(
                        state_root=root,
                        scope_id="scope",
                        epoch_runtime=epoch,
                        gc_gate=object() if case == "ensure-gate-type" else gate,
                        before_load=before_load
                        if case == "ensure-before-load"
                        else None,
                        require_current_admission=admit,
                    )
                elif case.startswith("arch"):
                    value = code.require_coding_arch_backup_writer(product)
                else:
                    if case == "worker-readonly":
                        path.unlink(missing_ok=True)
                    value = code.observe_coding_worker_backup_references_under_gc_guard(
                        product,
                        attempt_id="invalid" if case == "worker-attempt" else "a" * 32,
                    )
            else:
                value = code._read_topology(
                    state_root=root,
                    scope_id="" if case == "bad-scope" else "scope",
                    epoch_runtime=epoch,
                    create_if_new=case not in {"readonly-missing", "readonly-exact"},
                )
            outputs.append(
                {
                    "phase": phase,
                    "value": norm(value),
                    "error": None,
                    "tree": tree(),
                    "open_fds": sorted(owned.values()),
                }
            )
        except BaseException as exc:
            outputs.append(
                {
                    "phase": phase,
                    "value": None,
                    "error": error_graph(exc),
                    "tree": tree(),
                    "open_fds": sorted(owned.values()),
                }
            )
    # All injected close failures happen after real close; a leak is never repaired here.
    assert not owned, owned
    return {"outputs": outputs, "trace": norm(trace)}


def reflect():
    cls = code.CodingWorkerBackupReferenceObservationV1
    value = cls("a" * 32, "coding-product-backup-types:" + "b" * 64, False, ())
    return {
        "module": cls.__module__,
        "qualname": cls.__qualname__,
        "signature": str(inspect.signature(cls)),
        "annotations": cls.__annotations__,
        "slots": list(cls.__slots__),
        "fields": [f.name for f in dataclasses.fields(cls)],
        "repr": repr(value),
        "pickle_identity": type(pickle.loads(pickle.dumps(value))) is cls,
        "value": dataclasses.asdict(value),
    }


FIXED = json.loads(
    (Path(__file__).parent / "fixtures" / "backup_topology_v1.json").read_text()
)
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="fixed original POSIX topology IO and controlled Windows observation",
)


@pytest.mark.parametrize("case", CASES)
def test_original_backup_topology_custody(case, tmp_path, monkeypatch):
    actual = observe(case, tmp_path, monkeypatch)
    fingerprint = hashlib.sha256(
        json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert fingerprint == FIXED["observations"][case]["sha256"], actual


def test_original_backup_topology_observation_identity():
    actual = json.loads(json.dumps(reflect()))
    assert actual == FIXED["reflection"]
