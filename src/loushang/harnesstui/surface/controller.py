from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    ApprovalChoice,
    ApprovalSurface,
    InputIntent,
    Surface,
    SurfaceHandle,
    SurfaceHost,
    ThemeResolver,
)

SurfaceEventKind = Literal["surface_submit", "surface_close"]
ApprovalOutcome = Literal[
    "allow_once",
    "allow_session",
    "allow_project",
    "allow_user",
    "deny",
    "abort",
]
SurfaceEventSource = Literal[
    "model",
    "command",
    "settings",
    "session",
    "session_cancel",
    "delete",
    "fork",
    "rename",
    "dialog",
    "approval",
    "permissions",
]
SurfaceSubmitHandler = Callable[[Any], Awaitable[None]]

_APPROVAL_SURFACE_THEME = ThemeResolver(
    defaults={
        # Keep the primary text terminal-adaptive. Explicit bright yellow/white
        # has poor contrast on light terminal themes.
        "approval.title": {"bold": True},
        "approval.action.label": {"bold": True},
        "approval.action": {"color": "default", "bold": True},
        "approval.metadata": {"color": "bright_black", "dim": True},
        "approval.risk.label": {"color": "red", "bold": True},
        "approval.risk": {"color": "red"},
        "approval.choice.allow": {"color": "green"},
        "approval.choice.session": {"color": "cyan"},
        "approval.choice.persistent": {"color": "blue"},
        "approval.choice.deny": {"color": "red"},
        "approval.choice.selected": {"bold": True, "reverse": True},
    }
)


class ScreenSurfaceAppPort(Protocol):
    """Application state needed to coordinate framed screen surfaces."""

    active_surface: object | None
    surface_host: SurfaceHost | None


@dataclass(frozen=True, slots=True)
class ApprovalSurfaceDecision:
    """Product-neutral decision emitted by an approval presentation."""

    action_id: str | None
    action: str | None
    outcome: ApprovalOutcome
    raw_note: str | None

    @property
    def approved(self) -> bool:
        return self.outcome.startswith("allow_")

    @property
    def scope(self) -> Literal["once", "session"]:
        return "session" if self.outcome == "allow_session" else "once"


@dataclass(frozen=True, slots=True)
class SurfaceEvent:
    kind: SurfaceEventKind
    source: SurfaceEventSource | None = None
    payload: object | None = None


