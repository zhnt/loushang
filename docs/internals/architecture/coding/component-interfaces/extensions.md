# `extensions`

## Status

Superseded as a Coding-owned shared runtime. Product-neutral Extension loading,
routing, and lifecycle composition now belong to the
[Harness Extension Runtime Core](../../harness/extension-runtime-core-boundary.md).
The Product-specific semantics described below are retained as historical
adapter requirements.

## Role

- coding 扩展执行侧协调组件，以及可选的扩展发现/装载边界

## Owns

- `ExtensionRunner`
- `ExtensionLoader`（如保留为显式服务边界）
- 扩展描述符与 hook 注册表
- session 生命周期 hook 执行顺序

## Depends On

- `loader`
- `session`
- `tools`
- `control`
- mode 提供的可选 UI / command context

## Commands

- `load_extensions(...)`
- `reload_extensions(...)`
- `bind_session(...)`
- `emit_session_event(...)`
- `emit_event(...)`
- `emit_before_agent_start(...)`
- `emit_input(...)`
- `emit_tool_call(...)`
- `emit_tool_result(...)`

## Queries

- `get_extension(...)`
- `list_extensions()`
- `list_registered_hooks()`

## Events

- 消费 `session` / `tool` / `mode` 生命周期事件
- 当前不单独定义稳定外发事件

## Key Data

- `ExtensionDescriptor`
- `LoadedExtension`
- `SourceInfo`
- `SessionStartEvent`
- `SessionShutdownEvent`
- `SessionRefreshEvent`
- `BeforeAgentStartResult`
- `ResourceBundle`
- `InputEvent`
- `InputEventResult`
- agent lifecycle event payloads: `agent_start` / `agent_end` / `turn_start` / `turn_end` /
  `message_start` / `message_update` / `message_end` / `tool_execution_start` /
  `tool_execution_update` / `tool_execution_end`
- user shell hook payloads: `user_bash`
- model hook payloads: `model_select`

## Out Of Scope

- tool 执行实现
- policy 审批判定
- mode UI 渲染

## Reference Implementation Alignment

- `ExtensionRunner` 语义上直接对齐 `reference CLI` 的执行侧协调中心
- `ExtensionLoader` 更准确地对应 `reference CLI` 的 `extensions/loader.ts` 这一加载语义，但在整体结构上仍受 `DefaultResourceLoader` 聚合
- 保留扩展层作为 session 生命周期的可编程拦截面
- `ExtensionLoader` 必须把 descriptor provenance 复制进 `LoadedExtension`；`ExtensionRunner` 生成 command / flag / shortcut 视图时继续保留 package/top-level 来源
- `session_start` / `session_shutdown` 使用 typed event payload，而不是把 `AgentSession` 本体当 event；replacement 顺序对齐 `reference CLI`：`session_before_switch|fork -> session_shutdown(old) -> session_start(new)`
- lifecycle hook 是 async runtime path：session replacement 必须 await `session_shutdown` 和 `session_start`，不能通过同步 wrapper 偷跑
- session decision hooks 也是 async runtime path：`session_before_switch` / `session_before_fork` /
  `session_before_compact` / `session_before_tree` 按注册顺序 await，后续 handler 能看到前序决策结果的最新状态
- extension context 的 mutating API 是 async runtime path：`sendMessage` / `sendUserMessage` / `compact` 必须 await，不能 fire-and-forget；只读查询和 UI setter 保持同步绑定语义
- lifecycle event payload 带稳定 `type` discriminator，例如 `session_start`、`session_shutdown`、`session_before_switch`
- 旧 extension context 在 `session_shutdown` hook 内仍可用于清理；hook 返回后 runtime 才将旧 context 标记为 stale
- lifecycle event payload 提供 Python snake_case 字段与 reference-style camelCase alias；例如 `previous_session_file` / `previousSessionFile`
- session post-events 对齐 `reference CLI`：`session_compact` 在 compaction entry 写入后发出，`session_tree` 在 leaf 切换后发出；
  payload 同时提供 snake_case 与 reference-style camelCase alias，例如 `compaction_entry` / `compactionEntry`
- extension command context 的 `fork(entryId, { position })` 透传 runtime；`position="before"` 返回 `selected_text` / `selectedText` 并让 `withSession` 拿到 replacement session 的 fresh context
- `input` hook 对齐 `reference CLI`：在 extension slash command 未命中之后、prompt/skill preflight 之前运行；
  handler 可返回 `continue`、`transform` 或 `handled`，transform 结果继续进入 prompt/skill 展开但不会二次触发 extension command
- extension command 的 `get_argument_completions` 支持 sync / async completer；
  `ExtensionRunner.get_command_argument_completions()` 是 mode-neutral autocomplete 查询入口，非法返回值记录 diagnostics
- extension command handler 对齐 `reference CLI` 的 `Promise<void>` contract：注册时要求 async callable；
  command 内如需产生可见结果，应通过 `ctx.sendMessage()` / `ctx.sendUserMessage()` / session control context，而不是返回业务对象
- extension-registered tools 对齐 `reference CLI` 的 wrapper 语义：runner 收集工具时包装 `ToolDefinition.execute`，
  允许工具声明第五个 `ctx` 参数并在真实执行时拿到当前 `ExtensionContext`；旧 4 参数工具保留可执行但不作为新增扩展 API 推荐形态
