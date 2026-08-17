"""Observation-only Agent lifecycle callbacks for extension runtimes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import time
from typing import Any, Protocol


class ExtensionEventPort(Protocol):
    """Extension event sink used by one live Agent session."""

    async def emit_agent_event(self, event: object, *, cwd: str = "") -> None: ...


ExtensionEventProvider = Callable[[], ExtensionEventPort | None]
CwdProvider = Callable[[], str]
Clock = Callable[[], float]


@dataclass
class ExtensionAgentEventRuntime:
    """Project Agent lifecycle facts into extension callbacks.

    This adapter deliberately does not publish a runtime-event envelope.  It
    invokes the active extension runtime in Agent event order only.
    """

    get_extension_runtime: ExtensionEventProvider
    get_cwd: CwdProvider
    clock: Clock = time
    _turn_index: int = 0

    async def emit_agent_event(self, event: Mapping[str, Any]) -> None:
        extension_runtime = self.get_extension_runtime()
        if extension_runtime is None:
            return
        event_type = event["type"]
        if event_type == "agent_start":
            self._turn_index = 0
            await extension_runtime.emit_agent_event(
                {"type": "agent_start"},
                cwd=self.get_cwd(),
            )
            return
        if event_type == "turn_start":
            await extension_runtime.emit_agent_event(
                {
                    "type": "turn_start",
                    "turn_index": self._turn_index,
                    "timestamp": int(self.clock() * 1000),
                },
                cwd=self.get_cwd(),
            )
            return
        if event_type == "turn_end":
            await extension_runtime.emit_agent_event(
                {
                    "type": "turn_end",
                    "turn_index": self._turn_index,
                    "message": event["message"],
                    "tool_results": event["tool_results"],
                },
                cwd=self.get_cwd(),
            )
            self._turn_index += 1
            return
        await extension_runtime.emit_agent_event(event, cwd=self.get_cwd())


__all__ = ["Clock", "ExtensionAgentEventRuntime", "ExtensionEventPort"]