@dataclass(slots=True)
class ScreenSurfaceCoordinator:
    """Coordinate reusable screen-surface interaction and placement.

    The coordinator owns transient UI mechanics only. Products supply submit
    handlers and retain command, model, settings, approval, and status policy.
    The generic TUI ``SurfaceHost`` remains responsible for focus and overlay
    stack mechanics.
    """

    app: ScreenSurfaceAppPort
    handlers: Mapping[SurfaceEventSource, SurfaceSubmitHandler] = field(
        default_factory=dict
    )
    _active_overlay_view: ScreenSurfaceView | None = field(
        default=None, init=False, repr=False
    )
    _active_overlay_handle: SurfaceHandle | None = field(
        default=None, init=False, repr=False
    )
    _approval_queue: list[ApprovalSurface] = field(default_factory=list, repr=False)
    _approval_transitioning: bool = field(default=False, init=False, repr=False)
    _pending_page_view: ScreenSurfaceView | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def current(self) -> ScreenSurfaceView | object | None:
        self._adopt_pending_page()
        if self._active_overlay_view is not None:
            return self._active_overlay_view
        return self.app.active_surface

    async def handle_intent(self, intent: InputIntent[str]) -> int | None:
        surface = self.current
        if not isinstance(surface, ScreenSurfaceView):
            return None

        event = normalize_surface_intent(intent, surface)
        if event is None:
            return None
        if event.kind == "surface_close":
            self.close()
            if surface.purpose == "approval":
                self._open_next_approval()
            return None
        if event.source is None:
            return None
        handler = self.handlers.get(event.source)
        if handler is None:
            return None
        if event.source == "approval":
            await self._handle_approval_transition(handler, event.payload)
            return None
        await handler(event.payload)
        return None

    def open(self, view: ScreenSurfaceView) -> None:
        self.close()
        surface_host = self.app.surface_host
        if surface_host is None or view.exclusive_bottom:
            self.app.active_surface = view
            self._pending_page_view = view if view.full_screen_page else None
            return
        self.app.active_surface = None
        self._active_overlay_view = view
        self._active_overlay_handle = surface_host.open_surface(
            Surface(
                renderable=view,
                focus_target=view,
                presentation="page" if view.full_screen_page else "overlay",
                anchor="top-left" if view.full_screen_page else "bottom-left",
                width="100%",
                max_height="100%" if view.full_screen_page else "80%",
            )
        )
        self._pending_page_view = None

    def close(self) -> None:
        if self._active_overlay_handle is not None:
            self._active_overlay_handle.close("closed")
        self._active_overlay_handle = None
        self._active_overlay_view = None
        self._pending_page_view = None
        self.app.active_surface = None

    def _adopt_pending_page(self) -> None:
        pending = self._pending_page_view
        surface_host = self.app.surface_host
        if pending is None or surface_host is None:
            return
        if self.app.active_surface is pending:
            promote_pending_page_surface(self.app)
        for entry in surface_host.entries:
            if (
                entry.surface.renderable is pending
                and entry.surface.presentation == "page"
            ):
                self._active_overlay_view = pending
                self._active_overlay_handle = SurfaceHandle(
                    host=surface_host,
                    entry=entry,
                )
                self._pending_page_view = None
                return

    def present_approval(
        self,
        *,
        action: str,
        risk: str = "",
        requester: str = "",
        cwd: str = "",
        environment: str = "",
        grant_summary: str = "",
        action_id: str | None = None,
        allow_session: bool = False,
        options: tuple[ApprovalChoice, ...] = (),
    ) -> None:
        approval = ApprovalSurface(
            action=action,
            risk=risk,
            requester=requester,
            cwd=cwd,
            environment=environment,
            grant_summary=grant_summary,
            action_id=action_id,
            allow_session=allow_session,
            options=options,
            theme=_APPROVAL_SURFACE_THEME,
        )
        current = self.current
        if self._approval_transitioning or (
            isinstance(current, ScreenSurfaceView) and current.purpose == "approval"
        ):
            self._approval_queue.append(approval)
            return
        self._open_approval(approval)

    def clear_approvals(self) -> None:
        self._approval_queue.clear()
        current = self.current
        if isinstance(current, ScreenSurfaceView) and current.purpose == "approval":
            self.close()

    def dismiss_approval(self, action_id: str) -> None:
        current = self.current
        if (
            isinstance(current, ScreenSurfaceView)
            and current.purpose == "approval"
            and getattr(current.content, "action_id", None) == action_id
        ):
            self.close()
            if not self._approval_transitioning:
                self._open_next_approval()
            return
        self._approval_queue = [
            approval
            for approval in self._approval_queue
            if approval.action_id != action_id
        ]

    async def _handle_approval_transition(
        self,
        handler: SurfaceSubmitHandler,
        payload: object | None,
    ) -> None:
        self._approval_transitioning = True
        self.close()
        try:
            await handler(payload)
        finally:
            self._approval_transitioning = False
            self._open_next_approval()

    def _open_approval(self, approval: ApprovalSurface) -> None:
        self.open(
            ScreenSurfaceView(
                title="Approval required",
                purpose="approval",
                content=approval,
                footer="Enter confirm · ↑/↓ select · Esc stop turn",
                presentation="bottom-exclusive",
                theme=_APPROVAL_SURFACE_THEME,
                title_theme_token="approval.title",
            )
        )

    def _open_next_approval(self) -> None:
        if self._approval_queue:
            self._open_approval(self._approval_queue.pop(0))


