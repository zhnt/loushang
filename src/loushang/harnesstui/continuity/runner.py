"""Standalone terminal host for Product-neutral continuity discovery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TextIO, cast

from loushang.harness.continuity import ContinuityHub, ContinuityTarget
from loushang.harnesstui.continuity.surface import (
    ContinuitySurface,
    build_continuity_surface_view,
)
from loushang.tui import (
    InputEvent,
    KeybindingConfig,
    KeybindingManager,
    RenderRequestKind,
    Surface,
    Tui,
    TuiInputResult,
    TuiRunContext,
    TuiRunner,
)

ContinuityActivationHandler = Callable[[ContinuityTarget], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ContinuityPickerSelection:
    target: ContinuityTarget
    activation_result: object


async def run_continuity_picker(
    *,
    hub: ContinuityHub,
    activate: ContinuityActivationHandler,
    stdin: TextIO,
    stdout: TextIO,
    keybindings: KeybindingManager | KeybindingConfig | None = None,
) -> ContinuityPickerSelection | None:
    """Select a continuity target before a Product session exists."""

    tui = Tui()
    run_context: TuiRunContext | None = None
    selected: ContinuityPickerSelection | None = None
    load_task: asyncio.Task[None] | None = None

    def request_render(kind: str) -> None:
        if run_context is not None:
            run_context.request_render(_render_kind(kind))

    view = build_continuity_surface_view(
        hub=hub,
        request_render=request_render,
        keybindings=keybindings,
    )
    content = view.content
    if not isinstance(
        content, ContinuitySurface
    ):  # pragma: no cover - factory contract
        raise TypeError("continuity surface factory returned unsupported content")
    tui.surface_host.open_surface(
        Surface(
            renderable=view,
            focus_target=view,
            presentation="page",
            anchor="top-left",
            width="100%",
            max_height="100%",
        )
    )

    def start(context: TuiRunContext) -> None:
        nonlocal run_context, load_task
        run_context = context
        load_task = asyncio.create_task(content.start())

    async def handle_input(
        event: InputEvent,
        context: TuiRunContext,
    ) -> TuiInputResult:
        nonlocal selected
        intents = context.tui.handle_input(event)
        for intent in intents:
            kind = getattr(intent, "kind", None)
            if kind == "select":
                target = content.selected_target
                if target is not None:
                    try:
                        activation_result = await activate(target)
                    except Exception as error:
                        content.report_error(error)
                        return TuiInputResult(render_requested=True)
                    selected = ContinuityPickerSelection(
                        target=target,
                        activation_result=activation_result,
                    )
                    return context.stop()
            if kind in {"surface_close", "dialog_cancel"}:
                return context.stop()
        return TuiInputResult()

    try:
        await TuiRunner(tui, stdin=stdin, stdout=stdout).run(
            on_input=handle_input,
            on_start=start,
        )
        return selected
    finally:
        content.close()
        if load_task is not None and not load_task.done():
            load_task.cancel()
            await asyncio.gather(load_task, return_exceptions=True)


def _render_kind(kind: str) -> RenderRequestKind:
    if kind in {"input", "stream", "timer", "product", "resize"}:
        return cast(RenderRequestKind, kind)
    return "product"


__all__ = [
    "ContinuityActivationHandler",
    "ContinuityPickerSelection",
    "run_continuity_picker",
]
