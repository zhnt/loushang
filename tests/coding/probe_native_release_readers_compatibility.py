"""Fixed original inert reader observations with real files and descriptor custody.

Explicit local probe: no native code is executed and no old expectations are captured.
Product admission and durable approval are controlled; file/RECORD/receipt IO is real.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import sys
from base64 import urlsafe_b64encode
from contextlib import suppress
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_worker_installed_native as installed
from loushang.coding import package_product_worker_native_release as raw
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeReleaseApprovalV1,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from tests.harness.worker.test_native_executable_format import _static_elf

OBSERVATIONS = json.loads(
    (Path(__file__).parent / "fixtures" / "native_release_readers_v1.json").read_text()
)["observations"]

COMMON = (
    "valid",
    "platform",
    "machine",
    "root-mode",
    "root-link",
    "root-owner",
    "catalog-json",
    "catalog-canonical",
    "catalog-fields",
    "catalog-version",
    "catalog-platform",
    "catalog-source",
    "catalog-launcher",
    "catalog-flags",
    "source-missing",
    "source-before-json",
    "launcher-format",
    "launcher-writable",
    "catalog-writable",
    "catalog-link",
    "catalog-hardlink",
    "catalog-large",
    "member-overflow",
    "read-error",
    "close-member",
    "close-root",
    "close-both",
    "closure-error",
)
CHANGED = tuple(
    "changed-" + field
    for field in (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
)
RECORD = (
    "record-utf8",
    "record-csv",
    "record-short",
    "record-long",
    "record-duplicate",
    "record-self",
    "record-digest",
    "record-size",
    "record-incomplete",
    "record-unsupported",
    "extra-metadata",
    "max-metadata",
    "extra-unrecorded",
    "extra-root",
    "metadata-version",
    "wheel-tag",
    "initializer",
    "directory-link",
    "directory-owner",
    "directory-fstat",
    "version-error",
    "platform-before-version",
)
CASES = tuple(
    (kind, case) for kind in ("generated", "installed") for case in COMMON + CHANGED
)
CASES += tuple(("installed", case) for case in RECORD)
CASES += tuple(
    ("product", case)
    for case in (
        "valid",
        "receipt-scope",
        "receipt-digest",
        "source-wheel",
        "approval-missing",
    )
)
CASES += tuple(
    ("member", case)
    for case in (
        "valid",
        "empty-zero",
        "writable",
        "hardlink",
        "too-large",
        "read-error",
    )
)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


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
        "notes": getattr(exc, "__notes__", []),
        "suppress": exc.__suppress_context__,
        "cause": error_graph(exc.__cause__, normalize, seen),
        "context": error_graph(exc.__context__, normalize, seen),
    }


def observe(kind, case, base, patch):
    root = base / ("worker-native-release-v1" if kind == "product" else "release")
    root.mkdir(mode=0o700)
    installed_version = "0.1.0"
    source = base / "profile-source.c"
    source.write_bytes(b"inert H6 profile source input\n")
    patch.setattr(raw, "_SOURCE", source)
    package = "loushang_h6_native"
    dist_info = f"{package}-{installed_version}.dist-info"
    launcher = _static_elf() if case != "launcher-format" else b"not-ELF"
    catalog = {
        "catalogVersion": 1,
        "platform": "linux-x86_64",
        "profileSourceSha256": hashlib.sha256(raw._SOURCE.read_bytes()).hexdigest(),
        "launcherSha256": hashlib.sha256(launcher).hexdigest(),
        "launcherFile": "containment-launcher",
        "buildFlags": [],
    }
    if case == "catalog-fields":
        catalog["extra"] = True
    if case == "catalog-version":
        catalog["catalogVersion"] = True
    if case == "catalog-platform":
        catalog["platform"] = "windows-amd64"
    if case == "catalog-source":
        catalog["profileSourceSha256"] = "0" * 64
    if case == "catalog-launcher":
        catalog["launcherSha256"] = "0" * 64
    if case == "catalog-flags":
        catalog["buildFlags"] = [1]
    catalog_bytes = canonical(catalog)
    if case in ("catalog-json", "source-before-json"):
        catalog_bytes = b"not json"
    if case == "catalog-canonical":
        catalog_bytes = json.dumps(catalog).encode()
    if case == "catalog-large":
        catalog_bytes = b"x" * 4097
    if kind == "generated":
        files = {"catalog.json": catalog_bytes, "containment-launcher": launcher}
    elif kind == "member":
        files = {"catalog.json": b"" if case == "empty-zero" else b"payload"}
    else:
        files = {
            f"{package}/__init__.py": b"x" if case == "initializer" else b"",
            f"{package}/release/catalog.json": catalog_bytes,
            f"{package}/release/containment-launcher": launcher,
            f"{dist_info}/METADATA": (
                f"Metadata-Version: 2.1\nName: loushang-h6-native\nVersion: {installed_version}\n\n"
            ).encode(),
            f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: loushang-h6-release\nRoot-Is-Purelib: false\nTag: py3-none-linux_x86_64\n\n",
        }
        if case == "metadata-version":
            files[f"{dist_info}/METADATA"] = b"wrong metadata"
        if case == "wheel-tag":
            files[f"{dist_info}/WHEEL"] = b"wrong tag"
        for i in range(
            10
            if case == "max-metadata"
            else 11
            if case == "record-long"
            else 1
            if case == "extra-metadata"
            else 0
        ):
            files[f"{dist_info}/EXTRA{i}"] = b"extra"
        record_name = f"{dist_info}/RECORD"
        rows = [
            [
                name,
                "sha256="
                + urlsafe_b64encode(hashlib.sha256(data).digest())
                .rstrip(b"=")
                .decode(),
                str(len(data)),
            ]
            for name, data in sorted(files.items())
        ]
        rows.append([record_name, "", ""])
        if case == "record-short":
            rows = rows[:-1]
        if case == "record-duplicate":
            rows.append(rows[0])
        if case == "record-self":
            rows[-1][1] = "not-empty"
        if case == "record-digest":
            rows[0][1] = "sha256=wrong"
        if case == "record-size":
            rows[0][2] = "0000"
        if case == "record-incomplete":
            files[f"{dist_info}/OTHER"] = b"other"
            rows[0] = [
                f"{dist_info}/OTHER",
                "sha256="
                + urlsafe_b64encode(hashlib.sha256(b"other").digest())
                .rstrip(b"=")
                .decode(),
                "5",
            ]
        if case == "record-unsupported":
            rows[0][0] = "other/member"
        stream = io.StringIO()
        csv.writer(stream, lineterminator="\n").writerows(rows)
        files[record_name] = (
            b"\xff"
            if case == "record-utf8"
            else b'"unterminated'
            if case == "record-csv"
            else stream.getvalue().encode()
        )
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(body)
        path.chmod(0o500 if path.name == "containment-launcher" else 0o600)
    catalog_path = root / (
        "catalog.json"
        if kind in ("generated", "member")
        else f"{package}/release/catalog.json"
    )
    launcher_path = catalog_path.parent / "containment-launcher"
    if case == "launcher-writable":
        launcher_path.chmod(0o755)
    if case in ("catalog-writable", "writable"):
        catalog_path.chmod(0o666)
    if case in ("catalog-hardlink", "hardlink"):
        os.link(catalog_path, base / "hardlink")
    if case == "catalog-link":
        target = base / "catalog-target"
        catalog_path.rename(target)
        catalog_path.symlink_to(target)
    if case == "root-mode":
        root.chmod(0o755)
    if case == "directory-link":
        (root / package).rename(root / "other-package")
        (root / package).symlink_to(root / "other-package", target_is_directory=True)
    if case == "extra-unrecorded":
        (root / dist_info / "UNRECORDED").write_bytes(b"unknown")
    if case == "extra-root":
        (root / "unrelated").write_bytes(b"allowed root sibling")
    if case == "root-link":
        alias = base / "alias"
        alias.symlink_to(root, target_is_directory=True)
        read_root = alias
    else:
        read_root = root
    if case in ("source-missing", "source-before-json"):
        patch.setattr(raw, "_SOURCE", base / "missing-source.c")

    def normalize(value):
        return value.replace(str(base), "<ROOT>")

    trace = []
    active = {}
    counter = 0
    read_seen = set()
    fstat_seen = {}
    real_open, real_close, real_stat, real_read = os.open, os.close, os.fstat, os.read
    if case in ("platform", "platform-before-version"):
        patch.setattr(sys, "platform", "darwin")
    if case == "machine":
        patch.setattr(platform, "machine", lambda: "arm64")

    def runtime_version(_name):
        trace.append(["version"])
        if case in ("version-error", "platform-before-version"):
            raise PackageNotFoundError("loushang")
        return installed_version

    patch.setattr(installed, "version", runtime_version)
    original_closure = raw.CodingWorkerNativeClosureV1

    def closure(**values):
        trace.append(["closure", values])
        if case == "closure-error":
            raise ValueError("injected closure construction")
        return original_closure(**values)

    patch.setattr(raw, "CodingWorkerNativeClosureV1", closure)

    def opened(path, flags, *args, **kwargs):
        nonlocal counter
        parent = active.get(kwargs.get("dir_fd"))
        selected = parent is not None or str(path) in (str(read_root), str(root))
        name = parent[1] + "/" + str(path) if parent else normalize(str(path))
        if selected:
            trace.append(["open", name, flags])
        fd = real_open(path, flags, *args, **kwargs)
        if selected:
            counter += 1
            active[fd] = (f"fd{counter}", name)
            read_seen.discard(fd)
        return fd

    def fstat(fd):
        result = real_stat(fd)
        if fd not in active:
            return result
        label, name = active[fd]
        trace.append(["fstat", label])
        fstat_seen[fd] = fstat_seen.get(fd, 0) + 1
        if case == "directory-fstat" and name.endswith("/" + package):
            raise OSError("injected directory fstat")
        change = {}
        if case == "root-owner" and name == normalize(str(read_root)):
            change["st_uid"] = result.st_uid + 1
        if case == "directory-owner" and name.endswith("/" + package):
            change["st_uid"] = result.st_uid + 1
        if (
            case.startswith("changed-")
            and name.endswith("/catalog.json")
            and fd in read_seen
        ):
            field = case.removeprefix("changed-")
            change[field] = getattr(result, field) + 1
        return (
            NS(
                **{
                    field: change.get(field, getattr(result, field))
                    for field in dir(result)
                    if field.startswith("st_")
                }
            )
            if change
            else result
        )

    def read(fd, count):
        if fd in active:
            label, name = active[fd]
            trace.append(["read", label, count])
            if case == "read-error" and name.endswith("/catalog.json"):
                raise OSError("injected member read")
            data = real_read(fd, count)
            if (
                case == "member-overflow"
                and name.endswith("/catalog.json")
                and fd not in read_seen
            ):
                with catalog_path.open("ab") as stream:
                    stream.write(b"x" * 5000)
            read_seen.add(fd)
            return data
        return real_read(fd, count)

    def close(fd):
        if fd in active:
            label, name = active[fd]
            trace.append(["close", label])
            if (
                case in ("close-member", "close-both")
                and name.endswith("/catalog.json")
            ) or (
                case in ("close-root", "close-both")
                and name == normalize(str(read_root))
            ):
                raise OSError(
                    "injected close "
                    + ("member" if name.endswith("/catalog.json") else "root")
                )
        real_close(fd)
        active.pop(fd, None)

    gate = PluginPackageGcReservationJournal(base / "gc.jsonl")
    if kind == "product":
        wheel = b"inert retained wheel"
        (root / "source.whl").write_bytes(wheel)
        approval = CodingWorkerNativeReleaseApprovalV1(
            hashlib.sha256(wheel).hexdigest(),
            hashlib.sha256(catalog_bytes).hexdigest(),
            hashlib.sha256(launcher).hexdigest(),
            catalog["profileSourceSha256"],
        )
        receipt = {**approval.to_dict(), "scopeId": "scope", "version": 1}
        if case == "receipt-scope":
            receipt["scopeId"] = "other"
        receipt["recordDigest"] = hashlib.sha256(
            canonical(receipt).rstrip(b"\n")
        ).hexdigest()
        if case == "receipt-digest":
            receipt["recordDigest"] = "0" * 64
        (root / "product-native-release.json").write_bytes(canonical(receipt))
        if case == "source-wheel":
            (root / "source.whl").write_bytes(b"changed")

        class Approval:
            def __init__(self, product):
                trace.append(["approval-owner"])

            def current(self):
                trace.append(["approval-current"])
                return (
                    None
                    if case == "approval-missing"
                    else NS(action="approve", approval=approval, generation=3)
                )

        patch.setattr(installed, "CodingWorkerNativeApprovalJournal", Approval)
        product = NS(
            state_root=base,
            gc_gate=gate,
            policy=NS(project_scope_id="scope"),
            assert_root_gc_authority_current=lambda: trace.append(["current"]),
        )
    borrowed = None
    if kind == "member":
        borrowed = real_open(root, os.O_RDONLY | os.O_DIRECTORY)
        active[borrowed] = ("input", normalize(str(root)))
    patch.setattr(os, "open", opened)
    patch.setattr(os, "fstat", fstat)
    patch.setattr(os, "read", read)
    patch.setattr(os, "close", close)
    try:
        try:
            if kind == "generated":
                result = raw.CodingLinuxWorkerReleaseCatalogReader(
                    release_root=read_root, gc_gate=gate
                ).current_closure()
            elif kind == "installed":
                result = installed.CodingLinuxInstalledWorkerReleaseReader(
                    installation_root=read_root, gc_gate=gate
                ).current_closure()
            elif kind == "product":
                result = installed.CodingProductInstalledWorkerReleaseReader(
                    product_owner=product
                ).current_launch_material()
            else:
                result = raw._read_member(
                    borrowed,
                    "catalog.json",
                    0 if case == "empty-zero" else 3 if case == "too-large" else 4096,
                )
            if isinstance(result, bytes):
                result = {
                    "bytes": len(result),
                    "sha256": hashlib.sha256(result).hexdigest(),
                }
            elif kind == "product":
                result = {
                    "launcher": normalize(str(result.launcher_path)),
                    "closure": result.closure.to_dict(),
                }
            else:
                result = result.to_dict()
            error = None
        except BaseException as exc:
            result = None
            error = error_graph(exc, normalize)
        outstanding = [value[0] for fd, value in active.items() if fd != borrowed]
        return {
            "result": result,
            "error": error,
            "trace": trace,
            "outstanding": outstanding,
        }
    finally:
        for fd in tuple(active):
            with suppress(OSError):
                real_close(fd)
        active.clear()


@pytest.mark.parametrize("kind,case", CASES)
def test_original_native_reader(kind, case, tmp_path, monkeypatch):
    actual = observe(kind, case, tmp_path, monkeypatch)
    accepted = {
        "generated": {"valid", "catalog-writable"},
        "installed": {
            "valid",
            "catalog-writable",
            "launcher-writable",
            "extra-metadata",
            "max-metadata",
            "extra-root",
        },
        "product": {"valid"},
        "member": {"valid", "empty-zero", "writable"},
    }
    assert (actual["error"] is None) == (case in accepted[kind]), actual
    assert actual == OBSERVATIONS[f"{kind}-{case}"]
