# `diagnostics`

## Scope

- 诊断与错误报告对象

## Objects

### `DiagnosticRecord`

归属组件：

- `loushang.harness.diagnostics.types`

角色：

- 标准诊断记录对象

承担语义：

- 配置问题
- 环境问题
- 执行问题
- 错误归一化结果
- 去重 fingerprint
- 重复 occurrence count

### `ErrorReport`

归属组件：

- `loushang.harness.diagnostics.types`

角色：

- 对外错误报告对象

承担语义：

- 用户可见错误
- 内部错误摘要
- 关联上下文
- 已去重的 related diagnostics

### Serialized Diagnostics

归属组件：

- `loushang.harness.diagnostics.serialization`

角色：

- CLI/RPC 对外查询投影

承担语义：

- camelCase 字段名
- JSON-safe details
- `DiagnosticRecord` 到稳定 response payload 的转换
- `ErrorReport` 到 `primary` / `related` payload 的转换

### `StartupCheckResult`

归属组件：

- `loushang.harness.diagnostics.types`

角色：

- 启动检查返回对象

承担语义：

- 检查名称
- 成功/失败状态
- 用户可见消息
- 诊断级别、代码、来源与详情

## Reference Implementation Alignment

- 这组对象对齐的是 `reference coding agent` 的 diagnostics concerns
- 当前参考中没有足够清晰、稳定、同层级的一等数据对象名可直接复用

## Notes

- `DiagnosticRecord` 偏内部诊断对象
- `ErrorReport` 偏对外投影对象
- `serialize_diagnostic(...)` / `serialize_error_report(...)` 是 CLI/RPC 共享的稳定投影层
- Harness owns the neutral records and engine; Coding owns serialized product payloads and presentation.
