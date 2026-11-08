"""Opt-in POSIX Rust/Python private-record parity; temporary fixtures only."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from native_tools import cargo_path, native_binary

from loushang.appserver._posix_local_record import _PosixRecordFiles
from loushang.appserver.local_record import LocalRecordError

ROOT = Path(__file__).resolve().parents[2]
CRATE = ROOT / "gui/contracts/rust"
EXE = native_binary(CRATE / "target/debug", "record_probe")


def verify(root: Path, expected: bytes | None) -> None:
    reader = _PosixRecordFiles(root)
    accepted = False
    try:
        reader.prepare(create=False)
        snapshot = reader.read("fixture-record")
        accepted = snapshot is not None
        if accepted:
            assert expected is not None and snapshot.payload == expected
    except (LocalRecordError, OSError):
        pass
    finally:
        reader.close()
    assert accepted == (expected is not None), "Python reference admission changed"
    result = subprocess.run([str(EXE), str(root)], capture_output=True, timeout=5)
    if expected is None:
        assert result.returncode == 1 and not result.stdout
        assert result.stderr == b"record admission failed\n"
    else:
        assert result.returncode == 0 and not result.stderr
        assert result.stdout.decode().strip() == (
            f"{len(expected)} {hashlib.sha256(expected).hexdigest()}"
        )


def scenario(parent: Path, kind: str) -> None:
    root = parent / kind
    root.mkdir(mode=0o700)
    path = root / "fixture-record"
    payload = "公开测试数据🙂".encode()
    if kind == "boundary":
        payload = b"x" * 8192
    elif kind == "oversized":
        payload = b"x" * 8193
    path.write_bytes(payload)
    path.chmod(0o600)
    if kind == "hardlink":
        os.link(path, root / "alias")
    elif kind == "record_symlink":
        path.rename(root / "actual")
        path.symlink_to(root / "actual")
    elif kind == "root_symlink":
        actual = root.with_name(kind + "-actual")
        root.rename(actual)
        root.symlink_to(actual, target_is_directory=True)
    elif kind == "directory_record":
        path.unlink()
        path.mkdir(mode=0o700)
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif kind == "missing":
        path.unlink()
    elif kind.startswith("root_mode_"):
        root.chmod(int(kind.removeprefix("root_mode_"), 8))
    elif kind.startswith("record_mode_"):
        path.chmod(int(kind.removeprefix("record_mode_"), 8))
    verify(root, payload if kind in {"valid", "boundary"} else None)


def main() -> None:
    subprocess.run(
        [
            str(cargo_path()),
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
    cases = (
        "valid",
        "boundary",
        "oversized",
        "hardlink",
        "record_symlink",
        "root_symlink",
        "directory_record",
        "fifo",
        "missing",
        "root_mode_750",
        "root_mode_707",
        "record_mode_640",
        "record_mode_604",
    )
    with tempfile.TemporaryDirectory(prefix="gui-posix-record-") as temporary:
        for kind in cases:
            scenario(Path(temporary).resolve(), kind)
            print(f"POSIX record admission: {kind} passed", flush=True)
    print(f"POSIX record admission: {len(cases)} parity scenarios passed")


if __name__ == "__main__":
    main()
