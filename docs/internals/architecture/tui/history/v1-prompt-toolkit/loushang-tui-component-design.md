# Loushang TUI Component Design

## Status

Active design; P0 primitives and P1 lightweight controls are implemented. P1 integration is in progress. Completed assistant transcript Markdown rendering and coding-owned Tool Transcript Blocks are implemented.

## Date

2026-05-16

## Scope

本文档描述 `loushang.tui` 的白盒候选组件、边界约束与演进顺序。

`loushang.tui` 是通用 terminal UI primitive layer，不是 `loushang-coding` 产品 UI。它当前服务 inline terminal workflow：

- 保留真实 terminal scrollback 作为 transcript。
- 底部 composer / working / pending / status 区域是 transient UI。
- `loushang.coding.ui` 作为 consumer，把 coding runtime/session 状态适配成 generic TUI 输入。

本文不设计：

- `loushang.coding` 的 session / agent loop 状态机。
- model / tool / session 等业务语义。
- 完整 fullscreen app-style TUI 框架。
- extension UI 的最终协议。

## Current Implementation Snapshot

当前源码已经具备一组 P0 primitives 和轻量 P1 controls：

```text
src/loushang/tui/
  terminal.py       # interactive terminal detection
  output.py         # transcript-safe terminal output helpers
  control.py        # generic control controller/renderer protocols
  fragments.py      # generic (style, text) fragment helpers
  display.py        # generic TextView, Frame, KeyValueList, ColumnList, Notice primitives
  render/           # generic terminal rendering primitives
    blocks.py       # generic typed terminal transcript blocks
    console.py      # Rich console factory and renderable -> terminal text
    code.py         # code text -> terminal transcript rendering
    diff.py         # diff text/stat -> terminal transcript rendering
    markdown.py     # completed-block Markdown transcript rendering
    rule.py         # stable-width terminal rules
  text_utils.py     # fixed-width rendering helpers
  theme.py          # prompt_toolkit style tokens
  choices.py        # generic single-choice state model
  select_list.py    # generic select list control and runner
  confirm.py        # generic confirmation prompt and runner
  text_input.py     # generic text input prompt and runner
  info_panel.py     # generic read-only information panel and runner
  settings_list.py  # generic toggle settings control and runner
  autocomplete.py   # generic completion provider and input runner
  command_palette.py # generic searchable selector and runner
  inline/           # public inline prompt runtime package
    __init__.py     # inline prompt runtime facade
    keymap.py       # generic inline key/action routing
    app.py          # prompt_toolkit Application assembly
    composer.py     # internal composer normalization and height calculation
    composer_policy.py # internal composer delivery policy
    local_interaction.py # generic local control scheduling substrate
    command_palette.py # CommandPalette inline-local adapter
    info_panel.py   # InfoPanel inline-local adapter
    settings_list.py # SettingsList inline-local adapter
    confirm.py      # Confirm inline-local adapter
    text_input.py   # TextInput inline-local adapter
    actions.py      # generic inline action dispatch
    state.py        # inline runtime presentation state
    tasks.py        # prompt/abort/deferred task lifecycle
    views.py        # prompt_toolkit window builders
    layout.py       # prompt_toolkit root layout assembly
  status.py         # StatusLine and WorkingLine
  queue.py          # generic pending queue rendering
  prompt.py         # non-interactive prompt fallback
```

当前主要技术债不再是“缺少模块”，而是：

- `inline/` 已拆成 runtime facade + focused helpers，但仍承担 provider/callback wiring 与 prompt_toolkit application assembly。
- P1 lightweight controls 已经以 flat modules 形式存在；`SelectList`、`SettingsList`、`CommandPalette`、`Confirm`、`TextInput`、`InfoPanel` 已对齐为 controller/action 契约，选择类控件额外保留 renderer。`InlineLocalInteraction` 提供了通用本地交互宿主，负责保存/恢复 composer、统一 local control 结果/取消/错误状态、渲染本地控件区域，并优先分发本地控件动作。`start_inline_command_palette()`、`start_inline_info_panel()`、`start_inline_settings_list()`、`start_inline_confirm()`、`start_inline_text_input()` 已把这些 generic controls 适配到这个宿主；具体 slash command workflow 仍由 `loushang.coding.ui` 拥有。
- `prompt.py` 只提供 `run_non_interactive_prompt_loop()`，作为非交互 fallback，而不是第二套 TUI 架构。

因此后续开发应优先稳定 inline runtime 的内部边界，然后再添加交互控件。

## Dependency Boundary

源码依赖方向固定为：

```text
loushang.coding.ui -> loushang.tui
```

`loushang.tui` 不依赖：

- `loushang.coding`
- `loushang.agent`
- `loushang.ai`
- session / model / tool / method 等业务类型

`prompt_toolkit` 和 Rich 是内部实现技术，不是架构边界。公共 API 不应要求调用方理解 prompt_toolkit `Window`、`Buffer`、`Container` 或 Rich `Console` 的细节。

Rich-based terminal rendering belongs under `loushang.tui.render` when it is generic.
Product renderers may use the package facade, but `loushang.tui.render` must not know about
coding events, tools, sessions, models, or slash commands.
The `loushang.tui.render` package facade stays lazy: importing the facade and accessing helper functions
must not load Rich. Rich is an execution-time dependency of concrete render helpers, not an import-time
cost for product code that only needs helper references or pure utilities such as `diff_stat()`.

