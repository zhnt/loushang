# `sdk`

## Role

- 对外嵌入入口组件

## Owns

- package-level 创建入口
- 对宿主程序暴露的最小 public surface

## Depends On

- `bootstrap`
- `runtime`
- `session`

## Commands

- `create_agent_session(...)`
- `create_agent_session_from_services(...)`
- `create_agent_session_result(...)`
- `create_agent_session_services(...)`
- `create_agent_session_runtime(...)`
- `create_services(...)`

## Queries

- 当前无稳定 query surface

## Events

- 无

## Key Data

- `AgentSessionServices`
- `BootstrapServices`
- `CreateAgentSessionResult`
- `CwdBoundServicesAudit`
- `CwdBoundServicesAuditIssue`
- `DiagnosticsQuery`
- `DiagnosticSummary`
- `ExtensionFlagValues`
- `AgentSessionRuntime`

## Out Of Scope

- CLI 参数解析
- mode-specific I/O
- transcript persistence 细节

## Reference Implementation Alignment

- 语义上对齐 `reference CLI` 的 embedding / programmatic entry surface
- `create_agent_session(...)` 返回内部装配的 Coding session；原始
  `AgentSession(...)` 构造器不再属于 `loushang.coding` 稳定 SDK，宿主必须通过
  Catalog-aware factory 创建 session
- PLC6E 后所有 Coding session 创建入口只使用 Resource Catalog；SDK 与 CLI 均不再
  暴露 Resource authority 选择器，也不存在异常驱动或输入驱动的旧 loader 降级
- 自定义 loader 必须提供一次性 Catalog input receipt；原始 `package_roots`、旧
  `packages` 输入和只有 manifest 而没有已验证贡献声明的目录不能取得 Resource
  发布权威。需要共享资源时，应使用 native Resource roots 或带精确声明的 Plugin
- 旧 `--extension`、`--skill`、`--prompt-template`、`--theme` 及对应 `--no-*`
  开关已从 Coding grammar 删除；CLI 会在创建 runtime 前返回
  `coding_legacy_resource_input_removed` 和 native root / verified Plugin 迁移指引
- `register_coding_builtin_tools` 不再属于顶层稳定 SDK；Catalog-owned Coding
  session 拒绝通过 `tool_registry` 或 `tools` 注入保留的 base Tool 名称
- `create_agent_session_result(...)` 提供 Python 风格的结构化创建结果，暴露创建期 session、resource bundle、diagnostics、cwd audit snapshot
- `create_agent_session_services(...)` 对齐 `reference CLI` 的 cwd-bound service creation，暴露 settings/resource/diagnostics 服务包
- `create_agent_session_services(...)` 会加载 extension registry、暴露 `extension_runner`、应用 `extension_flag_values`，并把未知 flag / string flag 缺值收敛为创建期 diagnostics
- `create_agent_session_from_services(...)` 用已创建的 cwd-bound services 构造 session，避免宿主程序重复拼装 bootstrap 参数
- `loushang.coding` 顶层 `__all__` 是稳定 Python SDK 边界；新增对外类型时需要同步 public surface snapshot 和 smoke 测试
- 当前优先保留轻量模块入口，不先抽更重的 SDK 对象
- `sdk` 更适合作为对外嵌入面，而不是反向承担装配中心职责
