"""Explicit old-first local FD ordering and value projection comparisons."""

import errno
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.plugin_local_discovery as coding
import loushang.harness.resources._loader_discovery_filesystem as core

ORACLE = Path(__file__).parent / "fixtures" / "native_fallback_observations_v1.jsonl"


def run_case(monkeypatch, scenario, fail_at=None, error_number=errno.EIO):
    trace, handles = [], {}
    next_fd = 70

    def event(name):
        trace.append(name)
        if len(trace) == fail_at:
            raise OSError(error_number, "injected:" + name)

    class Root:
        def __init__(self, index):
            self.index = index
            self.reads = 0

        def lstat(self):
            self.reads += 1
            event(f"root{self.index}.lstat:{self.reads}")
            mode = stat.S_IFLNK if scenario == "root_link" else stat.S_IFDIR
            inode = self.index + (
                100 if scenario == "after_changed" and self.reads > 1 else 0
            )
            return SimpleNamespace(st_mode=mode, st_dev=1, st_ino=inode)

        def resolve(self, *, strict):
            assert strict is True
            event(f"root{self.index}.resolve")
            return object() if scenario == "noncanonical" else self

    roots = [Root(i) for i in range(18 if scenario == "root_budget" else 2)]

    class Receipt:
        @property
        def project_resource_root(self):
            event("receipt.project_root")
            return roots[0]

        @property
        def user_resource_roots(self):
            event("receipt.user_roots")
            return tuple(roots[1:])

    class Entry:
        def __init__(self, name, directory=True):
            self.name = name
            self.directory = directory

        def is_dir(self, *, follow_symlinks):
            assert follow_symlinks is False
            event("entry.is_dir:" + self.name)
            return self.directory

    def entries(kind):
        if scenario == "empty":
            return []
        if scenario == "entry_budget":
            return (
                [Entry("INVALID.md") for _ in range(501)] if kind == "prompts" else []
            )
        if scenario == "row_budget":
            return (
                [Entry("p" + str(i) + ".md") for i in range(501)]
                if kind == "prompts"
                else []
            )
        if scenario == "invalid_entries":
            return {
                "skills": [Entry("INVALID"), Entry("no-directory", False)],
                "prompts": [Entry("skip.txt"), Entry("INVALID.md"), Entry("link.md")],
                "themes": [Entry("zeta.json")],
            }[kind]
        return {
            "skills": [Entry("review")],
            "prompts": [Entry("zeta.md"), Entry("alpha.md")],
            "themes": [Entry("night.json")],
        }[kind]

    class Scan:
        def __init__(self, kind):
            self.kind = kind

        def __enter__(self):
            event("scandir.enter:" + self.kind)
            return iter(entries(self.kind))

        def __exit__(self, *args):
            event("scandir.exit:" + self.kind)

    def open_fd(path, flags, *, dir_fd=None):
        nonlocal next_fd
        assert flags == os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if isinstance(path, Root):
            kind, root_index = "root", path.index
            event(f"open:root{root_index}")
        else:
            parent_kind, root_index = handles[dir_fd]
            kind = str(path)
            event(f"open:{parent_kind}/{kind}")
        next_fd += 1
        handles[next_fd] = (kind, root_index)
        return next_fd

    def fstat(fd):
        kind, index = handles[fd]
        assert kind == "root"
        event(f"fstat:root{index}")
        return SimpleNamespace(
            st_dev=1, st_ino=index + (50 if scenario == "opened_changed" else 0)
        )

    def metadata(name, *, dir_fd, follow_symlinks):
        assert follow_symlinks is False
        kind, index = handles[dir_fd]
        event(f"stat:{kind}/{name}")
        mode = (
            stat.S_IFLNK
            if scenario == "invalid_entries" and name == "link.md"
            else stat.S_IFREG
        )
        return SimpleNamespace(st_mode=mode)

    def scandir(fd):
        kind, _ = handles[fd]
        event("scandir:" + kind)
        return Scan(kind)

    def close(fd):
        kind, index = handles[fd]
        event(f"close:{kind}:{index}")
        del handles[fd]

    fake_os = SimpleNamespace(
        O_RDONLY=os.O_RDONLY,
        O_DIRECTORY=os.O_DIRECTORY,
        open=open_fd,
        fstat=fstat,
        stat=metadata,
        scandir=scandir,
        close=close,
    )
    if scenario != "unsupported":
        fake_os.O_NOFOLLOW = os.O_NOFOLLOW

    def describe(error):
        if error is None:
            return None
        return {
            "type": type(error).__module__ + "." + type(error).__qualname__,
            "message": str(error),
            "errno": getattr(error, "errno", None),
            "context": describe(error.__context__),
            "cause": describe(error.__cause__),
        }

    outcome, rows, diagnostics = None, None, None
    with monkeypatch.context() as patch:
        patch.setattr(coding, "os", fake_os, raising=False)
        patch.setattr(core, "os", fake_os, raising=False)
        try:
            rows, diagnostics = coding._fallback_native_metadata(Receipt())
        except BaseException as error:
            outcome = describe(error)
    return {
        "trace": trace,
        "rows": rows,
        "diagnostics": sorted(diagnostics) if diagnostics is not None else None,
        "outcome": outcome,
        "open_handles": [list(item) for item in sorted(handles.values())],
    }


RECORDS = [json.loads(line) for line in ORACLE.read_text().splitlines()]


@pytest.mark.parametrize(
    "record",
    RECORDS,
    ids=lambda r: f"{r['scenario']}-{r['fail_at']}-{r['error_number']}",
)
def test_replay(monkeypatch, record):
    assert (
        run_case(
            monkeypatch, record["scenario"], record["fail_at"], record["error_number"]
        )
        == record["expected"]
    )
