"""Frozen Windows journal IO results using inert native calls and real local FDs.

These probes exercise file custody, not Product admission or native Windows ACLs.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

KINDS = ("native_approval", "opt_in", "receipt", "supervisor", "activation_state")
CLASSES = (
    "CodingWindowsWorkerNativeApprovalJournal",
    "CodingWindowsWorkerOptInJournal",
    "CodingWindowsWorkerReceiptJournal",
    "CodingWindowsProductWorkerSupervisorJournal",
    "CodingWindowsWorkerActivationStateJournal",
)
CASES = (
    "read:missing",
    "read:present",
    "read:oversize",
    "read:stream",
    "read:acl",
    "append:new",
    "append:match",
    "append:empty_expected",
    "append:conflict",
    "append:partial",
    "append:none",
    "append:zero",
    "append:write_error",
    "append:file_flush",
    "append:dir_flush",
    "append:stream",
    "prepare:new",
    "prepare:existing",
    "prepare:bad_size",
    "prepare:missing_lock",
    "prepare:stream",
    "prepare:short_marker",
    "prepare:file_flush",
    "prepare:dir_flush",
    "validate:zero",
    "validate:one",
    "validate:bad_marker",
    "validate:bad_size",
    "validate:identity",
    "validate:stream",
    "validate:acl",
    "mark:zero",
    "mark:one",
    "mark:none",
    "mark:zero_write",
    "mark:file_flush",
)
FIXTURE = Path(__file__).with_name("fixtures") / "worker_windows_journal_io_v1.json"


def observe(kind, case, root, monkeypatch):
    module = importlib.import_module(
        f"loushang.coding.package_product_worker_windows_{kind}_journal"
    )
    # The new shared adapter is patched at its actual native boundary too.
    # Original fixtures are generated before that module exists.
    native_name = "loushang.harness.resources.packages._windows_journal_file"
    backend = (
        importlib.import_module(native_name)
        if importlib.util.find_spec(native_name)
        else None
    )
    operation, fault = case.split(":")
    root.mkdir(mode=0o700)
    name, lock_name = module._NAME, module._NAME + ".lock"
    path, lock_path = root / name, root / lock_name
    if operation == "read" and fault != "missing":
        path.write_bytes(b"0123456789" if fault == "oversize" else b"prior")
    if operation == "append" and fault in {"match", "conflict"}:
        path.write_bytes(b"prior")
    if operation == "prepare" and fault == "missing_lock":
        path.write_bytes(b"prior")
    if operation in {"validate", "mark"} or (
        operation == "prepare" and fault in {"existing", "bad_size"}
    ):
        marker = (
            b"\1"
            if fault == "one"
            else b"x"
            if fault == "bad_marker"
            else b"xx"
            if fault == "bad_size"
            else b"\0"
        )
        lock_path.write_bytes(marker)
    trace, opened_fds = [], []
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    borrowed = None

    class ACL:
        security_descriptor = 123

        def validate(self, descriptor):
            trace.append(["acl"])
            if fault == "acl":
                raise PermissionError("fixture ACL denied")

    class File:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            trace.append(["handle_close"])
            return self.handle.__exit__(*args)

        def fileno(self):
            return self.handle.fileno()

        def seek(self, offset, whence=os.SEEK_SET):
            trace.append(["seek", offset, whence])
            return self.handle.seek(offset, whence)

        def read(self, size):
            trace.append(["read", size])
            return self.handle.read(size)

        def write(self, data):
            trace.append(["write", bytes(data).hex()])
            if fault == "none":
                return None
            if fault in {"zero", "zero_write"}:
                return 0
            if fault == "write_error":
                raise OSError("fixture write failure")
            return self.handle.write(data[:1] if fault == "partial" else data)

        def flush(self):
            trace.append(["buffer_flush"])
            return self.handle.flush()

    def opened(
        directory_fd,
        component,
        *,
        create_new,
        write,
        security_descriptor=None,
        read_control=False,
    ):
        assert directory_fd == root_fd
        trace.append(
            ["open", component, create_new, write, security_descriptor, read_control]
        )
        flags = os.O_RDWR if write else os.O_RDONLY
        if create_new:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor = os.open(component, flags, 0o600, dir_fd=directory_fd)
        opened_fds.append(descriptor)
        return descriptor

    def closed(descriptor):
        trace.append(["close"])
        return os.close(descriptor)

    def wrapped(descriptor, mode, *, closefd=True):
        if fault == "fdopen_failure":
            raise OSError("fixture file-wrapper failure")
        return File(os.fdopen(descriptor, mode, closefd=closefd))

    def fstat(descriptor):
        trace.append(["fstat"])
        return os.fstat(descriptor)

    def named(directory_fd, component):
        trace.append(["stat", component])
        value = os.stat(component, dir_fd=directory_fd, follow_symlinks=False)
        if fault == "identity":
            fields = list(value)
            fields[1] += 1
            return os.stat_result(fields)
        return value

    def streams(descriptor):
        trace.append(["streams"])
        return ("::$DATA", ":extra:$DATA") if fault == "stream" else ("::$DATA",)

    def flush_file(descriptor):
        trace.append(["file_flush"])
        if fault == "file_flush":
            raise OSError("fixture file flush failure")
        os.fsync(descriptor)

    def flush_directory(descriptor):
        trace.append(["dir_flush"])
        if fault == "dir_flush":
            raise OSError("fixture directory flush failure")
        os.fsync(descriptor)

    def marker_write(descriptor, data):
        trace.append(["marker_write", data.hex()])
        return 0 if fault == "short_marker" else os.write(descriptor, data)

    def listdir(descriptor):
        trace.append(["list"])
        return os.listdir(descriptor)

    class Product:
        state_root = root
        policy = SimpleNamespace(product_id="coding")

        def assert_root_gc_authority_current(self):
            pass

    namespace = SimpleNamespace(**vars(os))
    namespace.name = "nt"
    namespace.close, namespace.fdopen, namespace.fstat = closed, wrapped, fstat
    namespace.write = marker_write
    try:
        with monkeypatch.context() as patch:
            targets = [module] + ([backend] if backend else [])
            if kind in {"supervisor", "activation_state"}:
                targets.append(
                    importlib.import_module(
                        "loushang.harness.worker.history._windows_product_journals"
                    )
                )
            if backend:
                targets.append(
                    importlib.import_module(
                        "loushang.harness.resources.packages._file_consumption"
                    )
                )
            for target in targets:
                for attr, value in {
                    "open_windows_regular_file_at": opened,
                    "windows_stat_at": named,
                    "windows_regular_file_stream_names": streams,
                    "windows_flush_file": flush_file,
                    "windows_flush_directory": flush_directory,
                }.items():
                    if hasattr(target, attr):
                        patch.setattr(target, attr, value)
                patch.setattr(target, "os", namespace)
            for target in targets:
                if hasattr(target, "windows_listdir_at"):
                    patch.setattr(target, "windows_listdir_at", listdir)
            patch.setattr(module, "_MAX_BYTES", 8)
            cls = getattr(module, CLASSES[KINDS.index(kind)])
            if kind in {"supervisor", "activation_state"}:
                patch.setattr(module, "WindowsLocalWheelProductSessionOwner", Product)
                owner = cls(Product())
            else:
                owner = cls(path, scope_id="scope-a")
            io = getattr(owner, "_file_io", owner)
            acl = ACL()
            try:
                if operation == "read":
                    value = getattr(owner, "_read_raw", getattr(io, "read", None))(
                        root_fd, acl
                    )
                elif operation == "append":
                    expected = (
                        b"prior"
                        if fault == "match"
                        else b"foreign"
                        if fault == "conflict"
                        else b""
                        if fault == "empty_expected"
                        else None
                    )
                    value = getattr(owner, "_append", getattr(io, "append", None))(
                        root_fd,
                        acl,
                        expected=expected,
                        line=b"next\n",
                    )
                elif operation == "prepare":
                    value = owner._prepare_lock(root_fd, acl)
                elif operation == "validate":
                    borrowed = os.fdopen(os.open(lock_path, os.O_RDWR), "r+b")
                    wrapped_lock = File(borrowed)
                    if io is owner and kind == "activation_state":
                        value = owner._validate_lock(root_fd, acl, wrapped_lock)
                    else:
                        value = getattr(
                            owner, "_validate_lock", getattr(io, "validate_lock", None)
                        )(
                            root_fd,
                            acl,
                            locked_handle=wrapped_lock,
                        )
                else:
                    borrowed = os.fdopen(os.open(lock_path, os.O_RDWR), "r+b")
                    value = getattr(
                        owner,
                        "_mark_lock_initialized",
                        getattr(io, "mark_initialized", None),
                    )(File(borrowed))
                result = {"value": value.hex() if isinstance(value, bytes) else value}
            except BaseException as error:
                result = {
                    "error": type(error).__module__ + "." + type(error).__qualname__,
                    "message": str(error).replace(str(root), "$ROOT"),
                }
                if hasattr(error, "code"):
                    result["code"] = error.code
            borrowed_open = borrowed is not None and not borrowed.closed
    finally:
        if borrowed is not None:
            borrowed.close()
        os.close(root_fd)
    leaked = []
    for descriptor in opened_fds:
        try:
            os.fstat(descriptor)
        except OSError:
            pass
        else:
            leaked.append(descriptor)
            os.close(descriptor)
    return {
        "result": result,
        "trace": trace,
        "borrowed_open": borrowed_open,
        "leaked": len(leaked),
        "files": {
            child.name: child.read_bytes().hex() for child in sorted(root.iterdir())
        },
    }


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", CASES)
def test_original_windows_worker_file_contract(kind, case, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.read_text())
    prior = expected[f"{kind}:{case}"]
    # Original wrappers closed the FD implicitly. The shared owner keeps it
    # with closefd=False and explicitly closes it after closing the wrapper.
    # All original events, bytes, errors and leak assertions stay intact.
    trace = []
    for event in prior["trace"]:
        trace.append(event)
        if event == ["handle_close"]:
            trace.append(["close"])
    assert observe(kind, case, tmp_path / "state", monkeypatch) == {
        **prior,
        "trace": trace,
    }


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("operation", ("read", "append"))
def test_file_wrapper_failure_closes_the_new_native_descriptor(
    kind,
    operation,
    tmp_path,
    monkeypatch,
):
    case = operation + ":fdopen_failure"
    original = json.loads(
        FIXTURE.with_name("worker_windows_fdopen_failure_v1.json").read_text()
    )[f"{kind}:{case}"]
    # The original constructor failure leaked the newly opened descriptor.
    # This explicit bug fix adds exactly one close, leaving the original
    # exception, files and all other observations intact.
    assert original["leaked"] == 1
    expected = {**original, "leaked": 0, "trace": [*original["trace"], ["close"]]}
    assert observe(kind, case, tmp_path / "state", monkeypatch) == expected
