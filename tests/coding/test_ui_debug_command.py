from __future__ import annotations

import asyncio
from pathlib import Path


def test_plain_coding_app_binds_debug_intent_policy_to_shared_action() -> None:
    from loushang.coding.ui.plain_app import build_plain_coding_tui_app

    events: list[object] = []
    enabled: list[tuple[object, tuple[str, ...]]] = []
    disabled = 0

    class Session:
        session_id = "sid"
        session_name = "session"

    class Renderer:
        def render_status(self, text: str) -> None:
            events.append(("status", text))

        def render_error(self, text: str) -> None:
            events.append(("error", text))

        def render_worked(self, elapsed_seconds: float) -> None:
            events.append(("worked", elapsed_seconds))

    class EventRenderer:
        last_error_message = None

    class Writer:
        def write(self, _text: str) -> None:
            return None

        def flush(self) -> None:
            return None

    async def emit(write, *, label: str) -> None:
        events.append(("emit", label))
        write()

    def enable_debug(*, session: object, scopes: tuple[str, ...]) -> Path:
        enabled.append((session, scopes))
        return Path("/repo/.loushang/debug/session.log")

    def disable_debug() -> None:
        nonlocal disabled
        disabled += 1

    session = Session()
    app = build_plain_coding_tui_app(
        runtime=None,
        session=session,
        renderer=Renderer(),
        event_renderer=EventRenderer(),
        stderr=Writer(),
        verbose=False,
        cwd="/repo",
        emit=emit,
        trace=lambda name, **data: events.append(("trace", name, data)),
        now=lambda: 10.0,
        enable_debug=enable_debug,
        disable_debug=disable_debug,
    )

    enabled_result = asyncio.run(app.handle_prompt("/debug tui,agent"))
    disabled_result = asyncio.run(app.handle_prompt("/debug off"))

    assert enabled_result is None
    assert disabled_result is None
    assert enabled == [(session, ("tui", "agent"))]
    assert disabled == 1
    assert [event for event in events if event[:1] == ("emit",)] == [
        ("emit", "debug:enabled"),
        ("emit", "debug:disabled"),
    ]
    statuses = [event[1] for event in events if event[:1] == ("status",)]
    assert "Debug logging enabled:" in statuses[0]
    assert "Scopes: tui,agent" in statuses[0]
    assert statuses[1] == "Debug logging disabled."
    assert [event for event in events if event[:2] == ("trace", "debug.enabled")] == [
        (
            "trace",
            "debug.enabled",
            {
                "path": "/repo/.loushang/debug/session.log",
                "scopes": ["tui", "agent"],
            },
        )
    ]
    assert [event for event in events if event[:2] == ("trace", "debug.disabled")] == [
        ("trace", "debug.disabled", {})
    ]