- agent lifecycle events 对齐 `reference CLI`：`AgentSession` 将 agent event stream 桥接给 `ExtensionRunner.emit_event()`；
  `turn_start` / `turn_end` 带 reference-style `turn_index` / `turnIndex`，tool/message 事件保留 snake_case 与 camelCase alias
- `context` / `tool_call` / `tool_result` hook 支持 sync 或 async handler；
  async handler 会被 runner 串行 await，而不是记录 “async unsupported” 诊断
- `before_agent_start` 只保留 reference-style prompt 级拦截，不再承担旧 session 生命周期职责；
  session 生命周期逻辑使用 `session_start` / `session_refresh` / `session_shutdown`
- `before_agent_start` handler 可以读取 `event.prompt` / `event.systemPrompt` / `ctx.getSystemPrompt()`，
  返回 `systemPrompt` 覆盖、`systemPromptAppend` 追加，或返回 custom messages 注入本轮 agent prompt
- prompt 级 `before_agent_start` 的多扩展执行按注册顺序串行；后续 handler 看到前序 handler 修改后的 system prompt，
  diagnostics 回收进 extension diagnostics，hook 异常进入 runtime error sink
- `user_bash` 对齐 `reference CLI` 的用户 shell 拦截面：`execute_bash()` 在默认 bash tool 执行前发出事件；
  handler 可返回 `{ result: ... }` 直接替换执行结果并写入 session context，也可返回 `{ operations: ... }`
  让默认 bash 执行链继续运行但切换到自定义后端
- `model_select` 对齐 `reference CLI` 的模型切换事件：`set_model()` / `cycle_model()` 是 async API，
  在模型实际变化后发出 `model_select`，payload 提供 `model` / `previous_model` / `previousModel` / `source`
- extension factory 里的 `ExtensionAPI` 会绑定 runner runtime state；handler 闭包中可通过
  `api.get_commands()` / `api.get_active_tools()` / `api.get_all_tools()` / `api.get_flag(name)`
  读取当前 session command、tool 与 flag 状态，语义对应 `reference CLI` 的 read-only `ExtensionAPI` runtime facade
- extension command/runtime diagnostics 必须保留 command/session/source correlation；
  command failure details 包含 `invocation_name`、`command_name`、`extension_name` 与 structured `source_info`，
  resource diagnostics details 保留 `resource_id`、`resource_type`、`source_kind` 与 descriptor metadata
- headless projection includes `list_message_renderers()` / `listMessageRenderers()` and
  `get_diagnostic_snapshot()` so RPC/TUI can inspect registered renderer coverage and extension diagnostics without invoking UI rendering
- `ExtensionAPI` 同时提供 runtime action facade：`append_entry()`、`send_message()`、
  `send_user_message()`、`set_session_name()`、`get_session_name()`、`set_label()`；
  这些方法只代理到当前 runtime bindings，不在 API 层承载 session 业务逻辑
- extension runtime 直接执行能力通过 `ctx.exec_command(...)` / `api.exec_command(...)` 暴露，落到当前
  `AgentSession` 注入的 `ExecService`；默认 cwd 为 session cwd，传入相对 cwd 时按 session cwd 解析，
  默认使用当前 agent abort signal，调用方可传入自定义 `signal` 和 `on_update`。
- `exec_command(...)` 执行的是 argv 形式的直接进程调用，不默认启用 shell；扩展确实需要 shell 语义时应显式调用
  `bash` / `sh`。Python 中 `exec` 是关键字，因此不提供 `ctx.exec(...)` 点语法 API，这不作为 `reference CLI` gap。
- control facade 继续对齐 `reference CLI`：`set_active_tools()`、`set_model()`、`get_thinking_level()`、
  `set_thinking_level()` 通过 runtime bindings 落到当前 `AgentSession`；
- message renderer registry 对齐 `reference CLI` 的 headless contract：
  `register_message_renderer(custom_type, renderer)` / `registerMessageRenderer(...)` 写入 `LoadedExtension.message_renderers`；
  `ExtensionRunner.get_message_renderer(custom_type)` / `getMessageRenderer(...)` 按 extension 加载顺序返回第一个匹配 renderer
- `resources_discover` 支持 reference-style path result：handler 可返回
  `{"promptPaths": [...], "skillPaths": [...], "themePaths": [...]}`，runner 会转换为现有
  `PromptFragmentDescriptor` / `SkillDescriptor` / `ThemeDescriptor`
  并通过 `resource_diagnostic(...)` 把显式 path 缺失或读取失败收敛为
  `DiagnosticDraft`，避免 extension resource gap 静默丢失
- provider registration 只对齐生命周期语义，不采用 `reference CLI` 的 flat provider config shape：
  `register_provider(name, config)` 支持 load-time pending 与 bound runtime immediate apply；
  `unregister_provider(name)` 会清理扩展注册的 model/API/OAuth provider；
  dict config 允许保留，但 schema 应跟随 `loushang-ai.models.json` /
  `Provider -> Endpoint -> Model`，不是 reference-style `{ api, baseUrl, apiKey, models, streamSimple, oauth }`
  混合 flat config；native `Provider` 输入是优先 typed path。
  详见 `ARD-003: Provider And Model Boundary`。