### Public API Boundary

`loushang.tui.__init__` 是 consumer-facing facade，只导出稳定的 generic primitives、controls、view models 和 standalone runner 函数。业务层应优先从 `loushang.tui` facade 导入这些对象，例如 `CommandPalette`、`InfoPanel`、`PendingQueueView`。
Inline runtime 和 local-control host API 从 `loushang.tui.inline` facade 导入，例如 `InlinePromptConfig`、`InlineAction`、`run_inline_prompt_app()` 和 `start_inline_command_palette()`。Inline runtime delivery policy types, such as `ComposerPolicy` and `ComposerDelivery`, stay out of public facades.

Facade import must stay lightweight. `import loushang.tui` and access to any symbol exported
from `loushang.tui.__all__` must not import prompt_toolkit or Rich. Interactive runners, style
conversion, and generic terminal render helpers may load those dependencies at execution time.
The top-level and inline facades keep `TYPE_CHECKING` re-exports for static analysis; those
imports are not part of runtime startup.

允许直接从子模块导入的情况：

- `loushang.tui.render` package facade 是 production-facing terminal rendering primitive，例如 Markdown、console、ANSI conversion。它只能提供通用渲染能力，不能包含产品语义。Production code should import render helpers from the package facade; concrete `loushang.tui.render.*` modules remain stable implementation modules for tests and low-level TUI internals.
- `loushang.tui.prompt.run_non_interactive_prompt_loop()` 是 non-interactive fallback 的窄入口。
- `loushang.tui.text_utils.fixed_width` 是 status alignment 这类跨产品适配层需要的窄工具。
- 测试需要白盒覆盖 internal runtime 单元。

`loushang.coding` 生产代码的直接子模块导入只允许明确白名单：

- `loushang.tui.inline` for inline runtime and local-control host entry points.
- `loushang.tui.prompt` for `run_non_interactive_prompt_loop()`. It must reject interactive terminals; TTY mode belongs to `loushang.tui.inline.run_inline_prompt_app()`.
- `loushang.tui.render` for generic transcript rendering helpers, such as Markdown rendering.
- `loushang.tui.text_utils` for fixed-width status rendering.

其他 generic primitives 应从 `loushang.tui` 顶层 facade 导入。Inline runtime/local-control API 应从 `loushang.tui.inline` facade 导入。`TranscriptEmitter` 也属于 top-level facade API；产品层不直接导入 `loushang.tui.output`。

不允许产品层依赖的 internal surface：

- `loushang.tui.inline.*` helper modules，例如 `inline.runtime`、`inline.services`、`inline.layout`、`inline.local_interaction`。
- prompt_toolkit containers/buffers/windows。
- `output.py` 的低级 helper，如 `emit_in_terminal`、`patched_stdout`、`write_line`。这些 helper 可以保留在模块内供 runtime 使用，但不从 top-level facade 导出。

这条边界由 `tests/tui/test_import_boundaries.py` 固化：`loushang.tui.__all__` 必须是明确列表，所有顶层 public exports 必须保持 lazy/lightweight，`loushang.coding` 不得导入 `loushang.tui.inline.*`，并且直接 `loushang.tui.*` 子模块导入必须落在上述白名单内。

## Design Principles

### Primitive First, Framework Later

当前不直接实现完整的 `Component / Container / Focusable / Overlay` 框架。

这些抽象适合复杂 TUI：

- 多焦点区域
- 命令面板
- 选择器
- modal / overlay
- fullscreen layout
- extension-provided controls

但当前 P0 的主要问题是 inline runtime 内部职责混杂，而不是缺少完整 UI framework。因此先拆出可测试、可复用的 primitives。等局部 controls 变多后，再引入更强的 component/focus/overlay 架构。

### Stable Scrollback Is Product Behavior

Transcript 必须写入真实 terminal scrollback。它不是可重绘 component tree 的一部分。

因此：

- assistant/tool/error/final blocks 通过 transcript emitter 写入终端。
- composer/status/working/pending 是 transient 区域。
- 重绘 transient 区域不能破坏 scrollback。

### Rendering Boundary

Rendering is split by responsibility:

```text
loushang.tui.output
  transcript-safe terminal writes
  run_in_terminal / patched stdout

loushang.tui.render
  generic terminal rendering primitives
  console setup / Markdown / code / diff / rule / block helpers

loushang.coding.ui.renderer
  coding-specific transcript decisions
  user, assistant, tool summary, worked, interruption, error
```

`loushang.tui.render` is not a product renderer. It should answer questions like "how do I render Markdown to terminal output?" and "how do I turn a Rich renderable into ANSI for prompt_toolkit?", not "how should a tool call or provider error look?"

Generic render blocks are a small composition primitive for already-classified terminal
content. `TextBlock`, `MarkdownBlock`, `CodeBlock`, `DiffBlock`, and `RuleBlock` describe
rendering format only; `TerminalBlock` is the public type alias for those values.
`block_to_terminal_text()` and `blocks_to_terminal_text()` convert those blocks into terminal
text through the same lazy render helpers. They are allowed in `loushang.tui.render` because
they still do not know why the content exists; product layers own the projection from events
or domain objects into blocks.

