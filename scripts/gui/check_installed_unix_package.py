"""Install, reinstall and remove a Full DEB, RPM or PKG on a disposable hosted runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

APP = Path("/Applications/loushang-gui.app")
RECEIPT = "ai.loushang.full"
MAC_ENTRIES = ("loushang", "loushang-gui", "loushang-host", "loushang-mux", "loushang-web")
ROOT = Path(__file__).resolve().parents[2]


def run(*args: object, **kwargs: object) -> str:
    argv = [str(arg) for arg in args]
    print("+", *argv, flush=True)
    try:
        return subprocess.check_output(argv, text=True, timeout=180, **kwargs).strip()
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, flush=True)
        raise


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def verify_gui(binary: Path, cwd: Path, env: dict, evidence: Path, linux: bool) -> None:
    if not linux and (
        Path("/dev/console").stat().st_uid != os.getuid()
        or subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}"],
                          capture_output=True, timeout=15).returncode
    ):
        print("NOT VERIFIED: no macOS graphical login session")
        return
    with (evidence / "gui.log").open("w") as log:
        gui = subprocess.Popen([str(binary)], cwd=cwd, env=env, stdout=log, stderr=log)
        try:
            if linux:
                for _ in range(60):
                    assert gui.poll() is None, f"GUI exited: {gui.returncode}"
                    result = subprocess.run(
                        ["/usr/bin/xdotool", "search", "--onlyvisible", "--pid", str(gui.pid)],
                        env=env, capture_output=True, timeout=5,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        print("PASS: visible GUI window under Xvfb")
                        break
                    sleep(0.5)
                else:
                    raise RuntimeError("No visible GUI window under Xvfb")
            else:
                sleep(8)
                assert gui.poll() is None, f"GUI exited: {gui.returncode}"
                print("PASS: GUI started in macOS graphical session; window interaction not verified")
        finally:
            stop_process(gui)


def session_round_trip(web: Path, state: Path, cwd: Path, env: dict,
                       evidence: Path, phase: str, register: bool) -> dict:
    endpoint = state / "state/web/endpoint.json"
    endpoint.unlink(missing_ok=True)
    with (evidence / f"web-{phase}.log").open("w") as log:
        process = subprocess.Popen([str(web)], cwd=cwd, env=env, stdout=log, stderr=log)
        try:
            deadline = monotonic() + 30
            while not endpoint.exists() and process.poll() is None and monotonic() < deadline:
                sleep(0.1)
            assert endpoint.is_file(), "Web did not publish its endpoint"
            url = json.loads(endpoint.read_text())["url"]

            def call(operation: str, **fields: object) -> dict:
                request = Request(
                    f"{url}/api/loushang",
                    data=json.dumps({"operation": operation, **fields}).encode(),
                    headers={"X-Loushang-Client": "1", "Content-Type": "application/json"},
                )
                try:
                    with urlopen(request, timeout=45) as response:
                        return json.load(response)["result"]
                except HTTPError as error:
                    raise RuntimeError(
                        f"{operation}/{fields.get('action')}: HTTP {error.code} "
                        f"{error.read().decode(errors='replace')}"
                    ) from error

            with urlopen(url, timeout=10) as page:
                assert "text/html" in page.headers["Content-Type"] and b"<html" in page.read()
            assert call("manage", action="connect")["state"] == "running"
            workspace = "default"
            if register:
                created = call("workspace", action="create-chat", path=workspace,
                               title="Installer acceptance Session")
                assert created["sessionId"], created
            view = str(uuid4())
            snap = call("live", action="snapshot", workspace=str(workspace), viewId=view)
            identity = snap["sessions"][0]["executions"]["identity"]
            call("live", action="close", workspace=str(workspace), viewId=view)
            call("shutdown-adapter")
            assert process.wait(timeout=15) == 0
            print(f"PASS: installed Web connected to AppHost ({phase})")
            return identity
        finally:
            stop_process(process)


def verify_elf_payload(resources: Path, arch: str, programs: tuple[Path, ...]) -> None:
    machine = {"x86_64": 62, "aarch64": 183}[arch]
    native = set()
    for path in resources.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            header = stream.read(20)
        if header.startswith(b"\x7fELF"):
            assert header[4:6] == b"\x02\x01" and struct.unpack_from("<H", header, 18)[0] == machine, path
            native.add(path)
    for program in programs:
        assert program.resolve() in native, program


def verify(args: argparse.Namespace) -> None:
    linux = sys.platform == "linux"
    assert linux or sys.platform == "darwin"
    assert os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get(
        "RUNNER_ENVIRONMENT",
    ) == "github-hosted", "This check modifies system installation paths on a disposable hosted runner"
    native = {"arm64": "aarch64"}.get(platform.machine(), platform.machine())
    assert args.arch == native, (args.arch, native)
    deb_arch = {"x86_64": "amd64", "aarch64": "arm64"}[args.arch]
    mac_arch = "arm64" if args.arch == "aarch64" else args.arch
    package = args.package.resolve(strict=True)
    rpm = linux and package.suffix == ".rpm"
    if rpm:
        release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines()
                       if "=" in line)
        assert release.get("ID") == "fedora" and release.get("VERSION_ID") == "43", release
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    control = Path("/opt/loushang") if linux else APP
    entries = Path("/usr/bin" if linux else "/usr/local/bin")
    mux = entries / "loushang-mux"
    assert not control.exists() and not mux.exists(), "Existing installation found"
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    with package.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert package.with_name(package.name + ".sha256").read_text().strip() == f"{digest}  {package.name}"
    if linux:
        if rpm:
            assert run("rpm", "-qp", "--qf", "%{NAME}:%{VERSION}:%{ARCH}", package) == (
                f"loushang:{version}:{args.arch}"
            )
        else:
            assert run("dpkg-deb", "-f", package, "Package", "Version", "Architecture").splitlines() == [
                "Package: loushang", f"Version: {version}", f"Architecture: {deb_arch}",
            ]
        resources = control
        web = control / "bin/loushang-web"
        gui = entries / "loushang"
        tui = entries / "loushang-tui"
    else:
        assert all(not (entries / name).exists() for name in MAC_ENTRIES)
        assert run("/usr/bin/file", "-b", package).startswith("xar archive")
        resources = APP / "Contents/Resources"
        web = entries / "loushang-web"
        gui = entries / "loushang-gui"
        tui = entries / "loushang"
    python = resources / "runtime/bin/python3"
    print("PASS: installer format and SHA-256", flush=True)

    with tempfile.TemporaryDirectory(prefix="loushang-installed-") as temporary:
        cwd = Path(temporary).resolve()
        state = cwd / "product-home"
        state.mkdir(mode=0o700)
        env = {name: os.environ[name] for name in (
            "HOME", "USER", "TMPDIR", "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
        ) if name in os.environ}
        env.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin", LOUSHANG_HOME=str(state))
        config = state / "host.json"
        config_text = '{"web":{"port":0,"manageLocal":true}}\n'
        expected_identity = None
        try:
            for phase in ("clean", "reinstall"):
                if linux:
                    if rpm:
                        if phase == "clean":
                            run("sudo", "-n", "dnf", "install", "-y", package)
                        else:
                            run("sudo", "-n", "rpm", "-U", "--replacepkgs", package)
                        assert run("rpm", "-q", "--qf", "%{VERSION}:%{ARCH}", "loushang") == (
                            f"{version}:{args.arch}"
                        )
                    else:
                        run("sudo", "-n", "apt-get", "install", "-y",
                            *(("--reinstall",) if phase == "reinstall" else ()), package)
                        assert run("dpkg-query", "-W", "-f=${Version}", "loushang") == version
                else:
                    run("sudo", "-n", "/usr/sbin/installer", "-verboseR", "-pkg", package, "-target", "/")
                    receipt = plistlib.loads(run("/usr/sbin/pkgutil", "--pkg-info-plist", RECEIPT).encode())
                    assert receipt["pkg-version"] == version, receipt
                    info = plistlib.loads((APP / "Contents/Info.plist").read_bytes())
                    assert info["CFBundleShortVersionString"] == version, info
                    run("/usr/bin/codesign", "--verify", "--deep", "--strict", APP)

                manifest = json.loads((resources / "manifest.json").read_text())
                assert manifest["commit"] == args.commit and manifest["version"] == version
                assert manifest["architecture"] == (args.arch if linux else f"{args.arch}-apple-darwin")
                assert not any((resources / name).exists() for name in (
                    ".git", ".venv", ".loushang", "node_modules", "src",
                ))
                for name in ("LICENSE", "NOTICE", "web/index.html"):
                    assert (resources / name).is_file(), name
                for path in (gui, tui, mux, web, python):
                    assert path.is_file() and os.access(path, os.X_OK), path
                if linux:
                    verify_elf_payload(resources, args.arch, (gui, resources / "bin/harness-gui", web, python))
                else:
                    for program in (gui, web, tui, python):
                        assert mac_arch in run("/usr/bin/lipo", "-archs", program).split(), program
                try:
                    run(python, "-I", "-c", (
                        "import importlib.metadata as m, loushang.coding, sys;"
                        "from pathlib import Path;"
                        "assert m.version('loushang') == sys.argv[1];"
                        "assert Path(loushang.coding.__file__).resolve().is_relative_to(Path(sys.prefix).resolve());"
                        "print(m.version('loushang'))"
                    ), version, cwd=cwd, env=env)
                    if rpm:
                        run(python, "-I", "-c", (
                            "from io import BytesIO; from PIL import Image;"
                            "im = Image.new('RGB', (2, 2));"
                            "[im.save(BytesIO(), fmt) for fmt in ('JPEG', 'PNG', 'TIFF')]"
                        ), cwd=cwd, env=env)
                    run(tui, "--help" if linux else "--version", cwd=cwd, env=env)
                    if not linux:
                        run(entries / "loushang-host", "--help", cwd=cwd, env=env)
                    if phase == "clean":
                        config.write_text(config_text)
                    else:
                        assert config.read_text() == config_text
                    before = json.loads(run(mux, "service", "status", "--json", cwd=cwd, env=env))
                    assert before["state"] == "not_running", before
                    host = json.loads(run(mux, "service", "start", "--json", cwd=cwd, env=env))
                    assert host["state"] == "running", host
                    identity = session_round_trip(web, state, cwd, env, evidence, phase,
                                                  register=phase == "clean")
                    if phase == "clean":
                        expected_identity = identity
                    else:
                        assert identity == expected_identity, (identity, expected_identity)
                        verify_gui(gui, cwd, env, evidence, linux)
                finally:
                    stopped = json.loads(run(mux, "service", "stop", "--json", cwd=cwd, env=env))
                    assert stopped["state"] == "not_running", stopped
                print(f"PASS: {phase} install, CLI and AppHost lifecycle")
                if phase == "clean":
                    run("sudo", "-n", "rm", resources / "web/index.html")
        finally:
            if linux:
                if control.exists():
                    if rpm:
                        run("sudo", "-n", "dnf", "remove", "--no-autoremove", "-y", "loushang")
                    else:
                        run("sudo", "-n", "apt-get", "remove", "-y", "loushang")
            elif APP.exists():
                host_log = state / "state/macos-host/host.log"
                if host_log.is_file():
                    shutil.copyfile(host_log, evidence / "host.log")
                # Apple Installer has no uninstall command. Remove this PKG's
                # exact installed paths, then remove its receipt.
                run("sudo", "-n", "/bin/rm", "-rf", APP)
                run("sudo", "-n", "/bin/rm", "-f", *(entries / name for name in MAC_ENTRIES))
                run("sudo", "-n", "/usr/sbin/pkgutil", "--forget", RECEIPT)
        assert not control.exists() and not mux.exists() and not tui.exists()
        assert config.read_text() == config_text
        assert state.joinpath("data").is_dir(), "Session storage was removed"
        print("PASS: uninstall preserved configuration and session storage")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--arch", choices=("x86_64", "aarch64"), required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    verify(parser.parse_args())


if __name__ == "__main__":
    main()
