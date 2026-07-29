"""Product-neutral mode host contracts.

The mode layer is a host concern: products choose a concrete transport and
bind their session/work projections, while Harness owns the lifecycle action
grammar and the state-reading contract.  Concrete product factories should
not be implemented here.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import (
    Literal,
    Protocol,
    TypedDict,
    cast,
)

from loushang.harness.host.product_host import (
    ProductHostAction,
    ProductHostActionType,
    ProductHostAdapter,
    dispatch_product_host_action,
    normalize_product_host_action,
)

ModeName = Literal["text", "print", "json", "rpc"]
ModeActionType = ProductHostActionType


class ModeState(TypedDict, total=False):
    """Transport-neutral state projection for terminal and RPC hosts.

    The field names intentionally remain the established host contract.  A
    transport may project them into its own wire shape, but the shared host
    must not inspect product-specific session objects.
    """

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
    """Host mode selection and event-view policy supplied by a Product."""

    mode: ModeName = "text"
    event_view: str = "full"
    event_select: Sequence[str] | str | None = None
    render_tool_events: bool = False


ModeAction = ProductHostAction


def normalize_mode_action(
    action: ModeAction | Mapping[str, object],
) -> ModeAction:
    """Normalize a mode action through the shared Channel host contract."""

    return normalize_product_host_action(action, action_name="Mode action")


class ModeAdapter(ProductHostAdapter, Protocol):
    """Lifecycle adapter implemented by an injected Product host."""

    def get_mode_state(self) -> ModeState: ...


async def dispatch_mode_action(
    adapter: ModeAdapter,
    action: ModeAction | Mapping[str, object],
) -> int | ModeState:
    """Dispatch one shared lifecycle action and read the adapter state."""

    result = await dispatch_product_host_action(
        adapter,
        action,
        get_state=lambda current: cast(ModeAdapter, current).get_mode_state(),
    )
    return cast(int | ModeState, result)


async def dispose_host(*candidates: object) -> bool:
    """Dispose the first injected host candidate exposing ``dispose``."""

    for candidate in candidates:
        disposer = getattr(candidate, "dispose", None)
        if not callable(disposer):
            continue
        result = disposer()
        if inspect.isawaitable(result):
            await result
        return True
    return False


__all__ = [
    "ModeAction",
    "ModeActionType",
    "ModeAdapter",
    "ModeConfig",
    "ModeName",
    "ModeState",
    "dispatch_mode_action",
    "dispose_host",
    "normalize_mode_action",
]
