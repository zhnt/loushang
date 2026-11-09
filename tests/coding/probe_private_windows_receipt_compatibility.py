"""Frozen receipt bytes, failures and IO order; emulated primitives, not Windows ACL proof."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import loushang.coding.package_legacy_windows_receipt as legacy
from loushang.harness.resources.packages import _file_consumption

CASES = (
    "read",
    "missing",
    "staged",
    "allow_staged",
    "both",
    "oversized",
    "named_stream",
    "attributes",
    "ledger_relaxed",
    "denied_acl",
    "write",
    "resume_stage",
    "conflict",
    "already_published",
    "zero_write",
    "rename_failure",
    "invalid_bound",
)


def run_probe(native, case: str, root: Path) -> dict[str, object]:
    """The external baseline generator calls this before the original owner changes."""
    payload = b"private receipt"
    path = root / "record.json"
    if case in {
        "read",
        "both",
        "oversized",
        "named_stream",
        "attributes",
        "ledger_relaxed",
        "denied_acl",
        "already_published",
    }:
        path.write_bytes(payload)
    if case in {"staged", "allow_staged", "both", "resume_stage", "conflict"}:
        (root / "record.json.stage").write_bytes(
            b"different" if case == "conflict" else payload
        )
    trace: list[str] = []
    descriptors: dict[int, str] = {}

    class OsView:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

        def fstat(self, descriptor):
            value = os.fstat(descriptor)
            trace.append("stat:" + descriptors[descriptor])
            fields = {
                name: getattr(value, name)
                for name in dir(value)
                if name.startswith("st_")
            }
            fields["st_file_attributes"] = (
                0x10
                if stat.S_ISDIR(value.st_mode)
                else (0x02 if case in {"attributes", "ledger_relaxed"} else 0x20)
            )
            return SimpleNamespace(**fields)

        def read(self, descriptor, maximum):
            trace.append(f"read:{descriptors[descriptor]}:{maximum}")
            return os.read(descriptor, maximum)

        def write(self, descriptor, data):
            trace.append(f"write:{descriptors[descriptor]}:{len(data)}")
            return 0 if case == "zero_write" else os.write(descriptor, data)

        def close(self, descriptor):
            trace.append("close:" + descriptors.pop(descriptor))
            os.close(descriptor)

    class Acl:
        security_descriptor = 1

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def validate(self, descriptor, **_):
            trace.append("acl:" + descriptors[descriptor])
            if case == "denied_acl":
                raise PermissionError("probe ACL denied")

    def open_directory(directory, **_):
        trace.append("open:root")
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        descriptors[descriptor] = "root"
        return descriptor

    def open_file(directory_fd, name, *, create_new, write, **_):
        trace.append("open:" + name)
        flags = os.O_WRONLY if write else os.O_RDONLY
        if create_new:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        descriptors[descriptor] = name
        return descriptor

    def visible(directory_fd, name):
        descriptor = os.open(name, os.O_RDONLY, dir_fd=directory_fd)
        descriptors[descriptor] = name
        try:
            return OsView().fstat(descriptor)
        finally:
            descriptors.pop(descriptor)
            os.close(descriptor)

    def rename(directory_fd, old, new):
        trace.append("rename:" + old + ":" + new)
        if case == "rename_failure":
            raise OSError("probe publication interrupted")
        os.rename(old, new, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)

    def streams(descriptor):
        trace.append("streams:" + descriptors[descriptor])
        return (
            ("::$DATA", "extra:$DATA")
            if case in {"named_stream", "ledger_relaxed"}
            else ("::$DATA",)
        )

    with (
        patch.object(native, "os", OsView()),
        patch.object(_file_consumption, "os", OsView()),
        patch.object(native, "WindowsPrivateDirectoryAcl", Acl),
        patch.object(native, "open_windows_directory", open_directory),
        patch.object(native, "open_windows_regular_file_at", open_file),
        patch.object(native, "windows_stat_at", visible),
        patch.object(native, "windows_regular_file_stream_names", streams),
        patch.object(native, "windows_directory_stream_names", lambda fd: ()),
        patch.object(
            native,
            "windows_flush_file",
            lambda fd: trace.append("flush:" + descriptors[fd]),
        ),
        patch.object(
            native,
            "windows_flush_directory",
            lambda fd: trace.append("flush:" + descriptors[fd]),
        ),
        patch.object(legacy, "windows_rename_at", rename),
    ):
        try:
            if case in {
                "write",
                "resume_stage",
                "conflict",
                "already_published",
                "zero_write",
                "rename_failure",
            }:
                value = legacy.write_windows_private_receipt(path, payload)
            elif case == "ledger_relaxed":
                value = legacy.read_windows_product_desired_bytes(path)
            else:
                value = legacy.read_windows_private_receipt(
                    path,
                    maximum_bytes=0
                    if case == "invalid_bound"
                    else 2
                    if case == "oversized"
                    else 32,
                    allow_unpublished_stage=case == "allow_staged",
                )
            result = {"value": value.hex() if isinstance(value, bytes) else value}
        except Exception as error:
            result = {
                "error_type": type(error).__module__ + "." + type(error).__qualname__,
                "message": str(error),
            }
    return {
        **result,
        "trace": trace,
        "open_descriptors": list(descriptors.values()),
        "files": {
            item.name: item.read_bytes().hex() for item in sorted(root.iterdir())
        },
    }


@pytest.mark.parametrize("case", CASES)
def test_original_windows_receipt_contract(case: str, tmp_path: Path) -> None:
    from loushang.harness.resources.packages import _private_receipts_windows as native

    reference = json.loads(
        (
            Path(__file__).parent / "fixtures" / "private_windows_receipt_v1.json"
        ).read_text()
    )
    assert run_probe(native, case, tmp_path) == reference["cases"][case]