Markdown is data until it reaches a view:

- session records store raw Markdown.
- JSON, workflow, and export data keep raw Markdown unless their own format explicitly renders it.
- terminal transcript may render assistant final text as Markdown.
- inline composer, status, working line, and pending queue remain plain prompt_toolkit fragments.
- tool transcript blocks remain coding-owned projections. They may use generic terminal rendering helpers, but the decision about what a tool call means stays in `loushang.coding.ui`.

The first Markdown renderer should render only completed assistant blocks. Streaming Markdown rendering is deferred because incomplete fences, tables, and lists can cause layout jitter in scrollback-oriented terminal output.

### Tool Transcript Blocks

Tool transcript blocks are not generic TUI components. They are a coding UI projection over `tool_execution_start`,
`tool_execution_update`, and `tool_execution_end` events.

Reference boundaries:

- Kimi separates model-facing tool output from user-facing display blocks.
- Claude Code lets each tool provide a call/result renderer, then wraps that output in common tool chrome.
- Codex-style scrollback favors concise action summaries over dumping full tool output into the main transcript.

Loushang follows the same split:

```text
tool_execution_* event
  -> loushang.coding.ui.tool_blocks.ToolTranscriptProjector
  -> ToolTranscriptBlock
  -> loushang.coding.ui.renderer.render_tool_block()
  -> terminal transcript
```

The block shape is intentionally small:

- `verb`: `Ran`, `Explored`, `Edited`, `Tested`, or `Used <tool>`.
- `title`: one-line call summary such as `bash pytest -q` or `read src/foo.py`.
- `status`: `ok`, `error`, `cancelled`, `timed_out`, or `terminate`.
- `detail`: short failure/status summary or compact edit/write stat such as `+3 -1` or `created, 120 B`.
- `body`: optional bounded preview for tools where output is useful in scrollback.

Body policy:

- exploration and command tools may show bounded previews.
- long command/test output prefers the tail, because failures and summaries usually appear near the end.
- edit/write tools do not dump diffs or file content into the transcript; they use `detail` for compact change stats.
- failed tools show a short error detail and keep verbose output in tool result/export/debug paths.

The projector can reuse `ToolRenderRuntime` and per-tool `render_call` / `render_result`, but output is still bounded before entering the transcript. Full output, raw tool results, artifacts, and structured `rendered_tool_result` payloads remain available through JSON/RPC/export/debug paths.

### TUI Uses UI Semantics Only

`loushang.tui` 可以理解 generic UI action：

- submit
- newline
- abort
- exit
- dequeue
- running submit
- running alternate submit

`loushang.tui` 不理解 coding action：

- steer
- follow-up
- tool approval
- model selection
- session resume
- bash intent

这些业务语义由 `loushang.coding.ui` 解释。

### Business UI Is Adapter-Owned

`/models`、`/status`、`/statusline`、`/settings` 等 slash command 的解析与业务执行属于 `loushang.coding.ui`。

`loushang.tui` 只提供 generic controls，例如 select list、settings list、info panel、confirm dialog。

## P0 Components

P0 目标是拆分和稳定现有 inline runtime，不新增大型交互模型。

| Component | Module | Responsibility |
| --- | --- | --- |
| `TerminalPort` | `terminal.py` | TTY 判断、终端尺寸、基础 terminal capability |
| `TextUtils` | `text_utils.py` | fixed width、truncate、wrap、visible width |
| `TranscriptEmitter` | `output.py` | 封装 `run_in_terminal`，稳定写 transcript |
| `InlineRuntime` | `inline/` | 组装 inline prompt application |
| `InlineComposer` / `ComposerPolicy` | `inline/composer.py`, `inline/composer_policy.py` | 输入文本、空白判断、高度计算、运行中输入与 deferred prompt 投递策略 |
| `StatusLine` | `status.py` | fixed-height、no-wrap、right-truncate status |
| `WorkingLine` | `status.py` | 运行中状态与耗时 |
| `PendingQueueView` | `queue.py` | generic pending message sections |
| `KeyActionRouter` | `inline/keymap.py` | 按键到 generic UI action 的映射 |

P0 完成后，`inline/` 应主要负责组装，不再同时承载 composer、key binding、status、pending rendering 与 transcript helper。

### P0 Runtime Architecture

P0 inline runtime 应收敛为以下内部结构：

```text
InlineRuntime
  owns prompt_toolkit Application
  owns transient UI state
  composes generic primitives

  ├─ ComposerPolicy
  │    normalizes input, rejects blank submissions, calculates height, decides generic delivery
  ├─ InlineActionRouter
  │    maps key + running state + empty state to generic InlineAction
  ├─ WorkingLine
  │    renders elapsed working state
  ├─ PendingQueueRenderer
  │    renders generic pending sections
  ├─ StatusLine
  │    renders one-line status if visible
  └─ TranscriptEmitter
       writes durable transcript blocks outside redrawable layout
```

`InlineRuntime` owns only terminal presentation state:

- `running`
- `aborting`
- `started_at`
- temporary `status_message`
- deferred local prompt after abort settling

It does not own:

- agent run truth
- queued steer/follow-up truth
- session status truth
- model/session/tool state

