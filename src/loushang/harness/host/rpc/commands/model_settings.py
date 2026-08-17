"""Model and live Session settings commands for the shared RPC host."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from loushang.ai.model import ModelSelection
from loushang.harness.host.rpc.arguments import require_mode, require_string
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.host.rpc.wire import (
    project_available_models,
    project_session_state,
    project_session_stats,
    project_state_model,
)
from loushang.harness.session import SessionOperationRuntime


class _ModelSettingsState(Protocol):
    thinking_level: str


class _ModelSettingsSession(Protocol):
    """Only the Product model/settings capabilities consumed by this group."""

    def get_available_models(self) -> Sequence[ModelSelection]: ...

    def set_model(self, selection: ModelSelection) -> Awaitable[None]: ...

    def cycle_model(self) -> Awaitable[object | None]: ...

    def set_active_tools(self, tool_names: list[str]) -> Awaitable[None]: ...

    def set_thinking_level(self, level: str) -> Awaitable[None] | None: ...

    def cycle_thinking_level(self) -> Awaitable[object | None] | object | None: ...

    def set_steering_mode(self, mode: str) -> None: ...

    def set_follow_up_mode(self, mode: str) -> None: ...

    def get_session_stats(self) -> object: ...

    def get_state(self) -> _ModelSettingsState: ...


class RpcModelSettingsCommands:
    """Keep Product model/settings projection out of the RPC event loop."""

    def __init__(
        self,
        *,
        get_session: Callable[[], _ModelSettingsSession],
        get_operations: Callable[[], SessionOperationRuntime],
        output: RpcOutput,
    ) -> None:
        self._get_session = get_session
        self._get_operations = get_operations
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("set_model", self.set_model),
            ("get_available_models", self.get_available_models),
            ("cycle_model", self.cycle_model),
            ("set_active_tools", self.set_active_tools),
            ("set_thinking_level", self.set_thinking_level),
            ("cycle_thinking_level", self.cycle_thinking_level),
            ("set_steering_mode", self.set_steering_mode),
            ("set_follow_up_mode", self.set_follow_up_mode),
            ("get_session_stats", self.get_session_stats),
            ("set_session_name", self.set_session_name),
        )

    async def set_model(self, command_id: str | None, payload: dict[str, Any]) -> None:
        provider = require_string(payload, "provider")
        endpoint_id = require_string(payload, "endpointId", "endpoint_id")
        model_id = require_string(payload, "modelId", "model_id")
        selection = ModelSelection(
            provider=provider,
            endpoint_id=endpoint_id,
            model_id=model_id,
        )
        session = self._get_session()
        try:
            available_models = session.get_available_models()
        except Exception as error:
            self._error(
                command_id,
                "set_model",
                f"Failed to query model registry: {error}",
            )
            return
        if not isinstance(available_models, list):
            self._error(
                command_id,
                "set_model",
                "Model registry returned an invalid response.",
            )
            return
        if available_models and selection not in available_models:
            self._error(
                command_id,
                "set_model",
                f"Model not found: {provider}:{endpoint_id}:{model_id}",
            )
            return
        try:
            await session.set_model(selection)
        except KeyError:
            self._error(
                command_id,
                "set_model",
                f"Model not found: {provider}:{endpoint_id}:{model_id}",
            )
            return
        except Exception as error:
            self._error(
                command_id,
                "set_model",
                f"Failed to set model: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_model",
            data=project_state_model(session, session.get_state()),
        )

    def get_available_models(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        session = self._get_session()
        getter = getattr(session, "get_available_models", None)
        if not callable(getter):
            self._error(
                command_id,
                "get_available_models",
                "Model registry is not available.",
            )
            return
        try:
            models = getter()
        except Exception as error:
            self._error(
                command_id,
                "get_available_models",
                f"Failed to query model registry: {error}",
            )
            return
        if not isinstance(models, list):
            self._error(
                command_id,
                "get_available_models",
                "Model registry returned an invalid response.",
            )
            return
        try:
            serialized = project_available_models(session, models)
        except Exception as error:
            self._error(
                command_id,
                "get_available_models",
                f"Failed to serialize model registry: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_available_models",
            data={"models": serialized},
        )

    async def cycle_model(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        session = self._get_session()
        try:
            selection = await session.cycle_model()
        except TypeError as error:
            message = str(error)
            self._error(
                command_id,
                "cycle_model",
                (
                    message
                    if message == "Model registry returned an invalid response."
                    else f"Failed to cycle model: {error}"
                ),
            )
            return
        except Exception as error:
            self._error(
                command_id,
                "cycle_model",
                f"Failed to cycle model: {error}",
            )
            return
        if selection is None:
            self._output.success(
                request_id=command_id,
                command="cycle_model",
                data=None,
            )
            return
        try:
            state = session.get_state()
            model = project_state_model(session, state)
        except Exception as error:
            self._error(
                command_id,
                "cycle_model",
                f"Failed to serialize model: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="cycle_model",
            data={
                "model": model,
                "thinkingLevel": state.thinking_level,
                "isScoped": False,
            },
        )

    async def set_active_tools(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        tool_names = payload.get("toolNames", payload.get("tool_names"))
        if not isinstance(tool_names, list) or not all(
            isinstance(name, str) and name for name in tool_names
        ):
            raise ValueError("set_active_tools requires toolNames")
        session = self._get_session()
        try:
            await session.set_active_tools(tool_names)
        except Exception as error:
            self._error(
                command_id,
                "set_active_tools",
                f"Failed to set active tools: {error}",
            )
            return
        try:
            state = project_session_state(session)
        except Exception as error:
            self._error(
                command_id,
                "set_active_tools",
                f"Failed to read session state: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_active_tools",
            data=state,
        )

    async def set_thinking_level(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        level = require_string(payload, "level")
        try:
            result = self._get_session().set_thinking_level(level)
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            self._error(
                command_id,
                "set_thinking_level",
                f"Failed to set thinking level: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_thinking_level",
        )

    async def cycle_thinking_level(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            result = self._get_session().cycle_thinking_level()
            next_level = await result if inspect.isawaitable(result) else result
        except Exception as error:
            self._error(
                command_id,
                "cycle_thinking_level",
                f"Failed to set thinking level: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="cycle_thinking_level",
            data={"level": next_level},
        )

    def set_steering_mode(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        mode = require_mode(payload, "mode")
        try:
            self._get_session().set_steering_mode(mode)
        except Exception as error:
            self._error(
                command_id,
                "set_steering_mode",
                f"Failed to set steering mode: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_steering_mode",
        )

    def set_follow_up_mode(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        mode = require_mode(payload, "mode")
        try:
            self._get_session().set_follow_up_mode(mode)
        except Exception as error:
            self._error(
                command_id,
                "set_follow_up_mode",
                f"Failed to set follow-up mode: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_follow_up_mode",
        )

    def get_session_stats(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        getter = getattr(self._get_session(), "get_session_stats", None)
        if not callable(getter):
            self._error(
                command_id,
                "get_session_stats",
                "Session stats are not available.",
            )
            return
        try:
            stats = getter()
        except Exception as error:
            self._error(
                command_id,
                "get_session_stats",
                f"Failed to query session stats: {error}",
            )
            return
        try:
            serialized = project_session_stats(stats)
        except Exception as error:
            self._error(
                command_id,
                "get_session_stats",
                f"Session stats returned an invalid response: {error}",
            )
            return
        if not isinstance(serialized, dict):
            self._error(
                command_id,
                "get_session_stats",
                "Session stats returned an invalid response.",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_session_stats",
            data=serialized,
        )

    async def set_session_name(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        name = require_string(payload, "name").strip()
        if not name:
            self._error(
                command_id,
                "set_session_name",
                "Session name cannot be empty",
            )
            return
        try:
            await self._get_operations().set_session_name(name)
        except Exception as error:
            self._error(
                command_id,
                "set_session_name",
                f"Failed to set session name: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="set_session_name",
        )

    def _error(self, command_id: str | None, command: str, error: str) -> None:
        self._output.error(
            request_id=command_id,
            command=command,
            error=error,
        )


__all__ = ["RpcModelSettingsCommands"]
