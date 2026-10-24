# Loushang Coding Compaction Policy

## Scope

Compaction policy 是 coding runtime 配置，描述 Loushang 在长会话中如何使用模型上下文窗口。

它不属于 `loushang.ai`：AI 层只归一化 provider usage、stop reason 和 model capability 事实。
它也不应该重复写入每个 model entry：`context_window` 是模型能力，compaction policy 是 coding runtime 行为。

## Configuration

`CompactionSettings` 属于 `ControlConfig`，由 `SettingsManager` 加载。

配置来源分三层：

- global: `~/.loushang/coding/settings.json`
- project: `<project>/.loushang/settings.json`
- session: in-memory `SettingsManager` overrides

示例：

```json
{
  "compaction": {
    "enabled": true,
    "compact_percent": 80,
    "reserve_tokens": 8192,
    "keep_recent_tokens": 32768,
    "single_call_early_trigger": false
  }
}
```

## Field Semantics

- `enabled`: 是否允许自动 compaction，包括 threshold 与可选的 capacity 触发。
- `compact_percent`: 普通 threshold compaction 开始触发的 `context_window` 百分比。
- `reserve_tokens`: 固定安全余量，用于给 prompt 增长、tool result、summary 生成和模型输出留空间。
- `keep_recent_tokens`: compaction 后保留最近原文上下文的目标大小。
- `single_call_early_trigger`: 可选试验开关，默认 `false`。开启后，在普通阈值尚未触发时，若按当前 cut point 计算的待摘要内容达到单次摘要请求容量的 85%，提前自动压缩，事件原因为 `capacity`。

`reserve_tokens` 不等同于模型输出 token。它是安全预算，包含输出余量和下一轮不可预测的上下文增长。

`keep_recent_tokens` 不是触发阈值。它只影响 compaction 时选择 cut point 的位置。

摘要请求容量由实际准备的请求字节上限、输入 token 上限、摘要提示与已有摘要共同决定。提前触发只调整压缩时机；若压缩内容仍无法容纳于一次请求，执行器继续使用有界分批与合并路径。跨越未完成 turn 的 cut point 会在容量允许时一次生成历史摘要和独立的 turn context；格式校验不通过时回退原来的两段摘要路径。

## Threshold Calculation

`coding.compaction.policy.calculate_compaction_budget(...)` 统一计算：

```text
percent_threshold = floor(context_window * compact_percent / 100)
reserve_threshold = context_window - reserve_tokens
threshold_tokens = min(percent_threshold, reserve_threshold)
```

取较小值可以让策略保持保守：

- `compact_percent` 避免大上下文模型等到极高比例才 compact。
- `reserve_tokens` 保留 参考实现风格的固定安全余量，尤其适合较小上下文窗口。

示例：

```text
context_window = 128000
compact_percent = 80
reserve_tokens = 8192

percent_threshold = 102400
reserve_threshold = 119808
threshold_tokens = 102400
```

## Runtime Fact Chain

`ContextUsageSnapshot` 是 runtime、mode、TUI、RPC、extension 之间共享的事实对象。

Python 内部使用 dataclass / snake_case 字段保存事实；跨 session stats、RPC、event、extension runtime
边界时统一序列化为 reference-style camelCase payload，例如 `contextWindow`、`compactPercent`、
`keepRecentTokens`、`thresholdTokens`、`thresholdReason`、`staleAfterCompaction`。

它包含三类信息：

- usage fact: `tokens`、`context_window`、`percent`、`source`、`last_usage_index`、`stale_after_compaction`
- policy fact: `compact_percent`、`reserve_tokens`、`keep_recent_tokens`
- budget fact: `percent_threshold_tokens`、`reserve_threshold_tokens`、`threshold_tokens`、`threshold_reason`

`compaction_start` 事件携带当前 `usage` snapshot。
`compaction_end` 事件携带 `usage_before` 与 `usage_after`。
session stats 的 reference-style payload 还会携带 `latestCompaction`：

```json
{
  "entryId": "compaction-entry-id",
  "firstKeptEntryId": "entry-id",
  "tokensBefore": 195,
  "fromHook": false,
  "plan": {
    "firstKeptEntryId": "entry-id",
    "summarizedEntryIds": ["old-entry"],
    "turnPrefixEntryIds": [],
    "keptEntryIds": ["entry-id"],
    "isSplitTurn": false,
    "tokensBefore": 195,
    "keepRecentTokens": 32768
  }
}
```

`latestCompaction.plan` 来自持久化的 `CompactionEntry.details.compactionPlan`，用于让 RPC / workflow /
TUI 自动化直接解释 cut point，无需重新扫描 JSONL。
workflow 场景通过 `expect.session_stats.latestCompaction` 与 `expect.context_usage`
直接断言这条事实链；fake/runtime adapter 都应从 session 公共 facts API 读取，不重新推导。
即使 extension hook 或 compact implementation 返回自定义 `details`，controller 也必须把 preparation 阶段的
runtime `compactionPlan` 合并回最终 `CompactionResult.details`；自定义字段可以保留，但不能覆盖该 cut-point
事实链。

成功 compaction 后，如果还没有新的 assistant usage：

```text
usage_after.tokens = None
usage_after.percent = None
usage_after.stale_after_compaction = True
```

这表示旧 usage 不能继续作为当前上下文事实使用。

## Reference Implementation Alignment

参考实现使用：

```text
threshold = context_window - reserveTokens
```

默认 `reserveTokens = 16384`，`keepRecentTokens = 20000`。

Loushang 保留这个 reserve guard，同时增加全局 `compact_percent` runtime policy。
这样可以避免把 compaction 字段复制到每个 model metadata，同时让触发点更容易理解和调整。
