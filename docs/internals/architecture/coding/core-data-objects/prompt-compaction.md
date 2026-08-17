# `prompt-compaction`

## Scope

- prompt 组装结果与 compaction 相关对象

## Objects

### `PromptAssembly`

归属组件：

- `loushang.harness.capabilities.prompt_assembly`；Coding 保留兼容导入

角色：

- 一次 prompt 组装结果对象

承担语义：

- system prompt
- visible messages
- tool prompt
- resource injections
- method / skill injections

### `CompactionArtifact`

归属组件：

- `compaction`

角色：

- 压缩或摘要结果对象

承担语义：

- summary
- compaction result
- 预算收缩后的替代内容
- `first_kept_entry_id`
- `tokens_before`
- `details`

### `CompactionPlan`

归属组件：

- `compaction`

角色：

- 模型调用前的 deterministic cut-point 事实对象

承担语义：

- `previous_compaction_id`
- `previous_first_kept_entry_id`
- `first_kept_entry_id`
- `summarized_entry_ids`
- `turn_prefix_entry_ids`
- `kept_entry_ids`
- `is_split_turn`
- `tokens_before`
- `keep_recent_tokens`

持久化语义：

- `CompactionEntry.details.compactionPlan` 使用 reference-style camelCase 字段保存该对象
- 它解释新上下文为什么会重建为 `compactionSummary + firstKeptEntryId 后缀`
- 它不是摘要内容本身，也不调用模型

### `CompactionPreparation`

归属组件：

- `compaction`

角色：

- compaction 执行前准备对象

承担语义：

- `first_kept_entry_id`
- `messages_to_summarize`
- `turn_prefix_messages`
- `is_split_turn`
- `tokens_before`
- `previous_summary`
- `details.compactionPlan`
- `plan`

### `CompactionStatus`

归属组件：

- `compaction`

角色：

- compaction 运行状态对象

承担语义：

- `is_running`
- `reason`
- `will_retry`
- `last_error`

## Reference Implementation Alignment

- 这组对象对齐的是 `reference coding agent` 的 prompt assembly / compaction / summarization 语义
- 其中 `PromptAssembly` 与 `CompactionArtifact` 当前不直接复用 `reference CLI` 的稳定同名对象名

## Notes

- `PromptAssembly` 是观察“上下文已如何被组装”的关键数据对象
