# `session`

## Role

- 单个 coding session 的运行时门面

## Owns

- 活动 `Agent` 绑定
- session 级命令入口
- session 级产品事件定义与投影
- 当前 active tool names
- 当前 allowed tool names hard boundary
- 当前注入给 `Agent` 的 runtime tools
- steering / follow-up 输入适配与 Agent delivery
- 从 `SessionManager` 恢复出的运行上下文

## Uses Harness Core

- `loushang.harness.runtime.execution.HostRuntime` 协调 prompt / continue / abort /
  wait-for-idle / dispose 生命周期，并委托现有 `Agent` driver。
- `loushang.harness.runtime.input_queue.HostInputQueue` 持有中立队列账本和快照；
  Coding 继续负责 preflight、消息构造、Agent queue 和产品事件。
- `loushang.harness.events.OrderedEventBus` 提供有序异步分发；
  `loushang.harness.session.event_types.AgentSessionEvent` 定义标准 Agent
  会话投影。
- `loushang.harness.runtime.types.RunState` 是 Coding 公共路径复用的记录所有者。

## Depends On

- `store`
- `event`
- `control`
- `tools`
- `loader`
- `loushang-agent`
- `loushang.harness.events`
- `loushang.harness.runtime`
- `loushang.harness.session`

## Commands

- `prompt(..., preflight_result?)`
- `steer(...)`
- `follow_up(...)`
- `clear_queue()`
- `clearQueue()`
- `continue_run()`
- `abort()`
- `wait_for_idle()`
- `await set_model(...)`
- `await setModel(...)`
- `setScopedModels(scopedModels)`
- `await cycle_model(direction?)`
- `await cycleModel(direction?)`
- `set_thinking_level(...)`
- `setThinkingLevel(...)`
- `cycleThinkingLevel()`
- `setAutoRetryEnabled(enabled)`
- `setAutoCompactionEnabled(enabled)`
- `executeBash(command, onChunk?, options?)`
- `recordBashResult(command, result, options?)`
- `abortBash()`
- `abortCompaction()`
- `await refresh_resources()`
- `request_resource_refresh()`
- `await set_active_tools(...)`
- `setSessionName(name)`
- `await sendCustomMessage(message, options?)`
- `await sendMessage(message, options?)`
- `await sendUserMessage(content, options?)`
- `await materialize_package(source)`
- `exportToJsonl(outputPath?)`
- `exportToHtml(outputPath?)`
- `compact(...)`
- `list_commands() -> list[SessionCommandDescriptor]`
- `await execute_command_async(invocation_name: str, args: str) -> CommandExecutionResult | None`
- `get_command_argument_completions(invocation_name: str, prefix: str) -> list[object] | None`

## Queries

- `get_state()`
- `get_session_context()`
- `get_session_record()`
- `get_model_selection()`
- `get_active_tool_names()`
- `getActiveToolNames()`
- `get_all_tools()`
- `getAllTools()`
- `getToolDefinition(name)`
- `get_available_models()`
- `pending_message_count` / `pendingMessageCount`
- `get_steering_messages()` / `getSteeringMessages()`
- `get_follow_up_messages()` / `getFollowUpMessages()`
- `get_context_usage()`
- `get_session_state()`
- `get_session_stats()`
- `get_session_diagnostics(query?)`
- `get_packages(catalog_path=None)`
- `getAvailableThinkingLevels()`
- `supportsThinking()`
- `supportsXhighThinking()`
- `scopedModels`
- `prompt_templates`
- `resource_loader`
- `isRetrying`
- `autoRetryEnabled`
- `isBashRunning`
- `hasPendingBashMessages`
- reference-style state properties:
  `model`, `thinkingLevel`, `isStreaming`, `isCompacting`, `steeringMode`, `followUpMode`, `sessionFile`, `sessionId`, `sessionName`, `autoCompactionEnabled`

## Events

- `AgentEvent` passthrough
- `queue_update`
- `compaction_*` 预留
- `auto_retry_*` 预留

## Key Data

- `AgentSessionState`
- `SessionContext`
- `SessionRecord`
- `AgentSessionEvent`
- `CommandExecutionResult`
- `SessionCommandDescriptor`
- `CommandSourceInfo`
- `SessionStartEvent`
- `SessionShutdownEvent`
- `allowed_tool_names`
- `SlashCommandInfo`
- `BuiltinSlashCommand`

## Out Of Scope

- transcript 持久化细节
- prompt 组装细节
- 工具注册与执行实现
- compaction 算法本体

## Reference Implementation Alignment

- 语义上对齐 `reference CLI` 的 `AgentSession`
- 保留 session 作为业务中心与统一 orchestration center
- session 拥有 active tool state，而不是让 registry 直接等同于当前正在使用的工具集
- 默认 active tools 包含核心编辑/执行工具与文件探索工具：`read`、`ls`、`find`、`grep`、`bash`、`edit`、`write`；
  custom/extension tools 默认 active；
  `allowed_tool_names` 存在时默认 active set 为 allowlist 内所有可用工具
- 将 compaction、policy、tools 等横切能力拆成协作者，而不是继续膨胀 session
- 协作者的显式抽离不应削弱 `AgentSession` 作为 mode-neutral core facade 的主语义
- 命令面采用 `reference CLI` 风格的 session-level aggregation，不引入独立 command registry class；
  `list_commands()` 聚合 extension/prompt/skill 并返回 typed descriptor；
