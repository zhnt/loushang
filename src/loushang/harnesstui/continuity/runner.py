"""Standalone terminal host for Product-neutral continuity discovery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TextIO, cast

from loushang.harness.continuity import (
    ContinuityTarget,
    StableContinuityReference,
)
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
    reference: StableContinuityReference,
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
    activation_task: asyncio.Task[object] | None = None

    def request_render(kind: str) -> None:
        if run_context is not None:
            run_context.request_render(_render_kind(kind))

    view = build_continuity_surface_view(
        reference=reference,
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

    def _on_activation_done(
        task: asyncio.Task[object],
        target: ContinuityTarget,
    ) -> None:
        nonlocal selected
        if task.cancelled():
            content.cancel_activation()
            return
        error = task.exception()
        if error is not None:
            content.fail_activation(error)
            return
        selected = ContinuityPickerSelection(
            target=target,
            activation_result=task.result(),
        )
        if run_context is not None:
            # Stop the loop even if the user never presses another key.
            run_context.request_stop(0)

    def activation_done_callback(
        target: ContinuityTarget,
    ) -> Callable[[asyncio.Task[object]], None]:
        def on_activation_done(task: asyncio.Task[object]) -> None:
            _on_activation_done(task, target)

        return on_activation_done

    def start(context: TuiRunContext) -> None:
        nonlocal run_context, load_task
        run_context = context
        load_task = asyncio.create_task(content.start())

    async def activate_target(target: ContinuityTarget) -> object:
        return await activate(target)

    async def handle_input(
        event: InputEvent,
        context: TuiRunContext,
    ) -> TuiInputResult:
        nonlocal activation_task
        intents = context.tui.handle_input(event)
        for intent in intents:
            kind = getattr(intent, "kind", None)
            note = getattr(intent, "note", "")
            if note == "continuity_cancel_activation":
                if activation_task is not None and not activation_task.done():
                    activation_task.cancel()
                return TuiInputResult(render_requested=True)
            if kind == "select":
                target = content.selected_target
                if target is None:
                    continue
                if activation_task is not None and not activation_task.done():
                    continue
                if not content.begin_activation():
                    return TuiInputResult(render_requested=True)
                activation = asyncio.create_task(activate_target(target))
                activation_task = activation
                activation.add_done_callback(activation_done_callback(target))
                return TuiInputResult(render_requested=True)
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
        pending = [
            task
            for task in (load_task, activation_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def _render_kind(kind: str) -> RenderRequestKind:
    if kind in {"input", "stream", "timer", "product", "resize"}:
        return cast(RenderRequestKind, kind)
    return "product"


__all__ = [
    "ContinuityActivationHandler",
    "ContinuityPickerSelection",
    "run_continuity_picker",
]