Those remain in `loushang.coding` and are projected through providers/callbacks.

### Public Inline Contract

The stable P0 public contract is callback/provider based:

```python
async def run_inline_prompt_app(
    *,
    stdin: TextIO,
    stdout: TextIO,
    handle_prompt: Callable[[str], Awaitable[int | None] | int | None],
    handle_alternate_submit: Callable[[str], Awaitable[int | None] | int | None] | None,
    handle_dequeue: Callable[[str], Awaitable[str | None] | str | None] | None,
    pending_messages: Callable[[], PendingQueueView] | None,
    status: Callable[[], str | list[tuple[str, str]]],
    status_visible: Callable[[], bool] | None,
    on_abort: Callable[[], Awaitable[None] | None] | None,
    should_exit: Callable[[str], bool] | None,
    local_interaction_ready: InlineLocalInteractionReady | None,
    config: InlinePromptConfig | None,
) -> int:
    ...
```

This contract is intentionally small:

- TUI submits raw text.
- TUI reports generic alternate-submit/dequeue/abort UI actions through callbacks.
- TUI reads generic view state through providers.
- TUI does not receive a session object.
- TUI does not expose prompt_toolkit objects as public API.
- Local controls are attached through `local_interaction_ready`, which receives an `InlineLocalInteractionController` and a current composer query provider. Business adapters use that controller to host generic controls without touching inline runtime internals.

### Runtime Contract Matrix

The inline runtime contract is stable and covered by `tests/tui/test_inline.py`,
`tests/tui/test_keymap.py`, `tests/tui/test_inline_*`, and PTY lifecycle tests. Changes to
`loushang.tui.inline.*` modules must preserve this matrix unless the product contract is
intentionally changed first.

The focused lifecycle contract lives in
`docs/architecture/tui/history/v1-prompt-toolkit/inline-lifecycle-contract.md`.
That document is the narrower source for lifecycle phases, key mapping, abort/deferred
submission rules, and local interaction priority.

`_InlinePromptRuntime` is only the internal composition root. It exposes `services`,
`application_parts`, and `run()`. It must not mirror service graph fields through
passthrough properties such as `state`, `buffer`, `renderers`, `key_bindings`, `app`, or
abort helper methods. White-box tests can use `runtime.services.*` and
`runtime.application_parts.*`; product code uses the `loushang.tui.inline` facade.

`InlineRuntimeServices` is the service graph, not a second facade. It exposes owned
controllers such as `actions`, `submissions`, `abort`, `local_interactions`, and `views`,
but it must not duplicate internals from those controllers. For example,
`actions.action_router` and `actions.action_dispatcher` remain behind `actions`; status is
changed through the shared `state` or controller callbacks rather than through a service
passthrough method.

| State | Input | TUI Action | Consumer Meaning |
| --- | --- | --- | --- |
| Idle | Enter with non-blank text | `SUBMIT` | start prompt through `handle_prompt` |
| Idle | Alt+Enter | `NEWLINE` | insert newline in composer |
| Idle | Ctrl+J | `NEWLINE` | insert newline in composer |
| Idle | Ctrl-D on raw-empty composer | `EXIT` | close app |
| Running | Enter with non-blank text | `RUNNING_SUBMIT` | consumer may treat as steer |
| Running | Alt+Enter with non-blank text | `RUNNING_ALT_SUBMIT` | consumer may treat as follow-up |
| Running with no alternate-submit handler | Alt+Enter with non-blank text | status only | no alternate submit is queued |
| Running with `allow_input_while_running=False` | Enter / Alt+Enter | status only | no running submit or alternate submit is queued |
| Running | Ctrl+J | `NEWLINE` | insert newline in composer |
| Any with `submit_on_enter=False` | Enter | `NEWLINE` | insert newline in composer |
| Any with `should_exit(text)=True` | Enter | `EXIT` | close app before prompt or steer |
| Running with `should_exit(text)=True` | Alt+Enter | `RUNNING_ALT_SUBMIT` | still alternate submit; exit predicate does not override Alt+Enter |
| Any | Esc / Ctrl-C | `ABORT` | cancel local control first, otherwise abort run |
| Any | Alt-Up | `DEQUEUE` | restore pending queue into composer |
| Any | whitespace-only submit | `EMPTY` | clear/status only; no prompt, running submit, or alternate submit |
| Abort settling | Enter with non-blank text | deferred prompt | queued until abort settles |
| Abort settling | Esc / Ctrl-C | force abort | ask runtime to force-close |
| Abort settling | Alt+Enter / Alt-Up / Ctrl+J / arrows | status only | no alternate submit, dequeue, newline, or local movement |
| Local control active | Enter / Alt+Enter / Up / Down | local action first | local control consumes before prompt semantics |
| Local control active | Esc / Ctrl-C | cancel local control | does not abort run until next abort input |

The TUI layer only owns the generic action column. The consumer meaning column belongs to
`loushang.coding.ui` or another product adapter.

### Inline Local Control Contract

Inline local control adapters are the bridge between standalone generic controls and the inline prompt runtime. They share the same public shape:

