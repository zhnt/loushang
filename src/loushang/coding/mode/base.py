"""Shared mode abstractions used by print / rpc mode adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence, TextIO, TypedDict, cast, get_args

from loushang.coding.event import JsonEventView
from loushang.work import EventLogBackend

ModeName = Literal["text", "print", "json", "rpc"]
ModeActionType = Literal[
    "start",
    "stop",
    "submit_input",
    "render_event",
    "get_state",
    "wait_for_idle",
    "rebind_session",
    "dispose",
]


class ModeState(TypedDict, total=False):
    """Shape-aligned runtime mode state projection used by CLI/RPC print surfaces."""

    model: dict[str, object] | None
    thinkingLevel: str
    isStreaming: bool
    isCompacting: bool
    steeringMode: str
    followUpMode: str
    autoCompactionEnabled: bool
    messageCount: int
    pendingMessageCount: int
    sessionId: str
    sessionName: str
    sessionFile: str


@dataclass(frozen=True)
class ModeConfig:
    """Mode-level configuration shared by CLI and embedders."""

    mode: ModeName = "text"
    event_view: JsonEventView = "full"
    event_select: Sequence[str] | str | None = None
    render_tool_events: bool = False


@dataclass(frozen=True)
class ModeAction:
    """Serializable-ish command object for driving a mode adapter."""

    type: ModeActionType
    payload: object | None = None


_SUPPORTED_MODE_ACTION_TYPES = frozenset(get_args(ModeActionType))


def normalize_mode_action(action: ModeAction | dict[str, object]) -> ModeAction:
    """Normalize a dataclass or JSON-like payload into a validated `ModeAction`."""

    if isinstance(action, ModeAction):
        return action
    if not isinstance(action, dict):
        raise TypeError("Mode action must be a ModeAction or dict payload.")
    raw_type = action.get("type")
    if not isinstance(raw_type, str) or not raw_type:
        raise ValueError("Mode action requires string type.")
    if raw_type not in _SUPPORTED_MODE_ACTION_TYPES:
        raise ValueError(f"Unsupported mode action: {raw_type}")
    return ModeAction(cast(ModeActionType, raw_type), action.get("payload"))


class ModeAdapter(Protocol):
    """Low-level runtime mode contract."""

    async def start(self, *args: object, **kwargs: object) -> int: ...

    async def stop(self) -> int: ...

    async def submit_input(self, input_payload: object) -> int: ...

    async def wait_for_idle(self) -> int: ...

    def rebind_session(self, session: object | None = None) -> int: ...

    async def dispose(self) -> int: ...

    def render_event(self, event: object) -> None: ...

    def get_mode_state(self) -> ModeState: ...


async def dispatch_mode_action(adapter: ModeAdapter, action: ModeAction | dict[str, object]) -> int | ModeState:
    """Dispatch a mode action through the stable adapter contract."""

    action = normalize_mode_action(action)
    if action.type == "start":
        if isinstance(action.payload, tuple):
            return await adapter.start(*action.payload)
        if action.payload is None:
            return await adapter.start()
        return await adapter.start(action.payload)
    if action.type == "stop":
        return await adapter.stop()
    if action.type == "submit_input":
        return await adapter.submit_input(action.payload)
    if action.type == "render_event":
        adapter.render_event(action.payload)
        return 0
    if action.type == "get_state":
        return adapter.get_mode_state()
    if action.type == "wait_for_idle":
        return await adapter.wait_for_idle()
    if action.type == "rebind_session":
        return adapter.rebind_session(action.payload)
    if action.type == "dispose":
        return await adapter.dispose()
    raise ValueError(f"Unsupported mode action: {action.type}")


def create_mode_adapter(
    config: ModeConfig,
    *,
    runtime: Any,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO | None = None,
    session: Any | None = None,
    work_event_log: EventLogBackend | None = None,
    method_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
) -> ModeAdapter:
    """Create the concrete adapter for a configured coding mode."""

    if config.mode == "rpc":
        from loushang.coding.mode.rpc_mode import RpcMode

        return RpcMode(
            runtime=runtime,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            event_view=config.event_view,
            event_select=config.event_select,
            render_tool_events=config.render_tool_events,
        )

    if session is None:
        raise ValueError(f"{config.mode} mode requires a session")

    from loushang.coding.mode.print_mode import PrintMode

    return PrintMode(
        runtime=runtime,
        session=session,
        stdout=stdout,
        stderr=stderr,
        output_mode="text" if config.mode == "print" else config.mode,
        event_view=config.event_view,
        event_select=config.event_select,
        render_tool_events=config.render_tool_events,
        work_event_log=work_event_log,
        method_id=method_id,
        plan_id=plan_id,
        step_id=step_id,
        step_index=step_index,
        step_title=step_title,
    )


async def run_mode(
    config: ModeConfig,
    *,
    runtime: Any,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO | None = None,
    session: Any | None = None,
    user_input: str | None = None,
    images: list[object] | None = None,
    follow_up_messages: Sequence[str] = (),
    work_event_log: EventLogBackend | None = None,
    method_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    step_index: int | None = None,
    step_title: str | None = None,
    dispose: bool = True,
) -> int:
    adapter = create_mode_adapter(
        config,
        runtime=runtime,
        session=session,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        work_event_log=work_event_log,
        method_id=method_id,
        plan_id=plan_id,
        step_id=step_id,
        step_index=step_index,
        step_title=step_title,
    )
    if config.mode == "rpc":
        return await adapter.start(user_input)
    return await adapter.start(
        user_input,
        images=images,
        follow_up_messages=follow_up_messages,
        dispose=dispose,
    )
