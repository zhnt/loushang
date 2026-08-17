# `compaction`

## Role

- 长会话压缩、摘要与上下文预算协调组件

## Owns

- Coding summary prompt、model/auth 调用与代码/文件操作摘要格式
- `BranchSummarySettings` 与 branch summary 的产品语义
- Coding extension hook、command 与 TUI/RPC/HTML 投影

## Depends On

- `store`
- `control`
- `loushang-ai`
- `loushang.harness.transcript`
- `loushang.harness.context`

## Commands

- `compact_session(...)`
- `maybe_compact_after_turn(...)`
- `abort()`

## Queries

- `get_status()`
- `calculate_compaction_budget(...)`

## Events

- 组件本身不直接暴露独立事件面
- `compaction_*` 生命周期事件由 `session/event` 对外转发

## Key Data

- `CompactionSettings`
- `BranchSummarySettings`
- `CompactionStatus`
- `CompactionBudget` (owned by `loushang.harness.context.budget`)
- `SummaryEvaluationCase`
- `SummaryEvaluationResult`
- `SummaryResourceOperations`
- `SummaryValidationReport`
- `ContextUsageSnapshot`
- `CompactionDecision`
- summarized conversation prompt wrapped as `<conversation>` / `<previous-summary>`
- lightweight `readFiles` / `modifiedFiles` details extracted from assistant tool calls

## Out Of Scope

- transcript 持久化本体
- session event transport
- tool execution
- prompt/resource 发现
- session run loop orchestration

## Reference Implementation Alignment

- 语义上对齐 `reference CLI` 的 compaction / branch summarization layer
- 不复刻 `reference CLI` 把所有 compaction 逻辑继续堆进 `AgentSession`
- `session` 负责决定何时触发 compaction；`compaction` 负责准备、总结与结果回填协调
- summarization prompt 对齐 `reference CLI`：不把旧对话直接当作继续对话喂给模型，而是序列化为单条 user prompt，使用固定 summary schema；已有 compaction summary 时走 update prompt
- split-turn compaction 支持单独生成 turn-prefix summary，并合并到主 summary
- compaction result 会追加当前 Coding profile 选择的 `<read-files>` / `<modified-files>` 资源证据片段，并把对应列表放入 `details`
- branch summary 也使用相同的 serialized conversation summary path，追加 reference-style branch preamble 和 file operation details
- `loushang.harness.context.validate_summary(...)` 和 profile-driven `evaluate_summary_case(...)` 提供通用 summary
  evaluation runtime，用于验证固定结构、缺失 section、残留 prompt placeholder、关键词和由 profile 声明的资源操作；
  Coding 只绑定自己的 compaction / branch profiles 和 fixture convenience entrypoint，它们不改变生产摘要结果
- Harness 的 `plan_turn_aware_compaction(...)` 是 deterministic fact layer：它不调用模型，记录 previous
  compaction、`first_kept_entry_id`、`summarized_entry_ids`、`turn_prefix_entry_ids`、`kept_entry_ids`、
  `tokens_before` 与 `keep_recent_tokens`；`prepare_turn_aware_compaction(...)` 基于同一计划组装消息并写入
  camelCase `compactionPlan` details
- compaction preparation 使用 entry-aware cut point：上一轮 compaction 后从 `first_kept_entry_id` 边界继续，
  并在 cut point 落到 assistant/custom continuation 时拆出 `turn_prefix_messages`
- cut point 不能落在 `toolResult` 上；当 recent window 被最新 tool result 撑爆时，cut point 回退到最近的
  合法 entry，通常是产生该 tool result 的 assistant，从而保留 assistant tool call + tool result 后缀
- 成功 compaction 后，`CompactionEntry.details.compactionPlan` 持久化该事实链，用于解释“摘要覆盖了哪些 entry、
  保留了哪些原文 entry、是否 split turn、使用了哪次 previous compaction boundary”
- overflow recovery 对齐 `reference CLI`：同一连续 overflow 只允许一次自动 `compact + retry`；
  第二次 overflow 发出失败的 `compaction_end`，提示用户减少上下文或切换更大上下文模型
- 普通成功 assistant response 会重置 overflow recovery guard，避免一次历史 overflow 永久禁止后续恢复
- usage / compaction fact chain 对齐 `reference CLI` 的分层语义：
  `loushang.ai` 只负责 provider usage、stop_reason、context overflow 的归一化事实；
  `coding.session.context_usage` 基于 session branch 和 normalized assistant usage 生成 `ContextUsageSnapshot`；
  `AgentSession` 直接绑定 Harness `AgentTranscriptCompactionRuntime`，只消费
  `CompactionDecision` 触发 threshold / overflow compaction，不直接散落 token 计算逻辑
- `ContextUsageSnapshot` 是 usage / compaction 的唯一事实对象，除 `tokens`、`context_window`、`percent`、`source` 外，
  还携带 `compact_percent`、`reserve_tokens`、`keep_recent_tokens`、`percent_threshold_tokens`、
  `reserve_threshold_tokens`、`threshold_tokens`、`threshold_reason`；
  mode / TUI / RPC / extension 只能消费 snapshot，不应重复计算 threshold
- threshold accounting 由 `loushang.harness.context.budget.calculate_compaction_budget(...)` 统一计算，
  `coding.compaction.policy` 保留兼容导出：
  `percent_threshold = context_window * compact_percent / 100`，
  `reserve_threshold = context_window - reserve_tokens`，
  实际 `threshold_tokens = min(percent_threshold, reserve_threshold)`；这保留了 `reference CLI` 的 fixed reserve guard，
  同时增加 loushang 全局百分比阈值，避免大上下文模型等到过高比例才 compact
- 不能等到 `stop_reason="length"` 才 compact：只要上一轮可观测 usage 超过统一 policy 计算出的 `threshold_tokens`，
  下一次真正进入 agent prompt 前就应先触发 threshold compaction；extension command、streaming steer/follow-up 排队路径不触发 pre-prompt compaction
- compaction 后如果没有新的 assistant usage，当前 context usage 应标记为 stale/unknown，避免复用 compaction 前的 usage 反复触发或误报预算
- `ContextUsageEstimate` 记录由 `loushang.harness.context.usage` 所有；读取 assistant usage 和估算 trailing message token 的算法仍由 Coding 所有
- `compaction_start` 事件携带 `usage` snapshot；`compaction_end` 事件携带 `usage_before` / `usage_after` snapshot。
  compaction 成功后 `usage_after.tokens` 与 `usage_after.percent` 通常为 `None`，并标记 `stale_after_compaction=True`，
  直到下一次有效 assistant usage 出现

## Configuration

- compaction 配置归属 `loushang.coding.control.CompactionSettings`，由 `SettingsManager` 的 global/project/session 三层配置合并产生。
- 默认 JSON 形状：

```json
{
  "compaction": {
    "enabled": true,
    "compact_percent": 80,
    "reserve_tokens": 8192,
    "keep_recent_tokens": 32768
  }
}
```

- 全局路径：`~/.loushang/coding/settings.json`
- 项目路径：`<project>/.loushang/settings.json`
- model metadata 只提供 `context_window` 等能力事实；不要在每个 model 上重复 compaction policy。