```python
def start_inline_xxx(
    *,
    local_interactions: InlineLocalInteractionController[T],
    ...,
    on_result: Callable[[T], Awaitable[None] | None] | None = None,
    on_cancel: Callable[[], Awaitable[None] | None] | None = None,
) -> bool:
    ...
```

Rules:

- `local_interactions` is always keyword-only.
- `on_result` and `on_cancel` are always keyword-only.
- The adapter owns only UI translation: `InlineAction` -> generic control action -> generic result.
- The adapter does not parse slash commands or inspect coding/session state.
- If a control needs current input text, it receives a `query: Callable[[], str]` provider from the inline composer.
- Invalid required input keeps the control active and does not call `on_result`.
- Once a controller is done, later actions or text/query updates must not change its result.
- Once a controller is cancelled, later submit-like actions must keep returning the cancelled result.
- While a local control is active, local-control actions win over running prompt semantics. In particular, `RUNNING_SUBMIT` and `RUNNING_ALT_SUBMIT` must be interpreted by the active control before they can become steer/follow-up behavior in `loushang.coding.ui`.
- If an active local control declines an action, the inline runtime must stop at a local-control status update. It must not leak the same action into prompt, steer, follow-up, or dequeue behavior.
- New adapter behavior should have controller-level tests and at least one PTY smoke once it is used by a real coding UI flow.

Current adapters:

| Adapter | Result | Notes |
| --- | --- | --- |
| `start_inline_command_palette` | `str | None` | Searchable selector; submit/running submit/running alt-submit selects. |
| `start_inline_info_panel` | `None` | Read-only panel; submit/newline/running submit/running alt-submit closes. |
| `start_inline_settings_list` | `SettingsList` | Up/down moves; Ctrl+J or running Alt+Enter toggles; Enter submits. |
| `start_inline_confirm` | `bool | None` | Uses composer query text such as `yes` / `no`; invalid non-empty input stays active. |
| `start_inline_text_input` | `str | None` | Uses composer query text; required empty input stays active. |

### PTY Regression Matrix

PTY tests are the behavioral contract for terminal timing and key-sequence integration. They are not
unit tests for prompt_toolkit internals; they verify that real terminal input sequences preserve the
runtime contract above.

Current groups:

- `tests/tui/test_coding_tui_control_matrix.py`
  - mixed running steer/follow-up/blank/abort bursts
  - repeated burst cycles with prompt isolation after abort
- `tests/tui/test_coding_tui_local_controls_pty.py`
  - `/model`, `/command`, `/status`, `/settings`, `/hotkeys`, and `/commands` local controls
  - local control cancel restores prompt input
  - running local control Enter selects locally rather than becoming steer
  - running local control Alt+Enter selects/toggles locally rather than becoming follow-up
  - first Esc cancels a local panel; second Esc aborts the active run
- `tests/tui/test_coding_tui_pty_lifecycle.py`
  - lifecycle-level prompt/abort/recovery behavior

New TUI features should either fit one of these groups or add a new named matrix group before changing
runtime behavior.

## Theme Coverage

All production-rendered fragment classes must be covered by `default_inline_theme()`. This includes base inline runtime classes and local control classes:

```text
composer, prompt, working, pending, pending.arrow, status, local-interaction
palette.*, panel.*, select.*, settings.*, confirm, text-input
```

The goal is not heavy styling; the default theme stays quiet and white-background friendly. The important constraint is that every control has an explicit style token so future themes can override it without depending on prompt_toolkit fallback behavior.

## Generic Pending Queue

`loushang.tui` 不应暴露 `steering` / `follow_up` 字段。这些是 coding 语义。

使用 generic view model：

```python
@dataclass(frozen=True)
class PendingSection:
    label: str
    items: tuple[str, ...]
    hint: str | None = None


@dataclass(frozen=True)
class PendingQueueView:
    sections: tuple[PendingSection, ...] = ()
```

`loushang.coding.ui` 负责映射：

```text
steering messages
  -> PendingSection("Messages to be submitted after next tool call", ...)

follow-up messages
  -> PendingSection("Messages to be submitted at end of turn", ...)
```

这样 queue truth 仍归 coding/session runtime，TUI 只展示 snapshot。

## Key Action Routing

按键处理分两层：

1. key normalization：把 terminal key sequence 归一成稳定 key id。
2. action routing：根据 running/idle 状态映射成 generic UI action。

候选 action：

```python
class InlineAction(Enum):
    SUBMIT = "submit"
    NEWLINE = "newline"
    RUNNING_SUBMIT = "running_submit"
    RUNNING_ALT_SUBMIT = "running_alt_submit"
    ABORT = "abort"
    EXIT = "exit"
    DEQUEUE = "dequeue"
    MOVE_DOWN = "move_down"
    MOVE_UP = "move_up"
```

默认行为：

```text
Idle Enter          -> SUBMIT
Idle Alt+Enter      -> NEWLINE
Running Enter       -> RUNNING_SUBMIT
Running Alt+Enter   -> RUNNING_ALT_SUBMIT
Ctrl+J              -> NEWLINE
Esc / Ctrl-C        -> ABORT
Ctrl-D on empty     -> EXIT
Alt-Up              -> DEQUEUE
Down/Up             -> MOVE_DOWN / MOVE_UP while a local control is active
Whitespace input    -> ignored before any submit/running action
```

