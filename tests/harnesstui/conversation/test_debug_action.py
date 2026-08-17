from __future__ import annotations

import asyncio
import subprocess
import sys

from loushang.harnesstui.conversation.debug_action import (
    DebugActionCopy,
    DebugActionHandler,
    DebugActionPorts,
)


def _handler(events: list[object]) -> DebugActionHandler[str]:
    async def emit(write, *, label: str) -> None:
        events.append(("emit", label))
        write()

    return DebugActionHandler(
        copy=DebugActionCopy(
            enabled_status=lambda result, scopes: (
                f"Enabled {result}: {','.join(scopes)}"
            ),
            disabled_status="Disabled",
            enabled_emit_label="product:enabled",
            disabled_emit_label="product:disabled",
        ),
        ports=DebugActionPorts(
            enable=lambda scopes: events.append(("enable", scopes)) or "path",
            disable=lambda: events.append("disable"),
            on_enabled=lambda result, scopes: events.append(
                ("on_enabled", result, scopes)
            ),
            on_disabled=lambda: events.append("on_disabled"),
            emit=emit,
            render_status=lambda text: events.append(("status", text)),
        ),
    )


def test_debug_action_sequences_disable_callback_before_stable_status() -> None:
    events: list[object] = []

    result = asyncio.run(_handler(events).handle(enabled=False, scopes=()))

    assert result is None
    assert events == [
        "disable",
        "on_disabled",
        ("emit", "product:disabled"),
        ("status", "Disabled"),
    ]


def test_debug_action_sequences_enable_callback_before_stable_status() -> None:
    events: list[object] = []

    result = asyncio.run(
        _handler(events).handle(enabled=True, scopes=("terminal", "runtime"))
    )

    assert result is None
    assert events == [
        ("enable", ("terminal", "runtime")),
        ("on_enabled", "path", ("terminal", "runtime")),
        ("emit", "product:enabled"),
        ("status", "Enabled path: terminal,runtime"),
    ]


def test_debug_action_defers_enabled_copy_until_stable_write() -> None:
    events: list[object] = []
    writes = []

    async def emit(write, *, label: str) -> None:
        events.append(("emit", label))
        writes.append(write)

    handler = DebugActionHandler(
        copy=DebugActionCopy(
            enabled_status=lambda result, scopes: (
                events.append("copy") or f"{result}:{','.join(scopes)}"
            ),
            disabled_status="disabled",
            enabled_emit_label="enabled",
            disabled_emit_label="disabled",
        ),
        ports=DebugActionPorts(
            enable=lambda _scopes: "result",
            disable=lambda: None,
            on_enabled=lambda _result, _scopes: events.append("callback"),
            on_disabled=lambda: None,
            emit=emit,
            render_status=lambda text: events.append(("status", text)),
        ),
    )

    asyncio.run(handler.handle(enabled=True, scopes=("tui",)))

    assert events == ["callback", ("emit", "enabled")]
    writes[0]()
    assert events == [
        "callback",
        ("emit", "enabled"),
        "copy",
        ("status", "result:tui"),
    ]


def test_debug_action_stays_product_neutral_on_fresh_import() -> None:
    script = """
import sys

import loushang.harnesstui.conversation.debug_action

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
