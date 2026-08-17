from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from loushang.harness.session.extension_bridge import AgentSessionExtensionBridge


@dataclass
class _RecordingRuntime:
    refreshing: bool = False
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    @property
    def is_refreshing(self) -> bool:
        return self.refreshing

    async def bind(self, *, reason: str) -> None:
        self.calls.append(("bind", reason))

    def bind_bindings(self) -> None:
        self.calls.append(("bind_bindings", None))

    async def refresh(self, *, reason: str) -> None:
        self.calls.append(("refresh", reason))

    def refresh_bindings(self) -> None:
        self.calls.append(("refresh_bindings", None))

    def invalidate_contexts(self, message: str) -> None:
        self.calls.append(("invalidate_contexts", message))


def test_extension_bridge_owns_context_before_runtime_attachment() -> None:
    bridge = AgentSessionExtensionBridge()
    runtime_host = object()
    ui_context = object()

    bridge.set_runtime_host(runtime_host)
    bridge.set_ui_context(ui_context)

    assert bridge.runtime_host is runtime_host
    assert bridge.ui_context is ui_context
    assert bridge.is_refreshing is False


def test_extension_bridge_coordinates_attached_runtime() -> None:
    bridge = AgentSessionExtensionBridge()
    runtime = _RecordingRuntime(refreshing=True)
    bridge.attach_runtime(runtime)

    bridge.set_runtime_host(object())
    bridge.set_ui_context(object())
    asyncio.run(bridge.bind(reason="startup"))
    bridge.bind_bindings()
    asyncio.run(bridge.refresh(reason="model_selection_changed"))
    bridge.refresh_bindings()
    bridge.invalidate_contexts("stale")

    assert bridge.is_refreshing is True
    assert runtime.calls == [
        ("refresh_bindings", None),
        ("refresh_bindings", None),
        ("bind", "startup"),
        ("bind_bindings", None),
        ("refresh", "model_selection_changed"),
        ("refresh_bindings", None),
        ("invalidate_contexts", "stale"),
    ]


def test_extension_bridge_rejects_runtime_replacement() -> None:
    bridge = AgentSessionExtensionBridge()
    runtime = _RecordingRuntime()
    bridge.attach_runtime(runtime)
    bridge.attach_runtime(runtime)

    with pytest.raises(RuntimeError, match="already attached"):
        bridge.attach_runtime(_RecordingRuntime())


def test_extension_bridge_requires_runtime_for_lifecycle_operations() -> None:
    bridge = AgentSessionExtensionBridge()

    with pytest.raises(RuntimeError, match="not attached"):
        bridge.bind_bindings()