`loushang.coding.ui` 负责把：

```text
RUNNING_SUBMIT     -> steer
RUNNING_ALT_SUBMIT -> follow-up
```

## Slash Command UI Flow

Slash command 解析不进入 `loushang.tui`。

P0 slash commands can use simple transcript/status output. P1 slash commands may use generic controls.

P0 example `/models`:

```text
User enters /models
  -> loushang.tui submits raw text
  -> loushang.coding.ui parses ModelsIntent
  -> loushang.coding.ui formats available models
  -> loushang.tui emits generic text output
  -> loushang.tui returns to composer
```

P1 example `/model`:

```text
User enters /model
  -> loushang.tui submits raw text
  -> loushang.coding.ui parses ModelIntent
  -> loushang.coding.ui loads model options
  -> loushang.coding.ui asks loushang.tui to run a generic CommandPalette through InlineLocalInteraction
  -> user selects/cancels
  -> loushang.coding.ui updates session/model setting
  -> loushang.tui returns to composer
```

Example `/status`:

```text
User enters /status
  -> loushang.coding.ui builds status report
  -> loushang.tui shows a generic InfoPanel or transcript block
```

Example `/statusline`:

```text
User enters /statusline
  -> loushang.coding.ui toggles a status_visible provider
  -> loushang.tui hides/shows the generic StatusLine
```

## P1 Controls

P1 adds local controls for slash-command and settings workflows. It still does not require a full component tree.

| Control | Purpose |
| --- | --- |
| `InlineTheme` | 收敛 hard-coded styles |
| `InfoPanel` | `/status`、`/hotkeys`、help、error detail |
| `SelectList` | `/model`、session/tool/command selection |
| `SettingsList` | `/statusline`、`/settings` |
| `Confirm` | 删除、覆盖、危险操作确认 |
| `TextInput` | session name、filter、path 等简单输入 |
| `Autocomplete` | slash command、file path、model name completion |
| `CommandPalette` | searchable command/model/action selection |

可以先使用轻量协议：

```python
class TuiControl(Protocol):
    def render(self, width: int) -> AnyFormattedText: ...
```

如果控件开始需要焦点，再引入：

```python
class FocusableControl(TuiControl, Protocol):
    def handle_action(self, action: InlineAction) -> bool: ...
```

Inline-local controls must be fail-closed: action handler errors close the local control, restore the
saved composer text, and report a local interaction error status. A failed palette/settings/info
control must not leave the composer hidden or locked.

## P1 Rendering Primitives

P1 rendering work adds generic transcript rendering helpers without moving coding UI semantics into `loushang.tui`.

```text
loushang.tui.render/
  __init__.py
  console.py      # console factory and renderable -> terminal text
  code.py         # code text -> terminal transcript rendering
  diff.py         # diff text/stat -> terminal transcript rendering
  markdown.py     # Markdown text -> terminal transcript rendering
  rule.py         # stable-width terminal rules
  blocks.py       # generic typed transcript block composition
```

The first supported primitives are:

- `blocks.py`: generic typed block composition for text, Markdown, code, diff, and rules.
- `console.py`: common Rich console setup and renderable-to-terminal-text conversion.
- `code.py`: deterministic code rendering for already-selected source language.
- `diff.py`: deterministic diff rendering plus generic `+N -M` stat extraction.
- `markdown.py`: Markdown rendering for completed assistant transcript blocks.
- `rule.py`: simple fixed-width separators for transcript chrome.

They should:

- be deterministic in tests with injected `TextIO`.
- use terminal width conservatively and avoid forcing color in non-TTY captures.
- keep raw Markdown out of session mutation paths.
- let `loushang.coding.ui.renderer` decide when Markdown, code, diff, or rule rendering is appropriate.

Future `panel` or block-composition helpers can be added under `loushang.tui.render` only when there is a generic consumer. Tool-specific rendering stays in `loushang.coding.ui` or a coding-owned renderer module such as `tool_blocks.py`.

## P2 Framework Capabilities

只有当交互复杂度足够高时，再引入完整框架能力。

| Capability | Trigger |
| --- | --- |
| `Container` | 多区域布局需要可组合 measurement/layout |
| `Focusable` | 多控件同时存在并需要焦点切换 |
| `OverlayManager` | 多个 modal/overlay/help panel 需要统一管理 |
| `MarkdownBlock` | panel 或 transcript 需要 interactive/lifecycle-aware block rendering beyond simple completed-block Markdown |
| `ImageBlock` | terminal image capability 成为产品需求 |
| `History` / `UndoStack` / `KillRing` | composer 编辑体验需要增强 |

这部分可以参考成熟终端助手的 TUI substrate，但不是当前 P0 的前置条件。

### Framework Upgrade Criteria

Do not introduce `Component / Container / Focusable / OverlayManager` until at least two of these are true:

- More than one interactive control can be visible at the same time.
- A modal/overlay can be opened while the composer still has pending state.
- Focus must move between composer, selector, command palette, and panel.
- A control needs mount/dispose lifecycle beyond a single prompt_toolkit layout subtree.
- Extension-provided UI requires stable composition boundaries.

Before those triggers, prefer small generic controls with plain callback APIs.

## Proposed Module Layout

