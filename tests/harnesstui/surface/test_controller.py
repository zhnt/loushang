from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from loushang.harnesstui.surface.controller import (
    ApprovalSurfaceDecision,
    ScreenSurfaceCoordinator,
    SurfaceEventSource,
)
from loushang.harnesstui.surface.view import (
    ScreenSurfacePresentation,
    ScreenSurfacePurpose,
    ScreenSurfaceView,
)
from loushang.tui import InfoPanel, InputEvent, InputIntent, SurfaceHost


@dataclass(slots=True)
class _App:
    active_surface: object | None = None
    surface_host: SurfaceHost | None = None


def _view(
    purpose: ScreenSurfacePurpose,
    *,
    presentation: ScreenSurfacePresentation = "bottom-exclusive",
) -> ScreenSurfaceView:
    return ScreenSurfaceView(
        title=purpose.title(),
        purpose=purpose,
        content=InfoPanel(title=purpose.title(), text="body"),
        presentation=presentation,
    )


def _recording_handlers(
    events: list[tuple[SurfaceEventSource, object | None]],
) -> dict[SurfaceEventSource, Callable[[object | None], Awaitable[None]]]:
    def handler_for(
        source: SurfaceEventSource,
    ) -> Callable[[object | None], Awaitable[None]]:
        async def handle(payload: object | None) -> None:
            events.append((source, payload))

        return handle

    return {
        source: handler_for(source)
        for source in (
            "model",
            "command",
            "settings",
            "session",
            "delete",
            "fork",
            "dialog",
            "approval",
            "permissions",
        )
    }


@pytest.mark.parametrize(
    ("purpose", "intent", "source", "payload"),
    (
        (
            "model",
            InputIntent(kind="select", text="provider/model"),
            "model",
            "provider/model",
        ),
        ("command", InputIntent(kind="command", text="/status"), "command", "/status"),
        (
            "settings",
            InputIntent(kind="setting", text="statusline", note="false"),
            "settings",
            {"id": "statusline", "value": "false"},
        ),
        (
            "session",
            InputIntent(kind="select", text="/tmp/session.jsonl"),
            "session",
            "/tmp/session.jsonl",
        ),
        (
            "fork",
            InputIntent(kind="select", text="entry-1"),
            "fork",
            "entry-1",
        ),
        ("dialog", InputIntent(kind="dialog_confirm"), "dialog", None),
        ("delete", InputIntent(kind="dialog_confirm"), "delete", ""),
        (
            "permissions",
            InputIntent(kind="select", text="revoke:grant-1"),
            "permissions",
            "revoke:grant-1",
        ),
    ),
)
def test_screen_surface_coordinator_routes_submit_intents_by_purpose(
    purpose: ScreenSurfacePurpose,
    intent: InputIntent,
    source: SurfaceEventSource,
    payload: object | None,
) -> None:
    events: list[tuple[SurfaceEventSource, object | None]] = []
    app = _App()
    coordinator = ScreenSurfaceCoordinator(
        app=app,
        handlers=_recording_handlers(events),
    )
    coordinator.open(_view(purpose))

    asyncio.run(coordinator.handle_intent(intent))

    assert events == [(source, payload)]


def test_screen_surface_coordinator_closes_non_approval_close_intents() -> None:
    app = _App()
    coordinator = ScreenSurfaceCoordinator(app=app)
    coordinator.open(_view("dialog"))

    asyncio.run(coordinator.handle_intent(InputIntent(kind="dialog_cancel")))

    assert coordinator.current is None
    assert app.active_surface is None


@pytest.mark.parametrize("intent_kind", ("surface_close", "dialog_cancel"))
def test_screen_surface_coordinator_treats_approval_close_as_abort(
    intent_kind: str,
) -> None:
    decisions: list[ApprovalSurfaceDecision] = []

    async def handle_approval(payload: object | None) -> None:
        assert isinstance(payload, ApprovalSurfaceDecision)
        decisions.append(payload)

    app = _App()
    coordinator = ScreenSurfaceCoordinator(
        app=app,
        handlers={"approval": handle_approval},
    )
    coordinator.present_approval(action="delete cache", action_id="approval-1")

    asyncio.run(
        coordinator.handle_intent(InputIntent(kind=intent_kind, note="approval-1"))
    )

    assert decisions == [
        ApprovalSurfaceDecision(
            action_id="approval-1",
            action="delete cache",
            outcome="abort",
            raw_note="approval-1",
        )
    ]
    assert coordinator.current is None


