"""Fixed original descriptor custody and controlled cancellation observations.

Explicit local validation; this module has no capture path or default PR route.
Native IO is real. Runtime/model/provider activation is outside this probe.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import stat
import threading
from contextlib import suppress
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS

import pytest

from loushang.coding import continuity as product
from loushang.harness.continuity import (
    CONTINUITY_BUNDLE_MEDIA_TYPE,
    CONTINUITY_JSONL_MEDIA_TYPE,
    ContinuityActivationPayload,
)

OBSERVATIONS = json.loads(
    (
        Path(__file__).parent / "fixtures" / "continuity_payload_custody_v1.json"
    ).read_text()
)["observations"]


@pytest.fixture
def tmp_path():
    """Strict private input ancestors; managed pytest runtime/lease is unchanged.

    Can be loaded explicitly as a local plugin for the original Bridge tests.
    Workspace mode0775 cannot be an admitted Continuity source ancestor.
    """
    with TemporaryDirectory(prefix="loushang-continuity-custody-") as raw:
        yield Path(raw)


CASES = (
    "valid",
    "zip",
    "existing-root",
    "normalize-root-mode",
    "sticky-root",
    "writable-root",
    "root-link",
    "ancestor-link",
    "root-owner",
    "root-reparse",
    "root-identity",
    "unsupported",
    "collision-retry",
    "exhaustion",
    "short-write",
    "zero-write",
    "write-error",
    "fsync-error",
    "fchmod-file-error",
    "fstat-file-error",
    "write-error-replaced",
    "write-error-missing",
    "write-close-file-error",
    "write-close-both-error",
    "remove-missing",
    "remove-replaced",
    "remove-symlink",
    "remove-root-identity",
    "remove-root-renamed",
    "remove-stat-error",
    "remove-unlink-error",
    "remove-close-file",
    "remove-close-root",
    "remove-close-both",
    "remove-reparse",
    "async-success",
    "async-cancel-success",
    "async-cancel-repeat",
    "async-cancel-write-error",
    "async-done-error",
    "async-cancel-cleanup-error",
    "async-remove-cancel",
    "async-remove-error",
)
ACCEPTED = {
    "valid",
    "zip",
    "existing-root",
    "normalize-root-mode",
    "sticky-root",
    "collision-retry",
    "short-write",
    "remove-missing",
    "remove-root-renamed",
    "async-success",
}


def error_graph(exc, normalize, seen=None):
    if exc is None:
        return None
    seen = {} if seen is None else seen
    if id(exc) in seen:
        return {"ref": seen[id(exc)]}
    seen[id(exc)] = len(seen)
    return {
        "id": seen[id(exc)],
        "type": type(exc).__name__,
        "message": normalize(str(exc)),
        "notes": [normalize(n) for n in getattr(exc, "__notes__", [])],
        "suppress": exc.__suppress_context__,
        "cause": error_graph(exc.__cause__, normalize, seen),
        "context": error_graph(exc.__context__, normalize, seen),
    }


def changed(metadata, **changes):
    return NS(
        **{
            **{k: getattr(metadata, k) for k in dir(metadata) if k.startswith("st_")},
            **changes,
        }
    )


def observe(case, base, patch):
    root = base / "payload"
    token = "f" * 32
    name = f"continuity-{token}.jsonl"
    if case in {
        "existing-root",
        "normalize-root-mode",
        "sticky-root",
        "writable-root",
        "exhaustion",
        "collision-retry",
    }:
        root.mkdir(mode=0o700)
    if case == "normalize-root-mode":
        root.chmod(0o755)
    if case == "sticky-root":
        root.chmod(0o1777)
    if case == "writable-root":
        root.chmod(0o777)
    if case == "root-link":
        actual = base / "actual"
        actual.mkdir(mode=0o700)
        root.symlink_to(actual, target_is_directory=True)
    if case == "ancestor-link":
        actual = base / "actual"
        actual.mkdir(mode=0o700)
        alias = base / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        root = alias / "payload"
    if case in {"exhaustion", "collision-retry"}:
        (root / name).write_bytes(b"unowned")
    token_calls = 0

    def next_token(_size):
        nonlocal token_calls
        token_calls += 1
        return "e" * 32 if case == "collision-retry" and token_calls > 1 else token

    patch.setattr(secrets, "token_hex", next_token)
    payload = ContinuityActivationPayload.from_bytes(
        b"fixed payload bytes\n",
        media_type=CONTINUITY_BUNDLE_MEDIA_TYPE
        if case == "zip"
        else CONTINUITY_JSONL_MEDIA_TYPE,
    )
    real_open, real_close, real_fstat, real_stat = os.open, os.close, os.fstat, os.stat
    real_write, real_sync, real_chmod, real_unlink = (
        os.write,
        os.fsync,
        os.fchmod,
        os.unlink,
    )
    trace = []
    active = {}
    counter = 0
    phase = "write"
    root_stats = 0
    write_calls = 0
    entered = threading.Event()
    release = threading.Event()

    def normalize(value):
        return value.replace(str(base), "<ROOT>")

    def opened(path, flags, *args, **kwargs):
        nonlocal counter
        parent = active.get(kwargs.get("dir_fd"))
        selected = parent is not None or str(path) == str(root)
        if selected:
            trace.append(
                [
                    "open",
                    normalize(str(path)),
                    flags,
                    list(args),
                    None if parent is None else parent[0],
                ]
            )
        fd = real_open(path, flags, *args, **kwargs)
        if selected:
            counter += 1
            active[fd] = (f"fd{counter}", "root" if parent is None else "file")
        return fd

    def fstat(fd):
        value = real_fstat(fd)
        if fd not in active:
            return value
        label, kind = active[fd]
        trace.append(["fstat", label])
        if kind == "root" and phase == "write":
            if case == "root-owner":
                return changed(value, st_uid=value.st_uid + 1)
            if case == "root-reparse":
                return changed(value, st_reparse_tag=1)
        if kind == "root" and phase == "remove" and case == "remove-root-identity":
            return changed(value, st_ino=value.st_ino + 1)
        if kind == "file" and phase == "write" and case == "fstat-file-error":
            raise OSError("injected file fstat")
        return value

    def stat_path(path, *args, **kwargs):
        nonlocal root_stats
        parent = active.get(kwargs.get("dir_fd"))
        if parent:
            trace.append(
                ["stat", parent[0], str(path), kwargs.get("follow_symlinks", True)]
            )
            if phase == "remove" and case == "remove-stat-error":
                raise OSError("injected named stat")
        value = real_stat(path, *args, **kwargs)
        if str(path) == str(root) and not kwargs.get("follow_symlinks", True):
            root_stats += 1
            if case == "root-identity" and root_stats == 2:
                return changed(value, st_ino=value.st_ino + 1)
        if parent and phase == "remove" and case == "remove-reparse":
            return changed(value, st_reparse_tag=1)
        return value

    def write(fd, body):
        nonlocal write_calls
        if fd not in active:
            return real_write(fd, body)
        label, kind = active[fd]
        trace.append(["write", label, len(body)])
        write_calls += 1
        if case in {
            "async-cancel-success",
            "async-cancel-repeat",
            "async-cancel-write-error",
            "async-cancel-cleanup-error",
        }:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("probe did not release write")
        if case == "short-write":
            return real_write(fd, body[:3])
        if case == "zero-write":
            return 0
        if case in {"write-error-replaced", "write-error-missing"}:
            real_unlink(root / name)
            if case == "write-error-replaced":
                (root / name).write_bytes(b"replacement")
        if case in {
            "write-error",
            "write-error-replaced",
            "write-error-missing",
            "write-close-file-error",
            "write-close-both-error",
            "async-cancel-write-error",
            "async-done-error",
        }:
            raise OSError("injected payload write")
        return real_write(fd, body)

    def sync(fd):
        if fd in active:
            trace.append(["fsync", active[fd][0]])
            if case == "fsync-error":
                raise OSError("injected payload fsync")
        return real_sync(fd)

    def chmod(fd, mode):
        if fd in active:
            trace.append(["fchmod", active[fd][0], mode])
            if active[fd][1] == "file" and case == "fchmod-file-error":
                raise OSError("injected payload fchmod")
        return real_chmod(fd, mode)

    def unlink(path, *args, **kwargs):
        parent = active.get(kwargs.get("dir_fd"))
        if parent:
            trace.append(["unlink", parent[0], str(path)])
            if case == "async-remove-cancel":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("probe did not release unlink")
            if case in {
                "remove-unlink-error",
                "async-cancel-cleanup-error",
                "async-remove-error",
            }:
                raise OSError("injected payload unlink")
        return real_unlink(path, *args, **kwargs)

    def close(fd):
        if fd in active:
            label, kind = active[fd]
            trace.append(["close", label])
            if (
                kind == "file"
                and case
                in {
                    "write-close-file-error",
                    "write-close-both-error",
                    "remove-close-file",
                    "remove-close-both",
                }
            ) or (
                kind == "root"
                and case
                in {"write-close-both-error", "remove-close-root", "remove-close-both"}
            ):
                raise OSError("injected close " + kind)
        real_close(fd)
        active.pop(fd, None)

    patch.setattr(os, "open", opened)
    patch.setattr(os, "fstat", fstat)
    patch.setattr(os, "stat", stat_path)
    patch.setattr(os, "write", write)
    patch.setattr(os, "fsync", sync)
    patch.setattr(os, "fchmod", chmod)
    patch.setattr(os, "unlink", unlink)
    patch.setattr(os, "close", close)
    patch.setattr(
        os,
        "supports_dir_fd",
        set()
        if case == "unsupported"
        else os.supports_dir_fd | {opened, stat_path, unlink},
    )

    def stage_info(staged):
        root_meta, file_meta = (
            real_fstat(staged.root_descriptor),
            real_fstat(staged.file_descriptor),
        )
        return {
            "path": normalize(str(staged.path)),
            "fields": [f.name for f in fields(staged)],
            "fileIdentity": staged.file_identity
            == (file_meta.st_dev, file_meta.st_ino),
            "rootIdentity": staged.root_identity
            == (root_meta.st_dev, root_meta.st_ino),
            "fileMode": stat.S_IMODE(file_meta.st_mode),
            "rootMode": stat.S_IMODE(root_meta.st_mode),
            "rootInheritable": os.get_inheritable(staged.root_descriptor),
            "fileInheritable": os.get_inheritable(staged.file_descriptor),
            "data": staged.path.read_bytes().decode(),
        }

    info = None

    async def asynchronous():
        nonlocal phase, info
        if case in {"async-remove-cancel", "async-remove-error"}:
            staged = product._write_private_continuity_payload(root, payload)
            info = stage_info(staged)
            phase = "remove"
            task = asyncio.create_task(
                product._remove_private_continuity_payload_atomic(staged)
            )
        else:
            if case == "async-done-error":
                shield = asyncio.shield
                first = True

                def cancel_on_completion(work):
                    nonlocal first
                    result = shield(work)
                    if first:
                        first = False
                        caller = asyncio.current_task()
                        result.add_done_callback(
                            lambda _future: caller.cancel("done-cancel")
                        )
                    return result

                patch.setattr(asyncio, "shield", cancel_on_completion)
            task = asyncio.create_task(
                product._write_private_continuity_payload_atomic(root, payload)
            )
        if case in {
            "async-cancel-success",
            "async-cancel-repeat",
            "async-cancel-write-error",
            "async-cancel-cleanup-error",
            "async-remove-cancel",
        }:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel("first-cancel")
            await asyncio.sleep(0)
            if case == "async-cancel-repeat":
                task.cancel("second-cancel")
                await asyncio.sleep(0)
            release.set()
        staged = await task
        if case == "async-success":
            info = stage_info(staged)
            phase = "remove"
            await product._remove_private_continuity_payload_atomic(staged)

    try:
        try:
            if case.startswith("async-"):
                asyncio.run(asynchronous())
            else:
                staged = product._write_private_continuity_payload(root, payload)
                info = stage_info(staged)
                phase = "remove"
                if case == "remove-missing":
                    real_unlink(staged.path)
                if case in {"remove-replaced", "remove-symlink"}:
                    real_unlink(staged.path)
                    if case == "remove-replaced":
                        staged.path.write_bytes(b"replacement")
                    else:
                        staged.path.symlink_to(base / "unowned-target")
                if case == "remove-root-renamed":
                    root.rename(base / "moved")
                    root.mkdir(mode=0o700)
                    (root / name).write_bytes(b"unowned new root")
                product._remove_private_continuity_payload(staged)
            error = None
        except BaseException as exc:
            error = error_graph(exc, normalize)
        remaining = {}
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                remaining[str(path.relative_to(base))] = "symlink"
            elif path.is_file():
                remaining[str(path.relative_to(base))] = path.read_bytes().decode()
        return {
            "info": info,
            "error": error,
            "trace": trace,
            "remaining": remaining,
            "outstanding": [label for label, _kind in active.values()],
            "tokens": token_calls,
        }
    finally:
        release.set()
        for fd in tuple(active):
            with suppress(OSError):
                real_close(fd)
        active.clear()


@pytest.mark.parametrize("case", CASES)
def test_original_payload_custody(case, tmp_path, monkeypatch):
    actual = observe(case, tmp_path, monkeypatch)
    assert (actual["error"] is None) == (case in ACCEPTED), actual
    assert actual == OBSERVATIONS[case]
