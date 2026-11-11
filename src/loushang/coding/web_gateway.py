"""Web/desktop adapter process. Stdio is private to the development server.

No fixture fallback. Closing this adapter releases clients, never stops Hosts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from loushang.appserver.local import LocalAppClientConnectionV1
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalRecordError,
    LocalRecordErrorCodeV1,
)

from .client_settings import remember_workspace, settings_request
from .gui_local_host import operate
from .web_client import WebHostClient


@dataclass(frozen=True)
class ExternalHost:
    workspace: Path
    record_root: Path
    mux_name: str

    async def operate(self, request: dict) -> dict:
        reply = {
            "version": "gui-local-host/v1",
            "supported": True,
            "workspace": request["workspace"],
            "state": "not_running",
            "errorCode": None,
        }
        if request["workspace"] != str(self.workspace):
            return {**reply, "errorCode": "workspace_not_configured"}
        if request["action"] not in {"status", "connect"}:
            return {**reply, "errorCode": "external_service_managed"}
        directory = LocalConnectionDirectoryV1(self.record_root)
        connection = LocalAppClientConnectionV1(
            directory, "workspace", expected_product_id="coding"
        )
        try:
            await connection.start()
            execution = connection.execution_client
            if execution is None:
                return {**reply, "errorCode": "protocol_incompatible"}
            instance = execution.service_instance_id
            return {
                **reply,
                "state": "running",
                "instanceId": instance,
                "serviceInstanceId": instance,
                "recordRoot": str(self.record_root),
                "muxName": self.mux_name,
            }
        except LocalRecordError as error:
            if error.code is not LocalRecordErrorCodeV1.NOT_FOUND:
                raise
            return reply
        finally:
            try:
                await connection.close()
            finally:
                directory.close()


class WebGateway:
    def __init__(self, external_host: ExternalHost | None = None):
        self.clients: dict[str, WebHostClient] = {}
        self.management = asyncio.Lock()
        self.operate = external_host.operate if external_host is not None else operate

    async def close(self):
        for client in self.clients.values():
            async with client.lock:
                await client.close()
        self.clients.clear()

    async def dispatch(self, request: dict):
        operation = request.get("operation")
        if operation in {"environment", "preferences", "remember-workspace"}:
            return await asyncio.to_thread(settings_request, request)
        if operation == "account":
            import getpass

            return {"name": getpass.getuser(), "id": None}
        workspace = request.get("workspace")
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            raise ValueError("invalid_workspace")
        workspace = str(Path(workspace).resolve())
        if operation == "manage":
            async with self.management:
                action = request.get("action")
                result = await self.operate(
                    {
                        "action": action,
                        "workspace": workspace,
                        **(
                            {"instanceId": request["instanceId"]}
                            if request.get("instanceId")
                            else {}
                        ),
                    }
                )
                if (
                    action in {"connect", "start", "restart"}
                    and result.get("state") == "running"
                    and not result.get("errorCode")
                ):
                    if workspace not in self.clients and len(self.clients) >= 6:
                        raise ValueError("connection_limit")
                    previous = self.clients.get(workspace)
                    previous_execution = (
                        previous.connection.execution_client if previous is not None else None
                    )
                    healthy = False
                    if (
                        previous is not None
                        and previous_execution is not None
                        and previous_execution.service_instance_id == result["serviceInstanceId"]
                    ):
                        try:
                            await previous.call("snapshot", {})
                            healthy = True
                        except Exception:
                            pass
                    if not healthy:
                        self.clients.pop(workspace, None)
                        if previous:
                            async with previous.lock:
                                await previous.close()
                        client = WebHostClient(
                            Path(result["recordRoot"]), result["muxName"]
                        )
                        await client.start()
                        self.clients[workspace] = client
                    await asyncio.to_thread(remember_workspace, workspace)
                if action == "stop" and result.get("state") == "not_running":
                    previous = self.clients.pop(workspace, None)
                    if previous:
                        async with previous.lock:
                            await previous.close()
                return {
                    key: value
                    for key, value in result.items()
                    if key not in {"recordRoot", "muxName"}
                }
        if operation == "live":
            client = self.clients.get(workspace)
            if not client:
                raise ValueError("not_connected")
            return await client.call(request["action"], request.get("input", {}))
        raise ValueError("unknown_operation")


async def run_stdio(external_host: ExternalHost | None = None):
    tasks = set()
    gateway = WebGateway(external_host)

    async def handle(raw):
        identifier = None
        try:
            request = json.loads(raw)
            identifier = request["id"]
            async with asyncio.timeout(75):
                result = await gateway.dispatch(request["request"])
            reply = {"id": identifier, "result": result}
        except Exception as error:
            # Never disclose paths, provider secrets, request text or raw exceptions.
            code = getattr(getattr(error, "code", None), "value", None)
            reply = {"id": identifier, "error": code or "host_request_failed"}
        print(json.dumps(reply), flush=True)

    try:
        while raw := await asyncio.to_thread(sys.stdin.buffer.readline, 1_048_577):
            if len(raw) > 1_048_576 or len(tasks) >= 64:
                break
            task = asyncio.create_task(handle(raw))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)
        await gateway.close()


if __name__ == "__main__":
    import argparse
    from contextlib import suppress

    parser = argparse.ArgumentParser(description="Private GUI Host request adapter")
    parser.add_argument("--external-host", nargs=3)
    args = parser.parse_args()
    external = None
    if args.external_host:
        workspace, record_root, mux = args.external_host
        external = ExternalHost(Path(workspace).resolve(), Path(record_root).resolve(), mux)
    with suppress(KeyboardInterrupt):
        asyncio.run(run_stdio(external))
