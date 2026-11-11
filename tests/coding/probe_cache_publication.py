"""Explicit old-first publication observations with real temp files/FDs; no default gate."""

import errno
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.arch.cache as arch
import loushang.harness.journal._cache_publication as publication
import loushang.harness.transcript.model_input_v2_index_file as transcript

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Linux temp/FD observations; Windows callback is controlled",
)

FIXTURE = Path(__file__).parent / "fixtures" / "cache_publication_v1.jsonl"
ROWS = [json.loads(line) for line in FIXTURE.read_text().splitlines()][1:]


def observe(root, patch, owner, case):
    root.mkdir()
    target = root / "cache.json"
    target.write_bytes(b"old-cache")
    target.chmod(0o640)
    trace = []
    streams = []
    directory_fds = []
    faults = {}
    temporary = []
    wanted = set(case.split("+"))
    for stage in wanted:
        faults[stage] = (
            FileNotFoundError("fault:" + stage)
            if stage == "unlink_missing"
            else OSError("fault:" + stage)
        )

    def event(stage):
        trace.append(stage)
        if stage in wanted:
            raise faults[stage]

    def failure_graph(error, seen=None):
        if error is None:
            return None
        seen = set() if seen is None else seen
        if id(error) in seen:
            return {"cycle": True}
        seen.add(id(error))
        return {
            "type": type(error).__module__ + "." + type(error).__qualname__,
            "args": list(error.args),
            "stage": next((key for key, val in faults.items() if val is error), None),
            "cause": failure_graph(error.__cause__, seen),
            "context": failure_graph(error.__context__, seen),
            "suppress_context": error.__suppress_context__,
        }

    native = SimpleNamespace(
        mkdir=Path.mkdir,
        unlink=Path.unlink,
        temp=tempfile.NamedTemporaryFile,
        fsync=os.fsync,
        replace=os.replace,
        chmod=os.chmod,
        open=os.open,
        close=os.close,
    )

    def mkdir(path, *args, **kwargs):
        if path == root:
            event("mkdir")
        return native.mkdir(path, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        if path in temporary:
            trace.append("unlink")
            if "unlink_missing" in wanted:
                native.unlink(path, *args, **kwargs)
                raise faults["unlink_missing"]
            if "unlink" in wanted:
                raise faults["unlink"]
        return native.unlink(path, *args, **kwargs)

    class Stream:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        @property
        def name(self):
            return self.wrapped.name

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            trace.append("close")
            result = self.wrapped.__exit__(*args)
            if "close_after" in wanted:
                raise faults["close_after"]
            return result

        def fileno(self):
            return self.wrapped.fileno()

        def write(self, data):
            event("write")
            return self.wrapped.write(data)

        def flush(self):
            event("flush")
            return self.wrapped.flush()

    def new_temp(**kwargs):
        event("create")
        assert kwargs == dict(
            mode="wb", dir=root, prefix=".cache.json.", suffix=".tmp", delete=False
        )
        wrapped = native.temp(**kwargs)
        streams.append(wrapped)
        temporary.append(Path(wrapped.name))
        return Stream(wrapped)

    def sync(fd):
        event("directory_fsync" if fd in directory_fds else "file_fsync")
        return native.fsync(fd)

    def replace(source, destination):
        assert Path(source) in temporary and destination == target
        event("replace")
        return native.replace(source, destination)

    def chmod(path, mode):
        assert Path(path) in temporary and mode == 0o600
        event("chmod")
        return native.chmod(path, mode)

    def opening(path, flags, *args, **kwargs):
        if path == root:
            assert flags == os.O_RDONLY
            event("directory_open")
            fd = native.open(path, flags, *args, **kwargs)
            directory_fds.append(fd)
            return fd
        return native.open(path, flags, *args, **kwargs)

    def closing(fd):
        result = native.close(fd)
        if fd in directory_fds:
            event("directory_close_after")
        return result

    def callback(path, payload):
        assert path == target
        trace.append("delegate")
        if case == "delegate_error":
            raise OSError("delegate refused")
        assert isinstance(payload, bytes)

    error = None
    with patch.context() as scoped:
        scoped.setattr(Path, "mkdir", mkdir)
        scoped.setattr(Path, "unlink", unlink)
        scoped.setattr(tempfile, "NamedTemporaryFile", new_temp)
        for name, func in [
            ("fsync", sync),
            ("replace", replace),
            ("chmod", chmod),
            ("open", opening),
            ("close", closing),
        ]:
            scoped.setattr(os, name, func)
        try:
            if owner == "arch":
                snapshot = arch.ImportFactCacheSnapshot(
                    arch.ImportFactCacheNamespace("root", "python", 1, None), (), ()
                )
                private = None
                if case.startswith("delegate"):
                    namespace = SimpleNamespace(**vars(os))
                    namespace.name = "nt"
                    scoped.setattr(arch, "os", namespace)
                    private = callback
                arch._write_snapshot(
                    target,
                    snapshot,
                    max_bytes=1 if case == "quota" else None,
                    private_writer=private,
                )
            else:
                transcript._write_manifest(
                    target,
                    {"version": 1, "text": "μ"},
                    write_cache=callback if case.startswith("delegate") else None,
                )
        except BaseException as caught:
            error = failure_graph(caught)
    states = []
    for path in sorted(root.iterdir()):
        states.append(
            {
                "name": "target" if path == target else "temporary",
                "bytes": path.read_bytes().hex(),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        )
    states.sort(key=lambda x: x["name"])
    descriptors = []
    for fd in directory_fds:
        try:
            os.fstat(fd)
        except OSError as descriptor_error:
            assert descriptor_error.errno == errno.EBADF
            descriptors.append("closed")
        else:
            descriptors.append("open")
    return dict(
        trace=trace,
        error=error,
        files=states,
        temp_streams_closed=[x.closed for x in streams],
        directory_fds=descriptors,
    )


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["owner"] + "-" + row["case"])
def test_original_publication_observation(tmp_path, monkeypatch, row):
    source = Path(__file__).resolve().parents[2] / "src"
    for module, relative in (
        (arch, "loushang/coding/arch/cache.py"),
        (transcript, "loushang/harness/transcript/model_input_v2_index_file.py"),
        (publication, "loushang/harness/journal/_cache_publication.py"),
    ):
        assert Path(module.__file__).resolve() == (source / relative).resolve()
    value = observe(tmp_path / "case", monkeypatch, row["owner"], row["case"])
    assert value == row["observation"], value
