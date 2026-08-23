# 构建 TUI 应用

[English](../../en/user-guide/tui.md) | 中文

本文说明如何用 `loushang.tui` 构建小型终端 UI。需要产品化的交互式终端界面时，可以从这里开始。生命周期细节见 [TUI Runner 参考](../reference/tui-runner.md)。可复用输入编辑能力见 [TUI 编辑能力](../reference/tui-editing.md)。

## 选择入口

普通应用优先使用 `TuiRunner`。它负责终端设置、输入解析、渲染调度、输出和退出清理。

只有在需要自定义循环或 playback harness 时，才直接使用 `TuiRuntime`、`RenderLoop`、`InputReader`、`TerminalSession` 这类底层 API。

## 渲染根视图

一个 renderable 对象实现 `render(constraints)`，并返回 `RenderResult`。

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

把它挂到 `Tui` 上并运行：

```python
import asyncio

from loushang.tui import Tui, TuiRunner


async def main() -> int:
    tui = Tui()
    tui.add_child(StatusView())
    return await TuiRunner(tui).run()


raise SystemExit(asyncio.run(main()))
```

## 处理输入

不传 `on_input` 时，`TuiRunner` 会把事件交给 `tui.handle_input(event)`。如果 focusable child 或 surface 自己处理输入，这种方式最简单。

应用需要顶层命令时，可以传入 `on_input`：

```python
from loushang.tui import InputEvent, TuiInputResult


async def on_input(event: InputEvent, context) -> TuiInputResult:
    if event.kind == "text" and "q" in event.text.lower():
        return context.stop(0)
    context.tui.handle_input(event)
    return TuiInputResult()
```

传入 `on_input` 后，handler 完全接管事件处理。需要默认 focus 和 surface 路由时，要显式调用 `context.tui.handle_input(event)`。

## 从异步任务请求渲染

如果异步任务在 runner 等待输入时改变了可见状态，调用 `context.request_render(kind)`。

```python
async def refresh(context, view):
    view.status = "Refreshing"
    context.request_render("stream")
```

这个请求会经过渲染调度器，并唤醒输入等待循环。

## 使用 Surface 构建临时 UI

对话框、选择器、命令面板等临时 UI 可以用 `tui.show_overlay()`。如果 renderable 是 focusable，它在 surface 激活时可以接收输入。

```python
handle = tui.show_overlay(dialog, focus_target=dialog, presentation="modal", anchor="center")
```

临时 UI 不再需要时，关闭返回的 handle。

## 复用编辑基础设施

单行搜索、过滤等输入使用 `TextInput`。多行 prompt 编辑器使用 `Composer` 配合 `InputRouter`，以获得历史、paste marker、completion、selection、undo 和 kill/yank 行为。

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

通用 `InputRouter` 只产生中立的 `submit` 和 `prompt_cancel` intent，具体含义由
应用结合自身状态决定。基于 Harness 的会话如果需要运行中提交、steer/follow-up、
队列恢复和中断语义，应使用 Harnesstui 的 `ConversationInputRouter`。

`TextInput` selection 索引用 grapheme cluster。`Composer` selection 索引用 composer atom，因此 paste marker 会保持原子性。显示宽度由渲染层处理。

## 示例

- [examples/tui/40_runner_basic.py](../../../examples/tui/40_runner_basic.py)：使用 `TuiRunner` 的小型交互计数器。
- [examples/tui/41_editing_foundation.py](../../../examples/tui/41_editing_foundation.py)：TextInput 和 Composer 编辑 walkthrough。
- [TUI Runner 参考](../reference/tui-runner.md)：生命周期 API 细节。
- [TUI 编辑能力参考](../reference/tui-editing.md)：编辑基础设施、快捷键和 playback smoke 检查。
