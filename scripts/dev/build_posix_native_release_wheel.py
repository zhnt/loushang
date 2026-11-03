"""Package a verified Linux H6 launcher release in a platform-tagged Wheel.

The Wheel is a native distribution candidate. Installation and Product
provenance remain separate gates; this command grants no Worker authority.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import stat
import sys
import tempfile
import zipfile
from base64 import urlsafe_b64encode
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from loushang.harness.worker.native_executable_format import (
    verify_worker_native_executable_format,
)

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _ROOT / "src/loushang/hosting/native/contained_launcher_linux_x86_64.c"
_DISTRIBUTION = "loushang_h6_native"
_PACKAGE = "loushang_h6_native"
_TAG = "py3-none-linux_x86_64"
_MAX_LAUNCHER_BYTES = 16 * 1024 * 1024


def build_wheel(release_dir: Path, wheel_dir: Path) -> Path:
    """Verify one generated release, then publish a deterministic native Wheel."""

    if sys.platform != "linux" or platform.machine().lower() not in {
        "x86_64",
        "amd64",
    }:
        raise RuntimeError("Linux x86-64 is required")
    release = release_dir.expanduser().absolute()
    root_fd = os.open(
        release, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        root = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root.st_mode)
            or root.st_uid != os.geteuid()
            or stat.S_IMODE(root.st_mode) & 0o077
        ):
            raise ValueError("Native release root is not private")
        catalog_bytes, _ = _read_regular_at(root_fd, "catalog.json", limit=4096)
        launcher, launcher_mode = _read_regular_at(
            root_fd, "containment-launcher", limit=_MAX_LAUNCHER_BYTES,
        )
    finally:
        os.close(root_fd)
    catalog = json.loads(catalog_bytes)
    source_digest = sha256(_SOURCE.read_bytes()).hexdigest()
    if (
        type(catalog) is not dict
        or set(catalog)
        != {
            "catalogVersion",
            "platform",
            "profileSourceSha256",
            "launcherSha256",
            "launcherFile",
            "buildFlags",
        }
        or type(catalog["catalogVersion"]) is not int
        or catalog["catalogVersion"] != 1
        or catalog["platform"] != "linux-x86_64"
        or catalog["profileSourceSha256"] != source_digest
        or catalog["launcherFile"] != "containment-launcher"
        or not isinstance(catalog["buildFlags"], list)
        or any(type(flag) is not str for flag in catalog["buildFlags"])
        or catalog_bytes
        != (json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ):
        raise ValueError("Native release catalog changed")
    if launcher_mode != 0o500:
        raise ValueError("Native release launcher mode changed")
    if sha256(launcher).hexdigest() != catalog["launcherSha256"]:
        raise ValueError("Native release launcher changed")
    verify_worker_native_executable_format(launcher, platform="linux-x86_64")

    release_version = version("loushang")
    dist_info = f"{_DISTRIBUTION}-{release_version}.dist-info"
    files = {
        f"{_PACKAGE}/__init__.py": (b"", 0o644),
        f"{_PACKAGE}/release/catalog.json": (catalog_bytes, 0o644),
        f"{_PACKAGE}/release/containment-launcher": (launcher, 0o500),
        f"{dist_info}/METADATA": (
            (
                "Metadata-Version: 2.1\n"
                "Name: loushang-h6-native\n"
                f"Version: {release_version}\n\n"
            ).encode("ascii"),
            0o644,
        ),
        f"{dist_info}/WHEEL": (
            (
                "Wheel-Version: 1.0\n"
                "Generator: loushang-h6-release\n"
                "Root-Is-Purelib: false\n"
                f"Tag: {_TAG}\n\n"
            ).encode("ascii"),
            0o644,
        ),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, (body, _) in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    record_name = f"{dist_info}/RECORD"
    writer.writerow((record_name, "", ""))
    files[record_name] = (record.getvalue().encode("utf-8"), 0o644)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, (body, mode) in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | mode) << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, body)

    destination = wheel_dir.expanduser().absolute()
    if destination == release or destination.is_relative_to(release):
        raise ValueError("Native Wheel output overlaps its release input")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{_DISTRIBUTION}-{release_version}-{_TAG}.whl"
    temporary: Path | None = None
    try:
        descriptor, raw = tempfile.mkstemp(prefix=".h6-wheel-", dir=destination)
        temporary = Path(raw)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(output.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
        directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def _read_regular_at(
    root_fd: int, name: str, *, limit: int
) -> tuple[bytes, int]:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_size > limit
        ):
            raise ValueError("Native release member is unsafe")
        body = bytearray()
        while chunk := os.read(descriptor, min(64 * 1024, limit + 1 - len(body))):
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError("Native release member exceeds budget")
        after = os.fstat(descriptor)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_mode != metadata.st_mode
            or after.st_size != metadata.st_size
            or after.st_mtime_ns != metadata.st_mtime_ns
            or after.st_ctime_ns != metadata.st_ctime_ns
        ):
            raise ValueError("Native release member changed")
        return bytes(body), stat.S_IMODE(metadata.st_mode)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = build_wheel(args.release_dir, args.wheel_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Linux H6 native Wheel build refused: {exc}\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
