"""Native Rust/Python fixture-file admission parity; no live records or sockets."""

from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
import subprocess
import tempfile
from ctypes import wintypes as W
from pathlib import Path

from loushang.appserver._windows_local_record import _WindowsRecordFiles
from loushang.appserver.local_record import LocalConnectionDirectoryV1, LocalRecordError

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"
EXE = CRATE / "target/debug/record_probe.exe"


def set_dacl(path: Path, api, kind: str) -> None:
    """Mutate only temporary fixtures, using actual Windows security APIs."""
    descriptor, dacl = C.c_void_p(), C.c_void_p()
    present, defaulted = W.BOOL(), W.BOOL()
    try:
        if kind != "null":
            trustees = sorted({api.user_sid, "S-1-5-18"})
            sddl = "D:P" + "".join(f"(A;;FA;;;{sid})" for sid in trustees)
            if kind == "world":
                sddl += "(A;;FR;;;WD)"
            assert api.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, C.byref(descriptor), None
            )
            assert api.security.GetSecurityDescriptorDacl(
                descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)
            )
        function = api.security.SetNamedSecurityInfoW
        function.argtypes = [W.LPWSTR, C.c_int, W.DWORD] + [C.c_void_p] * 4
        function.restype = W.DWORD
        flags = 0x20000004 if kind == "unprotected" else 0x80000004
        assert function(str(path), 1, flags, None, None, dacl, None) == 0
    finally:
        if descriptor.value:
            assert not api.kernel.LocalFree(descriptor)


def verify(root: Path, expected: bytes | None) -> None:
    reader = _WindowsRecordFiles(root)
    accepted = False
    try:
        reader.prepare(create=False)
        snapshot = reader.read("fixture-record")
        accepted = snapshot is not None
        if accepted:
            assert expected is not None and snapshot.payload == expected
    except LocalRecordError:
        pass
    finally:
        reader.close()
    assert accepted == (expected is not None), "Python reference admission changed"
    result = subprocess.run([str(EXE), str(root)], capture_output=True, timeout=10)
    if expected is not None:
        digest = hashlib.sha256(expected).hexdigest()
        assert result.returncode == 0 and not result.stderr
        assert result.stdout.decode().strip() == f"{len(expected)} {digest}"
    else:
        assert result.returncode == 1 and not result.stdout
        assert result.stderr == b"record admission failed\n", (
            "unredacted native failure"
        )


def scenario(parent: Path, kind: str) -> None:
    root = parent / kind
    files = _WindowsRecordFiles(root)
    changed: Path | None = None
    try:
        files.prepare(create=True)
        path = root / "fixture-record"
        expected = "公开测试数据🙂".encode()
        if kind == "boundary":
            expected = b"x" * 8192
        elif kind == "oversized":
            expected = b"x" * 8193
        fd = files.open("fixture-record", "new")
        try:
            assert os.write(fd, expected) == len(expected)
        finally:
            files.close_descriptor(fd)
        if kind.startswith(("root_", "record_")):
            target, acl_kind = kind.split("_", 1)
            changed = root if target == "root" else path
            set_dacl(changed, files.api, acl_kind)
        elif kind == "hardlink":
            os.link(path, root / "alias")
        verify(root, expected if kind in {"valid", "boundary"} else None)
    finally:
        if changed is not None:
            set_dacl(changed, files.api, "private")
        files.close()


def combined_record(parent: Path, mode: str) -> None:
    root = parent / f"combined-{mode}"
    files = _WindowsRecordFiles(root)
    selected_profile = "local-detachable-execution/v1"
    payload = json.loads(
        (ROOT / "gui/contracts/fixtures/local-record.json").read_bytes()
    )
    if mode == "endpoint":
        payload["endpoint"] = "other"
    elif mode == "profile":
        selected_profile = "local-detachable/v1"
    name = hashlib.sha256(b"workspace").hexdigest() + ".json"
    try:
        files.prepare(create=True)
        fd = files.open(name, "new")
        try:
            raw = json.dumps(payload).encode()
            assert os.write(fd, raw) == len(raw)
        finally:
            files.close_descriptor(fd)
        if mode == "acl":
            set_dacl(root / name, files.api, "world")
        reader = LocalConnectionDirectoryV1(root)
        expected = None
        try:
            record = reader.read("workspace")
            if record.semantic_profile.value == selected_profile:
                public = dict(payload)
                del public["key"]
                expected = {
                    "public": public,
                    "semanticProfile": selected_profile,
                    "recordDigest": record.authentication.record_digest.hex(),
                    "filename": name,
                }
        except LocalRecordError:
            pass
        finally:
            reader.close()
        assert (expected is not None) == (mode == "valid")
        result = subprocess.run(
            [str(EXE), "--decode-record", str(root), "workspace", selected_profile],
            capture_output=True,
            timeout=10,
        )
        if expected is not None:
            assert result.returncode == 0 and not result.stderr
            assert json.loads(result.stdout) == expected
        else:
            assert result.returncode == 1 and not result.stdout
            assert result.stderr == b"record admission failed\n"
    finally:
        if mode == "acl":
            set_dacl(root / name, files.api, "private")
        files.close()


def junction(parent: Path) -> None:
    target, link = parent / "valid", parent / "junction"
    command = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
    subprocess.run(
        [str(command), "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
        timeout=10,
    )
    try:
        verify(link, None)
    finally:
        # Remove the junction itself, never recursively traverse its target.
        link.rmdir()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Native Windows record admission check requires Windows")
    cargo = Path.home() / ".cargo/bin/cargo.exe"
    subprocess.run(
        [
            str(cargo),
            "+1.98.1",
            "build",
            "--locked",
            "--offline",
            "--manifest-path",
            str(CRATE / "Cargo.toml"),
            "--bin",
            "record_probe",
        ],
        check=True,
        cwd=ROOT,
    )
    kinds = (
        "valid",
        "boundary",
        "oversized",
        "hardlink",
        "root_world",
        "root_null",
        "root_unprotected",
        "record_world",
        "record_null",
        "record_unprotected",
    )
    with tempfile.TemporaryDirectory(prefix="gui-record-contract-") as temporary:
        parent = Path(temporary).resolve()
        for kind in kinds:
            scenario(parent, kind)
            print(f"Windows record admission: {kind} passed", flush=True)
        junction(parent)
        print("Windows record admission: junction passed")
        for mode in ("valid", "endpoint", "profile", "acl"):
            combined_record(parent, mode)
            print(f"Combined record admission: {mode} passed")
    print("Native Rust/Python record admission: 15 scenarios passed")
