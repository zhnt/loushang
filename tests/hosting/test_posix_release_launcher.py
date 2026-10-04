"""Native check of the checked-in Linux H6 launcher release source."""

from __future__ import annotations

import json
import os
import platform
import select
import shutil
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_product_worker_installed_native import (
    CodingLinuxInstalledWorkerReleaseReader,
)
from loushang.coding.package_product_worker_native_release import (
    CodingLinuxWorkerReleaseCatalogReader,
    CodingWorkerNativeReleaseError,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from tests.hosting.test_posix_launch_preparation import (
    _compile_containment_payload,
)

_BUILDER = (
    Path(__file__).resolve().parents[2]
    / "scripts/dev/build_posix_containment_launcher.py"
)
_WHEEL_BUILDER = (
    Path(__file__).resolve().parents[2]
    / "scripts/dev/build_posix_native_release_wheel.py"
)


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="Linux x86-64 native launcher",
)
def test_checked_in_launcher_build_and_native_containment(tmp_path: Path) -> None:
    release = tmp_path / "release"
    built = subprocess.run(
        (sys.executable, str(_BUILDER), "--output-dir", str(release)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    catalog = json.loads(built.stdout)
    assert json.loads((release / "catalog.json").read_text()) == catalog
    launcher = release / "containment-launcher"
    assert sha256(launcher.read_bytes()).hexdigest() == catalog["launcherSha256"]
    repeated = subprocess.run(
        (sys.executable, str(_BUILDER), "--output-dir", str(release)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert repeated.returncode == 1
    assert sha256(launcher.read_bytes()).hexdigest() == catalog["launcherSha256"]
    payload = tmp_path / "payload"
    _compile_containment_payload(payload, marker="release-source")

    launcher_fd = os.open(launcher, os.O_RDONLY)
    payload_fd = os.open(payload, os.O_RDONLY)
    cwd_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        def invoke(profile_digest: str) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                (
                    str(launcher),
                    "--loushang-protocol",
                    "loushang-static-containment-launch/v1",
                    "--loushang-profile-sha256",
                    profile_digest,
                    "--loushang-payload-fd",
                    str(payload_fd),
                    "--loushang-preparation-fds",
                    f"{launcher_fd},{payload_fd},{cwd_fd}",
                    "--",
                    str(payload),
                ),
                cwd=tmp_path,
                input=b"release",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(launcher_fd, payload_fd, cwd_fd),
                timeout=10,
                check=False,
            )

        refused = invoke("0" * 64)
        assert refused.returncode == 87
        assert refused.stdout == b""
        accepted = invoke(str(catalog["profileSourceSha256"]))
        assert accepted.returncode == 0, (accepted.stdout, accepted.stderr)
        assert accepted.stdout == (
            f"release-source:contained:{tmp_path.stat().st_ino}\n".encode()
        )
    finally:
        os.close(cwd_fd)
        os.close(payload_fd)
        os.close(launcher_fd)

    reader = CodingLinuxWorkerReleaseCatalogReader(
        release_root=release,
        gc_gate=PluginPackageGcReservationJournal(tmp_path / "gc.jsonl"),
    )
    closure = reader.current_closure()
    assert closure.native_platform == "linux-x86_64"
    assert closure.containment_launcher_digest == catalog["launcherSha256"]
    assert closure.containment_profile_digest == catalog["profileSourceSha256"]
    assert closure.native_profile_catalog_revision.startswith("h6-linux:")
    wheels = []
    for output_name in ("wheels-one", "wheels-two"):
        packaged = subprocess.run(
            (
                sys.executable,
                str(_WHEEL_BUILDER),
                "--release-dir",
                str(release),
                "--wheel-dir",
                str(tmp_path / output_name),
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        assert packaged.returncode == 0, packaged.stderr
        wheels.append(Path(packaged.stdout.decode().strip()))
    assert wheels[0].name.endswith("-py3-none-linux_x86_64.whl")
    assert wheels[0].read_bytes() == wheels[1].read_bytes()
    with zipfile.ZipFile(wheels[0]) as archive:
        assert archive.read("loushang_h6_native/release/catalog.json") == (
            release / "catalog.json"
        ).read_bytes()
        launcher_member = "loushang_h6_native/release/containment-launcher"
        assert archive.read(launcher_member) == launcher.read_bytes()
        assert archive.getinfo(launcher_member).external_attr >> 16 & 0o777 == 0o500
        wheel_metadata = next(
            name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")
        )
        assert b"Tag: py3-none-linux_x86_64" in archive.read(wheel_metadata)
    repeated_wheel = subprocess.run(
        (
            sys.executable,
            str(_WHEEL_BUILDER),
            "--release-dir",
            str(release),
            "--wheel-dir",
            str(wheels[0].parent),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert repeated_wheel.returncode == 1
    installed = tmp_path / "installed"
    installed_wheel = subprocess.run(
        (
            "uv", "pip", "install", "--target", str(installed),
            "--link-mode", "copy", "--no-deps", "--no-index", str(wheels[0]),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
        env={**os.environ, "UV_CACHE_DIR": str(tmp_path / "uv-cache")},
    )
    assert installed_wheel.returncode == 0, installed_wheel.stderr
    installed.chmod(0o700)
    installed_launcher = installed / "loushang_h6_native/release/containment-launcher"
    assert sha256(installed_launcher.read_bytes()).hexdigest() == catalog["launcherSha256"]
    assert installed_launcher.stat().st_mode & 0o100
    installed_reader = CodingLinuxInstalledWorkerReleaseReader(
        installation_root=installed,
        gc_gate=reader.gc_gate,
    )
    assert installed_reader.current_closure() == closure

    installed_bytes = installed_launcher.read_bytes()
    installed_launcher.write_bytes(b"changed installed launcher")
    with pytest.raises(CodingWorkerNativeReleaseError):
        installed_reader.current_closure()
    installed_launcher.write_bytes(installed_bytes)
    assert installed_reader.current_closure() == closure
    extra = installed / "loushang_h6_native/release/extra-worker"
    extra.write_bytes(b"extra executable")
    with pytest.raises(CodingWorkerNativeReleaseError):
        installed_reader.current_closure()
    extra.unlink()
    assert installed_reader.current_closure() == closure
    metadata_path = next(installed.glob("*.dist-info/METADATA"))
    metadata_bytes = metadata_path.read_bytes()
    metadata_path.write_bytes(metadata_bytes + b"Changed: yes\n")
    with pytest.raises(CodingWorkerNativeReleaseError):
        installed_reader.current_closure()
    metadata_path.write_bytes(metadata_bytes)
    assert installed_reader.current_closure() == closure
    installed.chmod(0o755)
    with pytest.raises(CodingWorkerNativeReleaseError):
        installed_reader.current_closure()
    installed.chmod(0o700)
    launcher_bytes = launcher.read_bytes()
    launcher.unlink()
    launcher.write_bytes(b"changed launcher")
    launcher.chmod(0o500)
    with pytest.raises(CodingWorkerNativeReleaseError):
        reader.current_closure()
    refused_wheel = subprocess.run(
        (
            sys.executable, str(_WHEEL_BUILDER), "--release-dir", str(release),
            "--wheel-dir", str(tmp_path / "tampered-wheels"),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert refused_wheel.returncode == 1
    assert not (tmp_path / "tampered-wheels").exists()
    launcher.unlink()
    launcher.write_bytes(launcher_bytes)
    launcher.chmod(0o500)
    (release / "catalog.json").unlink()
    (release / "catalog.json").symlink_to(tmp_path / "foreign-catalog")
    with pytest.raises(CodingWorkerNativeReleaseError):
        reader.current_closure()
    refused_symlink = subprocess.run(
        (
            sys.executable, str(_WHEEL_BUILDER), "--release-dir", str(release),
            "--wheel-dir", str(tmp_path / "symlink-wheels"),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert refused_symlink.returncode == 1
    assert not (tmp_path / "symlink-wheels").exists()


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="Linux x86-64 native launcher",
)
def test_checked_in_launcher_keeps_descendants_in_original_group(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.fail("H6 native profile requires a C compiler")
    release = tmp_path / "release"
    built = subprocess.run(
        (sys.executable, str(_BUILDER), "--output-dir", str(release)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    catalog = json.loads(built.stdout)
    source = tmp_path / "group-escape.c"
    payload = tmp_path / "group-escape"
    source.write_text(
        r'''
#define _GNU_SOURCE
#include <errno.h>
#include <linux/sched.h>
#include <signal.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
int main(void) {
    int status;
    pid_t child;
    if (syscall(SYS_unshare, CLONE_NEWNS) != -1 || errno != EPERM) return 10;
    if (syscall(SYS_setns, -1, 0) != -1 || errno != EPERM) return 11;
    if (syscall(SYS_clone3, (void *)0, 0) != -1 || errno != ENOSYS) return 12;
    if (syscall(SYS_clone, CLONE_NEWNS | SIGCHLD, (void *)0) != -1 ||
        errno != EPERM) return 13;
    if (setsid() != -1 || errno != EPERM) return 14;
    if (setpgid(0, 0) != -1 || errno != EPERM) return 15;
    child = fork();
    if (child < 0) return 16;
    if (child == 0) _exit(0);
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) ||
        WEXITSTATUS(status) != 0) return 17;
    return 0;
}
''',
        encoding="utf-8",
    )
    compiled = subprocess.run(
        (compiler, "-static", "-O2", "-s", "-o", str(payload), str(source)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    launcher = release / "containment-launcher"
    launcher_fd = os.open(launcher, os.O_RDONLY)
    payload_fd = os.open(payload, os.O_RDONLY)
    cwd_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        checked = subprocess.run(
            (
                str(launcher),
                "--loushang-protocol",
                "loushang-static-containment-launch/v1",
                "--loushang-profile-sha256",
                str(catalog["profileSourceSha256"]),
                "--loushang-payload-fd",
                str(payload_fd),
                "--loushang-preparation-fds",
                f"{launcher_fd},{payload_fd},{cwd_fd}",
                "--",
                str(payload),
            ),
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(launcher_fd, payload_fd, cwd_fd),
            timeout=10,
            check=False,
        )
        assert checked.returncode == 0, (checked.returncode, checked.stderr)
    finally:
        os.close(cwd_fd)
        os.close(payload_fd)
        os.close(launcher_fd)


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="Linux x86-64 native launcher",
)
def test_checked_in_launcher_gated_v2_waits_for_parent_release(tmp_path: Path) -> None:
    release = tmp_path / "release"
    built = subprocess.run(
        (sys.executable, str(_BUILDER), "--output-dir", str(release)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    catalog = json.loads(built.stdout)
    launcher = release / "containment-launcher"
    payload = tmp_path / "payload"
    _compile_containment_payload(payload, marker="gated-release")
    launcher_fd = os.open(launcher, os.O_RDONLY)
    payload_fd = os.open(payload, os.O_RDONLY)
    cwd_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for token, expected_code in ((b"S", 0), (b"X", 88), (b"", 88)):
            gate_read, gate_write = os.pipe2(os.O_CLOEXEC)
            process: subprocess.Popen[bytes] | None = None
            try:
                process = subprocess.Popen(
                    (
                        str(launcher),
                        "--loushang-protocol",
                        "loushang-static-containment-launch/v2",
                        "--loushang-profile-sha256",
                        str(catalog["profileSourceSha256"]),
                        "--loushang-payload-fd",
                        str(payload_fd),
                        "--loushang-preparation-fds",
                        f"{launcher_fd},{payload_fd},{cwd_fd}",
                        "--loushang-start-gate-fd",
                        str(gate_read),
                        "--",
                        str(payload),
                    ),
                    cwd=tmp_path,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    pass_fds=(launcher_fd, payload_fd, cwd_fd, gate_read),
                )
                os.close(gate_read)
                gate_read = -1
                assert process.stdin is not None
                assert process.stdout is not None
                process.stdin.write(b"release")
                process.stdin.flush()
                assert not select.select((process.stdout,), (), (), 0.2)[0]
                if token:
                    assert os.write(gate_write, token) == 1
                os.close(gate_write)
                gate_write = -1
                process.stdin.close()
                process.stdin = None
                stdout, stderr = process.communicate(timeout=10)
                assert process.returncode == expected_code, stderr
                assert stdout == (
                    f"gated-release:contained:{tmp_path.stat().st_ino}\n".encode()
                    if expected_code == 0
                    else b""
                )
            finally:
                if gate_read >= 0:
                    os.close(gate_read)
                if gate_write >= 0:
                    os.close(gate_write)
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
    finally:
        os.close(cwd_fd)
        os.close(payload_fd)
        os.close(launcher_fd)
