"""Live-bound collaboration tools shared by Agent Products."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol, cast

from loushang.agent.types import AgentToolResult, TextPart
from loushang.ai.types import ToolCall
from loushang.harness.multiagent import (
    AgentCaller,
    AgentPath,
    AgentRecord,
    ControlCaller,
)
from loushang.harness.multiagent.types import AgentMessageKind
from loushang.harness.tools.contribution import ToolPackDefinition
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import DirectExecution, DirectToolContext
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

MULTIAGENT_TOOL_NAMES = (
    "spawn_agent",
    "send_message",
    "wait_agent",
    "list_agents",
    "interrupt_agent",
    "close_agent",
)
MULTIAGENT_TOOL_PACK = ToolPackDefinition(
    name="harness.multiagent",
    tools=MULTIAGENT_TOOL_NAMES,
)


class LiveMultiAgentRuntime(Protocol):
    async def spawn_child(
        self,
        *,
        caller: ControlCaller,
        parent_path: AgentPath,
        name: str,
        agent_type: str,
        initial_prompt: str,
    ) -> AgentRecord: ...

    async def send_message(
        self,
        *,
        caller: ControlCaller,
        target: str | AgentPath,
        text: str,
        kind: AgentMessageKind = "follow_up",
        references: tuple[str, ...] = (),
    ) -> object: ...

    async def wait_for_input(
        self,
        *,
        caller: AgentCaller,
        after_sequence: int,
        timeout: float | None = None,
    ) -> object: ...

    def list_agents(self, *, caller: ControlCaller) -> tuple[AgentRecord, ...]: ...

    async def interrupt_agent(
        self,
        *,
        caller: ControlCaller,
        target: AgentPath,
    ) -> AgentRecord: ...

    async def close_agent(
        self,
        *,
        caller: ControlCaller,
        target: AgentPath,
    ) -> object: ...


class MultiAgentToolPack:
    """Bind the common tool schemas to one caller and one live session tree."""

    def __init__(
        self,
        *,
        runtime: LiveMultiAgentRuntime,
        caller: AgentCaller,
        default_wait_seconds: float = 30.0,
        maximum_wait_seconds: float = 3600.0,
    ) -> None:
        if default_wait_seconds < 0:
            raise ValueError("default_wait_seconds must be non-negative")
        if maximum_wait_seconds < default_wait_seconds:
            raise ValueError(
                "maximum_wait_seconds must be at least default_wait_seconds"
            )
        self._runtime = runtime
        self._caller = caller
        self._default_wait_seconds = default_wait_seconds
        self._maximum_wait_seconds = maximum_wait_seconds
        self._wait_sequence = 0

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            self._spawn(),
            self._send(),
            self._wait(),
            self._list(),
            self._interrupt(),
            self._close(),
        )

    def register(
        self,
        registry: WorkspaceToolRegistry,
        *,
        enabled_tools: Iterable[str] | None = None,
    ) -> WorkspaceToolRegistry:
        enabled = (
            set(MULTIAGENT_TOOL_NAMES) if enabled_tools is None else set(enabled_tools)
        )
        unknown = enabled.difference(MULTIAGENT_TOOL_NAMES)
        if unknown:
            raise ValueError("unknown multi-agent tools: " + ", ".join(sorted(unknown)))
        for definition in self.definitions():
            if definition.name in enabled:
                registry.register_tool(definition)
        return registry

    def _spawn(self) -> ToolDefinition:
        async def execute(
            _call_id: str,
            params: dict[str, Any],
            _signal: object | None,
            _update: object | None,
        ) -> AgentToolResult[dict[str, object]]:
            record = await self._runtime.spawn_child(
                caller=self._caller,
                parent_path=self._caller.ref.path,
                name=str(params["name"]),
                agent_type=str(params["agent_type"]),
                initial_prompt=str(params["prompt"]),
            )
            return _result(f"Spawned {record.path}.", _record(record))

        return _definition(
            name="spawn_agent",
            label="Spawn agent",
            description=(
                "Create a bounded child agent for one focused task. A successful "
                "call returns its canonical path; a failed call creates no child."
            ),
            properties={
                "name": _string(),
                "agent_type": _string(),
                "prompt": _string(),
            },
            required=("name", "agent_type", "prompt"),
            execute=execute,
        )

    def _send(self) -> ToolDefinition:
        async def execute(
            _call_id: str,
            params: dict[str, Any],
            _signal: object | None,
            _update: object | None,
        ) -> AgentToolResult[dict[str, object]]:
            target = str(params["target"])
            kind = str(params.get("kind", "follow_up"))
            if kind not in {"follow_up", "steering"}:
                raise ValueError("kind must be follow_up or steering")
            outcome = await self._runtime.send_message(
                caller=self._caller,
                target=target,
                text=str(params["message"]),
                kind=cast(AgentMessageKind, kind),
            )
            return _result(
                f"Sent message to {target}.",
                {
                    "target": target,
                    "round_id": getattr(outcome, "round_id", None),
                    "triggered_new_round": bool(
                        getattr(outcome, "triggered_new_round", False)
                    ),
                },
            )

        return _definition(
            name="send_message",
            label="Send message",
            description=(
                "Send a follow-up to an authorized agent; an idle target starts "
                "its next tracked round."
            ),
            properties={
                "target": _string(),
                "message": _string(),
                "kind": {
                    "type": "string",
                    "enum": ["follow_up", "steering"],
                    "default": "follow_up",
                },
            },
            required=("target", "message"),
            execute=execute,
        )

    def _wait(self) -> ToolDefinition:
        async def execute(
            _call_id: str,
            params: dict[str, Any],
            _signal: object | None,
            _update: object | None,
        ) -> AgentToolResult[dict[str, object]]:
            timeout = float(params.get("timeout_seconds", self._default_wait_seconds))
            if timeout < 0 or timeout > self._maximum_wait_seconds:
                raise ValueError(
                    "timeout_seconds must be between 0 and "
                    f"{self._maximum_wait_seconds:g}"
                )
            outcome = await self._runtime.wait_for_input(
                caller=self._caller,
                after_sequence=self._wait_sequence,
                timeout=timeout,
            )
            activity = getattr(outcome, "activity", None)
            timed_out = bool(getattr(outcome, "timed_out", False))
            if activity is not None:
                self._wait_sequence = int(getattr(activity, "sequence"))
            details = {
                "wait_expired": timed_out,
                "activity": asdict(activity) if activity is not None else None,
            }
            text = (
                "No collaboration activity before timeout."
                if timed_out
                else f"Collaboration activity: {getattr(activity, 'kind', 'unknown')}."
            )
            return _result(text, details)

        return _definition(
            name="wait_agent",
            label="Wait for agent activity",
            description=(
                "Wait for the caller's next agent message, completion notice, "
                "or steering activity without polling hidden output."
            ),
            properties={
                "timeout_seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": self._maximum_wait_seconds,
                }
            },
            required=(),
            execute=execute,
        )

    def _list(self) -> ToolDefinition:
        async def execute(
            _call_id: str,
            _params: dict[str, Any],
            _signal: object | None,
            _update: object | None,
        ) -> AgentToolResult[dict[str, object]]:
            records = self._runtime.list_agents(caller=self._caller)
            return _result(
                f"Listed {len(records)} agents.",
                {"agents": [_record(record) for record in records]},
            )

        return _definition(
            name="list_agents",
            label="List agents",
            description="List the live agent tree visible to the caller.",
            properties={},
            required=(),
            execute=execute,
        )

    def _interrupt(self) -> ToolDefinition:
        async def execute(
            _call_id: str,
            params: dict[str, Any],
            _signal: object | None,
            _update: object | None,
        ) -> AgentToolResult[dict[str, object]]:
            path = AgentPath.parse(str(params["target"]))
            record = await self._runtime.interrupt_agent(
                caller=self._caller,
                target=path,
            )
            return _result(f"Interrupted {path}.", _record(record))

        return _definition(
            name="interrupt_agent",
            label="Interrupt agent",
            description="Abort an agent's current round while keeping it open.",
            properties={"target": _string()},
            required=("target",),
            execute=execute,
        )

    def _close(self) -> ToolDefinition:
        async def execute(
            _call_id: str,
            params: dict[str, Any],
            _signal: object | None,
            _update: object | None,
        ) -> AgentToolResult[dict[str, object]]:
            path = AgentPath.parse(str(params["target"]))
            outcome = await self._runtime.close_agent(
                caller=self._caller,
                target=path,
            )
            closed = tuple(getattr(outcome, "closed", ()))
            return _result(
                f"Closed {len(closed)} agents.",
                {"agents": [_record(record) for record in closed]},
            )

        return _definition(
            name="close_agent",
            label="Close agent",
            description=(
                "Close a child agent and its descendants, release their session "
                "resources, and free open-agent capacity. Completed, failed, and "
                "interrupted agents remain open until explicitly closed."
            ),
            properties={"target": _string()},
            required=("target",),
            execute=execute,
        )


def _result(
    text: str,
    details: Mapping[str, object],
) -> AgentToolResult[dict[str, object]]:
    return AgentToolResult(
        content=[TextPart(type="text", text=text)],
        details=dict(details),
    )


def _record(record: AgentRecord) -> dict[str, object]:
    return {
        "path": str(record.path),
        "incarnation": record.ref.incarnation,
        "parent": (
            str(record.parent_ref.path) if record.parent_ref is not None else None
        ),
        "agent_type": record.agent_type,
        "status": record.status,
        "round_id": record.round_id,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "workspace_ref": record.workspace_ref,
        "artifact_refs": list(record.artifact_refs),
        "change_set_ref": record.change_set_ref,
        "progress": {
            "latest_input_tokens": record.progress.usage.latest_input_tokens,
            "cumulative_output_tokens": (
                record.progress.usage.cumulative_output_tokens
            ),
            "tool_uses": record.progress.tool_uses,
            "recent_activity": record.progress.recent_activity,
            "summary": record.progress.summary,
        },
    }


def _string() -> dict[str, object]:
    return {"type": "string", "minLength": 1}


ToolExecute = Callable[
    [str, dict[str, Any], object | None, object | None],
    Awaitable[AgentToolResult[Any]],
]


@dataclass(frozen=True, slots=True)
class _MultiAgentDirectHandler:
    execute: ToolExecute

    async def __call__(
        self,
        call: ToolCall,
        context: DirectToolContext,
    ) -> AgentToolResult[Any]:
        return await self.execute(
            call.id,
            dict(call.arguments),
            context.signal,
            context.on_update,
        )


def _definition(
    *,
    name: str,
    label: str,
    description: str,
    properties: dict[str, object],
    required: tuple[str, ...],
    execute: ToolExecute,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        label=label,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
        execution=DirectExecution(_MultiAgentDirectHandler(execute)),
        execution_mode="sequential",
    )


__all__ = [
    "LiveMultiAgentRuntime",
    "MULTIAGENT_TOOL_NAMES",
    "MULTIAGENT_TOOL_PACK",
    "MultiAgentToolPack",
]
