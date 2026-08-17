"""Conversation input and state commands for the shared RPC host."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from loushang.harness.host.product_host import ProductHostTaskTracker
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.host.rpc.wire import project_session_state
from loushang.harness.session import (
    SessionOperationRuntime,
    SessionPromptRequest,
    SessionRpcOperationBinding,
)


class RpcConversationCommands:
    """Own immediate conversation control and prompt task settlement."""

    def __init__(
        self,
        *,
        get_session: Callable[[], object],
        get_operations: Callable[[], SessionOperationRuntime],
        operations: SessionRpcOperationBinding,
        output: RpcOutput,
        task_tracker: ProductHostTaskTracker,
    ) -> None:
        self._get_session = get_session
        self._get_operations = get_operations
        self._operations = operations
        self._output = output
        self._task_tracker = task_tracker
        self._active_prompt_task: asyncio.Task[None] | None = None

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("prompt", self.prompt),
            ("steer", self.steer),
            ("follow_up", self.follow_up),
            ("abort", self.abort),
            ("get_state", self.get_state),
        )

    async def prompt(
        self,
        command_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        request = self._operations.prompt_request(payload)
        task = asyncio.create_task(
            self._run_prompt(
                operations=self._get_operations(),
                command_id=command_id,
                request=request,
            )
        )
        self._active_prompt_task = task
        self._task_tracker.track(task)

    def steer(self, command_id: str | None, payload: dict[str, Any]) -> None:
        self._operations.steer(payload)
        self._output.success(request_id=command_id, command="steer")

    def follow_up(self, command_id: str | None, payload: dict[str, Any]) -> None:
        self._operations.follow_up(payload)
        self._output.success(request_id=command_id, command="follow_up")

    def abort(self, command_id: str | None, payload: dict[str, Any]) -> None:
        del payload
        self._operations.abort()
        self._output.success(request_id=command_id, command="abort")

    def get_state(self, command_id: str | None, payload: dict[str, Any]) -> None:
        del payload
        try:
            state = project_session_state(self._get_session())
        except Exception:
            self._output.error(
                request_id=command_id,
                command="get_state",
                error="Failed to serialize session state.",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_state",
            data=state,
        )

    async def _run_prompt(
        self,
        *,
        operations: SessionOperationRuntime,
        command_id: str | None,
        request: SessionPromptRequest,
    ) -> None:
        preflight_succeeded = False

        def on_preflight(did_succeed: bool) -> None:
            nonlocal preflight_succeeded
            if did_succeed and not preflight_succeeded:
                preflight_succeeded = True
                self._output.success(request_id=command_id, command="prompt")

        try:
            await operations.prompt(
                request,
                on_preflight=on_preflight,
            )
        except Exception as error:
            if not preflight_succeeded:
                self._output.error(
                    request_id=command_id,
                    command="prompt",
                    error=str(error),
                )
        else:
            if not preflight_succeeded:
                self._output.success(request_id=command_id, command="prompt")
        finally:
            if self._active_prompt_task is asyncio.current_task():
                self._active_prompt_task = None


__all__ = ["RpcConversationCommands"]
