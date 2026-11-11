"""Old-first controlled Windows directory custody, with no native Windows claim."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding._product_capability_plugin_composition as code
import loushang.harness.resources.packages._private_tree_windows as core

EXPECTED = Path(__file__).parent / "fixtures" / "windows_approval_root_custody_v1.json"
pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX-host controlled Windows boundary model"
)


def error_data(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return dict(
        type=f"{type(error).__module__}.{type(error).__qualname__}",
        args=list(error.args),
        notes=getattr(error, "__notes__", []),
        cause=error_data(error.__cause__, seen.copy()),
        context=error_data(error.__context__, seen.copy()),
        suppress=error.__suppress_context__,
    )


def observe(spec, monkeypatch):
    depth = spec.get("depth", 2)
    state = (
        Path("/approval/state")
        if depth <= 2
        else Path("/approval").joinpath(*(f"d{i}" for i in range(depth - 1)))
    )
    target = state / "product-private"
    chain = list(reversed([target, *target.parents]))
    existing = target
    for _ in range(depth):
        existing = existing.parent
    directories = {
        str(p): (7, 11 + index)
        for index, p in enumerate(chain)
        if p == existing or p in existing.parents
    }
    directories[str(existing)] = (7, 11)
    descriptors = {}
    trace, fired = [], []
    counts = Counter()
    faults = {(f["event"], f.get("occurrence", 1)): f for f in spec.get("faults", [])}
    faults_active = True
    next_fd = 100
    stat_count = 0
    race_done = False

    def event(name, *args):
        counts[name] += 1
        trace.append([name, *args])
        fault = faults.get((name, counts[name])) if faults_active else None
        if fault is not None:
            fired.append([name, counts[name]])
            kind = fault.get("kind", "os")
            label = f"fault:{name}:{counts[name]}"
            if kind == "stop":
                raise StopIteration(label)
            if kind == "cancel":
                raise asyncio.CancelledError(label)
            if kind == "interrupt":
                raise KeyboardInterrupt(label)
            raise OSError(5, label)

    class Acl:
        def __init__(self, *, inherit_children=False):
            self.role = "leaf" if inherit_children else "private"
            event("acl.construct", self.role)

        def __enter__(self):
            event("acl.enter", self.role)
            return self

        def __exit__(self, _type, error, _tb):
            event("acl.exit", self.role, error_data(error))

        @property
        def security_descriptor(self):
            event("acl.security", self.role)
            return "security:" + self.role

        def validate(self, fd):
            assert fd in descriptors
            event("acl.validate", self.role, fd)

    def exists(path):
        event("exists", str(path))
        return str(path) in directories

    def stat(path, *args, **kwargs):
        nonlocal stat_count
        assert not args and not kwargs
        stat_count += 1
        event("path.stat", str(path), stat_count)
        dev, ino = directories[str(path)]
        drift = spec.get("drift")
        if (drift == "dev-before" and stat_count == 1) or (
            drift == "dev-after" and stat_count == 3
        ):
            dev += 1
        if (drift == "ino-before" and stat_count == 2) or (
            drift == "ino-after" and stat_count == 4
        ):
            ino += 1
        return SimpleNamespace(st_dev=dev, st_ino=ino)

    def open_directory(path, **kwargs):
        nonlocal next_fd, race_done
        parent = kwargs.get("dir_fd")
        absolute = Path(path) if parent is None else Path(descriptors[parent]) / path
        action = (
            "open.parent"
            if parent is None
            else "open.create"
            if kwargs.get("create_new")
            else "open.reopen"
        )
        event(action, str(path), kwargs)
        if kwargs.get("create_new"):
            if spec.get("race") and not race_done:
                race_done = True
                directories[str(absolute)] = (7, 1000 + len(directories))
                event("race.created", str(absolute))
                raise FileExistsError(17, "race")
            if str(absolute) in directories:
                raise FileExistsError(17, "exists")
            directories[str(absolute)] = (7, 1000 + len(directories))
        elif str(absolute) not in directories:
            raise FileNotFoundError(2, "missing")
        fd = next_fd
        next_fd += 1
        descriptors[fd] = str(absolute)
        return fd

    def fstat(fd):
        event("fd.stat", fd)
        dev, ino = directories[descriptors[fd]]
        return SimpleNamespace(st_dev=dev, st_ino=ino)

    def close(fd):
        assert fd in descriptors
        if spec.get("close_after_effect"):
            del descriptors[fd]
        event("close", fd)
        if not spec.get("close_after_effect"):
            del descriptors[fd]

    def flush(fd):
        assert fd in descriptors
        event("flush", fd)

    value = (
        None
        if spec.get("input") == "none"
        else "not-a-path"
        if spec.get("input") == "str"
        else Path("relative")
        if spec.get("input") == "relative"
        else state
    )
    errors, results, phases = [], [], []
    program = code._prepare_windows_product_approval_state_root
    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", exists)
        patch.setattr(Path, "stat", stat)
        for module in (code, core):
            for name, replacement in (
                ("WindowsPrivateDirectoryAcl", Acl),
                ("open_windows_directory", open_directory),
                ("windows_flush_directory", flush),
            ):
                if hasattr(module, name):
                    patch.setattr(module, name, replacement)
            patch.setattr(module, "os", SimpleNamespace(fstat=fstat, close=close))
        for phase in range(2 if spec.get("retry") else 1):
            event("phase", phase)
            try:
                result = program(value)
            except BaseException as error:
                errors.append(error_data(error))
                results.append(None)
            else:
                errors.append(None)
                results.append(str(result))
            phases.append(
                dict(
                    directories=sorted(directories),
                    outstanding=dict(sorted(descriptors.items())),
                )
            )
            faults_active = False
    assert fired == [
        [f["event"], f.get("occurrence", 1)] for f in spec.get("faults", [])
    ], (spec, fired, trace)
    if spec.get("faults") or spec.get("input") or depth > 8 or spec.get("drift"):
        assert errors[0] is not None and results[0] is None, (spec, errors, trace)
    else:
        assert errors == [None] and results == [str(target)] and not descriptors, (
            spec,
            errors,
            trace,
        )
    if spec.get("retry"):
        # Fault-free retries after a controlled failure must be explicitly observed.
        assert len(results) == 2 and errors[1] is None and results[1] == str(target)
    return dict(trace=trace, fired=fired, errors=errors, results=results, phases=phases)


def source_guard():
    root = Path(__file__).resolve().parents[2]
    for module, relative in (
        (code, "src/loushang/coding/_product_capability_plugin_composition.py"),
        (core, "src/loushang/harness/resources/packages/_private_tree_windows.py"),
    ):
        assert Path(module.__file__).resolve() == root / relative


_ROWS = json.loads(EXPECTED.read_text())


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row["spec"]["name"])
def test_replay(row, monkeypatch):
    source_guard()
    assert json.dumps(observe(row["spec"], monkeypatch), sort_keys=True) == json.dumps(
        row["result"], sort_keys=True
    )
