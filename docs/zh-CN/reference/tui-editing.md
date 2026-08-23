# TUI 编辑能力

[English](../../en/reference/tui-editing.md) | 中文

`loushang.tui` 提供可复用的终端编辑基础设施。当 surface 需要光标移动、选择、undo、kill/yank、粘贴或 completion 行为时，应优先复用这些组件，而不是维护各自的编辑状态。

生命周期入口见 [TUI Runner](tui-runner.md)。

## 组件

| 组件 | 适用场景 | 索引单位 |
| --- | --- | --- |
| `TextInput` | 搜索、过滤、小型 prompt 等单行输入。 | Grapheme cluster |
| `Composer` | 多行 prompt 编辑器、bottom-frame composer、paste marker、历史和 completion。 | Composer atom |
| `InputRouter` | 按真实用户输入路径处理编辑，并产生中立的 `submit`、`prompt_cancel` intent。 | Composer atom |
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

`InputRouter` 不理解会话运行态。非空 Enter 只产生一个 `submit` intent；
未被消费的 Escape 或 Ctrl+C 产生 `prompt_cancel`。活跃 surface、聚焦编辑器、
completion 和待完成的字符跳转仍拥有更高优先级，可以先消费取消键。应用适配层
决定中立提交是启动任务、排队 follow-up 还是 steer 当前任务，也决定 prompt
cancel 是退出、清空还是中断工作。基于 Harness 的会话应用应使用 Harnesstui 的
`ConversationInputRouter` 承担运行态策略。

Harness 通过 `SessionInputCapabilities` 声明 steer 与 follow-up 交付能力；
Harnesstui 默认对运行中的普通提交采用 steer-first，并在 steer 不可用时确定性
降级为 follow-up。物理键位独立配置：Enter 仍是 `tui.input.submit`，显式
follow-up 使用 `conversation.input.followUp`（默认 Alt+Enter）。空闲时 Alt+Enter
仍按 `tui.input.newLine` 插入换行，运行态优先级由 `ConversationInputRouter` 解释。

快捷键默认值按所有者组合。通用 TUI 提供 Core
`TUI_CORE_KEYBINDING_CATALOG`；HarnessTUI 在构造会话或 continuity surface 时
追加相应 catalog。重复 action 定义会在组合时直接失败，用户覆盖则保留到对应
catalog 加载后再解析。剪贴板图片粘贴使用会话 action
`conversation.input.pasteImage`（默认 Ctrl+V）。

### 输入意图契约

`InputIntent` 保持为一个运行时数据类，并以开放的 kind 类型参数表达所有者词表。
通用 surface 和经过准入的 presentation adapter 使用 `InputIntent[str]`；各所有者
可以为自己产生的 kind 定义更窄的 `Literal` 别名。`InputRouter` 直接产生的词表仅限
`submit`、`prompt_cancel` 与 `invalidate_render`，surface 意图则原样转发，不重新解释。

`InputIntentKind` 暂时仍可导入，但它只是 `str` 兼容别名，不再是中央允许列表。
新的生产注解应使用 `InputIntent[str]` 或所有者本地的窄别名。外部 kind 建议使用
`example_plugin.openArtifact` 这类所有者限定名；为保持兼容，运行时 envelope 仍
有意接受任意字符串。未来的 Harness Plugin 声明不依赖 TUI；只有承担所有权的
presentation adapter 才能在准入后把声明转换为 `InputIntent[str]`。

两个 Router 下方共享 Prompt 编辑机械。`loushang.tui.input` 中的中立 helper
负责普通文本或字符跳转、粘贴、显式 Tab completion，以及垂直移动、历史和翻页。
它们只修改传入的 editor target，不产生 TUI intent 或 conversation result。
两个 Router 各自保留原有分支顺序，并把“已处理”转换为自己的结果：通用
`InputRouter` 不返回 intent，`ConversationInputRouter` 返回
`ConversationInputHandled`。

提交、取消、resize、surface 路由、剪贴板图片、本地命令、completion Enter，
以及运行中的 steer/follow-up 策略不会进入这些共享 helper，因为它们的顺序或
含义由不同所有者决定。

生产环境中的会话 Router 构造只使用一个标准 Factory 契约。该契约与
HarnessTUI 会话输入放在同一 owner 中，并由 screen runner 重导出。带剪贴板
能力的 Builder 是兼容扩展，只额外暴露可选的环境与测试依赖。产品适配器绑定
自己的策略和 profile 后直接传入该 Factory，不再使用类型强制转换。这个契约
只是输入装配接缝，并不定义插件生命周期。

Coding 的 `run_coding_tui()` 在组合根边界接受这个不可变的 screen run profile，
默认值仍是 `CODING_SCREEN_RUN_PROFILE`。Product adapter 可以注入其他 profile，
不必修改 HarnessTUI 或 screen binding；该入口只负责透传已选值，不执行插件
发现或生命周期管理。

Composer selection 使用 atom 索引。普通文本会拆成类 grapheme 的文本 atom；大型 paste marker 是单个 atom，range edit 不会把它拆开。

## Pre-1.0 InputRouter 迁移

通用 Router 不再拥有会话状态。这是一次有意的 pre-1.0 边界收窄：

| 旧 API | 基于 Harness 的替代方式 | 通用应用的替代方式 |
| --- | --- | --- |
| `InputRouter(running=...)` | 将状态投影给 `ConversationInputRouter`。 | 由应用状态解释通用 `submit`。 |
| `steering_supported=...` | 由 Harness `SessionInputCapabilities` 声明能力，Harnesstui `ConversationInputPolicy` 选择 steer-first 与降级。 | 在应用适配层解释能力投影。 |
| `submit(mode=...)` | 使用 HarnessTUI 的运行中提交路由。 | 调用无参数 `submit()`，再由应用解释结果。 |
| 第三个/第四个位置状态参数 | 改用显式 HarnessTUI 配置。 | 改用仅限关键字的通用配置与应用状态。 |

只有 `composer` 和 `surface_host` 仍可作为位置参数；`width`、`height`、
`keybindings` 和 `target` 都必须使用关键字。旧调用
`InputRouter(composer, None, True)` 现在会抛出 `TypeError`，不会把 `True`
静默绑定到 `width`。

原 `app.clipboard.pasteImage` 配置已替换为
`conversation.input.pasteImage`。这是一次 pre-1.0 重命名，用于明确剪贴板图片是
HarnessTUI 公共会话能力，而不是 Coding 应用私有 action。

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