```text
src/loushang/tui/
  __init__.py
  terminal.py
  text_utils.py
  output.py
  control.py
  inline/
    __init__.py
    keymap.py
    app.py
    local_interaction.py
    actions.py
    state.py
    tasks.py
    views.py
    layout.py
    runtime.py
    services.py
    composer.py
    composer_policy.py
  status.py
  queue.py
  theme.py
  choices.py
  select_list.py
  confirm.py
  text_input.py
  info_panel.py
  settings_list.py
  autocomplete.py
  render/
    __init__.py
    console.py
    markdown.py
    blocks.py
```

`toolbar.py` 应迁出 `loushang.tui`，因为它包含 coding-specific 字段：

```text
src/loushang/coding/ui/toolbar.py
```

## Migration Sequence

The first fourteen items are complete in the current codebase:

1. Move coding-specific toolbar rendering from `loushang.tui.toolbar` to `loushang.coding.ui.toolbar`.
2. Add `text_utils.py` and move fixed-width / visible-width helpers.
3. Add `status.py` for `StatusLine` and `WorkingLine`.
4. Replace `InlinePendingMessages(steering, follow_up)` with generic `PendingQueueView`.
5. Add `inline/composer.py` for composer policy and height calculation.
6. Add `inline/keymap.py` for key normalization and generic actions.
7. Slim `inline/` into an inline runtime facade with smaller internal helpers:
   - `InlinePromptState`
   - `InlineTaskController`
   - `inline.views` / `inline.layout`
   - `InlineActionDispatcher`
8. Add focused tests for abort/deferred prompt/task cancellation at the `InlineTaskController` boundary.
9. Treat `prompt.py` as non-interactive fallback and avoid growing it into a second UI runtime.
   - Its public function is `run_non_interactive_prompt_loop()`.
   - It must not start `PromptSession`, wire key bindings, or render interactive toolbars.
   - If called with an interactive terminal, it fails fast and tells the caller to use `run_inline_prompt_app`.
10. Add lightweight P1 controls:
   - `InfoPanel`
   - `SelectList`
   - `Confirm`
   - `TextInput`
   - `ConfirmAction` / `ConfirmController`, `TextInputAction` / `TextInputController`, and `InfoPanelAction` / `InfoPanelController` share the same local-control contract as selector controls.
11. Add `SettingsList` for simple toggle workflows.
    - `SettingsListAction` and `SettingsListController` align it with `SelectList` and `CommandPalette`.
12. Add `Autocomplete` for simple completion workflows.
13. Add `CommandPalette` for searchable selection workflows. It can be built from `CompletionProvider` so completion and palette workflows can share item data.
14. Add `InlineLocalInteraction` as the generic substrate for running local controls from the inline runtime.
    - It preserves and restores composer text around a local control.
    - It renders an inline local-control host between pending messages and composer.
    - It routes local-only actions, including up/down navigation, before normal prompt actions.
    - It rejects concurrent local controls.
    - It reports cancelled/error states through the generic status channel.
    - Runtime prompt/dequeue actions are blocked while a local interaction is active; abort first cancels the local interaction.
    - `start_inline_command_palette()` adapts `CommandPalette` into the host by using composer text as query, up/down as navigation, and Enter as selection.
15. Keep `_InlinePromptRuntime` and `InlineRuntimeServices` as boundary objects rather than
    catch-all facades.
    - `_InlinePromptRuntime` owns only `services`, `application_parts`, and `run()`.
    - `InlineRuntimeServices` owns service graph nodes but does not mirror nested
      controller internals such as action router/dispatcher or status setters.

The P1 integration work has started:

16. Connect generic controls to coding-owned slash command workflows without moving slash parsing into `loushang.tui`.
    - `/status`, `/models`, `/commands`, and `/hotkeys` can render through generic `InfoPanel`.
    - `/commands` exposes a coding-owned `CompletionProvider`.
    - `/models` exposes a coding-owned `CompletionProvider`.
    - `/command` and `/model` expose coding-owned `CommandPalette` adapters for selector workflows. `/commands` and `/models` remain read-only list workflows.
    - `/model <query>` is a coding-owned workflow that selects a unique model match.
    - `/command <query>` is a coding-owned workflow that selects a unique command match without executing it.
    - Interactive `/model` uses `InlineModelPaletteChooser` to bind `CommandPalette` to `InlineLocalInteraction`; non-interactive `/model` keeps the text list behavior.
    - Interactive `/command` uses `InlineCommandPaletteChooser`; non-interactive `/command <query>` keeps text status output and does not require a local control.
    - Interactive `/status`, `/models`, `/commands`, and `/hotkeys` use `InlineInfoPanelPresenter` to bind read-only `InfoPanel` views to `InlineLocalInteraction`; non-interactive mode keeps transcript output.
    - Interactive `/settings` uses `InlineSettingsListPresenter` to bind `SettingsList` to `InlineLocalInteraction`; `loushang.coding.ui` still owns mapping settings to statusline state.
    - `loushang.coding.ui` imports generic TUI primitives from the top-level `loushang.tui` API and inline runtime/local-control entry points from `loushang.tui.inline`. Direct imports from concrete modules such as `loushang.tui.info_panel`, `loushang.tui.queue`, `loushang.tui.inline.runtime`, and `loushang.tui.terminal` are guarded by boundary tests.
    - PTY smoke covers opening local `/model`, `/command`, `/status`, `/settings`, `/hotkeys`, and `/commands` controls, closing/cancelling/selecting them, and submitting a follow-on prompt after the composer is restored.
    - `select_available_model(..., choose=...)` and `build_coding_tui_app(..., model_palette_chooser=...)` provide the safe injection point for the interactive model selector.
    - `select_session_command(..., choose=...)` and `build_coding_tui_app(..., command_palette_chooser=...)` provide the same safe injection point for command selection.
    - `loushang.coding.ui.completion.complete_coding_input()` selects command vs. `/model ...` argument completions.
    - `loushang.coding.ui.completion.coding_inline_completion_provider()` builds a best-effort static startup provider for inline slash/model completion. Failure falls back to no completions and must not block TUI startup.
    - `InlinePromptConfig.completion_provider` wires a generic completion provider into the inline composer.