- slash command 执行顺序对齐 `reference CLI`：`prompt("/cmd")` 先尝试立即执行 extension command；
  未命中后才进入 extension `input` hook 与 prompt/skill preflight；
  `steer()` / `follow_up()` 遇到 extension command 必须拒绝排队
- `get_command_argument_completions()` 透传 extension command 的 `get_argument_completions`，
  为未来 interactive autocomplete 提供 mode-neutral 查询面
- extension slash command handler 对齐 `reference CLI`：必须是 async callable，语义为 `Promise<void>` / `Awaitable[None]`；
  handler 返回值不作为业务结果传播，`CommandExecutionResult.result` 仅保留兼容形状并始终为 `None`
- `CommandSourceInfo` 是统一对外投影：extension / prompt / skill 都保留 `path/source/scope/origin/base_dir`，其中 package 来源由 loader/extension 层提供，session 不重新猜测
- `session_start` / `session_shutdown` hook 接收 typed lifecycle event；session 本体通过 `ctx.sessionManager` 等 runtime binding 访问
- `AgentSessionRuntime` 的 replacement/action API 全部是 async：`create_session()`、`new_session()`、`restore_session()`、`switch_session()`、`fork_session()`、`fork()`、`clone_session()`、`import_from_jsonl()`、`replace_current_session()`、`dispose()`；
  原因是它们都会触发 lifecycle hook、replacement callback 或 session cleanup，不再提供同步 wrapper
- `create_replaced_session_context()` / `createReplacedSessionContext()` 提供 reference-style replacement session context，供 runtime / extension `withSession` 回调绑定新 session
- queue API 对齐 `reference CLI`：`pendingMessageCount` 只统计 session 本地 steering/follow-up 队列，`clearQueue()` 同时清 session mirror 和 agent queue 并发出 `queue_update`
- `prompt(..., preflight_result=...)` 对齐 `reference CLI` 的 prompt preflight 语义：命令/输入扩展、queue routing、before-agent-start 通过后立即回调 success；后续 LLM streaming / wait 继续异步执行
- SDK surface 保留 snake_case，同时补 reference-style camelCase state property aliases，避免 mode/RPC 之外的直接 SDK 调用再自行拼状态
- tool SDK surface 对齐 `reference CLI`：`getActiveToolNames()`、`getAllTools()`、`getToolDefinition(name)`、`setActiveToolsByName(names)` 复用 session active tool state 和 tool registry
- `getAllTools()` 对齐 `reference CLI` 的 ToolInfo projection，返回 `sourceInfo`；当前 builtin / sdk tools 使用 synthetic
  `<builtin:name>` / `<sdk:name>` provenance，extension tools 使用 registry entry metadata 透出真实 extension provenance
- model / thinking / session-name SDK surface 对齐 `reference CLI`：`set_model()` / `setModel()` 与 `cycle_model()` / `cycleModel()` 是 async model-control API，
  会在模型实际变化后发出 `model_select`；thinking/session-name 仍是同步轻量状态更新
- scoped model / resource SDK surface：`scopedModels` / `setScopedModels()` 参与 model cycling；`prompt_templates` 读取当前资源投影，公共刷新必须使用 `await refresh_resources()` 或 `request_resource_refresh()`，不允许调用方直接替换 resource bundle
- retry / bash / compaction SDK surface 对齐 `reference CLI`：`isRetrying`、`autoRetryEnabled`、`setAutoRetryEnabled()`、`setAutoCompactionEnabled()`、`executeBash()`、`recordBashResult()`、`abortBash()`、`isBashRunning`、`hasPendingBashMessages`、`abortCompaction()` 都复用已有 runtime state
- send SDK surface 对齐 `reference CLI` async runtime path：公开 `await sendCustomMessage()` / `await sendMessage()` / `await sendUserMessage()`，并复用 extension context 的 custom message、next-turn、streaming queue 和 command-preflight bypass 语义
- thinking / context / state / stats / export SDK surface 对齐 `reference CLI`：公开 `getAvailableThinkingLevels()`、`supportsThinking()`、`supportsXhighThinking()`、`get_context_usage()`、`get_session_state()`、`get_session_stats()`、`exportToHtml()`、`exportToJsonl()`；
  其中 `get_context_usage()` / `get_session_stats()` 是统一对外事实 payload，使用 reference-style camelCase 字段；内部 dataclass 聚合只保留在 view/controller 层（`build_session_stats()`），避免 mode、workflow、RPC 和 TUI 再兼容 `getContextUsage()` / `getSessionStats()` / `get_stats()`；
  `get_session_state()` 单独投影当前 run 状态、steering/follow-up 队列、compacting/retrying 状态和 queue delivery mode；stats 不再承载 `runtimeState`
- diagnostics SDK surface：`get_session_diagnostics()` 默认限定当前 `sessionId`，避免共享 diagnostics service 上跨 session 记录混杂；不提供 camelCase alias，避免与 Python 原生查询面重复
- replaced extension command context 的 `sendMessage` / `sendUserMessage` 必须经过 stale-context 检查；session replacement 后旧 ctx 不允许继续写入旧 session
- `execute_command_async()` 是 extension 命令的唯一会话执行入口；同步 prompt preflight 不执行 extension command，且 command handler 必须是 async `None` 返回语义
