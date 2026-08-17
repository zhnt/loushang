# `control-configs`

## Scope

- mode、control 与 model selection 相关配置对象

## Objects

### `ModeConfig`

归属组件：

- `mode`

角色：

- mode 级配置对象

承担语义：

- `print` / `json` / `rpc` / `interactive` 启动参数
- mode-specific 输出与交互选项

### `ControlConfig`

归属组件：

- `control`

角色：

- coding 产品层控制平面配置对象

承担语义：

- settings
- config
- model/profile selection
- 运行控制项
- `compaction_settings`
- `branch_summary_settings`
- `capabilities: {ProductCapabilityId: disabled | on_demand | always}`，表达 Product capability 的默认挂载策略；
  具体 capability id、默认值和 capability-to-pack 映射仍由 Coding Product 解释，配置层只校验通用挂载值。

### `CompactionSettings`

归属组件：

- `control`

角色：

- compaction 配置对象

承担语义：

- `enabled`
- `compact_percent`
- `reserve_tokens`
- `keep_recent_tokens`

字段含义：

- `compact_percent` 是全局自动 compaction 的百分比阈值，按模型 `context_window` 计算。
- `reserve_tokens` 是固定安全余量，用于给下一轮 prompt、工具结果、summary prompt/output 与模型输出留空间。
- `keep_recent_tokens` 是 compaction 后保留最近原文上下文的目标大小，不是输出 token 预算。
- 实际 threshold 由 `compaction.policy` 计算，取 `context_window * compact_percent / 100` 与
  `context_window - reserve_tokens` 中更保守的较小值。

### `BranchSummarySettings`

归属组件：

- `control`

角色：

- branch summarization 配置对象

承担语义：

- `enabled`
- `reserve_tokens`

### `ModelSelection`

归属组件：

- `control`

角色：

- model 选择结果对象

承担语义：

- 当前 session 或 run 所选模型
- 与 `loushang-ai` 的 model registry/query 接缝

## Reference Implementation Alignment

- `ControlConfig` 与 `ModelSelection` 在 `reference coding agent` 中没有足够清晰、稳定、同层级的一等对象名可直接复用

## Notes

- 这组对象属于控制与配置对象，不应与服务对象 `SettingsManager` / `ModelRegistry` 混为一层
- `context_window` 属于 model capability；compaction policy 属于 coding control config，不应重复写入每个 model metadata
