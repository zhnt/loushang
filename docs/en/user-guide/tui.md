# Building TUI Apps

English | [中文](../../zh-CN/user-guide/tui.md)

This guide shows how to build a small terminal UI with `loushang.tui`. Use it when you want a product-facing interactive terminal surface. For exact lifecycle details, see the [TUI Runner reference](../reference/tui-runner.md). For reusable input editing, see [TUI Editing](../reference/tui-editing.md).

## Choose The Entry Point

Use `TuiRunner` for normal applications. It owns terminal setup, input parsing, render scheduling, output, and cleanup.

Use lower-level APIs such as `TuiRuntime`, `RenderLoop`, `InputReader`, and `TerminalSession` only when you need a custom loop or a playback harness.

## Render A Root View

A renderable object implements `render(constraints)` and returns `RenderResult`.

```python
from loushang.tui import RenderConstraints, RenderLine, RenderResult


class StatusView:
    def __init__(self) -> None:
        self.status = "Ready"

    def render(self, constraints: RenderConstraints) -> RenderResult:
        rows = [
            "Loushang TUI",
            "",
            f"Status: {self.status}",
        ]
        return RenderResult.from_lines([RenderLine(row[: constraints.width]) for row in rows], constraints=constraints)
```

Attach it to a `Tui` and run it:

```python
import asyncio

from loushang.tui import Tui, TuiRunner


async def main() -> int:
    tui = Tui()
    tui.add_child(StatusView())
    return await TuiRunner(tui).run()


raise SystemExit(asyncio.run(main()))
```

## Handle Input

Without `on_input`, `TuiRunner` routes events through `tui.handle_input(event)`. This works well when focusable children or surfaces own input.

Pass `on_input` when the app needs top-level commands:

```python
from loushang.tui import InputEvent, TuiInputResult


async def on_input(event: InputEvent, context) -> TuiInputResult:
    if event.kind == "text" and "q" in event.text.lower():
        return context.stop(0)
    context.tui.handle_input(event)
    return TuiInputResult()
```

When `on_input` is provided, it fully owns event handling. Call `context.tui.handle_input(event)` explicitly when you want default focus and surface routing.

## Request Renders From Async Work

If an async task changes visible state while the runner is waiting for input, call `context.request_render(kind)`.

```python
async def refresh(context, view):
    view.status = "Refreshing"
    context.request_render("stream")
```

The request goes through the render scheduler and wakes the input wait loop.

## Use Surfaces For Temporary UI

Use `tui.show_overlay()` for dialogs, selectors, command palettes, and other temporary UI. If the renderable is focusable, it can receive input while the surface is active.

```python
handle = tui.show_overlay(dialog, focus_target=dialog, presentation="modal", anchor="center")
```

Close the returned handle when the surface is no longer needed.

## Reuse Editing Primitives

Use `TextInput` for single-line inputs such as search fields and filters. Use `Composer` plus `InputRouter` for multi-line prompt editors with history, paste markers, completion, selection, undo, and kill/yank behavior.

```python
from loushang.tui import Composer, InputEvent, InputRouter, TextInput


field = TextInput(prompt="Search: ")
field.handle_input(InputEvent(kind="text", text="hello world"))
field.handle_input(InputEvent(kind="key", key="ctrl+shift+left"))
field.handle_input(InputEvent(kind="text", text="loushang"))

composer = Composer(prompt="> ")
router = InputRouter(composer, width=80, height=24)
router.route(InputEvent(kind="text", text="alpha beta"))
router.route(InputEvent(kind="key", key="shift+left"))
router.route(InputEvent(kind="key", key="ctrl+k"))
```

The generic `InputRouter` emits neutral `submit` and `prompt_cancel` intents;
your application decides what they mean for its current state. Use Harnesstui's
`ConversationInputRouter` when a Harness-backed conversation needs running
submit, steer/follow-up, queue restore, and abort semantics.

`TextInput` selection indexes are grapheme clusters. `Composer` selection indexes are composer atoms, so paste markers remain atomic. Display width is handled by rendering.

## Examples

- [examples/tui/40_runner_basic.py](../../../examples/tui/40_runner_basic.py): small interactive counter using `TuiRunner`.
- [examples/tui/41_editing_foundation.py](../../../examples/tui/41_editing_foundation.py): TextInput and Composer editing walkthrough.
- [TUI Runner reference](../reference/tui-runner.md): lifecycle API details.
- [TUI Editing reference](../reference/tui-editing.md): editing primitives, keybindings, and playback smoke checks.
