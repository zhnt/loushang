"""Web/desktop adapter process. Stdio is private to the development server.

No fixture fallback. Closing this adapter releases clients, never stops Hosts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .client_settings import remember_workspace, settings_request
from .web_client import WebHostClient


async def operate(request: dict) -> dict:
    # The managed launcher outlives neither the request nor its caller's exit.
    # Keeping it inside the Web adapter leaves a stopped Host as its zombie child.
    helper = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "loushang.coding.gui_local_host",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )
    try:
        output, _ = await helper.communicate(json.dumps(request).encode())
    except BaseException:
        if helper.returncode is None:
            helper.terminate()
        await helper.wait()
        raise
    if helper.returncode != 0:
        raise ValueError("management_failed")
    return json.loads(output)


class WebGateway:
    def __init__(self):
        self.clients: dict[str, WebHostClient] = {}
        self.management = asyncio.Lock()
        self.operate = operate
        self.host: WebHostClient | None = None

    async def close(self):
        clients = [*self.clients.values(), *([self.host] if self.host else [])]
        results = await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup("client_cleanup_incomplete", failures)
        self.clients.clear()
        self.host = None

    async def _connect_host(self, result):
        if self.host is not None:
            execution = self.host.connection.execution_client
            if execution is not None and execution.service_instance_id == result["serviceInstanceId"]:
                await self.host.connection.client.list_muxes()
                return
            await self.close()
        client = WebHostClient(Path(result["recordRoot"]))
        await client.start()
        self.host = client

    async def dispatch(self, request: dict):
        operation = request.get("operation")
        if operation in {"environment", "preferences", "remember-workspace"}:
            return await asyncio.to_thread(settings_request, request)
        if operation == "account":
            import getpass
            return {"name": getpass.getuser(), "id": None}
        if operation == "manage":
            async with self.management:
                action = request.get("action")
                result = await self.operate({"action": action, **(
                    {"instanceId": request["instanceId"]} if request.get("instanceId") else {})})
                if not result.get("errorCode"):
                    if action in {"stop", "restart"}:
                        await self.close()
                    if action in {"connect", "start", "restart"} and result.get("state") == "running":
                        await self._connect_host(result)
                return {key: value for key, value in result.items() if key not in {"recordRoot", "muxName"}}
        if self.host is None:
            raise ValueError("not_connected")
        if operation == "workspace":
            async with self.management:
                result = await self.operate({"action": "workspace", "workspaceAction": request.get("action"),
                    **({"workspace": request["path"]} if request.get("path") is not None else {})})
                if result.get("errorCode"):
                    raise ValueError(result["errorCode"])
                if request.get("action") == "open":
                    path = result["workspace"]
                    if path not in self.clients:
                        if len(self.clients) >= 6:
                            raise ValueError("connection_limit")
                        client = WebHostClient(Path(result["recordRoot"]), result["muxName"],
                                               workspace_scope=result["workspaces"][0])
                        await client.start()
                        self.clients[path] = client
                    await asyncio.to_thread(remember_workspace, path)
                return {"workspaces": result["workspaces"]}
        if operation == "live":
            client = self.clients.get(request.get("workspace"))
            if client is None:
                raise ValueError("workspace_not_selected")
            return await client.call(request["action"], request.get("input", {}))
        raise ValueError("unknown_operation")


async def run_stdio():
    tasks = set()
    gateway = WebGateway()

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
    from contextlib import suppress

    with suppress(KeyboardInterrupt):
        asyncio.run(run_stdio())
