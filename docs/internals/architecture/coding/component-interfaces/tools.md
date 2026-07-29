# `tools`

## Role

- coding 工具定义与注册系统入口，以及 built-in tool family 的装配边界

## Owns

- `ToolRegistry`
- registered `ToolDefinition` 集合
- enabled / available tool definition 集合
- `ToolDefinition -> AgentTool` 的 materialization seam
- built-in tool definition family
- optional `ToolDefinition.render_call/render_result` renderer callbacks

## Depends On

- registry core 不强依赖 `exec` / `policy`
- built-in executable tool definitions 可依赖 Harness workspace execution
- 所有 effectful built-in tools 必须把冻结后的 action 交给统一 Gateway
- 只有 Gateway 可以调用 injected Policy evaluator 与 Approval resolver

## Commands

- `register_tool(...)`
- `enable_tool(...)`
- `disable_tool(...)`

## Queries

- `get_definition(...)`
- `list_definitions()`
- `list_enabled_definitions()`

## Events

- 当前无稳定事件面

## Key Data

- `ToolDefinition`
- enabled tool names
- optional tool source metadata
- `prompt_snippet` / `prompt_guidelines` as the model-visible tool prompt surface

## Out Of Scope

- 当前 session 的 active tool set
- shell / subprocess 执行细节
- approval UI 与用户交互
- mode / RPC / export 的 rendered event projection

## Reference Implementation Alignment

- 语义上对齐 `reference CLI` 的 built-in tool registry / tool definition layer
- 保持 definition-first，而不是直接把 `AgentTool` 当成 registry 中心
- `ToolRegistry` 更像把 `reference CLI` 中分散在 `AgentSession`、`core/tools/*`、wrapper seam 的定义面显式收束出来
- 明确把工具注册边界、session 激活边界、命令执行边界拆开
- `reference CLI` 的 `allowedToolNames` 语义由 `AgentSession.allowed_tool_names` 承担：硬过滤当前 session 可见和可激活工具，
  但不进入 `ToolRegistry`，避免把 session policy 写进全局工具定义注册表

## Compatibility Boundary

- `loushang` 的 Python public API、internal controller API、tool definition object surface 和 Python-side
  `AgentToolResult.details` 默认使用 Python 风格 `snake_case`
- 不为了 TypeScript / `reference CLI` surface parity 在 Python 对象或 Python result details 上增加重复的 camelCase alias
- camelCase 只出现在显式协议边界，且应由 serializer / adapter 层承担转换，例如：
  - RPC / extension wire payload
  - LLM tool input schema 中已经稳定存在的字段
  - 明确声明为 reference-compatible serialized payload 的嵌套对象
- 判断标准：如果调用方是在 Python 进程内以 Python object 使用该值，优先 `snake_case`；如果调用方通过 JSON / RPC /
  extension protocol 消费该值，按对应协议约定命名
- 对齐 `reference CLI` 时优先对齐行为、schema 语义、执行/abort/artifact/resource/extension 协议，不把 TypeScript 命名风格本身视为
  gap

## Notes

- 当前 session 正在使用哪些工具，属于 `AgentSession` 的 active tool state，不属于 `ToolRegistry`
- `ToolRegistry` 提供定义面；`AgentSession` 决定当前 turn 注入给 `Agent` 的 runtime tools
- tool 可以 active 但不进入 model prompt；只有设置了 `prompt_snippet` 的 `ToolDefinition` 会被 prompt assembler 暴露给模型，
  `prompt_guidelines` 作为附加工具使用建议追加。这对齐 参考实现中 extension tool 可隐藏但仍可由 runtime/extension 调用的语义。
- 工具执行失败严格对齐 `reference CLI`：工具抛异常，agent loop 生成 `ToolResultMessage(is_error=True)` 并送回模型；`tools` 不直接把普通执行失败写入 diagnostics。
- `AgentToolResult.terminate` 是工具执行语义的一部分；event/RPC/print JSON 投影必须保留 `terminate`，便于客户端理解工具批次是否请求终止 agent loop。
- 工具 renderer callback 属于 tool definition 的展示能力；`rendered_tool_call` / `rendered_tool_result`
  的 wire 合约属于 event projection / mode 边界，见
  [Loushang Coding Rendered Tool Events](../loushang-coding-rendered-tool-events.md)。
- 全局 `ToolsOptions.policy_engine` 会传入 bash/read/write/edit/ls/find/grep。默认策略保持 allow；配置
  `blocked_tools` 后，内建工具在实际执行或文件变更前抛出 `PermissionError`。
- 全局 `ToolsOptions.approval_resolver` 会处理 `ask_tools` / ask path / ask command policy。无 resolver 时默认拒绝；
  resolver 返回 allow 时工具继续执行，返回 deny 时工具在执行前失败。
- policy / approval 拒绝会抛出带 `tool_result_details` 的 `PolicyEnforcementError`。agent loop 会把这些 details 原样投影到
  `AgentToolResult.details`、`ToolResultMessage.details` 和 JSON/RPC `tool_execution_end.result.details`，让无 UI 环境也能观测拒绝原因。
