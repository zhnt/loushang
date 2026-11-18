"""Explicit per-user launchd management of the foreground Coding AppHost."""

from __future__ import annotations

import asyncio
import json
import os
import plistlib
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep

from loushang.apphost.managed._files import ManagedStorageError, PrivateManagedDirectory
from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.foundation.platform_paths import resolve_platform_home
from loushang.harness.machine_resources import prepare_private_directory_chain

from .managed_service import ServiceControlError

LAUNCHCTL = "/bin/launchctl"


def _launchctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [LAUNCHCTL, *arguments], capture_output=True, text=True, check=False, timeout=45,
    )


def _identity(home: Path) -> tuple[str, str]:
    label = "ai.loushang.host." + sha256(str(home).encode()).hexdigest()[:20]
    return label, f"user/{os.getuid()}/{label}"


async def _probe(record_root: Path, instance: str) -> str:
    directory = LocalConnectionDirectoryV1(record_root)
    connection = LocalAppClientConnectionV1(
        directory, "workspace", timeout=2, expected_product_id="coding", expected_instance=instance,
    )
    try:
        await connection.start()
        execution = connection.execution_client
        if execution is None:
            raise ServiceControlError("protocol_incompatible")
        return execution.service_instance_id
    finally:
        await connection.close()
        directory.close()


def _status(home: Path, target: str) -> dict[str, object]:
    printed = _launchctl("print", target)
    if printed.returncode:
        # Distinguish an absent job from an inaccessible/unavailable user domain.
        domain = target.rsplit("/", 1)[0]
        if _launchctl("print", domain).returncode:
            raise ServiceControlError("management_unavailable")
        return {"state": "not_running"}
    match = re.search(r"^\s*pid = ([0-9]+)\s*$", printed.stdout, re.MULTILINE)
    if match is None:
        return {"state": "exited"}
    pid = int(match[1])
    try:
        endpoint = json.loads((home / "state/macos-host/endpoint.json").read_text())
        if endpoint["pid"] != pid:
            return {"state": "starting"}
        instance = endpoint["instanceId"]
        record_root = home / "state/macos-host/connections"
        service_instance = asyncio.run(_probe(record_root, instance))
    except Exception:
        return {"state": "starting"}
    return {
        "state": "running", "pid": pid, "instanceId": instance,
        "serviceInstanceId": service_instance, "recordRoot": str(record_root),
    }


def _python() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "Resources/runtime/bin/python3"
    return Path(sys.executable)


def _write_agent(home: Path, label: str) -> Path:
    state = home / "state/macos-host"
    environment = {"LOUSHANG_HOME": str(home), "HOME": str(Path.home()),
                   "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"}
    # Provider credentials belong to launchd's environment or the user's normal
    # provider configuration. Never serialize inherited secrets into the plist.
    payload = {
        "Label": label,
        "ProgramArguments": [str(_python()), "-I", "-m", "loushang.coding.foreground_host"],
        "WorkingDirectory": str(home), "EnvironmentVariables": environment,
        "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
        "ExitTimeOut": 40, "ThrottleInterval": 5,
        "StandardOutPath": str(state / "host.log"),
        "StandardErrorPath": str(state / "host.log"),
    }
    agent = state / "host.plist"
    temporary = state / "host.plist.tmp"
    temporary.write_bytes(plistlib.dumps(payload))
    temporary.chmod(0o600)
    temporary.replace(agent)
    return agent


def _validate_state(state: Path) -> None:
    directory = PrivateManagedDirectory(state, create=False, defer_open=True)
    try:
        directory.open()
    except ManagedStorageError as error:
        raise ServiceControlError("unsafe_state_directory") from error
    finally:
        directory.close()


def control_launchd_service(operation: str, expected: str | None) -> dict[str, object]:
    import fcntl

    if operation not in {"status", "start", "stop", "restart"}:
        raise ServiceControlError("operation_unavailable")
    home = resolve_platform_home()
    label, target = _identity(home)
    if operation == "status":
        return _status(home, target)
    state_root = home / "state/macos-host"
    prepare_private_directory_chain(state_root)
    _validate_state(state_root)
    lock = os.open(state_root / "control.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ServiceControlError("management_busy") from error
        previous = _status(home, target)
        if expected is not None and previous.get("instanceId") != expected:
            raise ServiceControlError("instance_changed")
        if operation == "start" and previous["state"] == "running":
            return previous
        if operation in {"stop", "restart"} or previous["state"] == "exited":
            stopped = _launchctl("bootout", target)
            if stopped.returncode and previous["state"] != "not_running":
                raise ServiceControlError("stop_failed")
            if _launchctl("print", target).returncode == 0:
                raise ServiceControlError("stop_failed")
        if operation == "stop":
            return {"state": "not_running"}
        agent = _write_agent(home, label)
        if _launchctl("bootstrap", target.rsplit("/", 1)[0], str(agent)).returncode:
            raise ServiceControlError("start_failed")
        deadline = monotonic() + 45
        while monotonic() < deadline:
            status = _status(home, target)
            if status["state"] == "running":
                return status
            sleep(0.1)
        _launchctl("bootout", target)
        raise ServiceControlError("start_failed")
    finally:
        os.close(lock)


def print_logs() -> int:
    path = resolve_platform_home() / "state/macos-host/host.log"
    if not path.exists():
        return 0
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        print(stream.read(65536).decode("utf-8", errors="replace"), end="")
    return 0
