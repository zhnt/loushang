"""Observe the actual Windows cutover CM against controlled native effects."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

import loushang.coding.package_source_snapshot as product
import loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover as core

EVIDENCE = Path(__file__).parent
EXPECTED = EVIDENCE / "fixtures" / "windows_cutover_directory_custody_v1.jsonl"


def _error(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "args": list(error.args),
        "notes": getattr(error, "__notes__", []),
        "suppress": error.__suppress_context__,
        "cause": _error(error.__cause__, seen.copy()),
        "context": _error(error.__context__, seen.copy()),
    }


class _Effects:
    def __init__(self, config):
        self.config = config
        self.trace = []
        self.counts = {}
        self.fired = []
        self.data = b""

    def event(self, name, *args):
        self.trace.append([name, *args])
        self.counts[name] = self.counts.get(name, 0) + 1
        key = [name, self.counts[name]]
        if key in self.config.get("faults", []):
            self.fired.append(key)
            kind = self.config.get("fault_kind", "oserror")
            if kind == "stop":
                raise StopIteration("controlled", name, key[1])
            if kind == "interrupt":
                raise KeyboardInterrupt("controlled", name, key[1])
            raise OSError(5, f"controlled:{name}:{key[1]}")

    def token(self, size):
        self.event("token", size)
        return "ab" * size

    def acl(self):
        effects = self

        class Acl:
            security_descriptor = "exact-acl"

            def __enter__(self):
                effects.event("acl.enter")
                return self

            def validate(self, descriptor):
                effects.event("acl.validate", descriptor)

            def __exit__(self, _type, error, _tb):
                effects.event("acl.exit", _error(error))

        return Acl()

    def open_parent(self, path, **kwargs):
        self.event("parent.open", str(path), kwargs)
        effects = self

        class Authority:
            @property
            def descriptor(self):
                effects.event("parent.descriptor")
                return 10

            def assert_visible(self):
                effects.event("parent.visible")

            def close(self):
                effects.event("parent.close")

        return Authority()

    def open_directory(self, name, **kwargs):
        self.event("directory.open", name, kwargs)
        return 11

    def open_file(self, descriptor, name, **kwargs):
        self.event("file.open", descriptor, name, kwargs)
        return 12

    def fstat(self, descriptor):
        self.event("fstat", descriptor)
        return SimpleNamespace(st_dev=7, st_ino=descriptor)

    def stat_at(self, descriptor, name):
        self.event("stat_at", descriptor, name)
        identity = 12 if descriptor == 11 else 11
        if self.config.get("changed") == ("file" if descriptor == 11 else "directory"):
            identity += 100
        return SimpleNamespace(st_dev=7, st_ino=identity)

    def write(self, descriptor, pending):
        self.event("write", descriptor, bytes(pending).hex())
        amount = self.config.get("write_count", 2)
        if amount > 0:
            amount = min(amount, len(pending))
            self.data += bytes(pending[:amount])
        return amount

    def close(self, descriptor):
        self.event("close", descriptor)

    def flush_file(self, descriptor):
        self.event("flush_file", descriptor)

    def flush_directory(self, descriptor):
        self.event("flush_directory", descriptor)

    def unlink(self, descriptor, name):
        self.event("unlink", descriptor, name)

    def rmdir(self, descriptor, name):
        self.event("rmdir", descriptor, name)


def _observe(config):
    effects = _Effects(config)
    fake_os = SimpleNamespace(
        name=config.get("platform", "nt"),
        fstat=effects.fstat,
        write=effects.write,
        close=effects.close,
    )
    replacements = {
        "os": fake_os,
        "secrets": SimpleNamespace(token_hex=effects.token),
        "WindowsPrivateDirectoryAcl": effects.acl,
        "_PinnedWindowsAuthority": SimpleNamespace(open=effects.open_parent),
        "open_windows_directory": effects.open_directory,
        "open_windows_regular_file_at": effects.open_file,
        "windows_stat_at": effects.stat_at,
        "windows_flush_file": effects.flush_file,
        "windows_flush_directory": effects.flush_directory,
        "windows_unlink_at": effects.unlink,
        "windows_rmdir_at": effects.rmdir,
    }
    failure = None
    yielded = None
    payload = config.get("payload", "6162636465")
    with pytest.MonkeyPatch.context() as patch:
        for module in (product, core):
            for name, value in replacements.items():
                patch.setattr(module, name, value, raising=False)
        try:
            context = product.hold_coding_windows_private_cutover_directory(
                PurePosixPath("/private-parent"),
                prefix=config.get("prefix", "coding-pre-b-projection-"),
                projection_contents=None if payload is None else bytes.fromhex(payload),
            )
            effects.trace.append(["constructed"])
            with context as root:
                yielded = str(root)
                effects.event("body", yielded)
                body = config.get("body")
                if body == "error":
                    raise ValueError("controlled-body")
                if body == "stop":
                    raise StopIteration("controlled-body")
                if body == "interrupt":
                    raise KeyboardInterrupt("controlled-body")
                if body == "cancel":
                    raise asyncio.CancelledError("controlled-body")
                if body == "exit":
                    raise GeneratorExit("controlled-body")
        except BaseException as error:
            failure = _error(error)
    return {
        "trace": effects.trace,
        "yielded": yielded,
        "bytes": effects.data.hex(),
        "failure": failure,
        "fired": effects.fired,
    }


def _guard():
    root = Path(__file__).resolve().parents[2]
    for module, name in (
        (product, "src/loushang/coding/package_source_snapshot.py"),
        (
            core,
            "src/loushang/harness/resources/packages/plugin_lifecycle/windows_epoch_cutover.py",
        ),
    ):
        assert Path(module.__file__).resolve() == root / name


_RECORDS = [json.loads(line) for line in EXPECTED.read_text().splitlines()[1:]]


@pytest.mark.parametrize("record", _RECORDS, ids=lambda record: record["id"])
def test_replay(record):
    _guard()
    assert _observe(record["config"]) == record["result"]
