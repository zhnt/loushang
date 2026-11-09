"""Web/desktop adapter process. Stdio is private to the development server.

No fixture fallback. Closing this adapter releases clients, never stops Hosts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .client_settings import remember_workspace, settings_request
from .gui_local_host import operate
from .web_client import WebHostClient


class WebGateway:
    def __init__(self):
        self.clients: dict[str, WebHostClient] = {}
        self.management = asyncio.Lock()

    async def close(self):
        for client in self.clients.values():
            async with client.lock:
                await client.close()
        self.clients.clear()

    async def dispatch(self, request: dict):
        operation = request.get("operation")
        if operation in {"environment", "preferences", "remember-workspace"}:
            return await asyncio.to_thread(settings_request, request, local=True)
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
                result = await operate(
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
                    healthy = False
                    if (
                        previous is not None
                        and previous.connection.execution_client.service_instance_id
                        == result["serviceInstanceId"]
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


async def run_stdio():
    tasks = set()

    async def handle(raw):
        identifier = None
        try:
            request = json.loads(raw)
            identifier = request["id"]
            async with asyncio.timeout(75):
                result = await asyncio.to_thread(settings_request, request["request"])
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


if __name__ == "__main__":
    from contextlib import suppress

    with suppress(KeyboardInterrupt):
        asyncio.run(run_stdio())
