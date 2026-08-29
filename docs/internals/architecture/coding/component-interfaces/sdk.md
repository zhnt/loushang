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
- `ResourceAuthorityMode`
- `AgentSession`
- `AgentSessionRuntime`

## Out Of Scope

- CLI 参数解析
- mode-specific I/O
- transcript persistence 细节

## Reference Implementation Alignment

- 语义上对齐 `reference CLI` 的 embedding / programmatic entry surface
- `create_agent_session(...)` 保持兼容，继续返回 `AgentSession`
- session 创建入口默认使用 `resource_authority_mode="catalog_required"`；尚未迁移的自定义 loader 或原始 package path 必须由宿主显式选择 `legacy_explicit`，不存在自动降级。CLI 提供等价的 `--resource-authority-mode legacy_explicit` 显式迁移开关
- `create_agent_session_result(...)` 提供 Python 风格的结构化创建结果，暴露创建期 session、resource bundle、diagnostics、cwd audit snapshot
- `create_agent_session_services(...)` 对齐 `reference CLI` 的 cwd-bound service creation，暴露 settings/resource/diagnostics 服务包
- `create_agent_session_services(...)` 会加载 extension registry、暴露 `extension_runner`、应用 `extension_flag_values`，并把未知 flag / string flag 缺值收敛为创建期 diagnostics
- `create_agent_session_from_services(...)` 用已创建的 cwd-bound services 构造 session，避免宿主程序重复拼装 bootstrap 参数
- `loushang.coding` 顶层 `__all__` 是稳定 Python SDK 边界；新增对外类型时需要同步 public surface snapshot 和 smoke 测试
- 当前优先保留轻量模块入口，不先抽更重的 SDK 对象
- `sdk` 更适合作为对外嵌入面，而不是反向承担装配中心职责