def test_screen_surface_coordinator_treats_explicit_reject_as_denial() -> None:
    decisions: list[ApprovalSurfaceDecision] = []

    async def handle_approval(payload: object | None) -> None:
        assert isinstance(payload, ApprovalSurfaceDecision)
        decisions.append(payload)

    coordinator = ScreenSurfaceCoordinator(
        app=_App(),
        handlers={"approval": handle_approval},
    )
    coordinator.present_approval(action="delete cache", action_id="approval-1")

    asyncio.run(
        coordinator.handle_intent(
            InputIntent(
                kind="approval_decision",
                text="deny",
                note="approval-1",
            )
        )
    )

    assert decisions == [
        ApprovalSurfaceDecision(
            action_id="approval-1",
            action="delete cache",
            outcome="deny",
            raw_note="approval-1",
        )
    ]


def test_screen_surface_coordinator_emits_session_scoped_approval() -> None:
    decisions: list[ApprovalSurfaceDecision] = []

    async def handle_approval(payload: object | None) -> None:
        assert isinstance(payload, ApprovalSurfaceDecision)
        decisions.append(payload)

    app = _App()
    coordinator = ScreenSurfaceCoordinator(
        app=app,
        handlers={"approval": handle_approval},
    )
    coordinator.present_approval(
        action="publish main",
        action_id="approval-push",
        allow_session=True,
    )

    asyncio.run(
        coordinator.handle_intent(
            InputIntent(
                kind="approval_decision",
                text="allow_session",
                note="approval-push",
            )
        )
    )

    assert decisions == [
        ApprovalSurfaceDecision(
            action_id="approval-push",
            action="publish main",
            outcome="allow_session",
            raw_note="approval-push",
        )
    ]
    assert coordinator.current is None


def test_screen_surface_coordinator_ignores_unmapped_intents() -> None:
    app = _App()
    coordinator = ScreenSurfaceCoordinator(app=app)
    view = _view("info")
    coordinator.open(view)

    asyncio.run(coordinator.handle_intent(InputIntent(kind="abort")))

    assert coordinator.current is view
    assert app.active_surface is view


def test_screen_surface_coordinator_places_bottom_and_overlay_surfaces() -> None:
    host = SurfaceHost()
    app = _App(surface_host=host)
    coordinator = ScreenSurfaceCoordinator(app=app)
    bottom = _view("settings")

    coordinator.open(bottom)

    assert app.active_surface is bottom
    assert coordinator.current is bottom
    assert host.entries == []

    overlay = _view("info", presentation="bottom")
    coordinator.open(overlay)

    assert app.active_surface is None
    assert coordinator.current is overlay
    assert len(host.entries) == 1
    runtime_surface = host.entries[0].surface
    assert runtime_surface.renderable is overlay
    assert runtime_surface.focus_target is overlay
    assert runtime_surface.presentation == "overlay"
    assert runtime_surface.anchor == "bottom-left"
    assert runtime_surface.width == "100%"
    assert runtime_surface.max_height == "80%"

    coordinator.close()

    assert coordinator.current is None
    assert host.entries == []


def test_screen_surface_coordinator_opens_page_as_full_viewport_surface() -> None:
    host = SurfaceHost()
    app = _App(surface_host=host)
    coordinator = ScreenSurfaceCoordinator(app=app)
    page = _view("session", presentation="page")

    coordinator.open(page)

    assert app.active_surface is None
    assert coordinator.current is page
    assert len(host.entries) == 1
    surface = host.entries[0].surface
    assert surface.presentation == "page"
    assert surface.width == "100%"
    assert surface.max_height == "100%"


def test_screen_surface_coordinator_closes_overlay_idempotently_after_host_close() -> (
    None
):
    host = SurfaceHost()
    app = _App(surface_host=host)
    coordinator = ScreenSurfaceCoordinator(app=app)
    coordinator.open(_view("info", presentation="bottom"))

    intents = host.route_input(
        InputEvent(kind="key", key="escape"),
        close_on_intents=("surface_close", "dialog_cancel"),
    )

    assert intents == (InputIntent(kind="surface_close"),)
    assert host.entries == []
    asyncio.run(coordinator.handle_intent(intents[0]))
    coordinator.close()

    assert coordinator.current is None
    assert host.entries == []


