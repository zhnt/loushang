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

## Optional Capability Packs

- `coding.arch` 定位为标准安装、高频可用、默认按需激活，并允许用户通过 CLI 或 Coding 配置设为常驻的架构能力包。
- `coding.arch` 不属于 `CODING_BUILTIN_TOOL_PACK`；安装表示工具定义可用，`disabled` / `on_demand` / `always`
  激活策略决定当前 session 是否允许和默认激活该工具集合。
- `coding.arch` 是包含 Architecture Skill、工具能力和相关资源的 Coding Product Capability Bundle id，也是 Skill 或
  Method 使用的 opaque Product capability requirement。Coding Product binding 再将它解析为 family-specific Capability
  Packs；具体 tool-family pack 使用独立限定 id（例如 `coding.arch.tools`）并由 `CODING_ARCH_TOOL_PACK` 描述。Method
  资产不直接依赖 Harness ToolPack 类型或取得执行权限。
- 架构 Skill 负责匹配架构分析、架构设计和重构规划任务；具体工具保持事实导向和窄接口，通过命名 ToolPack 组合，不使用泛化的
  “分析架构”工具替代可验证的结构化查询。
- CLI 或 Coding 配置的显式常驻选择应增量加入默认工具集合，不得替换 builtin tools，也不得绕过 `--no-tools`、session
  allowlist、delegated execution profile、policy 或 approval 边界。
- Coding CLI 使用通用 `--capability CAPABILITY=MODE` 形式覆盖当前进程，例如
  `--capability coding.arch=always`；配置文件使用 `capabilities` 映射，例如
  `{"capabilities": {"coding.arch": "always"}}`。CLI 覆盖只写入 session 配置层，不持久化修改 project/global
  配置；未配置 `coding.arch` 时默认值为 `on_demand`。
- `on_demand` 表示工具定义已 admission、可由 `/tools` 或等价 Session API 手动激活，但不进入默认 Agent tools/prompt；
  `always` 表示增量加入默认激活集合；`disabled` 表示不向该 Session registry 注册该能力的工具定义。
- `inspect_import_graph` 只接受当前 Coding workspace 内的 root（包括解析 symlink 后的 canonical path），所有 query
  都受硬上限约束；工具返回 analyzer/cache 的可验证事实，不输出主观架构判断。
- 高频查询复用语言 provider 输出的版本化逐文件事实缓存，而不缓存 AST 或主观架构结论。CLI 默认在
  `LOUSHANG_HOME/cache/coding/arch` 使用磁盘缓存；长驻工具复用进程内缓存。内容指纹负责单文件失效，文件集合变化则使依赖
  模块索引的事实整体失效；缓存损坏或版本不兼容必须安全退化为重新分析。
- `coding.lsp` 同样是 Coding Product Capability Bundle，而不是 Harness builtin。它通过
  `coding.lsp.tools` 提供 `inspect_symbol` 与 `document_outline`；`on_demand` / `always` 只控制工具可见性，Server
  始终在第一次语义查询时惰性启动。
- Coding 拥有 `lsp.json` 的 Server 发现、优先级、可执行文件 admission 与结构化状态；Harness 只提供授权进程启动、
  Sandbox、裸字节传输和 Session 兜底清理。`loushang lsp status|doctor` 只检查 catalog，不隐式启动或安装 Server。

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
