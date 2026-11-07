"""Linux portable-package entry point; delegates runtime ownership to AppHost."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Loushang GUI with bundled AppHost")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--state-root", type=Path, help="private desktop state directory"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--start-only", action="store_true")
    actions.add_argument("--stop", action="store_true")
    actions.add_argument("--status", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve(strict=True)
    if not workspace.is_dir():
        parser.error("workspace must be a directory")
    package = Path(__file__).resolve().parent
    key = hashlib.sha256(os.fsencode(workspace)).hexdigest()
    base = args.state_root or (
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        / "loushang/desktop/v1"
    )
    base = base.expanduser().absolute()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = base / key
    root.mkdir(exist_ok=True, mode=0o700)
    info = root.lstat()
    if root.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        parser.error("desktop state must be an owner-only directory, not a symlink")
    command = [
        sys.executable,
        "-I",
        "-m",
        "loushang.coding.cli.mux",
        "--connection-root",
        str(root / "connection"),
        "--endpoint",
        "workspace",
    ]

    def cli(*arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            command + list(arguments), capture_output=True, text=True, timeout=20
        )

    # Serializes this package's startup attempts without stopping a shared host
    # when one GUI window exits. Kernel releases the lock after crashes.
    lock_fd = os.open(
        root / "launcher.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.stop or args.status:
            result = cli("stop" if args.stop else "list")
            print(result.stdout or result.stderr, end="")
            return result.returncode
        current = cli("list")
        if current.returncode:
            log_fd = os.open(
                root / "apphost.log",
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(log_fd, "a") as log:
                host = subprocess.Popen(
                    command
                    + [
                        "serve",
                        "--workspace",
                        str(workspace),
                        "--application-root",
                        str(root / "application"),
                        "--application-id",
                        "coding.desktop",
                        "--cwd-sessions",
                        str(root / "cwd-sessions"),
                        "--home-sessions",
                        str(root / "home-sessions"),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    cwd=workspace,
                    start_new_session=True,
                )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if host.poll() is not None:
                    raise RuntimeError(
                        f"AppHost exited; inspect {root / 'apphost.log'}"
                    )
                current = cli("list")
                if current.returncode == 0:
                    break
                time.sleep(0.2)
            else:
                host.terminate()
                try:
                    host.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    host.kill()
                    host.wait()
                raise RuntimeError(
                    f"AppHost startup timed out; inspect {root / 'apphost.log'}"
                )
        muxes = json.loads(current.stdout)
        # The management CLI emits a list wrapper; don't clear or replace state.
        if not any(mux["name"] == "desktop" for mux in muxes["muxes"]):
            created = cli("create", "desktop")
            if created.returncode:
                raise RuntimeError(
                    "Could not create desktop mux: " + created.stderr.strip()
                )
    if args.start_only:
        print(f"AppHost ready for {workspace}")
        return 0
    return subprocess.call(
        [
            str(package / "bin/harness-gui"),
            "--loushang-app-record-root",
            str(root / "connection"),
            "--loushang-mux-name",
            "desktop",
        ],
        cwd=workspace,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Loushang: {error}", file=sys.stderr)
        raise SystemExit(1) from None
