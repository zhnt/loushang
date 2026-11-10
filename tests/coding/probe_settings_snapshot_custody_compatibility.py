"""Real POSIX file/FD snapshot; Windows parent/native metadata ports are controlled."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_source_snapshot as code
import loushang.harness.config.store as core
import loushang.harness.resources.packages._file_consumption as consumption
import loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover as win_epoch
import loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine as win_io
from tests.coding.probe_windows_live_stage_verification_compatibility import Trace

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux disk-root settings snapshot model"
)

HERE = Path(__file__).parent
EXPECTED = HERE / "fixtures/settings_snapshot_custody_v1.json.gz"
FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_uid",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


def observe(spec, tmp_path, monkeypatch):
    root = tmp_path / "input"
    root.mkdir()
    path = root / "settings.json"
    bodies = {
        "valid": b'{"ok":true}\n',
        "duplicate": b'{"a":1,"a":2}',
        "nan": b'{"a":NaN}',
        "utf8": b"\xff",
        "array": b"[]",
        "empty": b"",
        "long": b'{"a":"' + b"x" * 70000 + b'"}',
    }
    body = bodies[spec.get("body", "valid")]
    kind = spec.get("input", "file")
    if kind == "directory":
        path.mkdir()
    elif kind != "missing":
        path.write_bytes(body)
        path.chmod(0o600)
        if kind == "symlink":
            path.rename(root / "target.json")
            path.symlink_to("target.json")
        elif kind == "hardlink":
            os.link(path, root / "other.json")
    anchor = None if kind == "missing" else path.lstat()
    original_lstat, native_open, native_close = Path.lstat, os.open, os.close
    native_read, native_fstat, native_seek, native_uid = (
        os.read,
        os.fstat,
        os.lseek,
        os.getuid,
    )
    original_json = json.loads
    original_consume = consumption.consume_file
    old_reader = not hasattr(core, "_read_stable_json_patch")
    consume_calls = 0
    trace = Trace(spec.get("faults", ()))
    owned, counts = {}, Counter()
    parent_closed = False
    platform = spec.get("platform", "posix")

    def event(*row):
        trace.append(list(row))

    def role(value):
        if value == str(path):
            return "@settings"
        if value == str(root):
            return "@parent"
        return value

    def data(v):
        if isinstance(v, bytes):
            return {"bytes": v.hex()}
        if isinstance(v, (tuple, list)):
            return [data(x) for x in v]
        if isinstance(v, str):
            return role(v)
        return v

    def error_data(error, seen=frozenset()):
        if error is None:
            return None
        if id(error) in seen:
            return {"cycle": True}
        seen = seen | {id(error)}
        return dict(
            type=f"{type(error).__module__}.{type(error).__qualname__}",
            args=data(error.args),
            filename=data(getattr(error, "filename", None)),
            filename2=data(getattr(error, "filename2", None)),
            notes=data(getattr(error, "__notes__", [])),
            cause=error_data(error.__cause__, seen),
            context=error_data(error.__context__, seen),
            suppress=error.__suppress_context__,
        )

    def metadata(value, phase):
        values = {f: getattr(value, f) for f in FIELDS}
        changed = spec.get("change")
        if changed and phase == spec.get("change_phase", "opened"):
            values[changed] += 1
        if spec.get("unsafe") == "owner" and phase == "before":
            values["st_uid"] += 1
        if spec.get("unsafe") == "size" and phase == "before":
            values["st_size"] = code._MAX_SETTINGS_BYTES + 1
        # Every field is retained; volatile physical identity/time/UID uses a verified prior-input offset.
        projected = {
            f: values[f] - getattr(anchor, f)
            if f in ("st_dev", "st_ino", "st_uid", "st_mtime_ns", "st_ctime_ns")
            else values[f]
            for f in FIELDS
        }
        event("metadata", phase, projected)
        return SimpleNamespace(**values)

    def path_stat(p, *args, **kwargs):
        if p != path:
            return original_lstat(p, *args, **kwargs)
        counts["stat"] += 1
        event("stat", counts["stat"])
        result = original_lstat(p, *args, **kwargs)
        return metadata(result, "before" if counts["stat"] == 1 else "visible")

    def opened(fd):
        owned[fd] = "file-" + str(len(owned) + 1)
        return fd

    def posix_open(p, flags, *args, **kwargs):
        assert p == path
        event("open", flags, args, kwargs)
        if spec.get("open_missing"):
            raise FileNotFoundError(2, "open race", str(path))
        return opened(native_open(p, flags, *args, **kwargs))

    def fstat(fd):
        assert fd in owned
        counts["fstat"] += 1
        event("fstat", owned[fd], counts["fstat"])
        return metadata(native_fstat(fd), "opened" if counts["fstat"] == 1 else "after")

    def read(fd, requested):
        assert fd in owned
        event("read", owned[fd], requested)
        raw = native_read(fd, min(requested, 3) if spec.get("short") else requested)
        event("read-return", owned[fd], len(raw), hashlib.sha256(raw).hexdigest())
        if spec.get("late_cap") == "shrink" and raw:
            code._MAX_SETTINGS_BYTES = 1
        if spec.get("late_cap") == "empty" and not raw:
            code._MAX_SETTINGS_BYTES = 0
        return raw

    def close(fd):
        assert fd in owned
        name = owned[fd]
        if spec.get("close_after"):
            native_close(fd)
            del owned[fd]
        event("close", name)
        if not spec.get("close_after"):
            native_close(fd)
            del owned[fd]

    class Port:
        name = platform

        def __getattr__(self, name):
            if name == "getuid":
                if platform == "nt":
                    raise AttributeError(name)

                def uid():
                    event("getuid")
                    return native_uid()

                return uid
            return getattr(os, name)

    Port.open, Port.fstat, Port.read, Port.close = map(
        staticmethod, (posix_open, fstat, read, close)
    )

    class Parent:
        descriptor = 88

        def assert_visible(self):
            event("parent-visible")

        def close(self):
            nonlocal parent_closed
            event("parent-close")
            parent_closed = True

    def pin(_cls, parent, **kwargs):
        assert parent == root
        event("parent-open", kwargs)
        if spec.get("parent_missing"):
            raise FileNotFoundError(2, "parent missing", str(root))
        return Parent()

    def win_stat(fd, name):
        assert fd == 88 and name == path.name
        return path_stat(path)

    def win_open(fd, name, **kwargs):
        assert fd == 88 and name == path.name
        event("win-open", kwargs)
        if spec.get("open_missing"):
            raise FileNotFoundError(2, "open race", str(path))
        return opened(native_open(path, os.O_RDONLY | os.O_NONBLOCK))

    def parse(raw, **kwargs):
        event("json", len(raw), hashlib.sha256(raw.encode()).hexdigest())
        return original_json(raw, **kwargs)

    def consume(*args, **kwargs):
        nonlocal consume_calls
        consume_calls += 1
        return original_consume(*args, **kwargs)

    result, failure = None, None
    with monkeypatch.context() as patch:
        patch.setattr(code, "_MAX_SETTINGS_BYTES", spec.get("cap", 4 * 1024 * 1024))
        for module in (code, core, consumption):
            if hasattr(module, "os"):
                patch.setattr(module, "os", Port())
        patch.setattr(consumption, "consume_file", consume)
        patch.setattr(Path, "lstat", path_stat)
        patch.setattr(win_epoch._PinnedWindowsAuthority, "open", classmethod(pin))
        for module in (code, win_io):
            if hasattr(module, "windows_stat_at"):
                patch.setattr(module, "windows_stat_at", win_stat)
            if hasattr(module, "open_windows_regular_file_at"):
                patch.setattr(module, "open_windows_regular_file_at", win_open)
        for module in (code, core):
            patch.setattr(module, "json", SimpleNamespace(loads=parse))
        try:
            result = code.read_coding_settings_patch_without_writes(
                Path("relative") if spec.get("relative") else path
            )
        except BaseException as caught:
            failure = error_data(caught)
        pending = {name: native_seek(fd, 0, os.SEEK_CUR) for fd, name in owned.items()}
        cap = code._MAX_SETTINGS_BYTES
    assert consume_calls == (
        0 if old_reader else int(any(row[0] == "read" for row in trace))
    ), (spec, consume_calls, trace)
    for fd in tuple(owned):
        native_close(
            fd
        )  # Observer-only cleanup after debt snapshot; never a Product retry.
    assert trace.fired == [
        [f["event"], f.get("occurrence", 1)] for f in spec.get("faults", ())
    ], (spec, trace.fired, trace)
    rejected = bool(
        spec.get("faults")
        or spec.get("relative")
        or spec.get("open_missing")
        or spec.get("unsafe")
        or spec.get("change")
        or kind in ("directory", "symlink", "hardlink")
        or spec.get("late_cap") == "shrink"
        or spec.get("cap", 4 * 1024 * 1024) < len(body)
        or spec.get("body") in ("duplicate", "nan", "utf8", "array", "empty")
    )
    if rejected:
        assert failure is not None and result is None, (spec, failure, trace)
    elif kind == "missing" or spec.get("parent_missing"):
        assert failure is None and result == (False, None, {}), (spec, failure, trace)
    else:
        assert failure is None and result == (
            True,
            hashlib.sha256(body).hexdigest(),
            original_json(body),
        ), (spec, failure, trace)
        assert not pending
    return dict(
        trace=list(trace),
        fired=trace.fired,
        error=failure,
        result=data(result),
        pending=pending,
        parent_closed=parent_closed,
        final_cap=cap,
    )


_ROWS = json.loads(gzip.decompress(EXPECTED.read_bytes()))


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row["spec"]["name"])
def test_replay(row, tmp_path, monkeypatch):
    assert json.dumps(
        observe(row["spec"], tmp_path, monkeypatch), sort_keys=True
    ) == json.dumps(row["result"], sort_keys=True)
