"""Frozen complete archive inventories with inert native/codec ports.

These observations validate enumeration/scopes/error priority, not Product
admission, native Windows, or real archive byte verification.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

WINDOWS = (
    "empty",
    "valid",
    "duplicate",
    "unexpected",
    "tombstone",
    "collision",
    "missing_parent",
    "missing_base",
    "unsafe_parent",
    "unsafe_base",
    "held_changed",
    "post_changed",
    "read_failure",
    "read_and_post_failure",
    "close_failure",
    "read_and_close_failure",
)
POSIX = (
    "empty",
    "valid",
    "staging",
    "tombstone",
    "unexpected",
    "missing_parent",
    "read_failure",
    "close_failure",
    "read_and_close_failure",
)
FIXTURE = Path(__file__).with_name("fixtures") / "private_archive_inventory_v1.json"


def observe(platform, case, monkeypatch):
    stem = (
        "package_private_data_windows_backup"
        if platform == "windows"
        else "package_private_data_backup"
    )
    code = importlib.import_module("loushang.coding." + stem)
    native = importlib.import_module(
        "loushang.harness.plugin_management."
        + (
            "_private_data_backup_windows"
            if platform == "windows"
            else "private_data_backup"
        )
    )
    trace = []
    backup = "b" * 64
    tombstone = ".expiring-" + "e" * 64

    class ProbePath(PurePosixPath):
        def lstat(self):
            trace.append(["lstat", self.as_posix()])
            if (self.name == "backups" and case == "missing_base") or (
                self.name == "installation" and case == "missing_parent"
            ):
                raise FileNotFoundError("missing visible directory")
            return SimpleNamespace()

    parent = ProbePath("/package/backups/installation")

    class Layout:
        @property
        def private_data_base(self):
            trace.append("private-base")
            return ProbePath("/private")

        @property
        def package_root(self):
            trace.append("package-root")
            return ProbePath("/package")

    key = "exact-key"

    def mapping(*args):
        trace.append("mapping")
        return parent

    def inspect(path):
        text = path.as_posix()
        trace.append(["inspect", text])
        if (
            path == parent
            and case
            in {"missing_parent", "missing_base", "unsafe_parent", "unsafe_base"}
        ) or (path == parent.parent and case in {"missing_base", "unsafe_base"}):
            raise FileNotFoundError("missing private directory")
        if (
            path == parent
            and trace.count(["inspect", text]) > 1
            and case in {"post_changed", "read_and_post_failure"}
        ):
            return (1, 99)
        return (1, 2)

    class ACL:
        def __enter__(self):
            trace.append("acl-enter")
            return self

        def validate(self, fd):
            trace.append(["acl", fd])

        def __exit__(self, kind, value, tb):
            trace.append(["acl-exit", None if kind is None else kind.__name__])

    def opened(path, **kwargs):
        trace.append(["open", path.as_posix(), kwargs])
        return 17

    def posix_open(base, path):
        trace.append(["open", base.as_posix(), path.as_posix()])
        if case == "missing_parent":
            raise FileNotFoundError("missing parent")
        return 17

    def identity(fd):
        trace.append(["identity", fd])
        return (1, 9) if case == "held_changed" else (1, 2)

    class NativeName(str):
        def strip(self, *args, **kwargs):
            trace.append("unexpected-strip")
            raise OSError("name.strip is outside original inventory checks")

    def names(fd):
        trace.append(["list", fd])
        if case == "valid_name_subclass":
            return (NativeName(backup),)
        return {
            "empty": (),
            "valid": (backup,),
            "duplicate": (backup, backup),
            "tombstone": (tombstone, backup),
            "collision": (tombstone, backup),
            "staging": (backup + ".staging", backup),
            "unexpected": ("bad",),
        }.get(case, (backup,))

    def close(fd):
        trace.append(["close", fd])
        if case in {"close_failure", "read_and_close_failure"}:
            raise OSError("close interrupted")

    def read(fd, name, *args):
        trace.append(["read", fd, name])
        if case in {"read_failure", "read_and_post_failure", "read_and_close_failure"}:
            raise OSError("read interrupted")
        return SimpleNamespace(installation_key=key, backup_id=name), SimpleNamespace()

    def verify(*args):
        trace.append(["verify", args[0], args[2] if platform == "windows" else args[1]])

    monkeypatch.setattr(
        code, "backup_parent" if platform == "windows" else "_backup_parent", mapping
    )
    fakeos = SimpleNamespace(close=close, listdir=names)
    if hasattr(code, "os"):
        monkeypatch.setattr(code, "os", fakeos)
    monkeypatch.setattr(native, "os", fakeos)
    if platform == "windows":
        for module in (code, native):
            monkeypatch.setattr(
                module, "inspect_windows_product_private_directory_identity", inspect
            )
            monkeypatch.setattr(module, "WindowsPrivateDirectoryAcl", ACL)
            monkeypatch.setattr(module, "open_windows_directory", opened)
            if hasattr(module, "windows_listdir_at"):
                monkeypatch.setattr(module, "windows_listdir_at", names)
        monkeypatch.setattr(code, "_directory_identity", identity)
        monkeypatch.setattr(
            type(code._native_io), "directory_identity", lambda self, fd: identity(fd)
        )
        monkeypatch.setattr(code, "_read_archive_manifest", read)
        monkeypatch.setattr(code, "_verify_archive", verify)
        monkeypatch.setattr(
            type(code._archive_io), "read_manifest", lambda self, *args: read(*args)
        )
        monkeypatch.setattr(
            type(code._archive_io), "verify_archive", lambda self, *args: verify(*args)
        )
    else:
        monkeypatch.setattr(code, "_open_private_path", posix_open)
        monkeypatch.setattr(
            type(code._private_io), "open_path", lambda self, *args: posix_open(*args)
        )
        monkeypatch.setattr(code, "_read_manifest", read)
        monkeypatch.setattr(code, "_verify_archive", verify)

        def shared_read(*args, io, codec):
            assert io is code._private_io and codec is code._archive_codec
            return read(*args)

        def shared_verify(*args, io, codec):
            assert io is code._private_io and codec is code._archive_codec
            return verify(*args)

        monkeypatch.setattr(native, "read_private_archive", shared_read)
        monkeypatch.setattr(native, "verify_private_archive", shared_verify)
    options = {
        "allowed_tombstone": tombstone if case in {"tombstone", "collision"} else None
    }
    if platform == "windows":
        options["pending_backup_id"] = backup if case == "collision" else None
    try:
        result = code._retained_receipts(Layout(), key, **options)
        outcome = {"backups": [r.backup_id for r in result]}
    except Exception as error:
        outcome = {
            "error": type(error).__name__,
            "message": str(error),
            "context": None
            if error.__context__ is None
            else [type(error.__context__).__name__, str(error.__context__)],
            "suppress_context": error.__suppress_context__,
        }
    return {"outcome": outcome, "trace": trace}


@pytest.mark.parametrize("platform,cases", [("posix", POSIX), ("windows", WINDOWS)])
def test_original_inventory_contract(platform, cases, monkeypatch):
    frozen = json.loads(FIXTURE.read_text())
    for case in cases:
        with monkeypatch.context() as patch:
            assert observe(platform, case, patch) == frozen[platform][case], case


def test_original_windows_name_predicate_does_not_add_strip(monkeypatch):
    frozen = json.loads(FIXTURE.read_text())["windows"]["valid"]
    assert observe("windows", "valid_name_subclass", monkeypatch) == frozen