16. Add generic terminal rendering primitives without moving product rendering into `loushang.tui`.
    - Create `loushang.tui.render.markdown` for completed-block Markdown transcript rendering.
    - Create `loushang.tui.render.blocks` for generic typed terminal block composition.
    - Create or reserve `loushang.tui.render.console` for console factory, pager policy, and future renderable-to-ANSI conversion.
    - Keep `loushang.tui.output` focused on transcript-safe writes and prompt_toolkit terminal interop.
    - Let `loushang.coding.ui.renderer` opt into Markdown rendering for completed assistant blocks only.
    - Add tests proving raw Markdown remains unchanged in session, JSON/workflow output, and non-rendering paths.

Each step should keep the public inline behavior stable:

- idle Enter submits
- running Enter queues running submit
- running Alt+Enter queues alternate running submit
- Ctrl+J inserts newline
- Esc / Ctrl-C abort
- whitespace-only input is ignored
- transcript remains in real scrollback

## Non-Goals

- Do not build a full fullscreen UI framework in P0.
- Do not make `loushang.tui` parse slash commands.
- Do not put coding-specific status fields in `loushang.tui`.
- Do not make prompt_toolkit classes part of the stable public API.
- Do not move transcript into a redrawable component tree.
- Do not turn `loushang.tui.render` into a product renderer for agent, tool, model, or session events.

## Development Roadmap

### Phase 1: Runtime Stabilization

Goal: keep `loushang.tui.inline.*` understandable and testable without changing visible behavior.

Work:

- Keep `_InlinePromptRuntime` as a composition root over `services` and `application_parts`.
- Keep service graph helpers individually testable.
- Preserve current key behavior exactly.
- Preserve current transcript behavior exactly.
- Add regression tests for abort, deferred submit after abort, repeated abort, and background task cleanup.

Exit criteria:

- `loushang.tui.inline` is mostly composition and prompt_toolkit glue.
- `_InlinePromptRuntime` has no flattened service passthroughs.
- Abort/steer/follow-up semantics remain covered by automated tests.
- Manual smoke still passes:
  - prompt -> response
  - long prompt -> Esc -> new prompt
  - running Enter -> steer
  - running Alt+Enter -> follow-up
  - whitespace-only Enter ignored

### Phase 2: Generic Controls

Goal: support local UI interactions without leaking coding semantics.

Work:

- Add `InfoPanel` for read-only help/status/error text.
- Add `SelectList` for single-choice workflows.
- Add `Confirm` for dangerous operations.
- Add `TextInput` for simple text prompts.
- Add `SettingsList` for simple toggles.
- Add `Autocomplete` for slash command, path, and model-name completion.
- Add `CommandPalette` for searchable command/model/action selection.

Exit criteria:

- `loushang.coding.ui` can implement `/model` and `/settings` by passing generic view models and callbacks.
- `loushang.tui` still has no imports from `loushang.coding`.

### Phase 3: Command Palette And Completion

Goal: improve slash command discoverability.

Work:

- Add command palette control.
- Add completion provider contract.
- Support command/filter text without moving slash parsing into `loushang.tui`.

Exit criteria:

- Slash command discovery works from the composer.
- Command source and conflict information remain owned by `loushang.coding`.

### Phase 4: Terminal Transcript Rendering

Goal: make terminal transcript readable while preserving raw data everywhere else.

Work:

- Add `loushang.tui.render.markdown`.
- Add `loushang.tui.render.console` only if console creation or ANSI conversion grows beyond `output.py`.
- Render completed assistant Markdown blocks in `loushang.coding.ui.renderer`.
- Keep tool summaries, status lines, pending queues, and composer text plain.
- Add regression tests for Markdown rendering, non-TTY output, and raw session data preservation.

Exit criteria:

- Assistant Markdown appears as readable terminal output.
- Session records, JSON mode, workflow mode, and exports preserve raw Markdown unless explicitly rendering their own format.
- Rich remains hidden behind `loushang.tui.render` helpers.

### Phase 5: Framework Upgrade If Needed

Only start this if the Framework Upgrade Criteria are met.

Work:

- Introduce minimal component lifecycle.
- Introduce focus manager.
- Introduce overlay manager.

Exit criteria:

- Controls can compose without ad hoc prompt_toolkit wiring.
- The public API remains callback/provider based.
