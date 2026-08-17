# TUI 编辑能力

[English](../../en/reference/tui-editing.md) | 中文

`loushang.tui` 提供可复用的终端编辑基础设施。当 surface 需要光标移动、选择、undo、kill/yank、粘贴或 completion 行为时，应优先复用这些组件，而不是维护各自的编辑状态。

生命周期入口见 [TUI Runner](tui-runner.md)。

## 组件

| 组件 | 适用场景 | 索引单位 |
| --- | --- | --- |
| `TextInput` | 搜索、过滤、小型 prompt 等单行输入。 | Grapheme cluster |
| `Composer` | 多行 prompt 编辑器、bottom-frame composer、paste marker、历史和 completion。 | Composer atom |
| `InputRouter` | 按真实用户输入路径路由 Composer 的 key、text、paste、completion、history、submit 和 surface event。 | Composer atom |
| `SelectionRange` / `SelectionController` | 可复用的 anchor/focus selection 状态。 | 由所属 buffer 决定 |

编辑索引不是终端显示列。CJK、emoji、组合字符和 paste marker 都保持稳定的逻辑索引；显示宽度只属于渲染和 hit-test 层。

## TextInput

`TextInput` 是可聚焦的单行编辑器。它内部使用 `EditorBuffer`、selection 状态、undo/redo stack 和 kill ring。

```python
from loushang.tui import InputEvent, RenderConstraints, TextInput


field = TextInput(prompt="Search: ", placeholder="type to filter")
field.focus()

field.handle_input(InputEvent(kind="text", text="hello world"))
field.handle_input(InputEvent(kind="key", key="ctrl+shift+left"))
assert field.selected_range == (6, 11)

field.handle_input(InputEvent(kind="text", text="loushang"))
assert field.value == "hello loushang"

field.handle_input(InputEvent(kind="key", key="ctrl+-"))
assert field.value == "hello world"

field.handle_input(InputEvent(kind="key", key="alt+r"))
assert field.value == "hello loushang"

result = field.render(RenderConstraints(width=40, max_height=1))
```

用户按键优先走 `handle_input()`，因为它会记录 undo 边界并触发回调。`set_text()` 和 `clear()` 是程序化 reset，会清理 undo/redo 历史。没有活跃非空 selection 时，`selected_range` 返回 `None`。

## Composer

`Composer` 是 prompt 和 bottom-frame UI 使用的多行编辑器。它提供 atom-aware editing、paste marker 安全性、历史、completion refresh 和 selection 高亮渲染。

希望得到接近真实终端输入的行为时，使用 `InputRouter`：

```python
from loushang.tui import Composer, InputEvent, InputRouter, RenderConstraints


composer = Composer(prompt="> ")
router = InputRouter(composer, width=72, height=12)

router.route(InputEvent(kind="text", text="alpha beta"))
router.route(InputEvent(kind="key", key="shift+left"))
assert composer.selected_range == (9, 10)

router.route(InputEvent(kind="key", key="ctrl+k"))
assert composer.value == "alpha bet"
assert composer.kill_ring[0] == "a"

router.route(InputEvent(kind="key", key="ctrl+y"))
assert composer.value == "alpha beta"

result = composer.render(RenderConstraints(width=72, max_height=6))
```

Composer selection 使用 atom 索引。普通文本会拆成类 grapheme 的文本 atom；大型 paste marker 是单个 atom，range edit 不会把它拆开。

## 默认编辑快捷键

| 动作 | 默认按键 |
| --- | --- |
| 左右移动 | `left`, `right`, `ctrl+b`, `ctrl+f` |
| 按词移动 | `alt+left`, `ctrl+left`, `alt+b`, `alt+right`, `ctrl+right`, `alt+f` |
| 移到行首/行尾 | `home`, `ctrl+a`, `alt+<`, `end`, `ctrl+e`, `alt+>` |
| 按字符选择 | `shift+left`, `shift+right` |
| 按词选择 | `ctrl+shift+left`, `alt+shift+b`, `ctrl+shift+right`, `alt+shift+f` |
| 按行范围选择 | `shift+home`, `shift+end` |
| 删除字符 | `backspace`, `delete`, `ctrl+d` |
| 删除词 | `ctrl+w`, `alt+backspace`, `alt+d`, `alt+delete` |
| kill 到行首/行尾 | `ctrl+u`, `ctrl+k` |
| Yank / yank-pop | `ctrl+y`, `alt+y` |
| Undo | `ctrl+-`, `ctrl+_`, `alt+u` |
| Redo | `alt+r` |
| 换行/提交 | `shift+enter`, `alt+enter`, `ctrl+j`, `enter` |

部分终端会把 `ctrl+-` 上报为 `ctrl+_`，两者都会触发 undo。`alt+u`
和 `alt+r` 提供更好记且更稳定的终端 undo/redo 备用键，同时不占用
`ctrl+u` 或 `ctrl+r`。

## Selection-Aware Edit

存在 selection 时：

- 输入文本和粘贴会用一次 undoable edit 替换选中范围
- Backspace 和 Delete 删除选中范围，不会额外删除相邻文本
- kill 命令只 kill 选中范围，不再继续应用行/词边界
- yank 会替换选中范围
- 应用 completion 会清除文本 selection
- undo 和 redo 恢复内容与光标，然后清除 selection

completion 列表 selection 和 composer 文本 selection 相互独立。selection 快捷键优先于 completion 列表导航；未加修饰的 `up`、`down`、`tab`、`enter` 仍保持 completion 行为。

## Playback Smoke Cookbook

修改 composer 输入、selection、paste marker、completion、keybinding 或 render highlight 行为前，运行 playback：

```bash
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py --list
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py composer-selection-stress --artifacts /tmp/loushang-selection-playback --include-frames
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py --tag composer --json
```

排查瞬时 selection 渲染时使用 `--include-frames`。replacement、kill、yank 或 undo 后 selection 会被刻意清除，最终屏幕通常看不到先前选中状态。

## 示例

- [examples/tui/41_editing_foundation.py](../../../examples/tui/41_editing_foundation.py)：确定性的 TextInput 和 Composer 编辑 walkthrough。
- [examples/tui/35_completion_providers.py](../../../examples/tui/35_completion_providers.py)：Composer completion provider 行为。
- [examples/tui/40_runner_basic.py](../../../examples/tui/40_runner_basic.py)：`TuiRunner` 生命周期和顶层输入处理。
