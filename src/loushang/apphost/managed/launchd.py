"""Own a launchd-managed local AppHost through readiness and graceful stop."""

from __future__ import annotations

import asyncio
import json
import plistlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from loushang.appserver.local import LocalAppClientConnectionV1, LocalConnectionModeV1
from loushang.appserver.local_record import LocalConnectionDirectoryV1
from loushang.harness.machine_resources import prepare_private_directory_chain
from loushang.hosting.service_launchd import (
    LaunchdJobError as ManagedLaunchdServiceError,
)
from loushang.hosting.service_launchd import LaunchdUserJob

from ._files import ManagedStorageError, PrivateManagedDirectory


@dataclass(frozen=True, slots=True)
class ManagedLaunchdService:
    label: str
    product_id: str
    endpoint: str
    state_root: Path
    working_directory: Path
    launch_arguments: Callable[[], tuple[tuple[str, ...], dict[str, str]]]

    def control(self, operation: str, expected: str | None) -> dict[str, object]:
        if operation not in {"status", "start", "stop", "restart"}:
            raise ManagedLaunchdServiceError("operation_unavailable")
        job = LaunchdUserJob(self.label)
        if operation == "status":
            return self._status(job)
        prepare_private_directory_chain(self.state_root)
        storage = PrivateManagedDirectory(self.state_root, defer_open=True)
        try:
            try:
                storage.open()
            except ManagedStorageError as error:
                raise ManagedLaunchdServiceError("unsafe_state_directory") from error
            with storage.lock("control.lock", create=True):
                return self._control_locked(job, storage, operation, expected)
        except ManagedStorageError as error:
            code = "management_busy" if error.code == "busy" else "management_unavailable"
            raise ManagedLaunchdServiceError(code) from error
        finally:
            storage.close()

    def _control_locked(
        self, job: LaunchdUserJob, storage: PrivateManagedDirectory, operation: str, expected: str | None,
    ) -> dict[str, object]:
        previous = self._status(job)
        if expected is not None and previous.get("instanceId") != expected:
            raise ManagedLaunchdServiceError("instance_changed")
        if operation == "start" and previous["state"] == "running":
            return previous
        if operation in {"stop", "restart"} or previous["state"] == "exited":
            if previous["state"] == "running":
                # A stop acknowledgement precedes the native exit observation.
                asyncio.run(self._probe(str(previous["instanceId"]), stop=True))
                pid = previous.get("pid")
                if type(pid) is not int:
                    raise ManagedLaunchdServiceError("management_unavailable")
                job.wait_for_exit(pid)
            job.remove(was_registered=previous["state"] != "not_running")
        if operation == "stop":
            return {"state": "not_running"}
        job.bootstrap(self._write_plist(storage))
        deadline = monotonic() + 45
        while monotonic() < deadline:
            status = self._status(job)
            if status["state"] == "running":
                return status
            sleep(0.1)
        job.discard_after_start_timeout()
        raise ManagedLaunchdServiceError("start_failed")

    def _status(self, job: LaunchdUserJob) -> dict[str, object]:
        state, pid = job.observe()
        if pid is None:
            return {"state": state}
        try:
            endpoint = json.loads((self.state_root / "endpoint.json").read_text())
            if endpoint["pid"] != pid:
                return {"state": "starting"}
            instance = endpoint["instanceId"]
            service_instance = asyncio.run(self._probe(instance))
        except Exception:
            return {"state": "starting"}
        return {
            "state": "running", "pid": pid, "instanceId": instance,
            "serviceInstanceId": service_instance, "recordRoot": str(self.state_root / "connections"),
        }

    async def _probe(self, instance: str, *, stop: bool = False) -> str:
        directory = LocalConnectionDirectoryV1(self.state_root / "connections")
        connection = LocalAppClientConnectionV1(
            directory, self.endpoint, timeout=2,
            expected_product_id=self.product_id, expected_instance=instance,
            mode=LocalConnectionModeV1.STOP if stop else LocalConnectionModeV1.APP,
        )
        try:
            await connection.start()
            if stop:
                return ""
            execution = connection.execution_client
            if execution is None:
                raise ManagedLaunchdServiceError("protocol_incompatible")
            return execution.service_instance_id
        finally:
            await connection.close()
            directory.close()

    def _write_plist(self, storage: PrivateManagedDirectory) -> Path:
        arguments, environment = self.launch_arguments()
        payload = {
            "Label": self.label, "ProgramArguments": list(arguments),
            "WorkingDirectory": str(self.working_directory), "EnvironmentVariables": environment,
            "LimitLoadToSessionType": "Background", "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False}, "ExitTimeOut": 40, "ThrottleInterval": 5,
            "StandardOutPath": str(self.state_root / "host.log"),
            "StandardErrorPath": str(self.state_root / "host.log"),
        }
        name = "host.plist"
        storage.write(name, plistlib.dumps(payload), expected=storage.read(name))
        return self.state_root / name
