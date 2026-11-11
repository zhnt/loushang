"""Web/desktop adapter process. Stdio is private to the development server.

No fixture fallback. Closing this adapter releases clients, never stops Hosts.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from loushang.appserver.local import MAX_LOCAL_APP_CONNECTIONS
from loushang.appserver.protocol import WorkspaceRequestV1

from .client_settings import TEMPORARY_WORKSPACE, remember_workspace, settings_request
from .gui_local_host import TEMPORARY_MUX, project_mux_name
from .web_client import WebHostClient

# The base connection and the short-lived management helper each need a slot.
MAX_WORKSPACE_CLIENTS = MAX_LOCAL_APP_CONNECTIONS - 2


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

    async def _navigation(self):
        client = self.host.connection.client
        projects = await client.workspace(WorkspaceRequestV1("projects"))
        muxes = {mux.name: mux for mux in (await client.list_muxes()).mux_spaces}

        def project_chats(name):
            mux = muxes.get(name)
            if mux is None or not mux.members:
                return []
            scope = f"mux:{mux.mux_space_id}"
            pinned = settings_request({"operation": "preferences", "scope": scope})["pinned"]
            return sorted(
                ({
                    "id": member.session.session_id,
                    "title": member.title,
                    "scope": scope,
                    "pinned": member.session.session_id in pinned,
                } for member in mux.members),
                key=lambda chat: not chat["pinned"],
            )

        def directory():
            return {
                "projects": [
                    {"path": item.path, "sessions": project_chats(project_mux_name(item.path))}
                    for item in projects.workspaces
                ],
                "temporarySessions": project_chats(TEMPORARY_MUX),
            }

        return await asyncio.to_thread(directory)

    async def _workspace_request(self, action, path=None):
        result = await self.operate({
            "action": "workspace", "workspaceAction": action,
            **({"workspace": path} if path is not None else {}),
        })
        if result.get("errorCode"):
            raise ValueError(result["errorCode"])
        return result

    async def _open_client(self, workspace, *, prepare_default=False):
        existing = self.clients.pop(workspace, None)
        if existing is not None:
            self.clients[workspace] = existing
            return workspace, existing
        if len(self.clients) >= MAX_WORKSPACE_CLIENTS:
            oldest = next(iter(self.clients))
            await self.clients[oldest].close()
            del self.clients[oldest]
        if workspace == TEMPORARY_WORKSPACE:
            result = await self._workspace_request("open-temporary")
            scope = None
        else:
            result = await self._workspace_request("open", workspace)
            workspace = result["workspace"]
            scope = result["workspaces"][0]
            if workspace in self.clients:
                return workspace, self.clients[workspace]
        client = WebHostClient(Path(result["recordRoot"]), result["muxName"], workspace_scope=scope)
        await client.start(prepare_default=prepare_default)
        self.clients[workspace] = client
        return workspace, client

    async def _create_chat(self, path, title):
        if type(title) is not str or not title.strip() or len(title) > 256:
            raise ValueError("invalid_chat_title")
        workspace, client = await self._open_client(TEMPORARY_WORKSPACE if path is None else path)
        scope = None
        if path is None:
            result = await self.host.connection.client.workspace(WorkspaceRequestV1("allocate-temporary"))
            allocated, = result.workspaces
            scope = {"scope": allocated.scope.value, "scopeFingerprint": allocated.scope_fingerprint}
        async with client.lock:
            created = await client.create({"title": title}, workspace_scope=scope)
        return {"workspace": workspace, **created}

    async def _workspace(self, request):
        action = request.get("action")
        if action == "navigation":
            return await self._navigation()
        path = request.get("path")
        if action == "create-chat":
            return await self._create_chat(path, request.get("title", "New Session"))
        if action == "open":
            workspace, client = await self._open_client(path, prepare_default=True)
            await asyncio.to_thread(remember_workspace, workspace)
            return {"workspaces": [{"path": workspace, **client.workspace_scope}]}
        result = await self._workspace_request(action, path)
        return {"workspaces": result["workspaces"]}

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
        if operation in {"workspace", "live"}:
            # Attachment eviction and reconnect cannot race a request using the old control.
            async with self.management:
                if self.host is None:
                    raise ValueError("not_connected")
                if operation == "workspace":
                    return await self._workspace(request)
                _, client = await self._open_client(request.get("workspace"))
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