def normalize_surface_intent(
    intent: InputIntent[str],
    surface: ScreenSurfaceView,
) -> SurfaceEvent | None:
    """Convert generic TUI intent into a neutral framed-surface event."""

    if (
        surface.purpose == "approval"
        and intent.kind in {"surface_close", "dialog_cancel"}
    ):
        return _approval_surface_event(
            surface,
            outcome="abort",
            note=intent.note,
        )
    if (
        surface.purpose == "session"
        and intent.kind == "consumed"
        and intent.note == "continuity_cancel_activation"
    ):
        return SurfaceEvent(kind="surface_submit", source="session_cancel")
    if intent.kind in {"surface_close", "dialog_cancel"}:
        return SurfaceEvent(kind="surface_close")
    if surface.purpose == "model" and intent.kind in {"command", "select"}:
        return SurfaceEvent(
            kind="surface_submit",
            source="model",
            payload=intent.text,
        )
    if surface.purpose == "command" and intent.kind in {"command", "select"}:
        return SurfaceEvent(
            kind="surface_submit",
            source="command",
            payload=intent.text,
        )
    if surface.purpose == "settings" and intent.kind == "setting":
        return SurfaceEvent(
            kind="surface_submit",
            source="settings",
            payload={"id": intent.text, "value": intent.note},
        )
    if surface.purpose == "session" and intent.kind == "select":
        selected_target = getattr(surface.content, "selected_target", None)
        return SurfaceEvent(
            kind="surface_submit",
            source="session",
            payload=selected_target if selected_target is not None else intent.text,
        )
    if surface.purpose == "delete" and intent.kind in {"select", "dialog_confirm"}:
        selected_target = getattr(surface.content, "selected_target", None)
        target = selected_target
        if target is None:
            target = getattr(surface.content, "target", None)
        return SurfaceEvent(
            kind="surface_submit",
            source="delete",
            payload=target if target is not None else intent.text,
        )
    if surface.purpose == "fork" and intent.kind == "select":
        selected_entry_id = getattr(surface.content, "selected_entry_id", None)
        return SurfaceEvent(
            kind="surface_submit",
            source="fork",
            payload=(
                selected_entry_id
                if selected_entry_id is not None
                else intent.text
            ),
        )
    if surface.purpose == "rename" and intent.kind == "select":
        return SurfaceEvent(
            kind="surface_submit",
            source="rename",
            payload=intent.text,
        )
    if surface.purpose == "dialog" and intent.kind == "dialog_confirm":
        return SurfaceEvent(kind="surface_submit", source="dialog")
    if surface.purpose == "approval" and intent.kind == "approval_decision":
        return _approval_surface_event(
            surface,
            outcome=cast(ApprovalOutcome, intent.text),
            note=intent.note,
        )
    if surface.purpose == "permissions" and intent.kind in {
        "select",
        "permission_profile_action",
    }:
        return SurfaceEvent(
            kind="surface_submit",
            source="permissions",
            payload=intent.text,
        )
    return None


def promote_pending_page_surface(app: ScreenSurfaceAppPort) -> bool:
    """Promote a page opened before the runner installed its SurfaceHost."""

    view = getattr(app, "active_surface", None)
    surface_host = getattr(app, "surface_host", None)
    if (
        surface_host is None
        or not isinstance(view, ScreenSurfaceView)
        or not view.full_screen_page
    ):
        return False
    app.active_surface = None
    surface_host.open_surface(
        Surface(
            renderable=view,
            focus_target=view,
            presentation="page",
            anchor="top-left",
            width="100%",
            max_height="100%",
        )
    )
    return True


def _approval_surface_event(
    surface: ScreenSurfaceView,
    *,
    outcome: ApprovalOutcome,
    note: str | None = None,
) -> SurfaceEvent:
    action_id = getattr(surface.content, "action_id", None)
    action = getattr(surface.content, "action", None)
    return SurfaceEvent(
        kind="surface_submit",
        source="approval",
        payload=ApprovalSurfaceDecision(
            action_id=action_id if isinstance(action_id, str) else None,
            action=action if isinstance(action, str) else None,
            outcome=outcome,
            raw_note=note or (action_id if isinstance(action_id, str) else None),
        ),
    )


__all__ = [
    "ApprovalSurfaceDecision",
    "ScreenSurfaceAppPort",
    "ScreenSurfaceCoordinator",
    "SurfaceEvent",
    "SurfaceEventKind",
    "SurfaceEventSource",
    "SurfaceSubmitHandler",
    "normalize_surface_intent",
    "promote_pending_page_surface",
]