def test_screen_surface_coordinator_queues_approvals_fifo() -> None:
    decisions: list[ApprovalSurfaceDecision] = []

    async def handle_approval(payload: object | None) -> None:
        assert isinstance(payload, ApprovalSurfaceDecision)
        decisions.append(payload)

    app = _App()
    coordinator = ScreenSurfaceCoordinator(
        app=app,
        handlers={"approval": handle_approval},
    )
    coordinator.present_approval(action="first", action_id="approval-1")
    coordinator.present_approval(action="second", action_id="approval-2")

    asyncio.run(
        coordinator.handle_intent(
            InputIntent(kind="approval_decision", text="allow_once")
        )
    )

    current = coordinator.current
    assert isinstance(current, ScreenSurfaceView)
    assert getattr(current.content, "action_id") == "approval-2"

    asyncio.run(
        coordinator.handle_intent(InputIntent(kind="approval_decision", text="deny"))
    )

    assert [decision.action_id for decision in decisions] == [
        "approval-1",
        "approval-2",
    ]
    assert [decision.approved for decision in decisions] == [True, False]
    assert coordinator.current is None


def test_screen_surface_coordinator_keeps_fifo_during_async_resolution() -> None:
    callback_started = asyncio.Event()
    release_callback = asyncio.Event()
    decisions: list[str | None] = []

    async def handle_approval(payload: object | None) -> None:
        assert isinstance(payload, ApprovalSurfaceDecision)
        decisions.append(payload.action_id)
        if payload.action_id == "approval-a":
            callback_started.set()
            await release_callback.wait()

    app = _App()
    coordinator = ScreenSurfaceCoordinator(
        app=app,
        handlers={"approval": handle_approval},
    )

    async def run() -> None:
        coordinator.present_approval(action="A", action_id="approval-a")
        coordinator.present_approval(action="B", action_id="approval-b")
        first = asyncio.create_task(
            coordinator.handle_intent(
                InputIntent(kind="approval_decision", text="allow_once")
            )
        )
        await callback_started.wait()
        coordinator.present_approval(action="C", action_id="approval-c")
        release_callback.set()
        await first

        for expected_id in ("approval-b", "approval-c"):
            current = coordinator.current
            assert isinstance(current, ScreenSurfaceView)
            assert getattr(current.content, "action_id") == expected_id
            await coordinator.handle_intent(
                InputIntent(kind="approval_decision", text="allow_once")
            )

    asyncio.run(run())

    assert decisions == ["approval-a", "approval-b", "approval-c"]
    assert coordinator.current is None


def test_screen_surface_coordinator_dismisses_and_clears_approvals() -> None:
    app = _App()
    coordinator = ScreenSurfaceCoordinator(app=app)
    coordinator.present_approval(action="A", action_id="approval-a")
    coordinator.present_approval(action="B", action_id="approval-b")
    coordinator.present_approval(action="C", action_id="approval-c")

    coordinator.dismiss_approval("approval-b")
    coordinator.dismiss_approval("approval-a")

    current = coordinator.current
    assert isinstance(current, ScreenSurfaceView)
    assert getattr(current.content, "action_id") == "approval-c"

    coordinator.present_approval(action="D", action_id="approval-d")
    coordinator.clear_approvals()

    assert coordinator.current is None
    coordinator.present_approval(action="E", action_id="approval-e")
    current = coordinator.current
    assert isinstance(current, ScreenSurfaceView)
    assert getattr(current.content, "action_id") == "approval-e"


def test_screen_surface_coordinator_advances_queue_when_handler_raises() -> None:
    async def handle_approval(payload: object | None) -> None:
        assert isinstance(payload, ApprovalSurfaceDecision)
        if payload.action_id == "approval-a":
            raise RuntimeError("resolution failed")

    app = _App()
    coordinator = ScreenSurfaceCoordinator(
        app=app,
        handlers={"approval": handle_approval},
    )
    coordinator.present_approval(action="A", action_id="approval-a")
    coordinator.present_approval(action="B", action_id="approval-b")

    with pytest.raises(RuntimeError, match="resolution failed"):
        asyncio.run(
            coordinator.handle_intent(
                InputIntent(kind="approval_decision", text="allow_once")
            )
        )

    current = coordinator.current
    assert isinstance(current, ScreenSurfaceView)
    assert getattr(current.content, "action_id") == "approval-b"
