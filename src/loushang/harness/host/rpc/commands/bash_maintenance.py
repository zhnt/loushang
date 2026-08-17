"""Bash execution and Session maintenance commands for the shared RPC host."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from loushang.harness.host.product_host import ProductHostTaskTracker
from loushang.harness.host.rpc.arguments import (
    optional_env_pairs,
    optional_number,
    optional_string,
    require_string,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.host.rpc.wire import camelize, project_json_value
from loushang.harness.session import SessionRpcOperationBinding


class _BashSession(Protocol):
    """Only the Product execution capabilities consumed by this group."""

    def execute_bash(
        self,
        command: str,
        *,
        cwd: str | None,
        env: list[list[str]] | None,
        timeout_seconds: float | None,
        stdin: str | None,
    ) -> Awaitable[object]: ...

    def abort_bash(self) -> None: ...


class RpcBashMaintenanceCommands:
    """Own Bash task state and maintenance wire projection."""

    def __init__(
        self,
        *,
        get_session: Callable[[], _BashSession],
        operations: SessionRpcOperationBinding,
        output: RpcOutput,
        task_tracker: ProductHostTaskTracker,
    ) -> None:
        self._get_session = get_session
        self._operations = operations
        self._output = output
        self._task_tracker = task_tracker
        self._active_bash_task: asyncio.Task[None] | None = None

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("bash", self.bash),
            ("abort_bash", self.abort_bash),
            ("compact", self.compact),
            ("set_auto_retry", self.set_auto_retry),
            ("abort_retry", self.abort_retry),
            ("set_auto_compaction", self.set_auto_compaction),
        )

    async def bash(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._ensure_no_active_bash(command="bash")
        command = require_string(payload, "command")
        task = asyncio.create_task(
            self._run_bash(
                command_id=command_id,
                command=command,
                cwd=optional_string(payload, "cwd"),
                env=optional_env_pairs(payload.get("env")),
                timeout_seconds=optional_number(
                    payload,
                    "timeoutSeconds",
                    "timeout_seconds",
                ),
                stdin=optional_string(payload, "stdin"),
            )
        )
        self._active_bash_task = task
        self._task_tracker.track(task)

    def abort_bash(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        self._get_session().abort_bash()
        self._output.success(
            request_id=command_id,
            command="abort_bash",
        )

    async def compact(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            result = await self._operations.compact(payload)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="compact",
                error=f"Failed to compact session: {error}",
            )
            return
        try:
            data = camelize(project_json_value(result))
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="compact",
                error=f"Failed to serialize compact response: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="compact",
            data=data,
        )

    def set_auto_retry(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            self._operations.set_auto_retry(payload)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="set_auto_retry",
                error=f"Failed to set auto-retry: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_auto_retry",
        )

    def abort_retry(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        self._operations.abort_retry()
        self._output.success(
            request_id=command_id,
            command="abort_retry",
        )

    def set_auto_compaction(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            self._operations.set_auto_compaction(payload)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="set_auto_compaction",
                error=f"Failed to set auto-compaction: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_auto_compaction",
        )

    async def _run_bash(
        self,
        *,
        command_id: str | None,
        command: str,
        cwd: str | None,
        env: list[list[str]] | None,
        timeout_seconds: float | None,
        stdin: str | None,
    ) -> None:
        try:
            result = await self._get_session().execute_bash(
                command,
                cwd=cwd,
                env=env,
                timeout_seconds=timeout_seconds,
                stdin=stdin,
            )
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="bash",
                error=str(error),
            )
        else:
            try:
                data = camelize(project_json_value(result))
            except Exception as error:
                self._output.error(
                    request_id=command_id,
                    command="bash",
                    error=f"Failed to serialize bash result: {error}",
                )
                return
            self._output.success(
                request_id=command_id,
                command="bash",
                data=data,
            )
        finally:
            if self._active_bash_task is asyncio.current_task():
                self._active_bash_task = None

    def _ensure_no_active_bash(self, *, command: str) -> None:
        task = self._active_bash_task
        if task is not None and not task.done():
            raise RuntimeError(
                f"{command} requires the active bash command to finish or abort first"
            )


__all__ = ["RpcBashMaintenanceCommands"]
